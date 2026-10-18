# Scheduler dentro del proceso (ARQUITECTURA §4.4–4.5): un tick cada 30 s de reloj real y otro apenas cambia el
# reloj (clock/advance, set) o se inyecta una caída. Por cada disparador: explain → presupuesto → ask → pregunta
# guardada → push. Idempotente: un disparador da como mucho una pregunta por persona y por día.
import asyncio
import datetime as dt
import logging

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app import clock, notify
from app.models import Explanation, Trigger
from app.pipeline import ask as ask_pipeline
from app.pipeline import context as context_builder
from app.pipeline import explain as explain_pipeline

from app.rules import budget, lanes
from app.rules.triggers import evaluate
from app.notify import dispatch


def budget_allow(person_id: int, kind: str, now: dt.datetime) -> bool:
    return budget.allow(person_id, kind, now)


log = logging.getLogger("entrecasa.scheduler")

TICK_SECONDS = 30
KICK_PATHS = {"/admin/clock/advance", "/admin/clock/set", "/admin/inject_drop"}

_lock = asyncio.Lock()
_kick: asyncio.Event | None = None
_task: asyncio.Task | None = None


def _dose_time(trigger: Trigger) -> dt.datetime | None:
    raw = (trigger.facts or {}).get("dose_time") or ((trigger.facts or {}).get("deviation") or {}).get("dose_time")
    if raw is None:
        return None
    return raw if isinstance(raw, dt.datetime) else dt.datetime.fromisoformat(str(raw))


REPEAT_DAYS = 7   # un disparador de texto no vuelve a preguntarle lo mismo a la misma persona antes de esto


def _already_handled(trigger: Trigger, now: dt.datetime) -> bool:
    dose = _dose_time(trigger)
    if dose is not None:
        return db.episode_for_dose(trigger.patient_id, dose) is not None
    since = now - dt.timedelta(days=REPEAT_DAYS)
    return db.questions_since(trigger.to_person_id, trigger.rule_id, since) > 0


async def handle(trigger: Trigger, now: dt.datetime) -> int | None:
    """Procesa un disparador. Devuelve el id de la pregunta enviada, o None si no se preguntó.
    Desvío (con toma): siempre se explica y se guarda el episodio; el presupuesto solo decide si se pregunta.
    Disparadores de texto: como mucho uno por regla y persona cada REPEAT_DAYS, y sin gastar IA si no hay presupuesto."""
    if await asyncio.to_thread(db.person_role, trigger.to_person_id) is None:
        log.warning("%s para una persona que no existe (%s): se ignora", trigger.rule_id, trigger.to_person_id)
        return None
    if await asyncio.to_thread(_already_handled, trigger, now):
        return None
    dose = _dose_time(trigger)
    if dose is None and not await asyncio.to_thread(budget_allow, trigger.to_person_id, "pregunta", now):
        log.info("presupuesto: no se pregunta %s a %s", trigger.rule_id, trigger.to_person_id)
        return None

    ctx = await context_builder.build(trigger, now)
    explanation: Explanation = await explain_pipeline.explain(trigger, ctx)
    deviation = ({**ctx.deviation.model_dump(mode="json"), "baseline_label": ask_pipeline.baseline_label(trigger)}
                 if ctx.deviation else None)

    async def save_episode(status: str, question_id: int | None) -> None:
        if dose is not None:
            await asyncio.to_thread(db.insert_episode, patient_id=trigger.patient_id, dose_time=dose,
                                    deviation=deviation, explanation=explanation.model_dump(),
                                    question_id=question_id, status=status)
            await _episode_alerts(trigger.patient_id)

    if explanation.explained:
        if dose is None:   # marca para no volver a evaluarlo (los desvíos se marcan con el episodio)
            await asyncio.to_thread(db.insert_question, patient_id=trigger.patient_id,
                                    to_person_id=trigger.to_person_id, rule_id=trigger.rule_id, question="",
                                    why=trigger.why, options=[], status="descartada", sent_at=now)
        log.info("%s explicado por lo que ya contaron: %s", trigger.rule_id, explanation.reasoning)
        await save_episode("explicado", None)
        return None

    if dose is not None and not await asyncio.to_thread(budget_allow, trigger.to_person_id, "pregunta", now):
        log.info("presupuesto: desvío de las %s sin pregunta para %s", f"{dose:%H:%M}", trigger.to_person_id)
        await save_episode("sin_pregunta", None)
        return None

    text = await ask_pipeline.ask(trigger, ctx)
    qid = await asyncio.to_thread(db.insert_question, patient_id=trigger.patient_id,
                                  to_person_id=trigger.to_person_id, rule_id=trigger.rule_id, question=text.question,
                                  why=trigger.why, options=text.options, status="enviada", sent_at=now)
    await save_episode("preguntado", qid)   # antes de la push: la pantalla del "por qué" lee episodes.deviation
    title = f"{ctx.patient_name}, una pregunta de hoy" if ctx.recipient_role == "paciente" else "Una pregunta de hoy"
    await notify.send(trigger.to_person_id, "pregunta", title, text.question, f"/casa/pregunta/{qid}")
    log.info("pregunta %s (%s) enviada a %s", qid, trigger.rule_id, trigger.to_person_id)
    return qid


async def _episode_alerts(patient_id: int) -> None:
    """Con un episodio nuevo, rules.lanes ve si se cumple A3 (3 en 7 días en el mismo tramo) y se reparte."""
    alerts = await asyncio.to_thread(lanes.evaluate, patient_id, [])
    await dispatch.dispatch(alerts)


async def tick() -> list[int]:
    """Un paso del scheduler para todos los pacientes. Serializado: dos ticks nunca corren a la vez."""
    sent: list[int] = []
    async with _lock:
        now = await asyncio.to_thread(clock.now)
        expired = await asyncio.to_thread(db.expire_questions, now.date())
        if expired:
            log.info("%s preguntas de días anteriores vencieron", expired)
        for patient in await asyncio.to_thread(db.patients):
            triggers = await asyncio.to_thread(evaluate, patient["id"], now)
            # Primero los desvíos: si hay pregunta del día, es para lo que midió el teléfono.
            for trigger in sorted(triggers, key=lambda t: _dose_time(t) is None):
                try:
                    qid = await handle(trigger, now)
                except Exception:
                    log.exception("falló el disparador %s", trigger.rule_id)
                    continue
                if qid:
                    sent.append(qid)
    return sent


async def tick_now() -> list[int]:
    """Tick inmediato, para llamar desde admin después de advance, set o inject_drop. Idempotente: si ya corrió,
    no repite preguntas; si hay un tick en curso, espera a que termine y corre otro."""
    return await tick()


async def _loop() -> None:
    assert _kick is not None
    while True:
        try:
            await asyncio.wait_for(_kick.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            pass
        _kick.clear()
        try:
            await tick()
        except Exception:
            log.exception("falló el tick")


def start() -> None:
    global _kick, _task
    _kick = asyncio.Event()
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None


def kick() -> None:
    """Pide un tick ya (sin esperar los 30 s)."""
    if _kick is not None:
        _kick.set()


async def kick_after_clock_change(request, call_next):
    """Middleware: después de mover el reloj o inyectar una caída, tick inmediato."""
    response = await call_next(request)
    if request.method == "POST" and request.url.path in KICK_PATHS and response.status_code < 400:
        kick()
    return response

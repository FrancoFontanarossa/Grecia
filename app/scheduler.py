# Scheduler dentro del proceso (ARQUITECTURA §4.4–4.5): un tick cada 30 s de reloj real y otro apenas cambia el
# reloj (clock/advance, set) o se inyecta una caída. Por cada disparador: explain → presupuesto → ask → pregunta
# guardada → push. Idempotente: un disparador da como mucho una pregunta por persona y por día.
import asyncio
import datetime as dt
import logging

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app import _tmp_rules, clock, notify
from app.models import Explanation, Trigger
from app.pipeline import ask as ask_pipeline
from app.pipeline import context as context_builder
from app.pipeline import explain as explain_pipeline

try:                                   # las reglas son de Franco; mientras no estén, los TEMPORAL
    from app.rules import triggers as _triggers  # type: ignore
    evaluate = _triggers.evaluate
except ImportError:
    evaluate = _tmp_rules.triggers_evaluate

try:
    from app.rules import budget as _budget  # type: ignore

    def budget_allow(person_id: int, kind: str, now: dt.datetime) -> bool:
        return _budget.allow(person_id, kind, now)
except ImportError:
    def budget_allow(person_id: int, kind: str, now: dt.datetime) -> bool:
        sent = db.questions_on_day(person_id, now.date(), statuses=("pendiente", "enviada", "respondida"))
        return _tmp_rules.budget_allow(kind, now, sent)

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


def _already_handled(trigger: Trigger, now: dt.datetime) -> bool:
    dose = _dose_time(trigger)
    if dose is not None and db.episode_for_dose(trigger.patient_id, dose):
        return True
    return db.questions_on_day(trigger.to_person_id, now.date(), rule_id=trigger.rule_id) > 0


async def handle(trigger: Trigger, now: dt.datetime) -> int | None:
    """Procesa un disparador. Devuelve el id de la pregunta enviada, o None si no se preguntó."""
    if await asyncio.to_thread(db.person_role, trigger.to_person_id) is None:
        log.warning("%s para una persona que no existe (%s): se ignora", trigger.rule_id, trigger.to_person_id)
        return None
    if await asyncio.to_thread(_already_handled, trigger, now):
        return None
    # El presupuesto se mira antes de explain para no gastar una llamada a la IA si igual no se va a preguntar.
    if not await asyncio.to_thread(budget_allow, trigger.to_person_id, "pregunta", now):
        log.info("presupuesto: no se pregunta %s a %s", trigger.rule_id, trigger.to_person_id)
        return None

    ctx = await context_builder.build(trigger, now)
    explanation: Explanation = await explain_pipeline.explain(trigger, ctx)
    dose = _dose_time(trigger)
    deviation = ctx.deviation.model_dump(mode="json") if ctx.deviation else None

    if explanation.explained:
        await asyncio.to_thread(db.insert_question, patient_id=trigger.patient_id, to_person_id=trigger.to_person_id,
                                rule_id=trigger.rule_id, question="", why=trigger.why, options=[],
                                status="descartada", sent_at=now)
        if dose is not None:
            await asyncio.to_thread(db.insert_episode, patient_id=trigger.patient_id, dose_time=dose,
                                    deviation=deviation, explanation=explanation.model_dump(), question_id=None,
                                    status="explicado")
        log.info("%s explicado por lo que ya contaron: %s", trigger.rule_id, explanation.reasoning)
        return None

    text = await ask_pipeline.ask(trigger, ctx)
    qid = await asyncio.to_thread(db.insert_question, patient_id=trigger.patient_id,
                                  to_person_id=trigger.to_person_id, rule_id=trigger.rule_id, question=text.question,
                                  why=trigger.why, options=text.options, status="enviada", sent_at=now)
    if dose is not None:
        await asyncio.to_thread(db.insert_episode, patient_id=trigger.patient_id, dose_time=dose, deviation=deviation,
                                explanation=explanation.model_dump(), question_id=qid, status="preguntado")
    title = f"{ctx.patient_name}, una pregunta de hoy" if ctx.recipient_role == "paciente" else "Una pregunta de hoy"
    await notify.send(trigger.to_person_id, "pregunta", title, text.question, f"/casa/pregunta/{qid}")
    log.info("pregunta %s (%s) enviada a %s", qid, trigger.rule_id, trigger.to_person_id)
    return qid


async def tick() -> list[int]:
    """Un paso del scheduler para todos los pacientes. Serializado: dos ticks nunca corren a la vez."""
    sent: list[int] = []
    async with _lock:
        now = await asyncio.to_thread(clock.now)
        for patient in await asyncio.to_thread(db.patients):
            triggers = await asyncio.to_thread(evaluate, patient["id"], now)
            for trigger in triggers:
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

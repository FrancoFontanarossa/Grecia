# Modo 2 en el scheduler (detrás de config.DAILY_PLAN_ENABLED):
#   plan_if_due:  a partir de las 21 de clock.now(), una vez por paciente y día: build_digest → daily_plan (IA) →
#                 rules.note limpia la nota del día (bitácora) y rules.plan prueba y decide → se guardan la nota,
#                 las hipótesis y las acciones (agendadas y descartadas con motivo).
#   run_plan(historia=True): para el precorrido de noches pasadas: nota e hipótesis, sin agendar acciones.
#   execute_due:  en cada tick, las acciones agendadas cuya hora llegó: golpeteo → push que abre el juego;
#                 pregunta o seguimiento → pipeline.ask con el motivo → questions + push (con el presupuesto del día).
#   link_test:    un juego hecho después de una invitación del plan basada en un desvío se vincula a ese episodio.
import asyncio
import datetime as dt
import json
import logging

from app import config, db, notify
from app.models import Trigger
from app.pipeline import daily_plan as daily_plan_pipeline
from app.pipeline.digest import build_digest
from app.rules import budget
from app.rules import note as note_rules
from app.rules import plan as plan_rules

log = logging.getLogger("entrecasa.plan")
GAME_TITLE = "¿Hacemos el juego de 20 segundos?"


def _planned(patient_id: int, plan_date: dt.date) -> bool:
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM daily_notes WHERE patient_id = ? AND date = ?",
                        (patient_id, (plan_date - dt.timedelta(days=1)).isoformat())).fetchone():
            return True
        return any(conn.execute(f"SELECT 1 FROM {t} WHERE patient_id = ? AND plan_date = ? LIMIT 1",
                                (patient_id, plan_date.isoformat())).fetchone() for t in ("hypotheses", "planned_actions"))


def reviewed(patient_id: int, day: dt.date) -> bool:
    """Ya hay revisión de ese día (nota, hipótesis o acciones para el día siguiente): el precorrido no la repite."""
    return _planned(patient_id, day + dt.timedelta(days=1))


def _save_note(patient_id: int, day: dt.date, note, removed: int, now: dt.datetime) -> None:
    row = note_rules.to_row(note)
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_notes (patient_id, date, text, points, follow_up, removed_count, created_at) "
                     "VALUES (?,?,?,?,?,?,?) ON CONFLICT (patient_id, date) DO UPDATE SET text = excluded.text, "
                     "points = excluded.points, follow_up = excluded.follow_up, removed_count = excluded.removed_count, "
                     "created_at = excluded.created_at",
                     (patient_id, day.isoformat(), row["text"], row["points"], row["follow_up"], removed, db.to_db(now)))


_done: set[tuple[int, str]] = set()      # planes vacíos de este proceso (no dejan filas): no se repiten en cada tick


def _save(patient_id: int, plan_date: dt.date, results, scheduled, discarded, now: dt.datetime) -> None:
    with db.connect() as conn:
        for r in results:
            h = r.hypothesis
            conn.execute("INSERT INTO hypotheses (patient_id, plan_date, condition, metric, lag_days, direction, reason, "
                         "passed, mediana_con, n_con, mediana_sin, n_sin, discard_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (patient_id, plan_date.isoformat(), h.condition, h.metric, h.lag_days, h.direction, h.reason,
                          int(r.passed), r.mediana_con, r.n_con, r.mediana_sin, r.n_sin, r.discard_reason))
        for row, status in [(a, "agendada") for a in scheduled] + [(a, "descartada") for a in discarded]:
            conn.execute("INSERT INTO planned_actions (patient_id, plan_date, kind, at, to_person_id, reason, why, basis, "
                         "evidence_ids, status, discard_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (patient_id, plan_date.isoformat(), row["kind"], row["at"], row["to_person_id"], row["reason"],
                          row.get("why"), row["basis"], json.dumps(row["evidence_ids"]), status,
                          row.get("discard_reason"), db.to_db(now)))


async def run_plan(patient_id: int, now: dt.datetime, *, historia: bool = False) -> dict:
    """Revisión diaria: nota del día, hipótesis y plan de mañana, validados y guardados. Con historia=True (noches
    pasadas del precorrido) guarda la nota y las hipótesis, pero no agenda acciones. Devuelve un resumen."""
    digest = await asyncio.to_thread(build_digest, patient_id, now)
    plan_date = dt.date.fromisoformat(digest["plan_date"])
    plan = await daily_plan_pipeline.daily_plan(digest)
    note_removed = None
    if plan.note is not None:
        note, note_removed = note_rules.verify_note(plan.note, digest)
        await asyncio.to_thread(_save_note, patient_id, plan_date - dt.timedelta(days=1), note, note_removed, now)
    if historia:
        plan = plan.model_copy(update={"actions": []})
    first, last = dt.date.fromisoformat(digest["ventana"]["desde"]), dt.date.fromisoformat(digest["ventana"]["hasta"])
    days = await asyncio.to_thread(plan_rules.daily_data, patient_id, first, last)
    results = [plan_rules.test_hypothesis(h, patient_id, (first, last), days) for h in plan.hypotheses]
    scheduled, discarded = await asyncio.to_thread(plan_rules.validate, plan, digest, now, results)
    await asyncio.to_thread(_save, patient_id, plan_date, results, scheduled, discarded, now)
    _done.add((patient_id, plan_date.isoformat()))
    summary = {"plan_date": plan_date.isoformat(), "hipotesis": len(results), "pasaron": sum(r.passed for r in results),
               "agendadas": len(scheduled), "descartadas": len(discarded), "historia": historia,
               "nota": plan.note is not None, "nota_borradas": note_removed}
    log.info("plan del paciente %s: %s", patient_id, summary)
    return summary


async def plan_if_due(patient_id: int, now: dt.datetime) -> None:
    if now.hour < config.DAILY_PLAN_HOUR:
        return
    plan_date = now.date() + dt.timedelta(days=1)
    if (patient_id, plan_date.isoformat()) in _done or await asyncio.to_thread(_planned, patient_id, plan_date):
        return
    await run_plan(patient_id, now)


def _due(patient_id: int, now: dt.datetime) -> list[dict]:
    today, hhmm = now.date().isoformat(), now.strftime("%H:%M")
    with db.connect() as conn:
        conn.execute("UPDATE planned_actions SET status = 'descartada', discard_reason = 'venció sin ejecutarse' "
                     "WHERE patient_id = ? AND status = 'agendada' AND plan_date < ?", (patient_id, today))
        return [dict(r) for r in conn.execute(
            "SELECT * FROM planned_actions WHERE patient_id = ? AND status = 'agendada' AND plan_date = ? AND at <= ? "
            "ORDER BY at", (patient_id, today, hhmm))]


def _mark(action_id: int, status: str, reason: str | None = None) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE planned_actions SET status = ?, discard_reason = ? WHERE id = ?", (status, reason, action_id))


async def execute_due(patient_id: int, now: dt.datetime) -> list[int]:
    """Ejecuta las acciones agendadas cuya hora llegó. Devuelve los ids ejecutados."""
    from app.pipeline import ask as ask_pipeline
    from app.pipeline import context as context_builder

    done = []
    for a in await asyncio.to_thread(_due, patient_id, now):
        reason, why = a["reason"], a["why"] or ""
        try:
            if a["kind"] == "golpeteo":
                await notify.send(a["to_person_id"], "resumen", GAME_TITLE, reason, f"/casa/golpeteo?desde=plan&accion={a['id']}")
            else:
                if not await asyncio.to_thread(budget.allow, a["to_person_id"], "pregunta", now):
                    await asyncio.to_thread(_mark, a["id"], "descartada", "ya hubo una pregunta hoy (presupuesto)")
                    continue
                trigger = Trigger(rule_id="PLAN", patient_id=patient_id, to_person_id=a["to_person_id"],
                                  facts={"plan_reason": reason, "basis": a["basis"]}, why=why or reason)
                ctx = await context_builder.build(trigger, now)
                q = await ask_pipeline.ask(trigger, ctx)
                from app import _tmp_db
                qid = await asyncio.to_thread(_tmp_db.insert_question, patient_id=patient_id, to_person_id=a["to_person_id"],
                                              rule_id="PLAN", question=q.question, why=why or reason, options=q.options,
                                              status="enviada", sent_at=now)
                title = f"{ctx.patient_name}, una pregunta de hoy" if ctx.recipient_role == "paciente" else "Una pregunta de hoy"
                await notify.send(a["to_person_id"], "pregunta", title, q.question, f"/casa/pregunta/{qid}")
        except Exception as exc:          # una acción que falla no frena el tick
            log.error("no se pudo ejecutar la acción %s (%s)", a["id"], type(exc).__name__)
            await asyncio.to_thread(_mark, a["id"], "descartada", f"falló al ejecutarse ({type(exc).__name__})")
            continue
        await asyncio.to_thread(_mark, a["id"], "ejecutada")
        done.append(a["id"])
        log.info("acción %s del plan ejecutada (%s)", a["id"], a["kind"])
    return done


def link_test(patient_id: int, test_id: int, now: dt.datetime) -> int | None:
    """Si hoy se ejecutó una invitación al juego basada en un desvío, el juego queda en ese episodio."""
    with db.connect() as conn:
        row = conn.execute("SELECT basis FROM planned_actions WHERE patient_id = ? AND kind = 'golpeteo' "
                           "AND status = 'ejecutada' AND plan_date = ? AND basis LIKE 'desvio:%' ORDER BY id DESC LIMIT 1",
                           (patient_id, now.date().isoformat())).fetchone()
        if not row:
            return None
        episode_id = int(row["basis"].split(":")[1])
        conn.execute("UPDATE episodes SET test_id = ? WHERE id = ? AND patient_id = ? AND test_id IS NULL",
                     (test_id, episode_id, patient_id))
        return episode_id

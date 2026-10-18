# PromptContext de explain y ask (CLAUDE.md §11). Si el destinatario es el paciente, lo reservado no entra
# (§6.2 y §6.4): ni el texto ni que existe. Ese filtro es código puro, con tests.
import asyncio
import datetime as dt

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app.models import ContextEntry, Deviation, PromptContext, Trigger

RECENT_DAYS = 3


def for_recipient(rows: list[dict], recipient_role: str) -> list[ContextEntry]:
    """Relatos que puede ver quien recibe la pregunta. Al paciente nunca le llega nada reservado."""
    visible = [r for r in rows if not (recipient_role == "paciente" and r["reserved"])]
    return [ContextEntry(speaker_role=r["speaker_role"], text=r["raw_text"],
                         created_at=db.from_db(r["created_at"]) if isinstance(r["created_at"], str) else r["created_at"])
            for r in visible]


def deviation_from(trigger: Trigger) -> Deviation | None:
    """rules.triggers.p_desvio pone el Deviation directo en facts; también se acepta facts["deviation"]."""
    facts = trigger.facts or {}
    raw = facts.get("deviation") or (facts if {"dose_time", "observed", "median"} <= facts.keys() else None)
    return Deviation.model_validate(raw) if raw else None


async def build(trigger: Trigger, now: dt.datetime) -> PromptContext:
    role = await asyncio.to_thread(db.person_role, trigger.to_person_id)
    patient = await asyncio.to_thread(db.person_info, trigger.patient_id)
    rows = await asyncio.to_thread(db.recent_entries, trigger.patient_id, now - dt.timedelta(days=RECENT_DAYS))
    return PromptContext(now=now, patient_name=(patient or {}).get("name") or "el paciente",
                         recipient_role=role or "paciente", trigger=trigger, deviation=deviation_from(trigger),
                         recent_entries=for_recipient(rows, role or "paciente"))

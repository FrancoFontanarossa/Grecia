# POST /api/entries (CLAUDE.md §11): guarda el relato crudo y, dentro del mismo pedido, lo pasa por la extracción.
# Todavía sin audio, rojos ni avisos (vienen con transcribe y las reglas de Franco).
import asyncio
from typing import Literal, get_args

from fastapi import APIRouter, Form, HTTPException

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app import _tmp_rules as rules  # TEMPORAL: app.rules de Franco
from app import notify
from app.models import Entry, Event, OccurredHint
from app.pipeline import extract as extraction

router = APIRouter()

OCCURRED_HINTS = get_args(OccurredHint)

# TODO: mover a app/models.py. "app": entra por la PWA; "precorrer": relatos de la semana escritos por el equipo
# (scripts/precorrer_semana.py), rotulados así en la declaración del README.
EntrySource = Literal["app", "precorrer"]

AI_ERROR = "No pude entenderlo esta vez. Lo guardé tal cual para tu neuróloga."


@router.post("/api/entries")
async def create_entry(
    person_id: int = Form(...),
    text: str | None = Form(None),
    occurred_hint: str | None = Form(None),
    question_id: int | None = Form(None),
    quick_reply: str | None = Form(None),
    reserved_requested: bool = Form(False),
):
    if occurred_hint is not None and occurred_hint not in OCCURRED_HINTS:
        raise HTTPException(422, f"occurred_hint inválido: {occurred_hint!r}. Valores: {', '.join(OCCURRED_HINTS)}")
    raw_text = (text or quick_reply or "").strip()
    if not raw_text:
        # TODO: audio (pipeline.transcribe)
        raise HTTPException(422, "Falta el texto")

    person = await asyncio.to_thread(db.person_info, person_id)
    if person is None:
        raise HTTPException(404, f"No existe la persona {person_id}")
    if person["role"] not in ("paciente", "cuidador", "familiar"):
        raise HTTPException(403, "Solo el paciente y la familia cuentan relatos")

    source: EntrySource = "app"
    entry_id = await asyncio.to_thread(
        db.insert_entry, patient_id=person["patient_id"], speaker_id=person_id,
        modality="toque" if quick_reply and not text else "texto",
        raw_text=raw_text, question_id=question_id, occurred_hint=occurred_hint,
        reserved_requested=reserved_requested, source=source,
    )
    row = await asyncio.to_thread(db.get_entry, entry_id)
    entry = Entry.model_validate({**row, "speaker_role": person["role"]})

    response = {"entry_id": entry_id, "transcript": raw_text, "understood": [], "red": None, "alerts": []}
    try:
        events = await extraction.extract(entry, patient_name=person["patient_name"] or "el paciente",
                                          speaker_name=person["name"])
    except extraction.ExtractionError:
        response["error"] = AI_ERROR   # el relato crudo ya quedó guardado
    else:
        await _save_events(entry, events)
        response["understood"] = extraction.understood(events, db.now())
        # TODO: rules.lanes.evaluate + rules.consent.recipients → alerts

    await notify.send(person_id, "resumen", "Recibido", "Anotamos lo que contaste.", "/casa")
    return response


async def _save_events(entry: Entry, events: list[Event]) -> list[int]:
    """Guarda los eventos con is_new y reserved calculados por código (CLAUDE.md §6.4)."""
    if not events:
        return []
    mentioned = await asyncio.to_thread(db.mentioned_symptoms, entry.patient_id)
    consent = await asyncio.to_thread(db.canal_reservado_active, entry.patient_id)
    rows = [{**e.model_dump(), "minutes_since_dose": None,   # TODO: con med_schedule y doses de Franco
             "is_new": new,
             "reserved": rules.is_reserved(e, reserved_requested=entry.reserved_requested,
                                           canal_reservado_active=consent)}
            for e, new in zip(events, rules.mark_new(events, mentioned))]
    return await asyncio.to_thread(db.insert_events, entry.id, entry.patient_id, rows)

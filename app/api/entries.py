# POST /api/entries (CLAUDE.md §11): guarda el relato crudo y, dentro del mismo pedido, lo pasa por la extracción.
# Todavía sin audio, rojos ni avisos (vienen con transcribe y las reglas de Franco).
import asyncio
from typing import Literal

from fastapi import APIRouter, Form, HTTPException

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app import notify
from app.models import Entry
from app.pipeline import extract as extraction

router = APIRouter()

# TODO: reemplazar por OccurredHint de app/models.py cuando Franco lo sume.
OCCURRED_HINTS = ("ahora", "esta_manana", "esta_tarde", "anoche", "ayer")

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
        response["understood"] = extraction.understood(events, db.now())
        # TODO: guardar los eventos (tabla events de Franco) y pasar a rules.lanes / consent.
    except extraction.ExtractionError:
        response["error"] = AI_ERROR   # el relato crudo ya quedó guardado

    await notify.send(person_id, "resumen", "Recibido", "Anotamos lo que contaste.", "/casa")
    return response

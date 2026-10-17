# POST /api/entries (CLAUDE.md §11): guarda el relato crudo y, dentro del mismo pedido, transcribe (si es audio)
# corre los rojos (reglas + respaldo con IA que solo sube) y extrae los eventos. Sin avisos todavía.
import asyncio
import logging
import time
from typing import Literal, get_args

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app import _tmp_rules as rules  # TEMPORAL: app.rules de Franco
from app import notify
from app.models import Entry, Event, OccurredHint
from app.pipeline import extract as extraction
from app.pipeline import red_backup
from app.pipeline import transcribe as transcription

router = APIRouter()
log = logging.getLogger("entrecasa.entries")

OCCURRED_HINTS = get_args(OccurredHint)

# TODO: mover a app/models.py. "app": entra por la PWA; "precorrer": relatos de la semana escritos por el equipo
# (scripts/precorrer_semana.py), rotulados así en la declaración del README.
EntrySource = Literal["app", "precorrer"]

AI_ERROR = "No pude entenderlo esta vez. Lo guardé tal cual para tu neuróloga."


@router.post("/api/entries")
async def create_entry(
    person_id: int = Form(...),
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
    occurred_hint: str | None = Form(None),
    question_id: int | None = Form(None),
    quick_reply: str | None = Form(None),
    reserved_requested: bool = Form(False),
):
    t0 = time.perf_counter()
    timing: dict[str, float] = {}
    if occurred_hint is not None and occurred_hint not in OCCURRED_HINTS:
        raise HTTPException(422, f"occurred_hint inválido: {occurred_hint!r}. Valores: {', '.join(OCCURRED_HINTS)}")
    raw_text = (text or quick_reply or "").strip()
    if audio is None and not raw_text:
        raise HTTPException(422, "Falta el texto o el audio")

    person = await asyncio.to_thread(db.person_info, person_id)
    if person is None:
        raise HTTPException(404, f"No existe la persona {person_id}")
    if person["role"] not in ("paciente", "cuidador", "familiar"):
        raise HTTPException(403, "Solo el paciente y la familia cuentan relatos")

    audio_path = None
    if audio is not None:
        data = await audio.read()
        try:
            audio_path = await asyncio.to_thread(transcription.save_audio, data, audio.content_type)
        except transcription.UnsupportedAudio as exc:
            raise HTTPException(415, str(exc)) from exc
        raw_text = ""   # se completa con la transcripción; si falla queda "" y el audio guardado
        modality = "audio"
    else:
        modality = "toque" if quick_reply and not text else "texto"

    source: EntrySource = "app"
    entry_id = await asyncio.to_thread(
        db.insert_entry, patient_id=person["patient_id"], speaker_id=person_id, modality=modality,
        raw_text=raw_text, question_id=question_id, occurred_hint=occurred_hint,
        reserved_requested=reserved_requested, source=source,
        audio_path=str(audio_path.relative_to(db.data_dir())) if audio_path else None,
    )

    response = {"entry_id": entry_id, "transcript": raw_text, "understood": [], "red": None, "alerts": []}
    if question_id is not None:   # respuesta a una pregunta proactiva: queda respondida y entra al episodio
        await asyncio.to_thread(db.answer_question, question_id, person_id, entry_id)
    if audio_path is not None:
        t = time.perf_counter()
        try:
            raw_text = await transcription.transcribe(audio_path)
        except transcription.TranscriptionError:
            response["error"] = AI_ERROR   # el audio quedó guardado para la neuróloga
        else:
            await asyncio.to_thread(db.set_entry_text, entry_id, raw_text)
            response["transcript"] = raw_text
        timing["transcripcion"] = time.perf_counter() - t

    if raw_text:
        row = await asyncio.to_thread(db.get_entry, entry_id)
        entry = Entry.model_validate({**row, "speaker_role": person["role"]})
        meds = await asyncio.to_thread(db.patient_meds, entry.patient_id)

        # Rojos: primero las reglas (código); el respaldo con IA solo puede subir. ARQUITECTURA §3.1
        red = rules.red_check(raw_text, meds)
        is_red = red is not None and red.missing_criterion is None
        events: list[Event] | None = None
        t = time.perf_counter()
        if not is_red:   # con rojo por regla no se extrae
            # El respaldo y la extracción corren en paralelo para no sumar latencia; si el respaldo sube a rojo,
            # la extracción se descarta.
            extracted, verdict = await asyncio.gather(
                _extract_or_error(entry, person),
                red_backup.red_backup(raw_text, red, meds=meds),
            )
            if red is None and verdict.escalate:
                red, is_red = rules.red_from_backup(verdict.suspected_rule), True
            elif isinstance(extracted, extraction.ExtractionError):
                response["error"] = AI_ERROR   # el relato crudo ya quedó guardado
            else:
                events = extracted
        timing["rojos_y_extraccion"] = time.perf_counter() - t
        if red is not None:
            response["red"] = red.model_dump()
            # TODO: alerta roja con rules.lanes + rules.consent de Franco → notify.send(..., "rojo", ...)
        if events is not None:
            await _save_events(entry, events)
            response["understood"] = extraction.understood(events, await asyncio.to_thread(db.now))
            # TODO: rules.lanes.evaluate + rules.consent.recipients → alerts

    await notify.send(person_id, "resumen", "Recibido", "Anotamos lo que contaste.", "/casa")
    timing["total"] = time.perf_counter() - t0
    log.info("entrada %s (%s): %s", entry_id, modality, " · ".join(f"{k}={v:.1f}s" for k, v in timing.items()))
    return response


async def _extract_or_error(entry: Entry, person: dict) -> list[Event] | extraction.ExtractionError:
    try:
        return await extraction.extract(entry, patient_name=person["patient_name"] or "el paciente",
                                        speaker_name=person["name"])
    except extraction.ExtractionError as exc:
        return exc


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

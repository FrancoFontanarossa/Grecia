# POST /api/entries (CLAUDE.md §11): guarda el relato crudo y, dentro del mismo pedido, transcribe (si es audio),
# corre los rojos (rules.red + respaldo con IA que solo sube), extrae los eventos y pasa a los avisos
# (rules.lanes → destinatarios de rules.consent → push con notify.dispatch).
import asyncio
import logging
import time
from typing import Literal, get_args

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app import notify
from app.notify import dispatch
from app.rules import consent, lanes
from app.rules import red as red_rules
from app.models import Entry, Event, OccurredHint
from app.pipeline import extract as extraction
from app.pipeline import red_backup, report
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
    data = await audio.read() if audio is not None else None
    return await process_entry(person_id=person_id, text=text, audio=data,
                               audio_type=audio.content_type if audio is not None else None,
                               occurred_hint=occurred_hint, question_id=question_id, quick_reply=quick_reply,
                               reserved_requested=reserved_requested, source="app")


async def process_entry(*, person_id: int, text: str | None = None, audio: bytes | None = None,
                        audio_type: str | None = None, occurred_hint: str | None = None,
                        question_id: int | None = None, quick_reply: str | None = None,
                        reserved_requested: bool = False, source: EntrySource = "app") -> dict:
    """Todo el recorrido de un relato (CLAUDE.md §5.2). Lo usan la API y scripts/precorrer_semana.py."""
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
        try:
            audio_path = await asyncio.to_thread(transcription.save_audio, audio, audio_type)
        except transcription.UnsupportedAudio as exc:
            raise HTTPException(415, str(exc)) from exc
        raw_text = ""   # se completa con la transcripción; si falla queda "" y el audio guardado
        modality = "audio"
    else:
        modality = "toque" if quick_reply and not text else "texto"

    if question_id is not None and not await asyncio.to_thread(db.answerable_question, question_id, person_id):
        # Respuesta tardía (pregunta vencida, ya respondida o de otra persona): se guarda como relato común.
        log.info("pregunta %s no está abierta para %s: el relato se guarda sin question_id", question_id, person_id)
        question_id = None
    entry_id = await asyncio.to_thread(
        db.insert_entry, patient_id=person["patient_id"], speaker_id=person_id, modality=modality,
        raw_text=raw_text, question_id=question_id, occurred_hint=occurred_hint,
        reserved_requested=reserved_requested, source=source,
        audio_path=str(audio_path.relative_to(db.data_dir())) if audio_path else None,
    )

    response = {"entry_id": entry_id, "transcript": raw_text, "understood": [], "red": None, "alerts": []}
    if question_id is not None:   # respuesta a una pregunta proactiva: queda respondida y entra al episodio
        await asyncio.to_thread(db.answer_question, question_id, person_id, entry_id)
    raw_text = await _analyze(entry_id, person, raw_text, audio_path, response, timing)

    timing["total"] = time.perf_counter() - t0
    log.info("entrada %s (%s): %s", entry_id, modality, " · ".join(f"{k}={v:.1f}s" for k, v in timing.items()))
    return response


async def _analyze(entry_id: int, person: dict, raw_text: str, audio_path, response: dict, timing: dict) -> str:
    """Transcribe (si es audio), corre los rojos, extrae, guarda eventos y reparte los avisos. Completa `response`."""
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
        meds = await asyncio.to_thread(red_rules.patient_meds, entry.patient_id)

        # Rojos: primero las reglas (código); el respaldo con IA solo puede subir. ARQUITECTURA §3.1
        red = red_rules.evaluate(raw_text, meds)
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
                red, is_red = red_rules.from_backup(verdict.suspected_rule), True
            elif isinstance(extracted, extraction.ExtractionError):
                response["error"] = AI_ERROR   # el relato crudo ya quedó guardado
            else:
                events = extracted
        timing["rojos_y_extraccion"] = time.perf_counter() - t
        event_ids: list[int] = []
        if events is not None:
            event_ids = await _save_events(entry, events)
            if events:
                report.request_regeneration(entry.patient_id)   # en segundo plano, como mucho cada 30 s
            response["understood"] = extraction.understood(events, await asyncio.to_thread(db.now))
        if red is not None:
            response["red"] = red.model_dump()
        alerts = await asyncio.to_thread(lanes.evaluate, entry.patient_id, event_ids, red=red, speaker_id=entry.speaker_id)
        await dispatch.dispatch(alerts)
        response["alerts"] = [a.model_dump(mode="json") for a in alerts if _visible_to(a, person)]

    return raw_text


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
    active = await asyncio.to_thread(consent.canal_reservado_active, entry.patient_id, entry.speaker_id)
    rows = [{**e.model_dump(), "minutes_since_dose": None,   # TODO: con med_schedule y doses de Franco
             "is_new": new,
             "reserved": consent.is_reserved(e, reserved_requested=entry.reserved_requested,
                                             canal_reservado_active=active)}
            for e, new in zip(events, consent.mark_new(events, mentioned))]
    return await asyncio.to_thread(db.insert_events, entry.id, entry.patient_id, rows)


def _visible_to(alert, person: dict) -> bool:
    """La respuesta va a quien contó: el paciente nunca ve un aviso reservado (§6.4)."""
    return person["role"] != "paciente" or consent.patient_can_see(reserved=alert.reserved, lane=alert.lane)


@router.post("/api/entries/{entry_id}/confirm")
async def confirm_entry(entry_id: int):
    """"Sí, está bien": no vuelve a procesar nada (§11)."""
    if await asyncio.to_thread(db.get_entry, entry_id) is None:
        raise HTTPException(404, f"No existe la entrada {entry_id}")
    return {"ok": True}


@router.post("/api/entries/{entry_id}/correct")
async def correct_entry(entry_id: int, text: str | None = Form(None), audio: UploadFile | None = File(None)):
    """Corrige un relato con texto o audio: reemplaza el texto, borra sus eventos y los avisos A1/A2 que dejaron
    (nunca un rojo), vuelve a pasar por rojos, extracción y reglas, y marca corrected=1. Responde como POST /api/entries."""
    t0 = time.perf_counter()
    timing: dict[str, float] = {}
    row = await asyncio.to_thread(db.get_entry, entry_id)
    if row is None:
        raise HTTPException(404, f"No existe la entrada {entry_id}")
    raw_text = (text or "").strip()
    if audio is None and not raw_text:
        raise HTTPException(422, "Falta el texto o el audio")
    person = await asyncio.to_thread(db.person_info, row["speaker_id"])
    audio_path = None
    if audio is not None:
        try:
            audio_path = await asyncio.to_thread(transcription.save_audio, await audio.read(), audio.content_type)
        except transcription.UnsupportedAudio as exc:
            raise HTTPException(415, str(exc)) from exc
        raw_text = ""
    removed = await asyncio.to_thread(
        db.reset_for_correction, entry_id, raw_text=raw_text, modality="audio" if audio_path else "texto",
        audio_path=str(audio_path.relative_to(db.data_dir())) if audio_path else None,
        alert_label=lanes._label)
    log.info("entrada %s corregida: %s eventos y %s avisos borrados", entry_id, *removed)
    response = {"entry_id": entry_id, "transcript": raw_text, "understood": [], "red": None, "alerts": []}
    await _analyze(entry_id, person, raw_text, audio_path, response, timing)
    timing["total"] = time.perf_counter() - t0
    log.info("corrección %s: %s", entry_id, " · ".join(f"{k}={v:.1f}s" for k, v in timing.items()))
    return response

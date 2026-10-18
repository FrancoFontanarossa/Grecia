# pipeline.extract(entry) -> list[Event] · Haiku con tool use forzado + schema strict, validado con Pydantic.
# 1 reintento si la salida no valida; después ExtractionError (la entrada ya quedó guardada con el texto crudo).
import datetime as dt
import logging
import os
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app import taxonomy
from app.config import MODEL_EXTRACT, TZ
from app.models import Domain, Entry, Event
from app.pipeline import knowledge, when
from app.pipeline.when import TimeSaid

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract.md"
TOOL_NAME = "registrar_eventos"
MAX_ATTEMPTS = 2   # 1 intento + 1 reintento
MAX_TOKENS = 4096
MAX_TEXT_CHARS = 3000   # un relato más largo se guarda entero, pero a la IA le llega recortado

HINT_LABEL = {"ahora": "ahora", "esta_manana": "esta mañana", "esta_tarde": "esta tarde",
              "anoche": "anoche", "ayer": "ayer"}
_WEEKDAY_LABEL = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class ExtractionError(Exception):
    """La IA no devolvió eventos válidos después del reintento (o la API falló)."""


class ExtractedEvent(BaseModel):          # lo que devuelve el modelo; el código lo convierte en Event (models.py)
    domain: Domain
    symptom: str
    negated: bool
    foreign_attribution: str | None
    attribution_by: str | None = None        # quién dijo la atribución: quien_cuenta | paciente | otra_persona
    severity: int | None = Field(ge=0, le=4)
    time_said: TimeSaid
    quote: str = Field(min_length=1)
    plain: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ExtractionOutput(BaseModel):
    events: list[ExtractedEvent]


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def tool_schema() -> dict:
    """JSON schema strict de la herramienta. Dominios y síntomas salen de taxonomy (enums)."""
    event = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "enum": list(taxonomy.DOMAINS)},
            "symptom": {"type": "string", "enum": list(taxonomy.SYMPTOMS)},
            "negated": {"type": "boolean"},
            "foreign_attribution": _nullable({"type": "string"}),
            "attribution_by": _nullable({"type": "string", "enum": ["quien_cuenta", "paciente", "otra_persona"]}),
            "severity": _nullable({"type": "integer", "enum": [0, 1, 2, 3, 4]}),
            "time_said": {
                "type": "object",
                "properties": {
                    "day": {"type": "string", "enum": ["hoy", "ayer", "anteayer", "dia_semana", "no_dice", "habitual"]},
                    "weekday": _nullable({"type": "string", "enum": when.WEEKDAYS}),
                    "part": _nullable({"type": "string", "enum": list(when.PART_TIME)}),
                    "clock": _nullable({"type": "string", "description": "HH:MM, solo si el relato dice la hora"}),
                },
                "required": ["day", "weekday", "part", "clock"],
                "additionalProperties": False,
            },
            "quote": {"type": "string", "description": "copiada carácter por carácter del relato"},
            "plain": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["domain", "symptom", "negated", "foreign_attribution", "attribution_by", "severity", "time_said",
                     "quote", "plain", "confidence"],
        "additionalProperties": False,
    }
    return {
        "name": TOOL_NAME,
        "description": "Registra los eventos de salud del relato. Lista vacía si no hay ninguno.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"events": {"type": "array", "items": event}},
            "required": ["events"],
            "additionalProperties": False,
        },
    }


def _symptom_list() -> str:
    by_domain: dict[str, list[str]] = {}
    for symptom, domain in taxonomy.SYMPTOMS.items():
        by_domain.setdefault(domain, []).append(symptom)
    return "\n".join(f"  - `{d}`: {', '.join(s)}" for d, s in by_domain.items())


def system_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    text = knowledge.strip_comment(text)
    return text.replace("{{SINTOMAS}}", _symptom_list())


_SYSTEM = None
_client: anthropic.AsyncAnthropic | None = None


def _system_blocks() -> list[dict]:
    global _SYSTEM
    if _SYSTEM is None:
        _SYSTEM = system_prompt()
    # knowledge + prompt, siempre iguales → se cachean. Lo variable (contexto y relato) va en el mensaje de usuario.
    return knowledge.system_blocks(_SYSTEM)


def user_message(entry: Entry, *, patient_name: str, speaker_name: str | None) -> str:
    created = entry.created_at.astimezone(TZ)
    who = f"{speaker_name} ({entry.speaker_role})" if speaker_name else entry.speaker_role
    hint = HINT_LABEL[entry.occurred_hint] if entry.occurred_hint else "no lo eligió"
    text = entry.raw_text[:MAX_TEXT_CHARS].replace("</relato>", "</ relato>")   # el relato no puede cerrar la etiqueta
    if len(entry.raw_text) > MAX_TEXT_CHARS:
        text += "\n[… el relato sigue; se recortó para leerlo]"
    return (
        "<contexto>\n"
        f"Paciente: {patient_name}\n"
        f"Cuenta: {who}\n"
        f"Lo cargó: {_WEEKDAY_LABEL[created.weekday()]} {created:%d/%m/%Y %H:%M}\n"
        f"¿Cuándo pasó?: {hint}\n"
        "</contexto>\n"
        f"<relato>\n{text}\n</relato>"
    )


async def _call_model(system: list[dict], content: str):
    global _client
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        # sin esto el SDK lanza TypeError (no AnthropicError) y el pedido terminaría en 500
        raise ExtractionError("Falta ANTHROPIC_API_KEY")
    if _client is None:
        # Una key que no está atada a un workspace necesita el header anthropic-workspace-id.
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        _client = anthropic.AsyncAnthropic(
            timeout=30.0, max_retries=1,
            default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    # Haiku 5.5: sin temperature (cualquier valor distinto del default da 400). La consistencia sale del tool
    # forzado + schema strict + enums, y effort bajo. Con tool forzado el modelo no piensa antes de llamar.
    return await _client.messages.create(
        model=MODEL_EXTRACT,
        max_tokens=MAX_TOKENS,
        system=system,
        tools=[tool_schema()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": content}],
    )


def _parse(response, raw_text: str) -> ExtractionOutput:
    if response.stop_reason == "refusal":
        raise ExtractionError("El modelo se negó a procesar el relato")
    block = next((b for b in response.content if b.type == "tool_use" and b.name == TOOL_NAME), None)
    if block is None:
        raise ValueError(f"Sin llamada a {TOOL_NAME} (stop_reason={response.stop_reason})")
    output = ExtractionOutput.model_validate(block.input)
    for ev in output.events:
        if ev.quote not in raw_text:
            raise ValueError(f"La cita no está literal en el relato: {ev.quote!r}")
        if ev.foreign_attribution and ev.attribution_by in ("paciente", "otra_persona") and "vos pens" in ev.plain.lower():
            raise ValueError(f"La atribución «{ev.foreign_attribution}» la dijo otra persona, pero plain dice "
                             f"'Vos pensás': nombrá a quien la dijo ({ev.plain!r})")
    return output


def _unquote(value: str | None) -> str | None:
    """El modelo a veces copia las comillas del ejemplo: '"no es nada"' → 'no es nada'."""
    if value is None:
        return None
    value = value.strip().strip('"\'“”«»`').strip()
    return value or None


def to_event(ev: ExtractedEvent, entry: Entry) -> Event:
    symptom = taxonomy.normalize(ev.symptom)
    domain = ev.domain if symptom == "otro" else taxonomy.SYMPTOMS[symptom]   # manda la taxonomía
    occurred_at, time_vague = when.resolve(ev.time_said, entry.occurred_hint, entry.created_at)
    return Event(
        domain=domain, symptom=symptom, severity=ev.severity, negated=ev.negated,
        occurred_at=occurred_at, time_vague=time_vague,
        speaker_role=entry.speaker_role,                     # lo pone el código: quién cargó
        foreign_attribution=_unquote(ev.foreign_attribution), quote=ev.quote, plain=ev.plain.strip(),
        confidence=ev.confidence,
    )


async def extract(entry: Entry, *, patient_name: str = "el paciente",
                  speaker_name: str | None = None) -> list[Event]:
    if not entry.raw_text.strip():
        return []
    content = user_message(entry, patient_name=patient_name, speaker_name=speaker_name)
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        message = content if last_error is None else (
            f"{content}\n<correccion>Tu respuesta anterior fue rechazada por el código: {last_error}. "
            f"Respondé de nuevo con {TOOL_NAME}, corrigiendo eso.</correccion>")
        try:
            response = await _call_model(_system_blocks(), message)
        except anthropic.AnthropicError as exc:               # sin key, o el SDK ya reintentó 429/5xx/conexión
            raise ExtractionError(f"Falló la llamada a Claude: {exc}") from exc
        try:
            output = _parse(response, entry.raw_text)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            log.warning("Extracción inválida (intento %s/%s, entrada %s): %s", attempt, MAX_ATTEMPTS, entry.id, exc)
            continue
        return [to_event(ev, entry) for ev in output.events]
    raise ExtractionError(f"La extracción no validó después de {MAX_ATTEMPTS} intentos: {last_error}")


def understood(events: list[Event], now: dt.datetime) -> list[dict]:
    """Lo que muestra "Anoté esto": plain, when (código) y domain (+ su etiqueta)."""
    return [{"plain": e.plain, "when": when.describe(e.occurred_at, e.time_vague, now),
             "domain": e.domain, "domain_label": taxonomy.label(e.domain)} for e in events]

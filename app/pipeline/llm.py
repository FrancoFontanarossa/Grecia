# Llamadas a Sonnet (explain, ask, report) con una herramienta de salida y schema strict.
# Sonnet 5.5 rechaza el tool_choice forzado (400): se usa "auto" + la instrucción en el prompt, y si no llama a la
# herramienta o la salida no valida, se reintenta una vez. Fallback del lado del servidor si el modelo declina.
import logging
import os

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import MODEL_REASON
from app.pipeline import knowledge

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.AsyncAnthropic | None = None


class LLMError(Exception):
    """La llamada falló o la salida no validó después del reintento. `rejected`: las salidas que validaron el schema
    pero que `check` rechazó, en orden, con su error (el que llama puede decidir usar alguna)."""
    def __init__(self, message: str, rejected: list[tuple[BaseModel, Exception]] | None = None):
        super().__init__(message)
        self.rejected = rejected or []


async def _create(**kwargs):
    global _client
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise LLMError("Falta ANTHROPIC_API_KEY")
    if _client is None:
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        _client = anthropic.AsyncAnthropic(
            timeout=90.0, max_retries=1,
            default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    return await _client.beta.messages.create(**kwargs)


async def call_tool(prompt: str, tool: dict, content: str, output: type[BaseModel], *,
                    check=None, max_tokens: int = 4096, effort: str = "low",
                    attempts: int = MAX_ATTEMPTS) -> BaseModel:
    """Pide a Sonnet que responda con `tool` y devuelve la salida validada con `output`.
    `check(parsed)` puede lanzar ValueError para rechazar una salida válida pero que no cumple una regla del código."""
    system = knowledge.system_blocks(prompt)
    last: Exception | None = None
    rejected: list[tuple[BaseModel, Exception]] = []
    message = content
    for attempt in range(1, attempts + 1):
        if last is not None:   # el reintento sabe por qué se rechazó la respuesta anterior
            message = (f"{content}\n<correccion>Tu respuesta anterior fue rechazada por el código: {last}. "
                       f"Respondé de nuevo con la herramienta {tool['name']}, corrigiendo eso.</correccion>")
        try:
            response = await _create(
                model=MODEL_REASON,
                max_tokens=max_tokens,
                system=system,
                tools=[tool],
                tool_choice={"type": "auto"},
                output_config={"effort": effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
                messages=[{"role": "user", "content": message}],
            )
        except anthropic.AnthropicError as exc:   # el SDK ya reintentó 429/5xx/conexión
            raise LLMError(f"Falló la llamada a Claude: {exc}", rejected) from exc
        if response.stop_reason == "refusal":
            raise LLMError("El modelo (y el de respaldo) se negaron", rejected)
        block = next((b for b in response.content if b.type == "tool_use" and b.name == tool["name"]), None)
        parsed = None
        try:
            if block is None:
                raise ValueError(f"Sin llamada a {tool['name']} (stop_reason={response.stop_reason})")
            parsed = output.model_validate(block.input)
            if check:
                check(parsed)
            return parsed
        except (ValidationError, ValueError) as exc:
            last = exc
            if parsed is not None:
                rejected.append((parsed, exc))
            log.warning("%s inválido (intento %s/%s, %s)", tool["name"], attempt, attempts, type(exc).__name__)
    raise LLMError(f"{tool['name']} no validó después de {attempts} intentos: {last}", rejected)


_WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _when(value, *, year: bool = False) -> str:
    from app.config import TZ
    v = value.astimezone(TZ)
    return f"{_WEEKDAYS[v.weekday()]} {v:%d/%m/%Y %H:%M}" if year else f"{_WEEKDAYS[v.weekday()]} {v:%d/%m %H:%M}"


def render_context(ctx) -> str:
    """PromptContext → mensaje de usuario. Los relatos van como datos, dentro de etiquetas."""
    lines = [
        "<contexto>",
        f"Ahora: {_when(ctx.now, year=True)}",
        f"Paciente: {ctx.patient_name}",
        f"A quién se le pregunta: {ctx.recipient_role}",
        f"Disparador: {ctx.trigger.rule_id}",
        f"Por qué (lo arma el código, no lo repitas con cifras): {ctx.trigger.why}",
    ]
    if ctx.deviation is not None:
        d = ctx.deviation
        lines.append(f"Toma de referencia: {_when(d.dose_time)} (ventana {d.window})")
    lines.append("</contexto>")
    lines.append("<relatos_ultimos_3_dias>")
    if not ctx.recent_entries:
        lines.append("(ninguno)")
    for e in ctx.recent_entries:
        text = e.text.replace("</relato>", "</ relato>")
        lines.append(f'<relato quien="{e.speaker_role}" cuando="{_when(e.created_at)}">'
                     f"{text}</relato>")
    lines.append("</relatos_ultimos_3_dias>")
    return "\n".join(lines)

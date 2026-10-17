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
    """La llamada falló o la salida no validó después del reintento."""


async def _create(**kwargs):
    global _client
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise LLMError("Falta ANTHROPIC_API_KEY")
    if _client is None:
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        _client = anthropic.AsyncAnthropic(
            default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    return await _client.beta.messages.create(**kwargs)


async def call_tool(prompt: str, tool: dict, content: str, output: type[BaseModel], *,
                    check=None, max_tokens: int = 4096, effort: str = "low") -> BaseModel:
    """Pide a Sonnet que responda con `tool` y devuelve la salida validada con `output`.
    `check(parsed)` puede lanzar ValueError para rechazar una salida válida pero que no cumple una regla del código."""
    system = knowledge.system_blocks(prompt)
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
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
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AnthropicError as exc:   # el SDK ya reintentó 429/5xx/conexión
            raise LLMError(f"Falló la llamada a Claude: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("El modelo (y el de respaldo) se negaron")
        block = next((b for b in response.content if b.type == "tool_use" and b.name == tool["name"]), None)
        try:
            if block is None:
                raise ValueError(f"Sin llamada a {tool['name']} (stop_reason={response.stop_reason})")
            parsed = output.model_validate(block.input)
            if check:
                check(parsed)
            return parsed
        except (ValidationError, ValueError) as exc:
            last = exc
            log.warning("%s inválido (intento %s/%s): %s", tool["name"], attempt, MAX_ATTEMPTS, exc)
    raise LLMError(f"{tool['name']} no validó después de {MAX_ATTEMPTS} intentos: {last}")


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

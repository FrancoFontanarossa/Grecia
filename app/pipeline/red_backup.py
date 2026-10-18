# pipeline.red_backup: respaldo de las reglas de rojo con Haiku. SOLO puede subir a rojo, nunca bajarlo.
# Si las reglas ya dieron rojo no se llama al modelo. Si la llamada falla, devuelve escalate=False y lo registra:
# las reglas siguen mandando.
import logging
import os
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import MODEL_EXTRACT   # Haiku (CLAUDE.md §7.4: extracción y respaldo de rojos)
from app.models import RedResult
from app.pipeline import knowledge

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "red_backup.md"
TOOL_NAME = "evaluar_rojo"
RULES = ("R1", "R2", "R3", "R4")


class BackupVerdict(BaseModel):
    escalate: bool                     # True: el modelo ve un rojo que las reglas no vieron
    suspected_rule: Literal["R1", "R2", "R3", "R4"] | None
    reason: str


class _ModelOutput(BaseModel):
    is_red: bool
    suspected_rule: Literal["R1", "R2", "R3", "R4"] | None
    reason: str


TOOL = {
    "name": TOOL_NAME,
    "description": "Evalúa si el relato describe una señal de alarma (R1 a R4) que las reglas no detectaron.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "is_red": {"type": "boolean"},
            "suspected_rule": {"anyOf": [{"type": "string", "enum": list(RULES)}, {"type": "null"}]},
            "reason": {"type": "string"},
        },
        "required": ["is_red", "suspected_rule", "reason"],
        "additionalProperties": False,
    },
}

_SYSTEM: str | None = None
_client: anthropic.AsyncAnthropic | None = None


def system_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    return knowledge.strip_comment(text)


def user_message(text: str, meds: list[str]) -> str:
    safe = text[:3000].replace("</relato>", "</ relato>")
    return (f"<medicacion>\n{', '.join(meds) if meds else 'sin datos'}\n</medicacion>\n"
            f"<relato>\n{safe}\n</relato>")


async def _call_model(system: list[dict], content: str):
    global _client
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError("Falta ANTHROPIC_API_KEY")
    if _client is None:
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        _client = anthropic.AsyncAnthropic(
            timeout=20.0, max_retries=1,
            default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    # Haiku 5.5: sin temperature (400). Tool forzado + schema strict.
    return await _client.messages.create(
        model=MODEL_EXTRACT,
        max_tokens=1024,
        system=system,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": content}],
    )


async def red_backup(text: str, rules_result: RedResult | None, *, meds: list[str] | None = None) -> BackupVerdict:
    """¿Sube a rojo lo que las reglas no vieron? Nunca baja: con un rojo de las reglas no se consulta al modelo."""
    global _SYSTEM
    if rules_result is not None:
        return BackupVerdict(escalate=False, suspected_rule=None, reason="ya es rojo por las reglas")
    if not text.strip():
        return BackupVerdict(escalate=False, suspected_rule=None, reason="sin texto")
    if _SYSTEM is None:
        _SYSTEM = system_prompt()
    system = knowledge.system_blocks(_SYSTEM)
    try:
        response = await _call_model(system, user_message(text, meds or []))
        if response.stop_reason == "refusal":
            raise ValueError("el modelo se negó")
        block = next(b for b in response.content if b.type == "tool_use" and b.name == TOOL_NAME)
        out = _ModelOutput.model_validate(block.input)
    except (anthropic.AnthropicError, RuntimeError, ValueError, ValidationError, StopIteration) as exc:
        log.error("red_backup falló; mandan las reglas: %s", exc)
        return BackupVerdict(escalate=False, suspected_rule=None, reason=f"error: {exc}")
    if out.is_red and out.suspected_rule is None:
        # Solo puede subir: se escala igual y quien llama usa el texto fijo genérico.
        log.warning("red_backup dijo rojo sin regla: %s", out.reason)
    return BackupVerdict(escalate=out.is_red, suspected_rule=out.suspected_rule if out.is_red else None,
                         reason=out.reason)

# pipeline.explain(trigger, context) -> Explanation · ¿lo que ya contaron explica el disparador? Sonnet.
# El código verifica: solo cuenta como explicado si cada frase de `by` está literal en un relato del contexto.
# Si la IA falla, no se da por explicado (se pregunta): es el lado seguro.
import logging
from pathlib import Path

from pydantic import BaseModel

from app.models import Explanation, PromptContext, Trigger
from app.pipeline import knowledge, llm

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "explain.md"
TOOL = {
    "name": "registrar_explicacion",
    "description": "Registra si los relatos explican el disparador.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "explained": {"type": "boolean"},
            "by": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"},
        },
        "required": ["explained", "by", "reasoning"],
        "additionalProperties": False,
    },
}


class _Output(BaseModel):
    explained: bool
    by: list[str]
    reasoning: str


def prompt() -> str:
    return knowledge.strip_comment(PROMPT_PATH.read_text(encoding="utf-8"))


def trigger_id(context: PromptContext) -> str:
    return f"{context.trigger.rule_id}/paciente {context.trigger.patient_id}"


def verify(out: _Output, context: PromptContext) -> Explanation:
    """Explicado solo con citas literales de los relatos del contexto. Ante la duda, no explicado."""
    texts = [e.text for e in context.recent_entries]
    quotes = [q.strip() for q in out.by if q.strip()]
    literal = bool(quotes) and all(any(q in t for t in texts) for q in quotes)
    if out.explained and not literal:
        log.info("explain dijo explicado sin citas literales (%s); se pregunta igual", trigger_id(context))
        return Explanation(explained=False, by=[], reasoning=f"Sin cita literal que lo respalde. {out.reasoning}")
    return Explanation(explained=out.explained, by=quotes if out.explained else [], reasoning=out.reasoning)


async def explain(trigger: Trigger, context: PromptContext) -> Explanation:
    if not context.recent_entries:
        return Explanation(explained=False, by=[], reasoning="No hay relatos de los últimos 3 días.")
    try:
        out = await llm.call_tool(prompt(), TOOL, llm.render_context(context), _Output, max_tokens=2048)
    except llm.LLMError as exc:
        log.error("explain falló; se pregunta igual (%s)", type(exc).__name__)
        return Explanation(explained=False, by=[], reasoning=f"No se pudo evaluar: {exc}")
    return verify(out, context)

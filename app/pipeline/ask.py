# pipeline.ask(trigger, context) -> QuestionText · redacta la pregunta proactiva y 3 respuestas rápidas. Sonnet.
# El código rechaza (y reintenta una vez) una pregunta con cifras, términos clínicos o un número de opciones distinto
# de tres. Si la IA falla, se usa la pregunta fija del banco para ese disparador.
import logging
import re
from pathlib import Path

from pydantic import BaseModel

from app import question_bank
from app.models import PromptContext, QuestionText, Trigger
from app.pipeline import knowledge, llm
from app.taxonomy import _fold

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "ask.md"
MAX_QUESTION_WORDS = 25
MAX_OPTION_WORDS = 7
CLINICAL = re.compile(r"\b(rigidez|alucinaci\w*|discinesi\w*|bradicinesi\w*|off|wearing|sintoma\w*|dosis|"
                      r"medicacion|levodopa|pramipexol|diagnostic\w*|parkinson)\b")
TOOL = {
    "name": "redactar_pregunta",
    "description": "Redacta la pregunta corta y las tres respuestas rápidas.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question", "options"],
        "additionalProperties": False,
    },
}


class _Output(BaseModel):
    question: str
    options: list[str]


def prompt() -> str:
    return knowledge.strip_comment(PROMPT_PATH.read_text(encoding="utf-8"))


def check(out: _Output) -> None:
    """Reglas del código sobre el texto del modelo. ValueError → reintento."""
    q = out.question.strip()
    if not q or len(q.split()) > MAX_QUESTION_WORDS:
        raise ValueError("pregunta vacía o demasiado larga")
    if len(out.options) != 3 or any(not o.strip() or len(o.split()) > MAX_OPTION_WORDS for o in out.options):
        raise ValueError("tienen que ser exactamente tres respuestas cortas")
    for text in [q, *out.options]:
        if re.search(r"\d", text):
            raise ValueError(f"tiene cifras: {text!r}")
        if CLINICAL.search(_fold(text)):
            raise ValueError(f"tiene términos clínicos: {text!r}")


async def ask(trigger: Trigger, context: PromptContext) -> QuestionText:
    try:
        out = await llm.call_tool(prompt(), TOOL, llm.render_context(context), _Output, check=check, max_tokens=2048)
    except llm.LLMError as exc:
        log.error("ask falló; pregunta fija del banco para %s: %s", trigger.rule_id, exc)
        return question_bank.proactive(trigger.rule_id, context.patient_name, context.recipient_role)
    return QuestionText(question=out.question.strip(), options=[o.strip() for o in out.options])

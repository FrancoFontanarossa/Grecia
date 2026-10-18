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


DEFAULT_BASELINE_LABEL = "otras tardes"
# Afirmar contra qué se compara solo vale si lo dice la base que usó el código (Franco usa la combinada si el
# estrato tiene menos de 10 puntos). Días de la semana, "fin de semana" o "días hábiles": solo si vienen en facts.
COMPARISON_WORDS = re.compile(r"\b(lunes|martes|miercoles|jueves|viernes|sabados?|domingos?|fines? de semana|"
                              r"habiles?)\b")


def baseline_label(trigger: Trigger) -> str:
    """La base contra la que comparó el código: facts["baseline_label"], o lo que rules.triggers puso antes de "≈"
    en el why ("Otras tardes de semana ≈ 1.300 pasos…" → "otras tardes de semana"), o "otras tardes"."""
    label = (trigger.facts or {}).get("baseline_label")
    if not label and "≈" in (trigger.why or ""):
        label = trigger.why.split("≈", 1)[0].strip()
    return str(label or DEFAULT_BASELINE_LABEL).lower()


def _facts_text(trigger: Trigger) -> str:
    values = [str(v) for v in (trigger.facts or {}).values() if isinstance(v, str)]
    return _fold(" ".join([*values, baseline_label(trigger)]))


def check(out: _Output, trigger: Trigger | None = None) -> None:
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
    allowed = _facts_text(trigger) if trigger else ""
    for word in COMPARISON_WORDS.findall(_fold(q)):
        if word not in allowed:
            raise ValueError(f"afirma una comparación que no viene en facts: {word!r}")


def user_message(trigger: Trigger, context: PromptContext) -> str:
    return (llm.render_context(context)
            + f"\n<comparacion>Si decís contra qué se compara, usá exactamente: \"{baseline_label(trigger)}\". "
            "No nombres días de la semana.</comparacion>")


async def ask(trigger: Trigger, context: PromptContext) -> QuestionText:
    try:
        out = await llm.call_tool(prompt(), TOOL, user_message(trigger, context), _Output,
                                  check=lambda o: check(o, trigger), max_tokens=2048)
    except llm.LLMError as exc:
        log.error("ask falló; pregunta fija del banco para %s: %s", trigger.rule_id, exc)
        return question_bank.proactive(trigger.rule_id, context.patient_name, context.recipient_role,
                                       baseline_label=baseline_label(trigger))
    return QuestionText(question=out.question.strip(), options=[o.strip() for o in out.options])

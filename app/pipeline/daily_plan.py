# pipeline.daily_plan(digest) -> DailyPlan · revisión diaria (modo 2). Sonnet con tool use + JSON schema + Pydantic,
# 1 reintento. La IA escribe la nota del día (bitácora, solo para el equipo médico; la limpia rules.note), propone
# hipótesis (vocabulario cerrado) y hasta 2 acciones para mañana; rules.plan las prueba y decide.
# Si la IA falla o no valida: plan vacío y el error al log. Nunca rompe el scheduler.
import json
import logging
import re
from pathlib import Path

from app.models import DailyPlan
from app.pipeline import knowledge, llm
from app.taxonomy import _fold

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "daily_plan.md"
FORBIDDEN = re.compile(r"\b(diagnostic\w*|estadio|off|on/off|wearing\w*|dosis|medicacion|levodopa|carbidopa|"
                       r"pramipexol|apixaban|causa\w*|provoca\w*)\b")

_HYP = {
    "type": "object",
    "properties": {
        "condition": {"type": "string"},
        "metric": {"type": "string"},
        "lag_days": {"type": "integer", "enum": [0, 1]},
        "direction": {"type": "string", "enum": ["mas", "menos"]},
        "reason": {"type": "string"},
    },
    "required": ["condition", "metric", "lag_days", "direction", "reason"],
    "additionalProperties": False,
}
_ACTION = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["golpeteo", "pregunta", "seguimiento", "nada"]},
        "at": {"type": "string"},
        "to_role": {"type": "string", "enum": ["paciente", "cuidador", "familiar"]},
        "reason": {"type": "string"},
        "basis": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "at", "to_role", "reason", "basis", "evidence_ids"],
    "additionalProperties": False,
}
_NOTE = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "points": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "evidence_ids"],
            "additionalProperties": False,
        }},
        "follow_up": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "points", "follow_up"],
    "additionalProperties": False,
}
TOOL = {
    "name": "planificar_manana",
    "description": "La nota del día para el equipo médico, hipótesis para que el código las pruebe y hasta dos "
                   "acciones para mañana.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"note": _NOTE, "hypotheses": {"type": "array", "items": _HYP},
                       "actions": {"type": "array", "items": _ACTION}},
        "required": ["note", "hypotheses", "actions"],
        "additionalProperties": False,
    },
}


def prompt() -> str:
    return knowledge.strip_comment(PROMPT_PATH.read_text(encoding="utf-8"))


def check(plan: DailyPlan) -> None:
    """Reglas del código sobre lo que escribió el modelo. ValueError → reintento."""
    texts = [h.reason for h in plan.hypotheses] + [a.reason for a in plan.actions]
    for text in texts:
        if re.search(r"\d", text):
            raise ValueError(f"un motivo tiene cifras (las pone el código): {text!r}")
        if FORBIDDEN.search(_fold(text)):
            raise ValueError(f"un motivo diagnostica, habla de medicación o de causa: {text!r}")
    # La nota no se valida acá: rules.note borra la frase con cifras ajenas o palabras prohibidas (medicación,
    # diagnóstico, causa) sin perder el resto del plan.


def user_message(digest: dict) -> str:
    return ("<resumen>\n" + json.dumps(digest, ensure_ascii=False, indent=1) + "\n</resumen>\n"
            "Escribí la nota de hoy y planificá mañana con la herramienta planificar_manana.")


async def daily_plan(digest: dict) -> DailyPlan:
    try:
        return await llm.call_tool(prompt(), TOOL, user_message(digest), DailyPlan, check=check,
                                   max_tokens=4096, effort="medium")
    except llm.LLMError as exc:
        log.error("daily_plan falló para el paciente %s: plan vacío (%s)", digest.get("patient_id"), exc)
        return DailyPlan()

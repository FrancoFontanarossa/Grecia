from fastapi import APIRouter, HTTPException

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])


def why_chart(facts: dict) -> dict | None:
    """Datos del gráfico "Por qué te pregunto" a partir de Trigger.facts (cifras del código, nunca del modelo).
    Para P-DESVIO usa los campos de Deviation: observed, median, window; y day_label ("sábados") si viene."""
    if "observed" not in facts or "median" not in facts:
        return None
    median = float(facts["median"])
    observed = float(facts["observed"])
    window = facts.get("window", "")
    day_label = facts.get("day_label") or "días"
    dose = facts.get("dose_label") or (f"de las {facts['dose_hour']}" if facts.get("dose_hour") else "")
    return {
        "usual": {"label": f"Otros {day_label}, {window}".strip(", "), "value": round(median), "approx": True,
                  "pct": 100},
        "today": {"label": f"Hoy, después de la toma {dose}".strip(), "value": round(observed),
                  "pct": max(2, min(100, round(observed / median * 100))) if median else 0},
    }


def _fake_question(question_id: int) -> dict | None:
    # TODO(contrato): reemplazar por la tabla questions (la crea el scheduler con pipeline.ask; why y facts del código).
    if question_id != 1:
        return None
    facts = {"observed": 420, "median": 1300, "window": "16 a 18 h", "day_label": "sábados", "dose_hour": 16}
    return {
        "id": 1, "person_id": 1, "rule_id": "P-DESVIO",
        "question": "Juan, hoy a la tarde caminaste menos que otros sábados. ¿Pasó algo?",
        "why": "Otros sábados, de 16 a 18 h: unos 1.300 pasos. Hoy, después de la toma de las 16: 420.",
        "options": ["Me sentí trabado", "Estaba cansado", "Me quedé en casa nomás"],
        "url": "/casa/pregunta/1", "status": "enviada", "facts": facts, "simulated": True,
    }


def get_question(question_id: int) -> dict:
    q = _fake_question(question_id)
    if not q:
        raise HTTPException(404, "No encontramos esa pregunta.")
    q["chart"] = why_chart(q.get("facts") or {})
    return q


@router.get("/questions/{question_id}")
def question(question_id: int):
    return get_question(question_id)

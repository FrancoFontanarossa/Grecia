import datetime as dt

from fastapi import APIRouter, HTTPException

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])


def why_chart(dev: dict | None) -> dict | None:
    """Gráfico "Por qué te pregunto" con las cifras del Deviation (código, nunca el modelo).
    La etiqueta dice la base que realmente se usó (CLAUDE.md §7.3): días hábiles, fin de semana o todos."""
    if not dev or "observed" not in dev or "median" not in dev:
        return None
    median, observed = float(dev["median"]), float(dev["observed"])
    dose = dt.datetime.fromisoformat(dev["dose_time"]) if dev.get("dose_time") else None
    end_h = (dose + dt.timedelta(hours=2)).hour if dose else None
    window = f"{dose.hour} a {end_h} h" if dose else dev.get("window", "")
    if dev.get("baseline") == "estrato" and dose:
        usual = "Otros fines de semana" if dose.weekday() >= 5 else "Otros días de semana"
    else:
        usual = "Otros días"
    part = ("a la mañana" if dose.hour < 12 else "a la tarde" if dose.hour < 20 else "a la noche") if dose else ""
    return {
        # La conclusión primero (REFERENCIAS.md): la arma el código, sin cifras; las cifras van en las barras.
        "headline": f"Hoy {part} caminaste menos que de costumbre".replace("  ", " "),
        "usual": {"label": f"{usual}, {window}", "value": round(median), "approx": True, "pct": 100},
        "today": {"label": f"Hoy, después de la toma de las {dose.hour}" if dose else "Hoy",
                  "value": round(observed), "pct": max(2, min(100, round(observed / median * 100))) if median else 0},
    }


def _fake_question(question_id: int) -> dict | None:
    # Sin base: la pregunta del lienzo de diseño, rotulada como ejemplo.
    if question_id != 1:
        return None
    return {
        "id": 1, "person_id": 1, "rule_id": "P-DESVIO",
        "question": "Juan, hoy a la tarde caminaste menos que otros sábados. ¿Pasó algo?",
        "why": "Otros fines de semana, de 16 a 18 h: unos 1.300 pasos. Hoy, después de la toma de las 16: 420.",
        "options": ["Me sentí trabado", "Estaba cansado", "Me quedé en casa nomás"],
        "url": "/casa/pregunta/1", "status": "enviada", "simulated": True,
        "deviation": {"dose_time": "2026-10-17T16:00:00-03:00", "window": "16:00-18:00", "observed": 420,
                      "median": 1300, "z": -4.1, "pct_change": -0.68, "baseline": "estrato", "baseline_n": 8},
    }


def get_question(question_id: int) -> dict:
    q = store.question(question_id) if store.has_db() else _fake_question(question_id)
    if not q:
        raise HTTPException(404, "No encontramos esa pregunta.")
    q["chart"] = why_chart(q.get("deviation"))
    return q


@router.get("/questions/{question_id}")
def question(question_id: int):
    return get_question(question_id)

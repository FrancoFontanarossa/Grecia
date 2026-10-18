import statistics
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api import _store as store
from app.models import GameResult, TapEvent

router = APIRouter(prefix="/api", tags=["app"])


class TestIn(BaseModel):
    person_id: int
    type: Literal["golpeteo"] = "golpeteo"
    taps: list[TapEvent] = Field(max_length=400)


def _score(patient_id: int, taps: list[TapEvent]) -> tuple[GameResult, bool]:
    """Devuelve (resultado, simulado). El puntaje es de rules.games (Franco); mientras no exista, un cálculo
    provisorio con la misma forma, marcado como simulado."""
    try:
        from app.rules import games  # type: ignore

        return games.score(taps, patient_id=patient_id, taken_at=store.now()), False
    except ImportError:
        pass
    # TODO(contrato): reemplazar cuando exista rules.games.score (con tests y la comparación contra el historial).
    times = [t.t_ms for t in taps]
    intervals = [b - a for a, b in zip(times, times[1:]) if b > a]
    mean = statistics.fmean(intervals) if intervals else 0
    cv = (statistics.pstdev(intervals) / mean) if len(intervals) > 1 and mean else 0.0
    left = sum(1 for t in taps if t.side == "izq")
    right = len(taps) - left
    taps_per_s = len(taps) / 20
    history = [h["metrics"]["taps_per_s"] for h in store.tests_history(patient_id)][-7:]
    if len(history) < 3:
        vs = "sin_historial"
    else:
        vs = "mas_lento" if taps_per_s < 0.85 * statistics.median(history) else "parecido"
    result = GameResult(patient_id=patient_id, game="tapping", taken_at=store.now(),
                        metrics={"taps_per_s": round(taps_per_s, 2), "interval_cv": round(cv, 3),
                                 "left_right_ratio": round(left / right, 2) if right else 0.0},
                        vs_history=vs)
    return result, True


@router.post("/tests")
def create_test(body: TestIn):
    person = store.person(body.person_id)
    if not person:
        raise HTTPException(404, "No encontramos a esa persona.")
    patient_id = person["patient_id"]
    previous = store.tests_history(patient_id)[-6:]
    result, simulated = _score(patient_id, body.taps)
    store.save_test({"patient_id": patient_id, "taken_at": result.taken_at.isoformat(), "metrics": result.metrics,
                     "raw": [t.model_dump() for t in body.taps], "source": "app"})
    episode_id = None
    if store.has_db():   # modo 2: si el juego vino de una invitación del plan basada en un desvío, va a ese episodio
        from app import db, plan_jobs
        with db.connect() as conn:
            test_id = conn.execute("SELECT max(id) FROM tests WHERE patient_id = ?", (patient_id,)).fetchone()[0]
        episode_id = plan_jobs.link_test(patient_id, test_id, store.now()) if test_id else None
    return {**result.model_dump(mode="json"), "simulated": simulated, "episode_id": episode_id,
            "history": [{"taken_at": h["taken_at"], "taps_per_s": h["metrics"]["taps_per_s"]} for h in previous]}

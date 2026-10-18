# Puntaje del golpeteo (CLAUDE.md §5.4) y comparación contra el propio historial. Nunca es diagnóstico.
import json
from datetime import datetime
from statistics import mean, median, pstdev
from typing import Literal

from app import clock, config, db
from app.models import GameResult, TapEvent

VsHistory = Literal["parecido", "mas_lento", "sin_historial"]


def metrics(taps: list[TapEvent]) -> dict[str, float]:
    """taps_per_s: toques entre el primero y el último; interval_cv: desvío/promedio de los intervalos;
    left_right_ratio: toques con la izquierda sobre toques con la derecha (0 si no hubo derecha)."""
    ordered = sorted(taps, key=lambda t: t.t_ms)
    intervals = [(b.t_ms - a.t_ms) / 1000 for a, b in zip(ordered, ordered[1:])]
    span = sum(intervals)
    left = sum(t.side == "izq" for t in ordered)
    right = len(ordered) - left
    return {
        "taps_per_s": round(len(intervals) / span, 2) if span > 0 else 0.0,
        "interval_cv": round(pstdev(intervals) / mean(intervals), 3) if len(intervals) > 1 and mean(intervals) > 0 else 0.0,
        "left_right_ratio": round(left / right, 3) if right else 0.0,
    }


def history(patient_id: int, before: datetime, limit: int = config.GAME_HISTORY) -> list[float]:
    """toques/s de las últimas `limit` sesiones de golpeteo antes de `before`."""
    with db.connect() as conn:
        rows = conn.execute("SELECT metrics FROM tests WHERE patient_id = ? AND type = 'golpeteo' AND taken_at < ? "
                            "ORDER BY taken_at DESC LIMIT ?", (patient_id, db.to_db(before), limit)).fetchall()
    return [json.loads(r["metrics"])["taps_per_s"] for r in rows]


def vs_history(taps_per_s: float, past: list[float]) -> VsHistory:
    if len(past) < config.GAME_MIN_HISTORY:
        return "sin_historial"
    return "mas_lento" if taps_per_s < config.GAME_SLOWER_RATIO * median(past) else "parecido"


def score(taps: list[TapEvent], *, patient_id: int, taken_at: datetime | None = None) -> GameResult:
    """Contrato de §11, con el paciente para leer su historial. No guarda la sesión (eso lo hace la API)."""
    taken_at = taken_at or clock.now()
    m = metrics(taps)
    return GameResult(patient_id=patient_id, game="tapping", taken_at=taken_at, metrics=m,
                      vs_history=vs_history(m["taps_per_s"], history(patient_id, taken_at)))

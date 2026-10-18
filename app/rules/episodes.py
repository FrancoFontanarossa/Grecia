# Desvío de pasos después de una toma (CLAUDE.md §7.3). Estadística robusta, sin LLM.
#   x = pasos en [toma, toma + 120 min). Sin un biometric_syncs que cubra la ventana: None (no se sabe);
#   con sync y sin muestras: x = 0.
#   Base = la misma ventana en las tomas de esa hora de los 28 días previos, del mismo estrato (hábil o
#   fin de semana), sin los días que ya son episodio ni las ventanas con pasos inyectados. Si el estrato
#   tiene menos de 10 puntos, base combinada; si tampoco llega, None.
#   z = (x − mediana) / (1,4826 · MAD), con MAD ≥ 10% de la mediana. Desvío si z ≤ −2,5 y caída ≥ 40%.
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Literal

from app import config, db
from app.config import TZ
from app.models import Deviation

WEEKEND = {5, 6}


@dataclass
class Baseline:
    kind: Literal["estrato", "combinada"]
    values: list[float]
    weekend: bool


def window(dose_time: datetime) -> tuple[datetime, datetime]:
    start = dose_time.astimezone(TZ)
    return start, start + timedelta(minutes=config.DEVIATION_WINDOW_MINUTES)


def _covered(conn, patient_id: int, start: datetime, end: datetime) -> bool:
    return conn.execute(
        "SELECT 1 FROM biometric_syncs WHERE patient_id = ? AND scope IS NULL AND window_start <= ? AND window_end >= ? "
        "LIMIT 1",
        (patient_id, db.to_db(start), db.to_db(end))).fetchone() is not None


def _steps(conn, patient_id: int, start: datetime, end: datetime) -> float:
    return conn.execute(
        "SELECT coalesce(sum(value), 0) FROM biometrics WHERE patient_id = ? AND kind = 'steps' "
        "AND start >= ? AND start < ?", (patient_id, db.to_db(start), db.to_db(end))).fetchone()[0]


def _excluded(conn, patient_id: int, start: datetime, end: datetime) -> bool:
    """Días que ya son episodio en esa toma, o con la ventana inyectada (no ensucian la base)."""
    episode = conn.execute("SELECT 1 FROM episodes WHERE patient_id = ? AND substr(dose_time, 1, 16) = ? LIMIT 1",
                           (patient_id, db.to_db(start)[:16])).fetchone()
    injected = conn.execute(
        "SELECT 1 FROM biometrics WHERE patient_id = ? AND source = 'inyectado' AND start >= ? AND start < ? LIMIT 1",
        (patient_id, db.to_db(start), db.to_db(end))).fetchone()
    return bool(episode or injected)


def _dose_scheduled(conn, patient_id: int, at: datetime) -> bool:
    return conn.execute("SELECT 1 FROM doses WHERE patient_id = ? AND scheduled_at = ? LIMIT 1",
                        (patient_id, db.to_db(at))).fetchone() is not None


def observed(patient_id: int, dose_time: datetime) -> float | None:
    """Pasos en la ventana, o None si ningún sync la cubre."""
    start, end = window(dose_time)
    with db.connect() as conn:
        return _steps(conn, patient_id, start, end) if _covered(conn, patient_id, start, end) else None


def baseline(patient_id: int, dose_time: datetime) -> Baseline | None:
    start, _ = window(dose_time)
    weekend = start.weekday() in WEEKEND
    points: list[tuple[bool, float]] = []
    with db.connect() as conn:
        for k in range(1, config.DEVIATION_BASELINE_DAYS + 1):
            s, e = window(start - timedelta(days=k))
            if (_dose_scheduled(conn, patient_id, s) and _covered(conn, patient_id, s, e)
                    and not _excluded(conn, patient_id, s, e)):
                points.append((s.weekday() in WEEKEND, _steps(conn, patient_id, s, e)))
    stratum = [v for w, v in points if w == weekend]
    if len(stratum) >= config.DEVIATION_MIN_POINTS:
        return Baseline("estrato", stratum, weekend)
    if len(points) >= config.DEVIATION_MIN_POINTS:
        return Baseline("combinada", [v for _, v in points], weekend)
    return None


def deviation(patient_id: int, dose_time: datetime) -> Deviation | None:
    x = observed(patient_id, dose_time)
    if x is None:
        return None
    base = baseline(patient_id, dose_time)
    if base is None:
        return None
    med = median(base.values)
    if med <= 0:
        return None                     # sin pasos de costumbre no hay caída que medir
    mad = max(median(abs(v - med) for v in base.values), config.DEVIATION_MAD_FLOOR * med)
    z = (x - med) / (config.DEVIATION_MAD_SCALE * mad)
    pct_change = (x - med) / med * 100
    if z > config.DEVIATION_Z_MAX or pct_change > -config.DEVIATION_MIN_DROP * 100:
        return None
    start, end = window(dose_time)
    return Deviation(dose_time=start, window=f"{start:%H:%M}–{end:%H:%M}", observed=round(x), median=med,
                     z=round(z, 2), pct_change=round(pct_change, 1), baseline=base.kind,
                     baseline_n=len(base.values))

# Meta de pasos del día (CLAUDE.md §4.10 y §5.6). Un día con episodio o rojo es "día difícil": no cuenta
# como fallado. Después de un rojo la meta queda en pausa (goals.paused_reason = "rojo") hasta que el rojo
# se marque como atendido (alerts.acked_at); en pausa no se logra la meta, así nada empuja a moverse.
from datetime import date, datetime, time, timedelta

from app import db
from app.config import TZ
from app.models import GoalDay


def _day_bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time(0), TZ)
    return db.to_db(start), db.to_db(start + timedelta(days=1))


def paused(patient_id: int) -> bool:
    """¿La meta está en pausa por un rojo?"""
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM goals WHERE patient_id = ? AND metric = 'steps' AND active = 1 "
                           "AND paused_reason = 'rojo' LIMIT 1", (patient_id,)).fetchone()
    return row is not None


def status(patient_id: int, day: date) -> GoalDay | None:
    """Estado de la meta de pasos de ese día (lo guarda en goal_days). None si el paciente no tiene meta."""
    start, end = _day_bounds(day)
    with db.connect() as conn:
        goal = conn.execute("SELECT id, target FROM goals WHERE patient_id = ? AND metric = 'steps' AND active = 1 "
                            "ORDER BY id DESC LIMIT 1", (patient_id,)).fetchone()
        if goal is None:
            return None
        value = conn.execute("SELECT coalesce(sum(value), 0) FROM biometrics WHERE patient_id = ? AND kind = 'steps' "
                             "AND start >= ? AND start < ?", (patient_id, start, end)).fetchone()[0]
        red_that_day = conn.execute("SELECT 1 FROM alerts WHERE patient_id = ? AND lane = 'rojo' "
                                    "AND created_at >= ? AND created_at < ? LIMIT 1", (patient_id, start, end)).fetchone()
        episode_that_day = conn.execute("SELECT 1 FROM episodes WHERE patient_id = ? AND dose_time >= ? AND dose_time < ? "
                                        "LIMIT 1", (patient_id, start, end)).fetchone()
        paused = conn.execute("SELECT 1 FROM alerts WHERE patient_id = ? AND lane = 'rojo' AND acked_at IS NULL "
                              "AND created_at < ? LIMIT 1", (patient_id, end)).fetchone() is not None
        conn.execute("UPDATE goals SET paused_reason = ? WHERE id = ? AND coalesce(paused_reason, '') IN ('', 'rojo')",
                     ("rojo" if paused else None, goal["id"]))
        hard_day = bool(red_that_day or episode_that_day or paused)
        achieved = value >= goal["target"] and not paused
        row = conn.execute(
            "INSERT INTO goal_days (goal_id, date, value, achieved, hard_day) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (goal_id, date) DO UPDATE SET value = excluded.value, achieved = excluded.achieved, "
            "hard_day = excluded.hard_day RETURNING id, notified",
            (goal["id"], day.isoformat(), value, int(achieved), int(hard_day))).fetchone()
    return GoalDay(id=row["id"], goal_id=goal["id"], date=day, value=value, achieved=achieved,
                   hard_day=hard_day, notified=bool(row["notified"]))

"""Pasos de prueba para las reglas: 16:00 y 17:00 de cada día del período, con un sync que lo cubre."""
import datetime as dt

from app import db
from app.config import TZ

START, END = dt.date(2026, 9, 20), dt.date(2026, 10, 17)


def usual(day: dt.date) -> float:
    """Pasos de 16 a 18 de un día normal: ~1.300, con algo de variación (fines de semana un poco menos)."""
    base = 1100 if day.weekday() >= 5 else 1300
    return base + (day.toordinal() % 5 - 2) * 40


def load(overrides: dict[dt.date, float | None] | None = None, *, sync=True, start=START, end=END):
    """Carga las ventanas de 16 a 18. overrides: día → pasos de 16 a 18 (None = sin muestras ese día)."""
    overrides = overrides or {}
    rows, day = [], start
    while day <= end:
        total = overrides.get(day, usual(day))
        if total is not None:
            for h in (16, 17):
                s = dt.datetime.combine(day, dt.time(h), TZ)
                rows.append((total / 2, db.to_db(s), db.to_db(s + dt.timedelta(hours=1))))
        day += dt.timedelta(days=1)
    with db.connect() as conn:
        conn.executemany('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) '
                         "VALUES (1, 'steps', ?, ?, ?, 'importacion')", rows)
    if sync:
        add_sync(dt.datetime.combine(start, dt.time(0), TZ), dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0), TZ))


def add_sync(start: dt.datetime, end: dt.datetime, patient_id: int = 1):
    with db.connect() as conn:
        conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
                     "VALUES (?, ?, ?, ?, 0)", (patient_id, db.to_db(start), db.to_db(end), db.to_db(end)))


def at16(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(16), TZ)

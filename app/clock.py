# Reloj de demo: la única fuente de la hora (CLAUDE.md §0). now() = hora real + offset guardado en
# clock_state, así el reloj sobrevive a un redeploy (ARQUITECTURA §4.3). Siempre en America/Montevideo.
from datetime import datetime, timedelta

from app import db
from app.config import TZ


def _real_now() -> datetime:
    # Único lugar del código que lee la hora real.
    return datetime.now(TZ)


def offset() -> timedelta:
    with db.connect() as conn:
        row = conn.execute("SELECT offset_seconds FROM clock_state WHERE id = 1").fetchone()
    return timedelta(seconds=row["offset_seconds"] if row else 0)


def now() -> datetime:
    return _real_now() + offset()


def _save(seconds: float) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO clock_state (id, offset_seconds, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET offset_seconds = excluded.offset_seconds, "
            "updated_at = excluded.updated_at",
            (seconds, db.to_db(_real_now())),
        )


def advance(minutes: float) -> datetime:
    _save(offset().total_seconds() + minutes * 60)
    return now()


def set(iso: str) -> datetime:
    """Fija el reloj en `iso`. Sin zona, se interpreta en America/Montevideo."""
    target = datetime.fromisoformat(iso)
    if target.tzinfo is None:
        target = target.replace(tzinfo=TZ)
    _save((target - _real_now()).total_seconds())
    return now()

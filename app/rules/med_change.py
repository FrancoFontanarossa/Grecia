# Cambios de medicación (med_schedule.changed_at) para A2 (CLAUDE.md §6.3).
from dataclasses import dataclass
from datetime import datetime, timedelta

from app import config, db


@dataclass
class MedChange:
    drug: str
    changed_at: datetime
    note: str | None


def changes(patient_id: int) -> list[MedChange]:
    with db.connect() as conn:
        rows = conn.execute("SELECT drug, changed_at, change_note FROM med_schedule "
                            "WHERE patient_id = ? AND changed_at IS NOT NULL ORDER BY changed_at", (patient_id,))
        return [MedChange(r["drug"], db.from_db(r["changed_at"]), r["change_note"]) for r in rows]


def recent_change(patient_id: int, when: datetime) -> tuple[MedChange, int] | None:
    """El cambio más reciente con `when` dentro de sus 8 semanas, y los días que pasaron desde el cambio."""
    window = timedelta(weeks=config.MED_CHANGE_WEEKS)
    hits = [c for c in changes(patient_id) if c.changed_at <= when <= c.changed_at + window]
    if not hits:
        return None
    last = hits[-1]
    return last, (when.date() - last.changed_at.date()).days

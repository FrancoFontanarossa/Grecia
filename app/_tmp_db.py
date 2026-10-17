# TEMPORAL: consultas de Guada sobre el esquema de app/db.py de Franco (entries, events, notifications,
# push_subscriptions, people, consents). No crea tablas: las crea db.init(). Se migra a app/db.py en otro PR.
# Funciones sync (una conexión por operación): llamarlas con asyncio.to_thread.
import datetime as dt
from pathlib import Path

from app import clock, config, db


def now() -> dt.datetime:
    return clock.now()


def data_dir() -> Path:
    return config.DATA_DIR


def person_info(person_id: int) -> dict | None:
    """{patient_id, role, name, patient_name} de la persona (el paciente de prueba es otro patient_id)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT p.patient_id, p.role, p.name,"
            " (SELECT name FROM people WHERE id = p.patient_id) AS patient_name"
            " FROM people p WHERE p.id = ?", (person_id,)).fetchone()
    return dict(row) if row else None


def insert_entry(*, patient_id: int, speaker_id: int, modality: str, raw_text: str,
                 question_id: int | None, occurred_hint: str | None, reserved_requested: bool,
                 source: str, audio_path: str | None = None) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO entries (patient_id, speaker_id, modality, question_id, raw_text, audio_path,"
            " occurred_hint, reserved_requested, corrected, created_at, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (patient_id, speaker_id, modality, question_id, raw_text, audio_path,
             occurred_hint, int(reserved_requested), db.to_db(clock.now()), source),
        )
        return cur.lastrowid


def set_entry_text(entry_id: int, raw_text: str) -> None:
    """Guarda la transcripción en una entrada de audio."""
    with db.connect() as conn:
        conn.execute("UPDATE entries SET raw_text = ? WHERE id = ?", (raw_text, entry_id))


def get_entry(entry_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def mentioned_symptoms(patient_id: int) -> set[str]:
    """Síntomas ya contados (no negados) en la historia del paciente, para calcular is_new."""
    with db.connect() as conn:
        rows = conn.execute("SELECT DISTINCT symptom FROM events WHERE patient_id = ? AND negated = 0",
                            (patient_id,)).fetchall()
    return {r["symptom"] for r in rows}


def canal_reservado_active(patient_id: int) -> bool:
    """Activo si algún destinatario lo tiene habilitado. Sin filas se asume activo: lo reservado no llega al paciente."""
    with db.connect() as conn:
        row = conn.execute("SELECT MAX(enabled) AS on_ FROM consents WHERE patient_id = ? AND kind = 'canal_reservado'",
                           (patient_id,)).fetchone()
    return bool(row["on_"]) if row and row["on_"] is not None else True


_EVENT_COLUMNS = ("domain", "symptom", "severity", "negated", "occurred_at", "time_vague", "speaker_role",
                  "foreign_attribution", "quote", "plain", "confidence", "minutes_since_dose", "is_new", "reserved")


def _to_column(value):
    if isinstance(value, dt.datetime):
        return db.to_db(value)
    if isinstance(value, bool):
        return int(value)
    return value


def insert_events(entry_id: int, patient_id: int, events: list[dict]) -> list[int]:
    """Guarda los eventos de una entrada (dicts con las columnas de events). Todo o nada."""
    ids = []
    with db.connect() as conn:
        for ev in events:
            cur = conn.execute(
                f"INSERT INTO events (entry_id, patient_id, {', '.join(_EVENT_COLUMNS)})"
                f" VALUES (?, ?, {', '.join('?' * len(_EVENT_COLUMNS))})",
                (entry_id, patient_id, *(_to_column(ev.get(c)) for c in _EVENT_COLUMNS)))
            ids.append(cur.lastrowid)
    return ids


def insert_notification(*, person_id: int, kind: str, lane: str | None, title: str, body: str,
                        url: str) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO notifications (person_id, kind, lane, title, body, url, created_at, push_sent)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (person_id, kind, lane, title, body, url, db.to_db(clock.now())),
        )
        row = conn.execute("SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def mark_push_sent(notification_id: int) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE notifications SET push_sent = 1 WHERE id = ?", (notification_id,))


def subscriptions_for(person_id: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM push_subscriptions WHERE person_id = ?", (person_id,)).fetchall()
    return [dict(r) for r in rows]


def save_subscription(*, person_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    """Un endpoint pertenece a una sola persona: si ya estaba, se reemplaza (la tabla no tiene UNIQUE)."""
    with db.connect() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.execute(
            "INSERT INTO push_subscriptions (person_id, endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?)",
            (person_id, endpoint, p256dh, auth, db.to_db(clock.now())),
        )


def delete_subscription(endpoint: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

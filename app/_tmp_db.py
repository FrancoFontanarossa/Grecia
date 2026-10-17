# TEMPORAL: reemplazar por app/db.py de Franco (y now() por app/clock.py).
# Solo las tablas que usa Guada (entries, events, notifications, push_subscriptions), con las columnas de CLAUDE.md §12.
# SQLite con WAL, busy_timeout=5000 y una conexión por operación. Funciones sync: llamarlas con asyncio.to_thread.
import datetime as dt
import os
import sqlite3
import threading
from pathlib import Path

from app.config import TZ


def now() -> dt.datetime: return dt.datetime.now(TZ)  # TEMPORAL: stub de clock.now()


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    speaker_id INTEGER NOT NULL,
    modality TEXT NOT NULL,             -- texto | audio | toque
    question_id INTEGER,
    raw_text TEXT,
    audio_path TEXT,
    occurred_hint TEXT,
    reserved_requested INTEGER NOT NULL DEFAULT 0,
    corrected INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    symptom TEXT NOT NULL,
    severity INTEGER,
    negated INTEGER NOT NULL,
    occurred_at TEXT,
    time_vague INTEGER NOT NULL,
    speaker_role TEXT NOT NULL,
    foreign_attribution TEXT,
    quote TEXT NOT NULL,
    plain TEXT NOT NULL,
    confidence REAL NOT NULL,
    minutes_since_dose INTEGER,
    is_new INTEGER NOT NULL,
    reserved INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                 -- pregunta | repregunta | logro | ambar | rojo | resumen
    lane TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    push_sent INTEGER NOT NULL DEFAULT 0,
    read_at TEXT
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_init_lock = threading.Lock()
_initialized: set[str] = set()


def db_path() -> Path:
    data_dir = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "./data"))
    return data_dir / "entrecasa.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    with _init_lock:
        if str(path) not in _initialized:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _initialized.add(str(path))
    return conn


# TEMPORAL: sin tabla people, las personas del seed de la demo (Juan, Marta, Laura) para el paciente 1.
_FALLBACK_PEOPLE = {1: (1, "paciente", "Juan"), 2: (1, "cuidador", "Marta"), 3: (1, "familiar", "Laura")}


def person_info(person_id: int) -> dict | None:
    """{patient_id, role, name, patient_name} de la persona (el paciente de prueba es otro patient_id)."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT p.patient_id, p.role, p.name,"
            " (SELECT name FROM people WHERE patient_id = p.patient_id AND role = 'paciente' LIMIT 1) AS patient_name"
            " FROM people p WHERE p.id = ?", (person_id,)).fetchone()
    except sqlite3.OperationalError:
        patient_id, role, name = _FALLBACK_PEOPLE.get(person_id, (1, "paciente", None))
        return {"patient_id": patient_id, "role": role, "name": name, "patient_name": "Juan"}
    finally:
        conn.close()
    return dict(row) if row else None


def insert_entry(*, patient_id: int, speaker_id: int, modality: str, raw_text: str | None,
                 question_id: int | None, occurred_hint: str | None, reserved_requested: bool,
                 source: str, audio_path: str | None = None) -> int:
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO entries (patient_id, speaker_id, modality, question_id, raw_text, audio_path,"
                " occurred_hint, reserved_requested, corrected, created_at, source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (patient_id, speaker_id, modality, question_id, raw_text, audio_path,
                 occurred_hint, int(reserved_requested), now().isoformat(), source),
            )
        return cur.lastrowid
    finally:
        conn.close()


def get_entry(entry_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mentioned_symptoms(patient_id: int) -> set[str]:
    """Síntomas ya contados (no negados) en la historia del paciente, para calcular is_new."""
    conn = connect()
    try:
        rows = conn.execute("SELECT DISTINCT symptom FROM events WHERE patient_id = ? AND negated = 0",
                            (patient_id,)).fetchall()
        return {r["symptom"] for r in rows}
    finally:
        conn.close()


def canal_reservado_active(patient_id: int) -> bool:
    """TEMPORAL: sin tabla consents se asume activo (lo que protege: lo reservado no le llega al paciente)."""
    conn = connect()
    try:
        row = conn.execute("SELECT MAX(enabled) AS on_ FROM consents WHERE patient_id = ? AND kind = 'canal_reservado'",
                           (patient_id,)).fetchone()
    except sqlite3.OperationalError:
        return True
    finally:
        conn.close()
    return bool(row["on_"]) if row and row["on_"] is not None else True


_EVENT_COLUMNS = ("domain", "symptom", "severity", "negated", "occurred_at", "time_vague", "speaker_role",
                  "foreign_attribution", "quote", "plain", "confidence", "minutes_since_dose", "is_new", "reserved")


def insert_events(entry_id: int, patient_id: int, events: list[dict]) -> list[int]:
    """Guarda los eventos de una entrada (dicts con las columnas de events). Todo o nada."""
    conn = connect()
    try:
        ids = []
        with conn:
            for ev in events:
                values = [ev.get(c) for c in _EVENT_COLUMNS]
                values = [v.isoformat() if hasattr(v, "isoformat") else int(v) if isinstance(v, bool) else v
                          for v in values]
                cur = conn.execute(
                    f"INSERT INTO events (entry_id, patient_id, {', '.join(_EVENT_COLUMNS)})"
                    f" VALUES (?, ?, {', '.join('?' * len(_EVENT_COLUMNS))})",
                    (entry_id, patient_id, *values))
                ids.append(cur.lastrowid)
        return ids
    finally:
        conn.close()


def insert_notification(*, person_id: int, kind: str, lane: str | None, title: str, body: str,
                        url: str) -> dict:
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO notifications (person_id, kind, lane, title, body, url, created_at, push_sent)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (person_id, kind, lane, title, body, url, now().isoformat()),
            )
        row = conn.execute("SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def mark_push_sent(notification_id: int) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute("UPDATE notifications SET push_sent = 1 WHERE id = ?", (notification_id,))
    finally:
        conn.close()


def subscriptions_for(person_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM push_subscriptions WHERE person_id = ?", (person_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_subscription(*, person_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO push_subscriptions (person_id, endpoint, p256dh, auth, created_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(endpoint) DO UPDATE SET person_id = excluded.person_id,"
                " p256dh = excluded.p256dh, auth = excluded.auth",
                (person_id, endpoint, p256dh, auth, now().isoformat()),
            )
    finally:
        conn.close()


def delete_subscription(endpoint: str) -> None:
    conn = connect()
    try:
        with conn:
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    finally:
        conn.close()

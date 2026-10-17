# TEMPORAL: reemplazar por app/db.py de Franco (y now() por app/clock.py).
# Solo las tablas de Guada (entries, notifications, push_subscriptions), con las columnas de CLAUDE.md §12.
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


def patient_id_for(person_id: int) -> int | None:
    """patient_id de la persona. TEMPORAL: si todavía no existe la tabla people, asume el paciente 1."""
    conn = connect()
    try:
        row = conn.execute("SELECT patient_id FROM people WHERE id = ?", (person_id,)).fetchone()
    except sqlite3.OperationalError:
        return 1
    finally:
        conn.close()
    return row["patient_id"] if row else None


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

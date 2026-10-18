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


# ── Proactividad (scheduler) ───────────────────────────────────────────────────────────────────────────

def patients() -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name FROM people WHERE role = 'paciente' ORDER BY id")]


def person_role(person_id: int) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT role FROM people WHERE id = ?", (person_id,)).fetchone()
    return row["role"] if row else None


def recent_entries(patient_id: int, since: dt.datetime) -> list[dict]:
    """Relatos con texto desde `since`, con quién los contó y si son reservados (pedido por la familia o con algún
    evento reservado). El filtro para el paciente se aplica en pipeline.context."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT e.id, e.raw_text, e.created_at, p.role AS speaker_role,"
            " (p.role != 'paciente' AND (e.reserved_requested = 1"
            "   OR EXISTS (SELECT 1 FROM events ev WHERE ev.entry_id = e.id AND ev.reserved = 1))) AS reserved"
            " FROM entries e JOIN people p ON p.id = e.speaker_id"
            " WHERE e.patient_id = ? AND e.created_at >= ? AND e.raw_text != '' ORDER BY e.created_at",
            (patient_id, db.to_db(since))).fetchall()
    return [dict(r) for r in rows]


def questions_on_day(to_person_id: int, day: dt.date, *, rule_id: str | None = None,
                     statuses: tuple[str, ...] = ("pendiente", "enviada", "respondida", "descartada")) -> int:
    with db.connect() as conn:
        sql = ("SELECT count(*) FROM questions WHERE to_person_id = ? AND substr(sent_at, 1, 10) = ?"
               f" AND status IN ({', '.join('?' * len(statuses))})")
        args: list = [to_person_id, day.isoformat(), *statuses]
        if rule_id:
            sql += " AND rule_id = ?"
            args.append(rule_id)
        return conn.execute(sql, args).fetchone()[0]


def questions_since(to_person_id: int, rule_id: str, since: dt.datetime) -> int:
    with db.connect() as conn:
        return conn.execute("SELECT count(*) FROM questions WHERE to_person_id = ? AND rule_id = ? AND sent_at >= ?",
                            (to_person_id, rule_id, db.to_db(since))).fetchone()[0]


def episode_for_dose(patient_id: int, dose_time: dt.datetime) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM episodes WHERE patient_id = ? AND dose_time = ?",
                           (patient_id, db.to_db(dose_time))).fetchone()
    return dict(row) if row else None


def insert_question(*, patient_id: int, to_person_id: int, rule_id: str, question: str, why: str,
                    options: list[str], status: str, sent_at: dt.datetime) -> int:
    """Guarda la pregunta; la url es /casa/pregunta/{id}."""
    import json
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO questions (patient_id, to_person_id, rule_id, question, why, options, url, status, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)",
            (patient_id, to_person_id, rule_id, question, why, json.dumps(options, ensure_ascii=False), status,
             db.to_db(sent_at)))
        qid = cur.lastrowid
        conn.execute("UPDATE questions SET url = ? WHERE id = ?", (f"/casa/pregunta/{qid}", qid))
    return qid


def insert_episode(*, patient_id: int, dose_time: dt.datetime, deviation: dict | None, explanation: dict,
                   question_id: int | None, status: str) -> int:
    import json
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO episodes (patient_id, dose_time, deviation, explanation, question_id, entry_ids, status)"
            " VALUES (?, ?, ?, ?, ?, '[]', ?)",
            (patient_id, db.to_db(dose_time), json.dumps(deviation, ensure_ascii=False, default=str) if deviation else None,
             json.dumps(explanation, ensure_ascii=False), question_id, status))
        return cur.lastrowid


def answer_question(question_id: int, person_id: int, entry_id: int) -> bool:
    """Marca la pregunta como respondida y suma la entrada a su episodio. False si no es de esa persona."""
    import json
    with db.connect() as conn:
        q = conn.execute("SELECT to_person_id FROM questions WHERE id = ?", (question_id,)).fetchone()
        if not q or q["to_person_id"] != person_id:
            return False
        conn.execute("UPDATE questions SET status = 'respondida', answered_entry_id = ? WHERE id = ?",
                     (entry_id, question_id))
        ep = conn.execute("SELECT id, entry_ids FROM episodes WHERE question_id = ?", (question_id,)).fetchone()
        if ep:
            ids = json.loads(ep["entry_ids"] or "[]")
            if entry_id not in ids:
                ids.append(entry_id)
            conn.execute("UPDATE episodes SET entry_ids = ?, status = 'respondido' WHERE id = ?",
                         (json.dumps(ids), ep["id"]))
    return True


def from_db(value: str) -> dt.datetime:
    return db.from_db(value)

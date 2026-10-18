import datetime as dt

import pytest

from app import config, db

TABLES = {
    "people", "push_subscriptions", "notifications", "clock_state", "consents",
    "med_schedule", "doses", "entries", "events", "biometrics", "biometric_syncs",
    "episodes", "questions", "tests", "alerts", "goals", "goal_days", "reports", "patterns",
}


def test_all_tables_created(data_dir):
    with db.connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_biometric_syncs_columns(data_dir):
    with db.connect() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(biometric_syncs)")]
    assert cols == ["id", "patient_id", "window_start", "window_end", "received_at", "n_samples", "scope"]


def test_init_is_idempotent(data_dir):
    with db.connect() as conn:
        conn.execute("INSERT INTO people (id, patient_id, role, name, relation) VALUES (1, 1, 'paciente', 'Juan', 'paciente')")
    db.init()
    db.init()
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == 1


def test_wal_and_busy_timeout(data_dir):
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_connect_rolls_back_on_error(data_dir):
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("INSERT INTO people (id, patient_id, role, name, relation) VALUES (1, 1, 'paciente', 'Juan', 'paciente')")
            raise RuntimeError
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == 0


def test_db_lives_in_data_dir(data_dir):
    assert db.db_path() == data_dir / "entrecasa.db"
    assert db.db_path().exists()


def test_to_db_normalizes_to_montevideo():
    utc = dt.datetime(2026, 10, 13, 19, 0, 30, 123456, tzinfo=dt.timezone.utc)
    assert db.to_db(utc) == "2026-10-13T16:00:30-03:00"
    assert db.from_db(db.to_db(utc)) == utc.replace(microsecond=0)
    assert db.from_db("2026-10-13T19:00:00+00:00").tzinfo == config.TZ
    with pytest.raises(ValueError):
        db.to_db(dt.datetime(2026, 10, 13, 16))


def test_biometrics_same_sample_is_stored_once(data_dir):
    row = (1, "steps", 312, "2026-10-13T16:00:00-03:00", "2026-10-13T16:10:00-03:00", "atajo")
    sql = 'INSERT OR IGNORE INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (?, ?, ?, ?, ?, ?)'
    with db.connect() as conn:
        conn.execute(sql, row)
        conn.execute(sql, row)
        assert conn.execute("SELECT count(*) FROM biometrics").fetchone()[0] == 1


def test_patterns_columns(data_dir):
    with db.connect() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(patterns)")]
    assert cols == ["id", "patient_id", "day", "kind", "title", "description", "evidence_ids",
                    "suggested_action", "verified", "question_id", "created_at"]


OLD_BIOMETRICS = """CREATE TABLE biometrics (id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL, kind TEXT NOT NULL,
    value REAL NOT NULL, start TEXT NOT NULL, "end" TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('atajo','importacion','seed','inyectado')),
    UNIQUE (patient_id, kind, start, "end", source));
CREATE TABLE biometric_syncs (id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL, window_start TEXT NOT NULL,
    window_end TEXT NOT NULL, received_at TEXT NOT NULL, n_samples INTEGER NOT NULL);"""


def test_migrates_a_db_created_before_the_wearable(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    old = sqlite3.connect(tmp_path / "entrecasa.db")
    old.executescript(OLD_BIOMETRICS)
    old.execute("INSERT INTO biometrics (patient_id, kind, value, start, \"end\", source) "
                "VALUES (1, 'steps', 400, '2026-10-13T16:00:00-03:00', '2026-10-13T17:00:00-03:00', 'importacion')")
    old.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
                "VALUES (1, 'a', 'b', 'c', 1)")
    old.commit()
    old.close()

    db.init()
    db.init()                                                   # idempotente
    with db.connect() as conn:
        assert [dict(r) for r in conn.execute("SELECT kind, value, source FROM biometrics")] == [
            {"kind": "steps", "value": 400.0, "source": "importacion"}]
        conn.execute("INSERT INTO biometrics (patient_id, kind, value, start, \"end\", source) "
                     "VALUES (1, 'sleep_minutes', 400, 'x', 'y', 'simulado')")
        conn.execute("INSERT INTO biometrics (patient_id, kind, value, start, \"end\", source) "
                     "VALUES (1, 'sleep_minutes', 400, 'x', 'y', 'pulsera')")
        assert conn.execute("SELECT scope FROM biometric_syncs").fetchone()[0] is None
        indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "ix_biometrics_patient" in indexes


def test_unknown_source_still_rejected(data_dir):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute("INSERT INTO biometrics (patient_id, kind, value, start, \"end\", source) "
                         "VALUES (1, 'steps', 1, 'x', 'y', 'inventado')")

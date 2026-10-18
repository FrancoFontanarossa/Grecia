import datetime as dt
import json

import pytest

from app import clock, db
from app.config import TZ
from data import seed


def rows(sql, *args):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


@pytest.fixture
def env(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: dt.datetime(2026, 10, 17, 19, tzinfo=TZ))
    return data_dir


def import_steps():
    """Pasos importados: 400 por hora de 8 a 20 cada día del período, con su biometric_syncs."""
    hours, day = [], seed.PERIOD_START
    while day <= seed.PERIOD_END:
        for h in range(8, 20):
            start = dt.datetime.combine(day, dt.time(h), TZ)
            hours.append((db.to_db(start), db.to_db(start + dt.timedelta(hours=1))))
        day += dt.timedelta(days=1)
    with db.connect() as conn:
        conn.executemany('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) '
                         "VALUES (1, 'steps', 400, ?, ?, 'importacion')", hours)
        conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
                     "VALUES (1, '2026-09-20T00:00:00-03:00', '2026-10-18T00:00:00-03:00', '2026-10-17T19:00:00-03:00', ?)",
                     (len(hours),))


def test_people(env):
    seed.run()
    assert rows("SELECT id, patient_id, role, name FROM people ORDER BY id") == [
        {"id": 1, "patient_id": 1, "role": "paciente", "name": "Juan"},
        {"id": 2, "patient_id": 1, "role": "cuidador", "name": "Marta"},
        {"id": 3, "patient_id": 1, "role": "familiar", "name": "Laura"},
        {"id": 4, "patient_id": 1, "role": "neurologo", "name": "Dra. Pereira"},
        {"id": 5, "patient_id": 5, "role": "paciente", "name": "Paciente de prueba"},
        {"id": 6, "patient_id": 5, "role": "cuidador", "name": "Familiar de prueba"},
    ]
    assert rows("SELECT why_walk FROM people WHERE id = 1") == [{"why_walk": "llegar a la plaza a ver a sus nietos"}]


def test_consents(env):
    seed.run()
    got = rows("SELECT patient_id, recipient_id, kind, enabled FROM consents ORDER BY patient_id, recipient_id, kind")
    assert got == [{"patient_id": p, "recipient_id": r, "kind": k, "enabled": 1}
                   for p, r in ((1, 2), (1, 3), (5, 6)) for k in ("avisos", "canal_reservado", "logros")]


def test_med_schedule_and_pramipexol_change(env):
    seed.run()
    meds = {r["drug"]: r for r in rows("SELECT * FROM med_schedule WHERE patient_id = 1")}
    assert json.loads(meds["levodopa/carbidopa"]["times"]) == ["08:00", "12:00", "16:00", "20:00"]
    changed = db.from_db(meds["pramipexol"]["changed_at"])
    assert changed.date() == dt.date(2026, 10, 3)
    assert (dt.date(2026, 10, 14) - changed.date()).days == 11   # CLAUDE.md §3


def test_rerun_moves_an_old_pramipexol_change(data_dir):
    seed.run()
    with db.connect() as conn:
        conn.execute("UPDATE med_schedule SET changed_at = '2026-09-22T00:00:00-03:00' WHERE drug = 'pramipexol'")
    seed.run()
    [row] = rows("SELECT changed_at FROM med_schedule WHERE drug = 'pramipexol'")
    assert db.from_db(row["changed_at"]).date() == dt.date(2026, 10, 3)
    assert len(rows("SELECT * FROM med_schedule")) == 2

def test_doses_cover_the_period(env):
    seed.run()
    doses = [db.from_db(r["scheduled_at"]) for r in rows("SELECT scheduled_at FROM doses ORDER BY scheduled_at")]
    assert len(doses) == 28 * 4
    assert doses[0] == dt.datetime(2026, 9, 20, 8, tzinfo=TZ)
    assert doses[-1] == dt.datetime(2026, 10, 17, 20, tzinfo=TZ)
    assert {d.hour for d in doses} == {8, 12, 16, 20}
    assert rows("SELECT DISTINCT source, confirmed_at FROM doses") == [{"source": "seed", "confirmed_at": None}]


def test_goal(env):
    seed.run()
    assert rows("SELECT patient_id, metric, target, unit, set_by, active FROM goals") == [
        {"patient_id": 1, "metric": "steps", "target": 4000.0, "unit": "pasos", "set_by": 4, "active": 1}]


def test_tapping_history(env):
    seed.run()
    sessions = rows("SELECT * FROM tests ORDER BY taken_at")
    assert len(sessions) == 8
    assert {(s["patient_id"], s["type"], s["source"]) for s in sessions} == {(1, "golpeteo", "seed")}
    days = [db.from_db(s["taken_at"]).date() for s in sessions]
    assert dt.date(2026, 10, 1) <= min(days) and max(days) <= dt.date(2026, 10, 11)
    for s in sessions:
        m = json.loads(s["metrics"])
        assert 4.2 <= m["taps_per_s"] <= 4.8
        assert 0.12 <= m["interval_cv"] <= 0.18
        assert 0.95 <= m["left_right_ratio"] <= 1.05


def test_creates_no_ai_output(env):
    seed.run()
    for table in ("events", "entries", "questions", "reports", "alerts", "notifications", "patterns"):
        assert rows(f"SELECT count(*) AS n FROM {table}") == [{"n": 0}], table


def test_without_imported_steps_warns_and_continues(env):
    result = seed.run()
    assert result["injected_drops"] == 0
    assert len(result["warnings"]) == 1 and "import_health" in result["warnings"][0]
    assert result["tapping_sessions"] == 8                    # el resto se creó igual


def test_drops_on_imported_steps(env):
    import_steps()
    result = seed.run()
    assert result["warnings"] == [] and result["injected_drops"] == 3
    injected = rows('SELECT value, start, "end" FROM biometrics WHERE source = \'inyectado\' ORDER BY start')
    assert [r["start"][:16] for r in injected] == [
        "2026-10-13T16:00", "2026-10-13T17:00", "2026-10-15T16:00", "2026-10-15T17:00",
        "2026-10-16T16:00", "2026-10-16T17:00"]
    assert all(r["value"] == pytest.approx(120) for r in injected)
    # Nada fuera de las ventanas: las demás horas siguen en 400 e importacion.
    assert rows("SELECT DISTINCT value, source FROM biometrics WHERE source != 'inyectado'") == [
        {"value": 400.0, "source": "importacion"}]


def test_idempotent(env):
    import_steps()
    first = seed.run()
    again = seed.run()
    assert again == first
    assert {k: v for k, v in first.items() if k != "people"} == {
        "consents": 9, "med_schedule": 2, "doses": 112, "goals": 1, "step_samples": 28 * 12,
        "tapping_sessions": 8, "injected_drops": 3, "warnings": []}
    assert rows("SELECT DISTINCT value FROM biometrics WHERE source = 'inyectado'") == [{"value": pytest.approx(120)}]


def test_rerun_keeps_consent_changes(env):
    seed.run()
    with db.connect() as conn:
        conn.execute("UPDATE consents SET enabled = 0 WHERE recipient_id = 3 AND kind = 'logros'")
    seed.run()
    assert rows("SELECT enabled FROM consents WHERE recipient_id = 3 AND kind = 'logros'") == [{"enabled": 0}]


def test_prints_summary(env, capsys):
    seed.print_summary(seed.run())
    out = capsys.readouterr().out
    assert "Familiar de prueba" in out and "Sesiones de golpeteo de Juan: 8" in out and "AVISO" in out

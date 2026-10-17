import datetime as dt
import json

from app import db
from app.config import TZ
from data import seed


def rows(sql, *args):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def test_people(data_dir):
    seed.run()
    assert rows("SELECT id, patient_id, role, name FROM people ORDER BY id") == [
        {"id": 1, "patient_id": 1, "role": "paciente", "name": "Juan"},
        {"id": 2, "patient_id": 1, "role": "cuidador", "name": "Marta"},
        {"id": 3, "patient_id": 1, "role": "familiar", "name": "Laura"},
        {"id": 4, "patient_id": 1, "role": "neurologo", "name": "Dra. Pereira"},
        {"id": 5, "patient_id": 5, "role": "paciente", "name": "Paciente de prueba"},
    ]
    assert rows("SELECT why_walk FROM people WHERE id = 1") == [{"why_walk": "llegar a la plaza a ver a sus nietos"}]


def test_consents(data_dir):
    seed.run()
    got = rows("SELECT recipient_id, kind, enabled FROM consents WHERE patient_id = 1 ORDER BY recipient_id, kind")
    assert got == [{"recipient_id": r, "kind": k, "enabled": 1}
                   for r in (2, 3) for k in ("avisos", "canal_reservado", "logros")]


def test_med_schedule_and_pramipexol_change(data_dir):
    seed.run()
    meds = {r["drug"]: r for r in rows("SELECT * FROM med_schedule WHERE patient_id = 1")}
    assert json.loads(meds["levodopa/carbidopa"]["times"]) == ["08:00", "12:00", "16:00", "20:00"]
    changed = db.from_db(meds["pramipexol"]["changed_at"])
    assert changed.date() == dt.date(2026, 9, 22)
    assert (dt.date(2026, 10, 14) - changed.date()).days == 22   # CLAUDE.md §3


def test_doses_cover_the_period(data_dir):
    seed.run()
    doses = [db.from_db(r["scheduled_at"]) for r in rows("SELECT scheduled_at FROM doses ORDER BY scheduled_at")]
    assert len(doses) == 28 * 4
    assert doses[0] == dt.datetime(2026, 9, 20, 8, tzinfo=TZ)
    assert doses[-1] == dt.datetime(2026, 10, 17, 20, tzinfo=TZ)
    assert {d.hour for d in doses} == {8, 12, 16, 20}
    assert rows("SELECT DISTINCT source, confirmed_at FROM doses") == [{"source": "seed", "confirmed_at": None}]


def test_goal(data_dir):
    seed.run()
    assert rows("SELECT patient_id, metric, target, unit, set_by, active FROM goals") == [
        {"patient_id": 1, "metric": "steps", "target": 4000.0, "unit": "pasos", "set_by": 4, "active": 1}]


def test_creates_no_ai_output(data_dir):
    seed.run()
    for table in ("events", "entries", "questions", "reports", "alerts", "notifications", "biometrics"):
        assert rows(f"SELECT count(*) AS n FROM {table}") == [{"n": 0}], table


def test_idempotent(data_dir):
    first = seed.run()
    assert seed.run() == first == {"people": 5, "consents": 6, "med_schedule": 2, "doses": 112, "goals": 1}


def test_rerun_keeps_consent_changes(data_dir):
    seed.run()
    with db.connect() as conn:
        conn.execute("UPDATE consents SET enabled = 0 WHERE recipient_id = 3 AND kind = 'logros'")
    seed.run()
    assert rows("SELECT enabled FROM consents WHERE recipient_id = 3 AND kind = 'logros'") == [{"enabled": 0}]

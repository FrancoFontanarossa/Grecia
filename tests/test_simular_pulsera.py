"""El simulador manda por HTTP y la app procesa: nada simulado escribe directo en la base."""
import datetime as dt
import re
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import clock, config, db
from app.config import TZ
from app.rules import biometrics, episodes
from scripts import simular_pulsera as sim

REAL = dt.datetime(2026, 10, 17, 19, tzinfo=TZ)
SLEEP = {"sleep_minutes", "sleep_awakenings"}


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    monkeypatch.setenv("WEARABLE_TOKEN", "pulsera")
    from app.main import app
    with TestClient(app) as client:
        yield client


def rows(sql, *args):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def test_the_script_does_not_touch_the_db_or_the_rules():
    source = (Path(sim.__file__)).read_text()
    assert not re.search(r"^\s*(from|import) app\b", source, re.M)


def test_one_request_per_day_with_every_metric():
    bodies = sim.payloads()
    assert len(bodies) == 28
    assert all(b["device"]["vendor"] == "simulador" and b["source"] == "simulado" for b in bodies)
    counts = Counter(s["type"] for b in bodies for s in b["samples"])
    assert {k: counts[k] for k in ("sleep_minutes", "sleep_awakenings", "heart_rate_rest", "hrv_ms", "spo2_pct",
                                   "resp_rate", "active_minutes")} == dict.fromkeys(
        ("sleep_minutes", "sleep_awakenings", "heart_rate_rest", "hrv_ms", "spo2_pct", "resp_rate", "active_minutes"), 28)
    assert counts["tremor_minutes"] == counts["dyskinesia_minutes"] == 28 * 24
    assert sim.payloads() == bodies                                       # determinístico


def test_nights_follow_the_scenario():
    for d in range(4, 11):
        n = sim.nightly(dt.date(2026, 10, d))
        assert n["sleep_awakenings"] >= 6 and n["sleep_minutes"] <= 230
    short = sim.nightly(dt.date(2026, 10, 14))
    assert short["sleep_awakenings"] in (4, 5) and short["sleep_minutes"] < 210
    for d in (13, 16, 17):                                               # 12→13, 15→16, 16→17
        n = sim.nightly(dt.date(2026, 10, d))
        assert n["sleep_awakenings"] <= 3 and n["sleep_minutes"] >= 370


def test_end_to_end_the_simulator_sends_and_the_expected_anomalies_come_out(app_client):
    results = sim.send(app_client, "pulsera", sim.payloads())
    assert len(results) == 28 and all(r["duplicates"] == 0 for r in results)
    assert rows("SELECT DISTINCT source FROM biometrics") == [{"source": "simulado"}]
    assert {r["scope"] for r in rows("SELECT scope FROM biometric_syncs")} == {"pulsera"}

    def kinds(d):
        return {a["kind"] for a in biometrics.anomalies(1, dt.date(2026, 10, d))}

    for d in range(4, 11):
        assert kinds(d) == SLEEP, d
    assert kinds(14) == {"sleep_minutes"}                                # la noche que cuenta Marta
    for d in (13, 15, 16):
        assert kinds(d) == {"tremor_minutes"}, d                         # noches 12→13, 15→16 normales
    for d in (1, 2, 3, 11, 12, 17):
        assert kinds(d) == set(), d


def test_resending_does_not_duplicate(app_client):
    sim.send(app_client, "pulsera", sim.payloads())
    n = rows("SELECT count(*) AS n FROM biometrics")[0]["n"]
    again = sim.send(app_client, "pulsera", sim.payloads())
    assert all(r["stored"] == 0 for r in again)
    assert rows("SELECT count(*) AS n FROM biometrics")[0]["n"] == n


def test_does_not_touch_steps(app_client):
    from data import seed
    from tests.rules import steps
    seed.run()
    steps.load()
    before = rows("SELECT * FROM biometrics WHERE kind = 'steps' ORDER BY id")
    d = episodes.deviation(1, steps.at16(dt.date(2026, 10, 14)))
    sim.send(app_client, "pulsera", sim.payloads())
    assert rows("SELECT * FROM biometrics WHERE kind = 'steps' ORDER BY id") == before
    assert episodes.deviation(1, steps.at16(dt.date(2026, 10, 14))) == d


def test_bad_token_stops_with_an_error(app_client):
    with pytest.raises(RuntimeError, match="HTTP 401"):
        sim.send(app_client, "otro", sim.payloads()[:1])


def test_cli_needs_a_token(monkeypatch, capsys):
    monkeypatch.delenv("WEARABLE_TOKEN", raising=False)
    monkeypatch.delenv("ATAJO_TOKEN", raising=False)
    monkeypatch.setattr(sim, "ROOT", Path("/nonexistent"))              # que no lea el .env de verdad
    assert sim.main(["--url", "http://localhost:1"]) == 1
    assert "Falta el token" in capsys.readouterr().err


def test_seed_wearable_endpoint_is_gone(app_client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin")
    assert app_client.post("/admin/seed_wearable", headers={"X-Admin-Token": "admin"}).status_code in (404, 405)

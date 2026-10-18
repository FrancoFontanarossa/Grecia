import datetime as dt
from collections import Counter

import pytest

from app import clock, db
from app.config import TZ
from app.rules import episodes
from data import mock_wearable as mw

REAL = dt.datetime(2026, 10, 17, 19, tzinfo=TZ)


@pytest.fixture
def env(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    return data_dir


def rows(sql, *args):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def test_28_days_of_every_metric():
    counts = Counter(k for k, *_ in mw.samples())
    assert {k: counts[k] for k in mw.NIGHTLY + mw.DAILY} == {k: 28 for k in mw.NIGHTLY + mw.DAILY}
    assert counts["tremor_minutes"] == counts["dyskinesia_minutes"] == 28 * 24


def test_deterministic():
    assert mw.samples() == mw.samples()


def test_bad_nights_only_the_week_of_the_dreams():
    for day in (dt.date(2026, 10, 4) + dt.timedelta(days=k) for k in range(7)):
        n = mw.nightly(day)
        assert n["sleep_awakenings"] >= 6 and n["sleep_minutes"] <= 255, day
    for day in (dt.date(2026, 10, 3), dt.date(2026, 10, 11), dt.date(2026, 10, 17)):
        n = mw.nightly(day)
        assert n["sleep_awakenings"] <= 3 and n["sleep_minutes"] >= 370, day


def test_night_16_to_17_is_normal():
    n = mw.nightly(dt.date(2026, 10, 17))
    assert n["sleep_awakenings"] <= 3 and n["sleep_minutes"] >= 370


def test_more_tremor_from_16_to_18_on_the_drop_days():
    for day in mw.TREMOR_DAYS:
        assert all(mw.hourly(day, h)["tremor_minutes"] >= 24 for h in (16, 17))
        assert mw.hourly(day, 14)["tremor_minutes"] <= 5
    assert all(mw.hourly(dt.date(2026, 10, 14), h)["tremor_minutes"] <= 5 for h in (16, 17))


def test_run_stores_simulated_and_registers_the_window(env):
    result = mw.run()
    assert rows("SELECT DISTINCT source FROM biometrics") == [{"source": "simulado"}]
    assert rows("SELECT count(*) AS n FROM biometrics") == [{"n": result["samples"]}]
    assert rows("SELECT window_start, window_end, scope FROM biometric_syncs") == [
        {"window_start": "2026-09-19T23:00:00-03:00", "window_end": "2026-10-18T00:00:00-03:00", "scope": "pulsera"}]
    mw.run()                                                       # idempotente
    assert rows("SELECT count(*) AS n FROM biometrics") == [{"n": result["samples"]}]
    assert rows("SELECT count(*) AS n FROM biometric_syncs") == [{"n": 1}]


def test_does_not_touch_steps_or_steps_syncs(env):
    from tests.rules import steps
    from data import seed
    seed.run()
    steps.load()
    before = rows("SELECT * FROM biometrics WHERE kind = 'steps' ORDER BY id")
    d13 = episodes.deviation(1, steps.at16(dt.date(2026, 10, 14)))
    mw.run()
    assert rows("SELECT * FROM biometrics WHERE kind = 'steps' ORDER BY id") == before
    assert episodes.deviation(1, steps.at16(dt.date(2026, 10, 14))) == d13
    assert len(rows("SELECT * FROM biometric_syncs WHERE scope IS NULL")) == 1


def test_seed_wearable_endpoint(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import admin
    monkeypatch.setenv("ADMIN_TOKEN", "admin")
    app = FastAPI()
    app.include_router(admin.router)
    client = TestClient(app)
    assert client.post("/admin/seed_wearable").status_code == 401
    r = client.post("/admin/seed_wearable", headers={"X-Admin-Token": "admin"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["by_kind"]["sleep_minutes"] == 28
    assert rows("SELECT count(*) AS n FROM biometrics WHERE kind = 'steps'") == [{"n": 0}]   # no corre el seed

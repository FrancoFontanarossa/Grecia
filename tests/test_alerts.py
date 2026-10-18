import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import clock, db
from app.api import alerts
from app.config import TZ
from app.rules import goals
from data import seed

REAL = dt.datetime(2026, 10, 17, 19, 0, tzinfo=TZ)
DAY = dt.datetime(2026, 10, 14, 10, tzinfo=TZ)


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    seed.run()
    clock.set(DAY.isoformat())
    app = FastAPI()
    app.include_router(alerts.router)
    return TestClient(app)


def red(at=DAY):
    with db.connect() as conn:
        return conn.execute("INSERT INTO alerts (patient_id, lane, rule_id, text, created_at) VALUES (1, 'rojo', 'R1', 't', ?)",
                            (db.to_db(at),)).lastrowid


def walk(steps):
    with db.connect() as conn:
        conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, \'steps\', ?, ?, ?, \'atajo\')',
                     (steps, db.to_db(DAY), db.to_db(DAY + dt.timedelta(hours=1))))


def acked_at(alert_id):
    with db.connect() as conn:
        return conn.execute("SELECT acked_at FROM alerts WHERE id = ?", (alert_id,)).fetchone()[0]


def test_ack_sets_acked_at_with_the_demo_clock_and_lifts_the_pause(client):
    walk(5000)
    alert_id = red()
    assert not goals.status(1, DAY.date()).achieved and goals.paused(1)
    r = client.post(f"/api/alerts/{alert_id}/ack")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "acked_at": "2026-10-14T10:00:00-03:00", "goal_paused": False}
    assert acked_at(alert_id) == "2026-10-14T10:00:00-03:00"
    assert not goals.paused(1)
    assert goals.status(1, DAY.date()).achieved


def test_pause_stays_while_another_red_is_pending(client):
    first, second = red(), red(DAY + dt.timedelta(minutes=5))
    assert client.post(f"/api/alerts/{first}/ack").json()["goal_paused"] is True
    assert client.post(f"/api/alerts/{second}/ack").json()["goal_paused"] is False


def test_ack_twice_keeps_the_first_time(client):
    alert_id = red()
    client.post(f"/api/alerts/{alert_id}/ack")
    clock.advance(30)
    assert client.post(f"/api/alerts/{alert_id}/ack").json()["acked_at"] == "2026-10-14T10:00:00-03:00"


def test_unknown_alert_is_404(client):
    assert client.post("/api/alerts/999/ack").status_code == 404

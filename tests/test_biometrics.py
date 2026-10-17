import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import clock, db
from app.api import biometrics
from app.config import TZ

REAL = dt.datetime(2026, 10, 17, 19, 0, tzinfo=TZ)
PAYLOAD = {
    "window_start": "2026-10-17T16:00:00-03:00",
    "window_end": "2026-10-17T19:00:00-03:00",
    "samples": [
        {"kind": "steps", "value": 312, "start": "2026-10-17T16:05:00-03:00", "end": "2026-10-17T16:15:00-03:00"},
        {"kind": "steps", "value": "48", "start": "2026-10-17T20:30:00Z", "end": "2026-10-17T20:40:00Z"},
    ],
}
OK = {"X-Atajo-Token": "secreto"}


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ATAJO_TOKEN", "secreto")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    app = FastAPI()
    app.include_router(biometrics.router)
    return TestClient(app)


def rows(sql):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


@pytest.mark.parametrize("headers", [{}, {"X-Atajo-Token": "otro"}, {"X-Atajo-Token": ""}])
def test_bad_token_is_401(client, headers):
    assert client.post("/api/biometrics/atajo", json=PAYLOAD, headers=headers).status_code == 401
    assert rows("SELECT * FROM biometrics") == []
    assert rows("SELECT * FROM biometric_syncs") == []


def test_unset_token_rejects_everything(client, monkeypatch):
    monkeypatch.delenv("ATAJO_TOKEN")
    assert client.post("/api/biometrics/atajo", json=PAYLOAD, headers=OK).status_code == 401


def test_saves_samples_and_window(client):
    r = client.post("/api/biometrics/atajo", json=PAYLOAD, headers=OK)
    assert r.status_code == 200 and r.json() == {"received": 2}
    assert rows('SELECT patient_id, kind, value, start, "end", source FROM biometrics ORDER BY start') == [
        {"patient_id": 1, "kind": "steps", "value": 312.0, "start": "2026-10-17T16:05:00-03:00",
         "end": "2026-10-17T16:15:00-03:00", "source": "atajo"},
        {"patient_id": 1, "kind": "steps", "value": 48.0, "start": "2026-10-17T17:30:00-03:00",
         "end": "2026-10-17T17:40:00-03:00", "source": "atajo"},
    ]
    assert rows("SELECT patient_id, window_start, window_end, received_at, n_samples FROM biometric_syncs") == [
        {"patient_id": 1, "window_start": "2026-10-17T16:00:00-03:00", "window_end": "2026-10-17T19:00:00-03:00",
         "received_at": "2026-10-17T19:00:00-03:00", "n_samples": 2},
    ]


def test_resend_does_not_duplicate_samples(client):
    client.post("/api/biometrics/atajo", json=PAYLOAD, headers=OK)
    client.post("/api/biometrics/atajo", json=PAYLOAD, headers=OK)
    assert len(rows("SELECT * FROM biometrics")) == 2
    assert len(rows("SELECT * FROM biometric_syncs")) == 2


def test_empty_window_is_registered(client):
    r = client.post("/api/biometrics/atajo", json={**PAYLOAD, "samples": []}, headers=OK)
    assert r.json() == {"received": 0}
    assert rows("SELECT n_samples FROM biometric_syncs") == [{"n_samples": 0}]


def test_naive_dates_are_422(client):
    body = {**PAYLOAD, "window_start": "2026-10-17T16:00:00"}
    assert client.post("/api/biometrics/atajo", json=body, headers=OK).status_code == 422


def test_demo_mode_shifts_every_date(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    clock.set("2026-10-13T19:00:00-03:00")          # 4 días antes de la hora real
    client.post("/api/biometrics/atajo", json=PAYLOAD, headers=OK)
    assert [r["start"] for r in rows("SELECT start FROM biometrics ORDER BY start")] == [
        "2026-10-13T16:05:00-03:00", "2026-10-13T17:30:00-03:00"]
    assert [r["end"] for r in rows('SELECT "end" FROM biometrics ORDER BY start')] == [
        "2026-10-13T16:15:00-03:00", "2026-10-13T17:40:00-03:00"]
    assert rows("SELECT window_start, window_end, received_at FROM biometric_syncs") == [
        {"window_start": "2026-10-13T16:00:00-03:00", "window_end": "2026-10-13T19:00:00-03:00",
         "received_at": "2026-10-13T19:00:00-03:00"},
    ]


def test_without_demo_mode_dates_are_not_shifted(client):
    clock.set("2026-10-13T19:00:00-03:00")
    client.post("/api/biometrics/atajo", json=PAYLOAD, headers=OK)
    assert rows("SELECT window_start FROM biometric_syncs") == [{"window_start": "2026-10-17T16:00:00-03:00"}]

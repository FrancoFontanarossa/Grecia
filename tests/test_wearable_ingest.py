import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import clock, db
from app.api import biometrics
from app.config import TZ

REAL = dt.datetime(2026, 10, 17, 19, tzinfo=TZ)
OK = {"X-Device-Token": "dispositivo"}


def payload(*samples, source="pulsera"):
    return {"device": {"vendor": "Acme", "model": "Band 2", "id": "AB-12"}, "source": source,
            "window_start": "2026-10-13T23:00:00-03:00", "window_end": "2026-10-14T08:00:00-03:00",
            "samples": list(samples) or [sample()]}


def sample(type_="sleep_minutes", value=400, unit="min", start="2026-10-13T23:00:00-03:00",
           end="2026-10-14T07:00:00-03:00"):
    return {"type": type_, "value": value, "unit": unit, "start": start, "end": end}


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    monkeypatch.setenv("WEARABLE_TOKEN", "dispositivo")
    app = FastAPI()
    app.include_router(biometrics.router)
    return TestClient(app)


def rows(sql):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def test_valid_payload_is_stored_with_the_device_source_and_window(client):
    body = payload(sample(), sample("sleep_awakenings", 2, "count"), sample("heart_rate_rest", 61, "bpm"),
                   source="simulado")
    r = client.post("/api/biometrics/wearable", json=body, headers=OK)
    assert r.status_code == 200 and r.json() == {"received": 3, "stored": 3, "duplicates": 0}
    assert rows('SELECT kind, value, start, "end", source FROM biometrics ORDER BY kind') == [
        {"kind": "heart_rate_rest", "value": 61.0, "start": "2026-10-13T23:00:00-03:00",
         "end": "2026-10-14T07:00:00-03:00", "source": "simulado"},
        {"kind": "sleep_awakenings", "value": 2.0, "start": "2026-10-13T23:00:00-03:00",
         "end": "2026-10-14T07:00:00-03:00", "source": "simulado"},
        {"kind": "sleep_minutes", "value": 400.0, "start": "2026-10-13T23:00:00-03:00",
         "end": "2026-10-14T07:00:00-03:00", "source": "simulado"},
    ]
    assert rows("SELECT window_start, window_end, received_at, n_samples, scope FROM biometric_syncs") == [
        {"window_start": "2026-10-13T23:00:00-03:00", "window_end": "2026-10-14T08:00:00-03:00",
         "received_at": "2026-10-17T19:00:00-03:00", "n_samples": 3, "scope": "pulsera"}]


def test_default_source_is_a_real_wearable(client):
    body = payload()
    del body["source"]
    client.post("/api/biometrics/wearable", json=body, headers=OK)
    assert rows("SELECT source FROM biometrics") == [{"source": "pulsera"}]


@pytest.mark.parametrize("s,value", [
    (sample("sleep_minutes", 6.5, "h"), 390.0),
    (sample("sleep_minutes", 23400, "s"), 390.0),
    (sample("hrv_ms", 0.032, "s"), 32.0),
    (sample("walking_speed", 3.6, "km/hr"), 1.0),
    (sample("tremor_minutes", 90, "s"), 1.5),
    (sample("resp_rate", 15, "count/min"), 15.0),
])
def test_units_are_normalized(client, s, value):
    assert client.post("/api/biometrics/wearable", json=payload(s), headers=OK).status_code == 200
    assert rows("SELECT value FROM biometrics") == [{"value": pytest.approx(value)}]


@pytest.mark.parametrize("s,message", [
    (sample("pulso", 60, "bpm"), "type 'pulso' no válido"),
    (sample("steps", 400, "count"), "los pasos entran por POST /api/biometrics/atajo"),
    (sample("sleep_minutes", 7, "horas"), "unit 'horas' no válida para sleep_minutes; usar min o h o s"),
    (sample("spo2_pct", 0.97, "%"), "spo2_pct = 0.97 % fuera de rango (50 a 100)"),
    (sample("sleep_minutes", -5, "min"), "fuera de rango"),
    (sample(end="2026-10-13T22:00:00-03:00"), "end (2026-10-13T22:00:00-03:00) es anterior a start"),
])
def test_invalid_sample_is_422_with_a_clear_message_and_nothing_is_stored(client, s, message):
    r = client.post("/api/biometrics/wearable", json=payload(sample(), s), headers=OK)
    assert r.status_code == 422 and message in r.json()["detail"] and r.json()["detail"].startswith("samples[1]")
    assert rows("SELECT * FROM biometrics") == [] and rows("SELECT * FROM biometric_syncs") == []


@pytest.mark.parametrize("change,message", [
    ({"window_start": "2026-10-13T23:00:00"}, "window_start"),
    ({"window_end": "2026-10-13T20:00:00-03:00"}, "window_end tiene que ser posterior"),
    ({"device": {"vendor": "x"}}, "device.model"),
    ({"source": "inventado"}, "source"),
])
def test_invalid_body_is_422(client, change, message):
    r = client.post("/api/biometrics/wearable", json={**payload(), **change}, headers=OK)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_resend_does_not_duplicate(client):
    body = payload(sample(), sample("sleep_awakenings", 2, "count"))
    client.post("/api/biometrics/wearable", json=body, headers=OK)
    r = client.post("/api/biometrics/wearable", json=body, headers=OK)
    assert r.json() == {"received": 2, "stored": 0, "duplicates": 2}
    assert len(rows("SELECT * FROM biometrics")) == 2


@pytest.mark.parametrize("headers", [{}, {"X-Device-Token": "otro"}, {"X-Device-Token": ""}])
def test_bad_token_is_401(client, headers):
    assert client.post("/api/biometrics/wearable", json=payload(), headers=headers).status_code == 401
    assert rows("SELECT * FROM biometrics") == []


def test_falls_back_to_atajo_token(client, monkeypatch):
    monkeypatch.delenv("WEARABLE_TOKEN")
    monkeypatch.setenv("ATAJO_TOKEN", "atajo")
    assert client.post("/api/biometrics/wearable", json=payload(), headers={"X-Device-Token": "atajo"}).status_code == 200
    monkeypatch.delenv("ATAJO_TOKEN")
    assert client.post("/api/biometrics/wearable", json=payload(), headers={"X-Device-Token": "atajo"}).status_code == 401


def test_wearable_window_is_not_a_steps_sync(client):
    from app.rules import episodes
    client.post("/api/biometrics/wearable", json=payload(), headers=OK)
    assert episodes.observed(1, dt.datetime(2026, 10, 13, 23, tzinfo=TZ)) is None

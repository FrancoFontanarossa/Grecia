import datetime as dt

import pytest

from app import clock, db
from app.config import TZ
from data import seed

REAL = dt.datetime(2026, 10, 17, 19, 0, tzinfo=TZ)


@pytest.fixture
def seeded(data_dir, monkeypatch):
    """Base con el seed de la demo (sin pasos importados) y el reloj real fijo."""
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    seed.run()
    return data_dir


def add_entry(speaker_id, text="x", *, created_at, patient_id=1, reserved_requested=False):
    with db.connect() as conn:
        return conn.execute(
            "INSERT INTO entries (patient_id, speaker_id, modality, raw_text, reserved_requested, created_at, source) "
            "VALUES (?, ?, 'texto', ?, ?, ?, 'app')",
            (patient_id, speaker_id, text, int(reserved_requested), db.to_db(created_at))).lastrowid


def add_event(entry_id, *, domain, symptom, speaker_role, occurred_at=None, negated=False, is_new=False,
              reserved=False, patient_id=1, quote="cita"):
    with db.connect() as conn:
        return conn.execute(
            "INSERT INTO events (entry_id, patient_id, domain, symptom, severity, negated, occurred_at, time_vague, "
            "speaker_role, foreign_attribution, quote, plain, confidence, is_new, reserved) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?, 0, ?, NULL, ?, 'plain', 0.9, ?, ?)",
            (entry_id, patient_id, domain, symptom, int(negated), db.to_db(occurred_at) if occurred_at else None,
             speaker_role, quote, int(is_new), int(reserved))).lastrowid


@pytest.fixture
def wearable(seeded, monkeypatch):
    """La pulsera de Juan cargada como en la demo: el simulador la manda por HTTP a la ingesta real."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import biometrics as biometrics_api
    from scripts import simular_pulsera

    monkeypatch.setenv("WEARABLE_TOKEN", "pulsera")
    app = FastAPI()
    app.include_router(biometrics_api.router)
    simular_pulsera.send(TestClient(app), "pulsera", simular_pulsera.payloads())
    return seeded

"""POST /admin/precorrer y su status. La IA está falseada por los fixtures autouse de tests/conftest.py."""
import asyncio
import datetime as dt
import time

import pytest
from fastapi.testclient import TestClient

from app import clock, db, scheduler
from app.api import admin
from app.config import TZ
from data import seed
from scripts import precorrer_semana as pre

OK = {"X-Admin-Token": "admin"}
REAL = dt.datetime(2026, 10, 18, 7, 45, tzinfo=TZ)


def small_scenario() -> pre.Escenario:
    at = lambda d, h, m=0: dt.datetime(2026, 10, d, h, m, tzinfo=TZ)
    relatos = [pre.Relato(at=at(12, 9), person_id=1, text="Hoy me levanté bien, fui a la plaza."),
               pre.Relato(at=at(12, 21), person_id=2, text="Anoche durmió de corrido.", hint="anoche")]
    return pre.Escenario(patient_id=1, relatos=relatos, end=at(12, 23), ticks=[at(12, 10, 5), at(12, 22, 5)])


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    monkeypatch.setenv("ADMIN_TOKEN", "admin")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "x")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:x@y.z")
    monkeypatch.setattr(pre, "ESC", small_scenario())
    monkeypatch.setitem(admin._precorrer, "running", False)
    seed.run()
    from app.main import app
    with TestClient(app) as c:                       # con lifespan: el scheduler en vivo está corriendo
        yield c


def wait_done(client, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = client.get("/admin/precorrer/status", headers=OK).json()
        if s["done"]:
            return s
        time.sleep(0.05)
    raise AssertionError("el precorrido no terminó")


def test_runs_the_script_in_the_background_and_status_reflects_it(client):
    r = client.post("/admin/precorrer", headers=OK)
    assert r.status_code == 200 and r.json() == {"started": True}
    s = wait_done(client)
    assert s["running"] is False and s["relatos_cargados"] == 2 and s["ya_estaban"] == 0
    assert s["reloj"] == "2026-10-12T23:00:00-03:00"
    assert s["informe_generado"] is False and s["errores"] == [
        "el informe final no se pudo generar: volver a correr el precorrido"]    # Sonnet falso no redacta informes
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM entries WHERE source = 'precorrer'").fetchone()[0] == 2
    # Otra vez: no duplica (lo hace el script).
    client.post("/admin/precorrer", headers=OK)
    assert wait_done(client)["ya_estaban"] == 2


def test_cannot_run_twice_at_the_same_time(client, monkeypatch):
    async def slow(esc):
        await asyncio.sleep(0.5)
        return {"cargados": 0, "ya_estaban": 0, "preguntas": [], "informe": {"ok": True}}
    monkeypatch.setattr(pre, "run", slow)
    assert client.post("/admin/precorrer", headers=OK).status_code == 200
    r = client.post("/admin/precorrer", headers=OK)
    assert r.status_code == 409 and "ya está corriendo" in r.json()["detail"]
    assert client.get("/admin/precorrer/status", headers=OK).json()["running"] is True
    assert wait_done(client)["errores"] == []


def test_live_scheduler_is_paused_while_it_runs_and_resumed_after(client, monkeypatch):
    seen = {}

    async def spy(esc):
        seen["scheduler_running"] = scheduler._task is not None
        return {"cargados": 1, "ya_estaban": 0, "preguntas": [7], "informe": {"ok": True}}
    monkeypatch.setattr(pre, "run", spy)
    assert scheduler._task is not None
    client.post("/admin/precorrer", headers=OK)
    s = wait_done(client)
    assert seen == {"scheduler_running": False}
    assert scheduler._task is not None and not scheduler._task.done()
    assert s["informe_generado"] is True and s["preguntas"] == 1 and s["errores"] == []


def test_resumed_even_if_it_fails(client, monkeypatch):
    async def broken(esc):
        raise RuntimeError("se cortó la base")
    monkeypatch.setattr(pre, "run", broken)
    client.post("/admin/precorrer", headers=OK)
    s = wait_done(client)
    assert s["errores"] == ["RuntimeError: se cortó la base"] and s["running"] is False
    assert scheduler._task is not None and not scheduler._task.done()
    assert client.post("/admin/precorrer", headers=OK).status_code == 200      # se puede volver a correr
    wait_done(client)


def test_requires_admin_token(client):
    assert client.post("/admin/precorrer").status_code == 401
    assert client.get("/admin/precorrer/status").status_code == 401

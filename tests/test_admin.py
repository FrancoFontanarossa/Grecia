import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import clock, db
from app.api import admin
from app.config import TZ

REAL = dt.datetime(2026, 10, 17, 19, 0, tzinfo=TZ)
OK = {"X-Admin-Token": "admin"}


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin")
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    app = FastAPI()
    app.include_router(admin.router)
    return TestClient(app)


def people_names():
    with db.connect() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM people ORDER BY id")]


def add_person(id_, name):
    with db.connect() as conn:
        conn.execute("INSERT INTO people (id, patient_id, role, name, relation) VALUES (?, 1, 'familiar', ?, 'x')",
                     (id_, name))


@pytest.mark.parametrize("method,path,body", [
    ("get", "/admin/clock/state", None),
    ("post", "/admin/clock/advance", {"minutes": 10}),
    ("post", "/admin/clock/set", {"iso": "2026-10-13T08:00"}),
    ("post", "/admin/snapshot", None),
    ("post", "/admin/restore", None),
])
@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "otro"}])
def test_requires_admin_token(client, method, path, body, headers):
    r = getattr(client, method)(path, headers=headers, **({"json": body} if body else {}))
    assert r.status_code == 401


def test_unset_admin_token_rejects(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    assert client.get("/admin/clock/state", headers=OK).status_code == 401


def test_clock_endpoints(client):
    assert client.get("/admin/clock/state", headers=OK).json() == {"now": "2026-10-17T19:00:00-03:00", "offset_seconds": 0.0}
    r = client.post("/admin/clock/set", json={"iso": "2026-10-13T08:00"}, headers=OK)
    assert r.json() == {"now": "2026-10-13T08:00:00-03:00"}
    r = client.post("/admin/clock/advance", json={"minutes": 90}, headers=OK)
    assert r.json() == {"now": "2026-10-13T09:30:00-03:00"}
    assert client.get("/admin/clock/state", headers=OK).json()["now"] == "2026-10-13T09:30:00-03:00"


def test_set_with_bad_iso_is_422(client):
    assert client.post("/admin/clock/set", json={"iso": "martes"}, headers=OK).status_code == 422


def test_restore_without_snapshot_is_409(client):
    assert client.post("/admin/restore", headers=OK).status_code == 409


def test_snapshot_change_restore(client, data_dir):
    add_person(1, "Juan")
    client.post("/admin/clock/set", json={"iso": "2026-10-17T15:50"}, headers=OK)
    assert client.post("/admin/snapshot", headers=OK).json() == {"ok": True}
    assert (data_dir / "snapshot.db").exists()

    # Cambios después del snapshot: datos nuevos y el reloj adelantado.
    add_person(2, "Jurado")
    client.post("/admin/clock/advance", json={"minutes": 120}, headers=OK)
    assert people_names() == ["Juan", "Jurado"]

    assert client.post("/admin/restore", headers=OK).json() == {"ok": True}
    assert people_names() == ["Juan"]
    assert clock.now() == dt.datetime(2026, 10, 17, 15, 50, tzinfo=TZ)

    # Se puede restaurar más de una vez (entre ensayos) y la base sigue usable y en WAL.
    add_person(3, "Otro jurado")
    client.post("/admin/restore", headers=OK)
    assert people_names() == ["Juan"]
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"



def test_admin_clock_is_free_for_the_html_panel(client):
    assert client.get("/admin/clock", headers=OK).status_code == 404


def add_sync(window_start, window_end):
    with db.connect() as conn:
        conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
                     "VALUES (1, ?, ?, ?, 0)", (window_start, window_end, window_start))


def add_steps(start, end, value, source="importacion"):
    with db.connect() as conn:
        conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, \'steps\', ?, ?, ?, ?)',
                     (value, start, end, source))


def steps():
    with db.connect() as conn:
        return [(r["start"], r["value"], r["source"])
                for r in conn.execute("SELECT start, value, source FROM biometrics ORDER BY start")]


DROP = {"patient_id": 1, "dose_time": "2026-10-13T16:00:00-03:00", "pct": 0.7}


def test_inject_drop_applies_and_labels_only_the_window(client):
    add_sync("2026-10-13T00:00:00-03:00", "2026-10-14T00:00:00-03:00")
    add_steps("2026-10-13T15:00:00-03:00", "2026-10-13T16:00:00-03:00", 500)   # antes de la toma
    add_steps("2026-10-13T16:00:00-03:00", "2026-10-13T17:00:00-03:00", 400)   # dentro
    add_steps("2026-10-13T17:30:00-03:00", "2026-10-13T17:40:00-03:00", 100, source="atajo")  # dentro
    add_steps("2026-10-13T18:00:00-03:00", "2026-10-13T19:00:00-03:00", 300)   # justo después
    add_steps("2026-10-12T16:00:00-03:00", "2026-10-12T17:00:00-03:00", 450)   # otro día
    assert client.post("/admin/inject_drop", json=DROP, headers=OK).json() == {"ok": True}
    assert steps() == [
        ("2026-10-12T16:00:00-03:00", 450, "importacion"),
        ("2026-10-13T15:00:00-03:00", 500, "importacion"),
        ("2026-10-13T16:00:00-03:00", pytest.approx(120), "inyectado"),
        ("2026-10-13T17:30:00-03:00", pytest.approx(30), "inyectado"),
        ("2026-10-13T18:00:00-03:00", 300, "importacion"),
    ]


def test_inject_drop_twice_does_not_compound(client):
    add_sync("2026-10-13T00:00:00-03:00", "2026-10-14T00:00:00-03:00")
    add_steps("2026-10-13T16:00:00-03:00", "2026-10-13T17:00:00-03:00", 400)
    client.post("/admin/inject_drop", json=DROP, headers=OK)
    client.post("/admin/inject_drop", json=DROP, headers=OK)
    assert steps() == [("2026-10-13T16:00:00-03:00", pytest.approx(120), "inyectado")]


@pytest.mark.parametrize("sync", [None, ("2026-10-13T16:30:00-03:00", "2026-10-13T19:00:00-03:00"),
                                  ("2026-10-13T12:00:00-03:00", "2026-10-13T17:59:00-03:00")])
def test_inject_drop_without_covering_sync_is_409(client, sync):
    if sync:
        add_sync(*sync)
    add_steps("2026-10-13T16:00:00-03:00", "2026-10-13T17:00:00-03:00", 400)
    assert client.post("/admin/inject_drop", json=DROP, headers=OK).status_code == 409
    assert steps() == [("2026-10-13T16:00:00-03:00", 400, "importacion")]


@pytest.mark.parametrize("body", [{**DROP, "pct": 0}, {**DROP, "pct": 1.5}, {**DROP, "dose_time": "2026-10-13T16:00"}])
def test_inject_drop_validates_body(client, body):
    assert client.post("/admin/inject_drop", json=body, headers=OK).status_code == 422


def test_inject_drop_requires_token(client):
    assert client.post("/admin/inject_drop", json=DROP).status_code == 401

from fastapi.testclient import TestClient

from app import config, db
from app.main import app


def test_lifespan_creates_db_and_routes_respond(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "volumen")
    monkeypatch.setenv("ADMIN_TOKEN", "admin")
    monkeypatch.setenv("ATAJO_TOKEN", "atajo")
    with TestClient(app) as client:
        assert db.db_path().exists()
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/admin/clock", headers={"X-Admin-Token": "admin"}).status_code == 200
        body = {"window_start": "2026-10-17T16:00:00-03:00", "window_end": "2026-10-17T19:00:00-03:00", "samples": []}
        r = client.post("/api/biometrics/atajo", json=body, headers={"X-Atajo-Token": "atajo"})
        assert r.json() == {"received": 0}

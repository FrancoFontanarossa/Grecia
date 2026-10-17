from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pywebpush import WebPushException

from app import _tmp_db as db
from app.main import app
from app.notify import push

client = TestClient(app)


def _rows(table):
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def test_texto_se_guarda_y_devuelve_el_contrato(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    texto = "  anoche hablaba con alguien que no estaba; debe ser el cansancio "

    r = client.post("/api/entries", data={"person_id": 2, "text": texto, "occurred_hint": "anoche"})

    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"entry_id", "transcript", "understood", "red", "alerts"}
    assert body["transcript"] == texto.strip()
    assert body["understood"] == [] and body["red"] is None and body["alerts"] == []
    entry = db.get_entry(body["entry_id"])
    assert entry["raw_text"] == texto.strip()
    assert entry["occurred_hint"] == "anoche" and entry["modality"] == "texto" and entry["speaker_id"] == 2


def test_entrada_queda_guardada_aunque_la_push_falle(tmp_data_dir, monkeypatch):
    def boom(**kw):
        raise WebPushException("falló", response=SimpleNamespace(status_code=500, text=""))
    monkeypatch.setattr(push, "webpush", boom)
    db.save_subscription(person_id=1, endpoint="https://push.example/x", p256dh="p", auth="a")

    r = client.post("/api/entries", data={"person_id": 1, "text": "me sentí trabado"})

    assert r.status_code == 200
    assert _rows("entries")[0]["raw_text"] == "me sentí trabado"
    notif = _rows("notifications")
    assert len(notif) == 1 and notif[0]["push_sent"] == 0 and notif[0]["kind"] == "resumen"


def test_manda_recibido_a_quien_conto(tmp_data_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(push, "webpush", lambda **kw: calls.append(kw))
    db.save_subscription(person_id=1, endpoint="https://push.example/x", p256dh="p", auth="a")

    client.post("/api/entries", data={"person_id": 1, "text": "hola"})

    n = _rows("notifications")[0]
    assert (n["person_id"], n["title"], n["url"], n["push_sent"]) == (1, "Recibido", "/casa", 1)
    assert len(calls) == 1


@pytest.mark.parametrize("hint", ["ahora", "esta_manana", "esta_tarde", "anoche", "ayer"])
def test_hints_validos(tmp_data_dir, monkeypatch, hint):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    assert client.post("/api/entries", data={"person_id": 1, "text": "x", "occurred_hint": hint}).status_code == 200


@pytest.mark.parametrize("hint", ["hoy", "Anoche", "esta_noche"])
def test_hint_invalido_da_422_y_no_guarda(tmp_data_dir, hint):
    r = client.post("/api/entries", data={"person_id": 1, "text": "x", "occurred_hint": hint})
    assert r.status_code == 422
    assert _rows("entries") == []


def test_hint_vacio_cuenta_como_sin_hint(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    r = client.post("/api/entries", data={"person_id": 1, "text": "x", "occurred_hint": ""})
    assert r.status_code == 200 and _rows("entries")[0]["occurred_hint"] is None


def test_sin_texto_da_422(tmp_data_dir):
    assert client.post("/api/entries", data={"person_id": 1, "text": "   "}).status_code == 422


def test_respuesta_rapida_se_guarda_como_toque(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    r = client.post("/api/entries", data={"person_id": 1, "question_id": 5, "quick_reply": "Me sentí trabado",
                                          "reserved_requested": "true"})
    assert r.status_code == 200 and r.json()["transcript"] == "Me sentí trabado"
    e = _rows("entries")[0]
    assert (e["modality"], e["question_id"], e["reserved_requested"]) == ("toque", 5, 1)

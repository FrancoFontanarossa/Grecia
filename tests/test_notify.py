import asyncio
from types import SimpleNamespace

import pytest
from pywebpush import WebPushException

from app import _tmp_db as db
from app import notify
from app.notify import push


def _subscribe(person_id, endpoint="https://push.example/abc"):
    db.save_subscription(person_id=person_id, endpoint=endpoint, p256dh="p", auth="a")


def _notifications():
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM notifications")]
    finally:
        conn.close()


def test_guarda_y_marca_push_sent(tmp_data_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(push, "webpush", lambda **kw: calls.append(kw))
    _subscribe(1)

    n = asyncio.run(notify.send(1, "resumen", "Recibido", "Anotamos lo que contaste.", "/casa"))

    assert n.push_sent is True and n.kind == "resumen" and n.created_at.tzinfo is not None
    assert _notifications()[0]["push_sent"] == 1
    assert calls[0]["subscription_info"]["endpoint"] == "https://push.example/abc"
    assert '"url": "/casa"' in calls[0]["data"]


def test_push_que_falla_no_lanza_y_la_notificacion_queda(tmp_data_dir, monkeypatch):
    def boom(**kw):
        raise WebPushException("falló", response=SimpleNamespace(status_code=500, text=""))
    monkeypatch.setattr(push, "webpush", boom)
    _subscribe(1)

    n = asyncio.run(notify.send(1, "resumen", "Recibido", "x", "/casa"))

    assert n.push_sent is False
    rows = _notifications()
    assert len(rows) == 1 and rows[0]["push_sent"] == 0
    assert db.subscriptions_for(1)  # un 500 no borra la suscripción


def test_error_inesperado_tampoco_lanza(tmp_data_dir, monkeypatch):
    def boom(**kw):
        raise ConnectionError("sin red")
    monkeypatch.setattr(push, "webpush", boom)
    _subscribe(1)

    n = asyncio.run(notify.send(1, "resumen", "Recibido", "x", "/casa"))
    assert n.push_sent is False and len(_notifications()) == 1


@pytest.mark.parametrize("status", [404, 410])
def test_suscripcion_vencida_se_borra(tmp_data_dir, monkeypatch, status):
    def gone(**kw):
        raise WebPushException("gone", response=SimpleNamespace(status_code=status, text=""))
    monkeypatch.setattr(push, "webpush", gone)
    _subscribe(1)

    asyncio.run(notify.send(1, "resumen", "Recibido", "x", "/casa"))
    assert db.subscriptions_for(1) == []


def test_sin_suscripciones_guarda_igual(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: pytest.fail("no debería mandar"))
    n = asyncio.run(notify.send(7, "logro", "Juan llegó a su meta", "4.060 pasos hoy.", "/casa"))
    assert n.push_sent is False and _notifications()[0]["person_id"] == 7


def test_manda_a_todas_las_suscripciones_de_la_persona(tmp_data_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(push, "webpush", lambda **kw: calls.append(kw["subscription_info"]["endpoint"]))
    _subscribe(1, "https://push.example/telefono")
    _subscribe(1, "https://push.example/compu")
    _subscribe(2, "https://push.example/otra-persona")

    asyncio.run(notify.send(1, "resumen", "Recibido", "x", "/casa"))
    assert sorted(calls) == ["https://push.example/compu", "https://push.example/telefono"]


def test_sin_vapid_no_manda_pero_guarda(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY")
    monkeypatch.setattr(push, "webpush", lambda **kw: pytest.fail("no debería mandar"))
    _subscribe(1)
    n = asyncio.run(notify.send(1, "resumen", "Recibido", "x", "/casa"))
    assert n.push_sent is False and len(_notifications()) == 1


def test_kind_fuera_del_contrato_falla_antes_de_guardar(tmp_data_dir):
    with pytest.raises(Exception):
        asyncio.run(notify.send(1, "inventado", "t", "b", "/casa"))
    assert _notifications() == []


def test_vapid_public_key(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "BPublica123")
    r = TestClient(app).get("/api/push/vapid-public-key")
    assert r.status_code == 200 and r.json() == {"key": "BPublica123"}


def test_vapid_public_key_faltante_da_503(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    assert TestClient(app).get("/api/push/vapid-public-key").status_code == 503

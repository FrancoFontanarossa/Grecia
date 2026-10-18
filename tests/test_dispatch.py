from fastapi.testclient import TestClient

from app import _tmp_db as db
from app import db as base
from app.main import app
from app.notify import push

client = TestClient(app)


def _rows(sql):
    with base.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def _subscribe_all():
    for pid in (1, 2, 3):
        db.save_subscription(person_id=pid, endpoint=f"https://push.example/{pid}", p256dh="p", auth="a")


def test_rojo_r1_va_a_juan_marta_y_laura_con_la_pantalla_de_emergencia(tmp_data_dir, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kw: sent.append(kw["subscription_info"]["endpoint"]))
    _subscribe_all()
    body = client.post("/api/entries", data={"person_id": 2, "text": "se cayó, se golpeó la cabeza y toma apixabán"}).json()

    [alert] = _rows("SELECT * FROM alerts")
    assert alert["lane"] == "rojo" and alert["rule_id"] == "R1"
    rojos = _rows("SELECT * FROM notifications WHERE kind = 'rojo' ORDER BY person_id")
    assert [n["person_id"] for n in rojos] == [1, 2, 3]
    assert all(n["url"] == f"/casa/emergencia/{alert['id']}" and n["title"] == "Rojo · Juan" for n in rojos)
    assert body["red"]["rule_id"] == "R1" and body["alerts"][0]["lane"] == "rojo"
    assert sorted(set(sent)) == ["https://push.example/1", "https://push.example/2", "https://push.example/3"]


def test_rojo_sale_en_silencio_nocturno(tmp_data_dir, monkeypatch):
    from app import clock
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    clock.set("2026-10-17T03:00:00")
    client.post("/api/entries", data={"person_id": 2, "text": "se golpeó la cabeza y vomitó"})
    assert len(_rows("SELECT * FROM notifications WHERE kind = 'rojo'")) == 3


def test_a1_reservado_a_marta_sin_detalle_y_juan_no_ve_nada(tmp_data_dir, monkeypatch):
    from app.pipeline import extract
    from tests.conftest import FakeModel, tool_response
    from app import clock
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    clock.set("2026-10-14T21:40:00")
    with base.connect() as conn:
        conn.execute("INSERT INTO people (id, patient_id, role, name, relation) VALUES (4, 1, 'neurologo', 'Dra. Pereira', 'neuróloga')")
        conn.execute("INSERT INTO consents (patient_id, recipient_id, kind, enabled) VALUES (1, 2, 'avisos', 1)")
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([{
        "domain": "neuropsiquiatrico", "symptom": "alucinaciones", "negated": False, "foreign_attribution": "el cansancio",
        "severity": None, "time_said": {"day": "ayer", "weekday": None, "part": "noche", "clock": None},
        "quote": "anoche hablaba con alguien que no estaba", "confidence": 0.9,
        "plain": "Anoche Juan habló con alguien que no estaba."}])))

    body = client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba, debe ser el cansancio"}).json()

    a1 = [a for a in _rows("SELECT * FROM alerts") if a["rule_id"] == "A1"]
    assert len(a1) == 1 and a1[0]["reserved"] == 1
    ambar = _rows("SELECT * FROM notifications WHERE kind = 'ambar'")
    assert [n["person_id"] for n in ambar] == [2]                         # Marta; la neuróloga lo ve en el informe
    assert ambar[0]["body"] == "Hay algo nuevo en Hoy." and "alguien" not in ambar[0]["body"]
    assert _rows("SELECT * FROM notifications WHERE person_id = 1 AND kind != 'resumen'") == []   # Juan: nada
    assert any(a["rule_id"] == "A1" for a in body["alerts"])                # Marta ve el aviso en su respuesta


def test_a_juan_no_le_vuelve_un_aviso_reservado_en_la_respuesta(tmp_data_dir):
    from app.api.entries import _visible_to
    from app.models import Alert
    from app import clock
    a = Alert(id=1, patient_id=1, lane="ambar", rule_id="A1", recipients=[], text="x", reserved=True, created_at=clock.now())
    assert not _visible_to(a, {"role": "paciente"}) and _visible_to(a, {"role": "cuidador"})


def test_ambar_a_la_familia_una_push_por_dia(tmp_data_dir, monkeypatch):
    import asyncio
    from app import clock
    from app.models import Alert
    from app.notify import dispatch
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    clock.set("2026-10-15T12:00:00")
    alerts = [Alert(id=i, patient_id=1, lane="ambar", rule_id="A2", recipients=[2], text="x", reserved=False,
                    created_at=clock.now()) for i in (1, 2)]
    assert asyncio.run(dispatch.dispatch(alerts)) == 1

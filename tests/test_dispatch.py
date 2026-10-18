# Alcance de las 04:15: Entrecasa no es un botón de pánico ni un canal con la neuróloga. Los avisos no mandan push:
# el rojo solo muestra un mensaje fijo a quien escribió y queda marcado en el informe; el ámbar es prioridad en el
# informe. Estos tests recorren POST /api/entries de punta a punta con la push falsa.
from fastapi.testclient import TestClient

from app import _tmp_db as db
from app import db as base
from app.main import app
from app.notify import push
from app.rules import red

client = TestClient(app)


def _rows(sql):
    with base.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def _subscribe_all():
    for pid in (1, 2, 3):
        db.save_subscription(person_id=pid, endpoint=f"https://push.example/{pid}", p256dh="p", auth="a")


def test_rojo_solo_muestra_el_mensaje_fijo_a_quien_escribe_y_no_manda_push(tmp_data_dir, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kw: sent.append(kw))
    _subscribe_all()
    body = client.post("/api/entries", data={"person_id": 2, "text": "se cayó, se golpeó la cabeza y toma apixabán"}).json()

    assert body["red"]["rule_id"] == "R1" and body["red"]["text"] == red.RED_MESSAGE
    [alert] = _rows("SELECT * FROM alerts")
    assert alert["lane"] == "rojo" and alert["rule_id"] == "R1" and alert["text"] == red.RED_LABELS["R1"]
    assert alert["recipients"] == "[]"                                     # marcado para el informe, a nadie
    assert _rows("SELECT * FROM notifications") == [] and sent == []


def test_rojo_se_extrae_igual_para_anote_esto(tmp_data_dir, monkeypatch, fake_model):
    from tests.conftest import tool_response
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    fake_model.responses = [tool_response([{
        "domain": "caidas", "symptom": "caida", "negated": False, "foreign_attribution": None, "severity": None,
        "time_said": {"day": "hoy", "weekday": None, "part": None, "clock": None},
        "quote": "se cayó, se golpeó la cabeza", "confidence": 0.9, "plain": "Juan se cayó y se golpeó la cabeza."}])]
    body = client.post("/api/entries", data={"person_id": 2, "text": "se cayó, se golpeó la cabeza y toma apixabán"}).json()
    assert body["red"]["text"] == red.RED_MESSAGE
    assert [u["plain"] for u in body["understood"]] == ["Juan se cayó y se golpeó la cabeza."]


def test_r4_muestra_la_linea_vida(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    body = client.post("/api/entries", data={"person_id": 1, "text": "ya no quiero vivir"}).json()
    assert body["red"]["rule_id"] == "R4" and "0800 0767" in body["red"]["text"]
    assert _rows("SELECT * FROM notifications") == []


def test_ambar_no_notifica_a_nadie_y_juan_no_ve_nada(tmp_data_dir, monkeypatch):
    from app.pipeline import extract
    from tests.conftest import FakeModel, tool_response
    from app import clock
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    _subscribe_all()
    clock.set("2026-10-14T21:40:00")
    with base.connect() as conn:
        conn.execute("INSERT INTO people (id, patient_id, role, name, relation) VALUES (4, 1, 'neurologo', 'Dra. Pereira', 'neuróloga')")
        conn.execute("INSERT INTO consents (patient_id, recipient_id, kind, enabled) VALUES (1, 2, 'avisos', 1)")
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([{
        "domain": "neuropsiquiatrico", "symptom": "alucinaciones", "negated": False, "foreign_attribution": "el cansancio",
        "severity": None, "time_said": {"day": "ayer", "weekday": None, "part": "noche", "clock": None},
        "quote": "anoche hablaba con alguien que no estaba", "confidence": 0.9,
        "plain": "Anoche Juan habló con alguien que no estaba."}])))

    client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba, debe ser el cansancio"})

    a1 = [a for a in _rows("SELECT * FROM alerts") if a["rule_id"] == "A1"]
    assert len(a1) == 1 and a1[0]["reserved"] == 1 and a1[0]["recipients"] == "[4]"   # solo el equipo, en el informe
    assert _rows("SELECT * FROM notifications") == []


def test_a_juan_no_le_vuelve_un_aviso_reservado_en_la_respuesta(tmp_data_dir):
    from app.api.entries import _visible_to
    from app.models import Alert
    from app import clock
    a = Alert(id=1, patient_id=1, lane="ambar", rule_id="A1", recipients=[], text="x", reserved=True, created_at=clock.now())
    assert not _visible_to(a, {"role": "paciente"}) and _visible_to(a, {"role": "cuidador"})


def test_dispatch_no_manda_nada(tmp_data_dir, monkeypatch):
    import asyncio
    from app import clock
    from app.models import Alert
    from app.notify import dispatch
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    alerts = [Alert(id=i, patient_id=1, lane=lane, rule_id="A2", recipients=[2], text="x", reserved=False,
                    created_at=clock.now()) for i, lane in ((1, "ambar"), (2, "rojo"))]
    assert asyncio.run(dispatch.dispatch(alerts)) == 0
    assert _rows("SELECT * FROM notifications") == []


def test_pedido_de_medicacion_devuelve_el_texto_fijo_de_limites(tmp_data_dir, monkeypatch):
    from app.rules import limits
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    body = client.post("/api/entries", data={"person_id": 2, "text": "¿le subo el pramipexol?"}).json()
    assert body["limit"] == limits.LIMIT_TEXT
    assert db.get_entry(body["entry_id"])["raw_text"] == "¿le subo el pramipexol?"   # se anota igual
    assert client.post("/api/entries", data={"person_id": 2, "text": "hoy caminó bien"}).json()["limit"] is None

import json

from fastapi.testclient import TestClient

from app import clock
from app import db as base
from app.main import app
from app.notify import push
from app.pipeline import extract, llm
from tests.conftest import FakeModel, FakeSonnet, tool_response

client = TestClient(app)


def rows(sql):
    with base.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def ev(symptom, domain, quote, plain, **over):
    return {"domain": domain, "symptom": symptom, "negated": False, "foreign_attribution": None, "severity": None,
            "time_said": {"day": "ayer", "weekday": None, "part": "noche", "clock": None},
            "quote": quote, "plain": plain, "confidence": 0.9, **over}


ALUCINACION = ev("alucinaciones", "neuropsiquiatrico", "anoche hablaba con alguien que no estaba",
                 "Anoche Juan habló con alguien que no estaba.", foreign_attribution="el cansancio")
CANSANCIO = ev("cansancio", "sueno", "anoche estaba muy cansado", "Anoche Juan estaba muy cansado.")


def test_confirm(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    eid = client.post("/api/entries", data={"person_id": 1, "text": "hola"}).json()["entry_id"]
    assert client.post(f"/api/entries/{eid}/confirm").json() == {"ok": True}
    assert client.post("/api/entries/999/confirm").status_code == 404


def test_correct_reemplaza_eventos_y_marca_corrected(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([ALUCINACION]), tool_response([CANSANCIO])))
    eid = client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba, debe ser el cansancio"}).json()["entry_id"]

    r = client.post(f"/api/entries/{eid}/correct", data={"text": "anoche estaba muy cansado"})

    body = r.json()
    assert set(body) >= {"entry_id", "transcript", "understood", "red", "alerts"} and body["entry_id"] == eid
    assert body["transcript"] == "anoche estaba muy cansado" and body["understood"][0]["domain"] == "sueno"
    [e] = rows(f"SELECT * FROM entries WHERE id = {eid}")
    assert e["corrected"] == 1 and e["raw_text"] == "anoche estaba muy cansado"
    assert [x["symptom"] for x in rows("SELECT symptom FROM events")] == ["cansancio"]


def test_corregir_un_reservado_a_no_reservado_no_filtra_el_anterior_a_juan(tmp_data_dir, monkeypatch):
    from app.pipeline import context
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    clock.set("2026-10-14T21:40:00")
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([ALUCINACION]), tool_response([CANSANCIO])))
    eid = client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba, debe ser el cansancio"}).json()["entry_id"]
    assert any(a["rule_id"] == "A1" and a["reserved"] == 1 for a in rows("SELECT * FROM alerts"))

    client.post(f"/api/entries/{eid}/correct", data={"text": "anoche estaba muy cansado"})

    # El A1 reservado y el evento viejo desaparecen; nada del relato anterior queda en la base.
    assert not [a for a in rows("SELECT * FROM alerts") if a["rule_id"] in ("A1", "A2") and "alucin" in a["text"].lower()]
    dump = json.dumps([rows("SELECT * FROM entries"), rows("SELECT * FROM events"), rows("SELECT * FROM alerts"),
                       rows("SELECT * FROM notifications")], ensure_ascii=False)
    assert "hablaba con alguien" not in dump
    # Lo que Juan puede ver: avisos y contexto de las preguntas, sin rastro del relato anterior.
    for a in rows("SELECT * FROM alerts"):
        if 1 in json.loads(a["recipients"]):
            assert "alucin" not in a["text"].lower()
    from app import _tmp_db as db
    visible = context.for_recipient(db.recent_entries(1, clock.now().replace(day=10)), "paciente")
    assert [v.text for v in visible] == ["anoche estaba muy cansado"]


def test_corregir_no_borra_un_rojo_ya_marcado(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    eid = client.post("/api/entries", data={"person_id": 2, "text": "se golpeó la cabeza y toma apixabán"}).json()["entry_id"]
    client.post(f"/api/entries/{eid}/correct", data={"text": "se golpeó la rodilla"})
    assert [a["rule_id"] for a in rows("SELECT rule_id FROM alerts WHERE lane = 'rojo'")] == ["R1"]
    assert rows("SELECT * FROM notifications") == []          # alcance de las 04:15: el rojo no manda push


def test_corregir_con_audio_transcribe(tmp_data_dir, monkeypatch):
    from app.pipeline import transcribe
    monkeypatch.setattr(push, "webpush", lambda **kw: None)

    async def fake(path):
        return "anoche estaba muy cansado"
    monkeypatch.setattr(transcribe, "transcribe", fake)
    eid = client.post("/api/entries", data={"person_id": 2, "text": "algo"}).json()["entry_id"]
    r = client.post(f"/api/entries/{eid}/correct", files={"audio": ("a.m4a", b"\x00", "audio/mp4")})
    assert r.json()["transcript"] == "anoche estaba muy cansado"
    [e] = rows(f"SELECT * FROM entries WHERE id = {eid}")
    assert e["modality"] == "audio" and e["audio_path"].endswith(".m4a") and e["corrected"] == 1


def test_correct_sin_texto_ni_audio_y_entrada_inexistente(tmp_data_dir):
    assert client.post("/api/entries/999/correct", data={"text": "x"}).status_code == 404
    eid = client.post("/api/entries", data={"person_id": 1, "text": "hola"}).json()["entry_id"]
    assert client.post(f"/api/entries/{eid}/correct", data={"text": " "}).status_code == 422


# ── 2d: la respuesta de POST /api/entries trae alerts para R1, A1 y A3 ──

def test_alerts_en_la_respuesta_r1_a1_a3(tmp_data_dir, monkeypatch):
    import datetime as dt
    from app import _tmp_db as db
    from app.config import TZ
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    r1 = client.post("/api/entries", data={"person_id": 2, "text": "se golpeó la cabeza y toma apixabán"}).json()
    assert [a["rule_id"] for a in r1["alerts"]] == ["R1"]

    clock.set("2026-10-14T21:40:00")
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([ALUCINACION])))
    a1 = client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba"}).json()
    assert "A1" in [a["rule_id"] for a in a1["alerts"]]

    for day in (13, 15, 16):
        db.insert_episode(patient_id=1, dose_time=dt.datetime(2026, 10, day, 16, tzinfo=TZ), deviation=None,
                          explanation={}, question_id=None, status="preguntado")
    clock.set("2026-10-16T19:00:00")
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([])))
    a3 = client.post("/api/entries", data={"person_id": 2, "text": "hoy estuvo tranquilo"}).json()
    assert "A3" in {a["rule_id"] for a in a3["alerts"]} and "A3-sugerencia" not in {a["rule_id"] for a in a3["alerts"]}


# ── GET /api/entries/{id} ──

def test_get_entry_devuelve_lo_guardado_sin_llamar_a_la_ia(tmp_data_dir, monkeypatch, fake_model):
    clock.set("2026-10-14T21:40:00")
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([ALUCINACION])))
    posted = client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba"}).json()
    calls = len(extract._call_model.calls)

    got = TestClient(app, cookies={"ec_person": "2"}).get(f"/api/entries/{posted['entry_id']}").json()

    assert len(extract._call_model.calls) == calls                       # sin IA
    assert got["entry_id"] == posted["entry_id"] and got["transcript"] == posted["transcript"]
    assert [u["plain"] for u in got["understood"]] == [u["plain"] for u in posted["understood"]]
    assert got["understood"][0]["domain_label"] == "Alucinaciones y confusión" and got["understood"][0]["reserved"] is True
    assert {a["rule_id"] for a in got["alerts"]} == {a["rule_id"] for a in posted["alerts"]}


def test_get_entry_juan_no_ve_un_relato_reservado_de_marta(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([ALUCINACION])))
    eid = client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba"}).json()["entry_id"]
    assert TestClient(app, cookies={"ec_person": "1"}).get(f"/api/entries/{eid}").status_code == 404
    assert client.get(f"/api/entries/{eid}?person_id=3").status_code == 404           # Laura tampoco
    assert client.get(f"/api/entries/{eid}").status_code == 404                        # sin identificar
    assert client.get(f"/api/entries/{eid}?person_id=2").status_code == 200            # quien lo contó
    with base.connect() as conn:
        conn.execute("INSERT INTO people (id, patient_id, role, name, relation) VALUES (4, 1, 'neurologo', 'Dra. Pereira', 'neuróloga')")
    assert client.get(f"/api/entries/{eid}?person_id=4").status_code == 200            # el equipo
    assert client.get("/api/entries/999?person_id=2").status_code == 404


def test_get_entry_rojo_y_audio_sin_transcribir(tmp_data_dir, monkeypatch):
    rojo = client.post("/api/entries", data={"person_id": 2, "text": "se golpeó la cabeza y toma apixabán"}).json()
    got = client.get(f"/api/entries/{rojo['entry_id']}?person_id=2").json()
    assert got["red"]["rule_id"] == "R1" and [a["rule_id"] for a in got["alerts"]] == ["R1"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    eid = client.post("/api/entries", data={"person_id": 2}, files={"audio": ("a.m4a", b"\x00", "audio/mp4")}).json()["entry_id"]
    got = client.get(f"/api/entries/{eid}?person_id=2").json()
    assert got["transcript"] == "" and got["error_code"] == "ia"

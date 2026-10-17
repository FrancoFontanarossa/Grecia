from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pywebpush import WebPushException

from app import _tmp_db as db
from app import db as base
from app.main import app
from app.notify import push

client = TestClient(app)


def _rows(table):
    with base.connect() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def test_texto_se_guarda_y_devuelve_el_contrato(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    texto = "  anoche hablaba con alguien que no estaba; debe ser el cansancio "

    r = client.post("/api/entries", data={"person_id": 2, "text": texto, "occurred_hint": "anoche"})

    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"entry_id", "transcript", "understood", "red", "alerts"}  # sin "error"
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


def test_understood_sale_de_la_extraccion(tmp_data_dir, monkeypatch):
    from app.pipeline import extract
    from tests.conftest import FakeModel, tool_response
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([{
        "domain": "motor", "symptom": "rigidez", "negated": False, "foreign_attribution": None, "severity": None,
        "time_said": {"day": "no_dice", "weekday": None, "part": "tarde", "clock": None},
        "quote": "me sentí trabado", "confidence": 0.8, "plain": "A la tarde te sentiste trabado."}])))

    r = client.post("/api/entries", data={"person_id": 1, "text": "me sentí trabado"})

    [u] = r.json()["understood"]
    assert u["plain"] == "A la tarde te sentiste trabado." and u["domain"] == "motor"
    assert u["domain_label"] == "Movimiento" and u["when"]
    assert "error" not in r.json()


def test_si_falla_la_ia_queda_el_texto_crudo_y_el_mensaje(tmp_data_dir, monkeypatch):
    import anthropic
    from app.pipeline import extract
    from tests.conftest import FakeModel
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    monkeypatch.setattr(extract, "_call_model", FakeModel(anthropic.APIConnectionError(request=None)))

    r = client.post("/api/entries", data={"person_id": 2, "text": "anoche hablaba con alguien que no estaba"})

    assert r.status_code == 200
    body = r.json()
    assert body["understood"] == [] and body["error"].startswith("No pude entenderlo esta vez")
    assert _rows("entries")[0]["raw_text"] == "anoche hablaba con alguien que no estaba"


def _marta_event(**over):
    base = {"domain": "neuropsiquiatrico", "symptom": "alucinaciones", "negated": False,
            "foreign_attribution": "el cansancio", "severity": None,
            "time_said": {"day": "ayer", "weekday": None, "part": "noche", "clock": None},
            "quote": "anoche hablaba con alguien que no estaba", "confidence": 0.9,
            "plain": "Anoche Juan habló con alguien que no estaba. Vos pensás que fue el cansancio."}
    return {**base, **over}


def test_los_eventos_se_guardan_con_is_new_y_reserved(tmp_data_dir, monkeypatch):
    from app.pipeline import extract
    from tests.conftest import FakeModel, tool_response
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([_marta_event()])))
    texto = "anoche hablaba con alguien que no estaba, debe ser el cansancio"

    first = client.post("/api/entries", data={"person_id": 2, "text": texto}).json()
    second = client.post("/api/entries", data={"person_id": 2, "text": texto}).json()

    rows = _rows("events")
    assert [r["entry_id"] for r in rows] == [first["entry_id"], second["entry_id"]]
    assert [r["is_new"] for r in rows] == [1, 0]        # la segunda vez ya no es primera mención
    assert all(r["reserved"] == 1 for r in rows)        # Marta + neuropsiquiátrico → reservado
    r = rows[0]
    assert (r["speaker_role"], r["foreign_attribution"], r["patient_id"]) == ("cuidador", "el cansancio", 1)
    assert r["occurred_at"].startswith("2026-") and r["quote"] == "anoche hablaba con alguien que no estaba"


def test_lo_de_juan_no_es_reservado_aunque_lo_pida(tmp_data_dir, monkeypatch):
    from app.pipeline import extract
    from tests.conftest import FakeModel, tool_response
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([_marta_event(
        quote="veía gente", plain="Viste gente que no estaba.", foreign_attribution=None)])))
    client.post("/api/entries", data={"person_id": 1, "text": "veía gente", "reserved_requested": "true"})
    assert _rows("events")[0]["reserved"] == 0


def test_si_falla_la_ia_no_hay_eventos(tmp_data_dir, monkeypatch):
    import anthropic
    from app.pipeline import extract
    from tests.conftest import FakeModel
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    monkeypatch.setattr(extract, "_call_model", FakeModel(anthropic.APIConnectionError(request=None)))
    client.post("/api/entries", data={"person_id": 2, "text": "algo"})
    assert _rows("events") == [] and len(_rows("entries")) == 1


def test_audio_se_transcribe_y_se_extrae(tmp_data_dir, monkeypatch):
    from app.pipeline import extract, transcribe
    from tests.conftest import FakeModel, tool_response
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    seen = {}

    async def fake_transcribe(path):
        seen["path"] = path
        return "anoche hablaba con alguien que no estaba, debe ser el cansancio"
    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    monkeypatch.setattr(extract, "_call_model", FakeModel(tool_response([_marta_event()])))

    r = client.post("/api/entries", data={"person_id": 2, "occurred_hint": "anoche"},
                    files={"audio": ("grabacion", b"\x00audio", "audio/mp4;codecs=mp4a.40.2")})

    assert r.status_code == 200
    body = r.json()
    assert body["transcript"].startswith("anoche hablaba") and len(body["understood"]) == 1 and "error" not in body
    e = _rows("entries")[0]
    assert e["modality"] == "audio" and e["raw_text"].startswith("anoche hablaba")
    assert e["audio_path"].startswith("audios/") and e["audio_path"].endswith(".m4a")
    assert seen["path"].suffix == ".m4a" and (tmp_data_dir / e["audio_path"]).read_bytes() == b"\x00audio"
    assert len(_rows("events")) == 1


def test_audio_sin_transcribir_queda_guardado_con_texto_vacio(tmp_data_dir, monkeypatch):
    from app.pipeline import transcribe
    monkeypatch.setattr(push, "webpush", lambda **kw: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    r = client.post("/api/entries", data={"person_id": 2},
                    files={"audio": ("a.webm", b"\x00audio", "audio/webm")})

    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "" and body["understood"] == []
    assert body["error"] == "No pude entenderlo esta vez. Lo guardé tal cual para tu neuróloga."
    e = _rows("entries")[0]
    assert e["raw_text"] == "" and e["modality"] == "audio" and e["audio_path"].endswith(".webm")
    assert _rows("events") == [] and len(_rows("notifications")) == 1


def test_audio_de_formato_desconocido_da_415_y_no_guarda(tmp_data_dir):
    r = client.post("/api/entries", data={"person_id": 2}, files={"audio": ("a.mp3", b"x", "audio/mpeg")})
    assert r.status_code == 415 and _rows("entries") == []

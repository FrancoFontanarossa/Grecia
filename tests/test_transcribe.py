import asyncio
from types import SimpleNamespace

import openai
import pytest

from app.pipeline import transcribe as t


@pytest.mark.parametrize("ctype, ext", [
    ("audio/mp4", ".m4a"),
    ("audio/mp4;codecs=mp4a.40.2", ".m4a"),     # Safari en iPhone
    ("Audio/MP4", ".m4a"),
    ("audio/webm", ".webm"),
    ("audio/webm;codecs=opus", ".webm"),         # Chrome / Android
    ("audio/ogg; codecs=opus", ".ogg"),
])
def test_extension_por_content_type(ctype, ext):
    assert t.extension_for(ctype) == ext


@pytest.mark.parametrize("ctype", [None, "", "video/mp4", "audio/mpeg", "text/plain"])
def test_content_type_desconocido(ctype):
    with pytest.raises(t.UnsupportedAudio):
        t.extension_for(ctype)


def test_guarda_en_data_dir_audios_con_extension(tmp_data_dir):
    path = t.save_audio(b"\x00\x01audio", "audio/mp4;codecs=mp4a.40.2")
    assert path.parent == tmp_data_dir / "audios" and path.suffix == ".m4a"
    assert path.read_bytes() == b"\x00\x01audio"


def test_audio_vacio_o_enorme(tmp_data_dir, monkeypatch):
    with pytest.raises(t.NotHeard):
        t.save_audio(b"", "audio/mp4")
    monkeypatch.setattr(t, "MAX_BYTES", 4)
    with pytest.raises(t.UnsupportedAudio):
        t.save_audio(b"12345", "audio/mp4")


class FakeTranscriptions:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.kwargs = result, error, None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def _fake_client(monkeypatch, **kw):
    fake = FakeTranscriptions(**kw)
    monkeypatch.setattr(t, "_client", SimpleNamespace(audio=SimpleNamespace(transcriptions=fake)))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return fake


def test_transcribe_manda_nombre_con_extension_idioma_y_farmacos(tmp_data_dir, monkeypatch):
    fake = _fake_client(monkeypatch, result=SimpleNamespace(text="  me sentí trabado  "))
    path = t.save_audio(b"audio", "audio/mp4")

    assert asyncio.run(t.transcribe(path)) == "me sentí trabado"
    name, data, ctype = fake.kwargs["file"]
    assert name.endswith(".m4a") and data == b"audio" and ctype == "audio/mp4"
    assert fake.kwargs["model"] == "gpt-4o-transcribe" and fake.kwargs["language"] == "es"
    assert all(d in fake.kwargs["prompt"] for d in ("levodopa", "carbidopa", "pramipexol", "apixabán"))


def test_sin_key_es_error_claro(tmp_data_dir, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = t.save_audio(b"audio", "audio/webm")
    with pytest.raises(t.TranscriptionError, match="OPENAI_API_KEY"):
        asyncio.run(t.transcribe(path))


def test_error_de_api_es_transcription_error(tmp_data_dir, monkeypatch):
    _fake_client(monkeypatch, error=openai.APIConnectionError(request=SimpleNamespace()))
    path = t.save_audio(b"audio", "audio/webm")
    with pytest.raises(t.TranscriptionError):
        asyncio.run(t.transcribe(path))


def test_transcripcion_vacia_es_error(tmp_data_dir, monkeypatch):
    _fake_client(monkeypatch, result=SimpleNamespace(text="   "))
    path = t.save_audio(b"audio", "audio/ogg")
    with pytest.raises(t.TranscriptionError):
        asyncio.run(t.transcribe(path))


@pytest.mark.parametrize("eco", ["La vida de alguien que vive con Parkinson",
                                 "Relato en español rioplatense sobre la vida diaria de una persona con Parkinson."])
def test_el_eco_del_prompt_es_no_te_escuche(eco):
    assert t.unintelligible(eco)


@pytest.mark.parametrize("eco", [
    "Mi vida diaria incluye tomar levodopa, carbidopa, pramipexol y apixabán.",     # el del iPhone, con silencio
    "Tomo apixabán y pramipexol en mi vida diaria con Parkinson.",                 # parafraseado, otro orden
    "Mi relato sobre la vida diaria con Parkinson y los medicamentos.",
    "Mi vida diaria incluye tomar levodopa, carbidopa, pramipexol y apixabán",
    "Relato en español rioplatense sobre la vida diaria de una persona con Parkinson",
])
def test_el_eco_parafraseado_del_prompt_es_no_te_escuche(eco):
    assert t.unintelligible(eco)


@pytest.mark.parametrize("real", ["Anoche hablaba con alguien que no estaba. Debe ser el cansancio.",
                                  "Se cayó en el baño, se golpeó la cabeza y toma apixabán.",
                                  # un rojo que nombra tres fármacos no puede volverse "no te escuché"
                                  "Se cayó, se golpeó la cabeza y toma levodopa, carbidopa y apixabán.",
                                  "Hoy me olvidé la levodopa y el pramipexol, y a la tarde estaba duro.",
                                  "Tomé la levodopa a las ocho.",
                                  "Desde que le subieron el pramipexol duerme peor, dice que es por el Parkinson."])
def test_un_relato_real_no_es_eco(real):
    assert not t.unintelligible(real)


# ── Los fármacos solos no son eco, y un rojo nunca es "no te escuché" ──

@pytest.mark.parametrize("real", [
    "Tomé la levodopa, la carbidopa y el pramipexol",
    "Tomo levodopa, carbidopa y apixabán",
    "Ya tomé el pramipexol y la levodopa",
    "Me caí. Tomo levodopa, carbidopa, pramipexol y apixabán.",
    "Me golpeé la cabeza, tomo levodopa, carbidopa, pramipexol y apixabán",
    "Juan se cayó y se golpeó la cabeza. Toma levodopa carbidopa pramipexol apixabán",
    "La vida con Parkinson es difícil, hoy tomé la levodopa tarde",
])
def test_nombrar_farmacos_no_es_no_te_escuche(real):
    assert not t.unintelligible(real)


@pytest.mark.parametrize("solo_farmacos", ["Levodopa, pramipexol, apixabán.",
                                           "Medicamentos: levodopa, carbidopa, pramipexol, apixabán."])
def test_solo_nombres_de_farmacos_ya_no_es_eco(solo_farmacos):
    # Antes eran eco; ahora hacen falta 2 palabras del prompt que no sean fármacos: mejor guardarlo que perder un rojo.
    assert not t.unintelligible(solo_farmacos)


@pytest.mark.parametrize("rojo", ["Me golpeé la cabeza, tomo levodopa, carbidopa, pramipexol y apixabán",
                                  "Relato de la vida diaria de una persona con Parkinson: se golpeó la cabeza y vomitó",
                                  "No puede tragar y vomita, toma levodopa"])
def test_un_rojo_nunca_es_no_te_escuche(rojo):
    assert t.is_red(rojo) and not t.unintelligible(rojo)


def test_transcribe_no_descarta_un_rojo(tmp_data_dir, monkeypatch):
    texto = "Me golpeé la cabeza, tomo levodopa, carbidopa, pramipexol y apixabán"
    _fake_client(monkeypatch, result=SimpleNamespace(text=texto))
    path = t.save_audio(b"audio", "audio/mp4")
    assert asyncio.run(t.transcribe(path)) == texto


def _relatos_reales() -> list[str]:
    import json
    from pathlib import Path

    import yaml
    root = Path(__file__).resolve().parent.parent
    textos = []
    for name in ("relatos", "rojos", "cebos"):
        textos += [json.loads(line)["text"] for line in (root / "eval" / "sets" / f"{name}.jsonl").read_text("utf-8").splitlines() if line.strip()]
    escenario = yaml.safe_load((root / "data" / "escenario" / "juan.yaml").read_text("utf-8"))
    textos += [r["texto"] for r in escenario["relatos"]]
    return textos


def test_cero_falsos_no_te_escuche_en_los_101_relatos_reales():
    textos = _relatos_reales()
    assert len(textos) == 101
    assert [x for x in textos if t.unintelligible(x)] == []

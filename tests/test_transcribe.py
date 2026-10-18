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

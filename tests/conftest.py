from types import SimpleNamespace

import pytest

from app.pipeline import extract


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Base SQLite nueva en un directorio temporal para cada test."""
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "clave-de-prueba")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@entrecasa.uy")
    return tmp_path


def tool_response(events: list[dict] | None = None, *, stop_reason: str = "tool_use", tool: bool = True):
    """Respuesta falsa de Claude con una llamada a registrar_eventos."""
    content = [SimpleNamespace(type="tool_use", name=extract.TOOL_NAME, input={"events": events or []})] if tool else []
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeModel:
    """Reemplaza extract._call_model: devuelve las respuestas en orden y guarda lo que recibió."""
    def __init__(self, *responses):
        self.responses = list(responses) or [tool_response()]
        self.calls: list[tuple[list, str]] = []

    async def __call__(self, system, content):
        self.calls.append((system, content))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    """Ningún test llama a la API real. Por defecto la extracción devuelve cero eventos."""
    fake = FakeModel()
    monkeypatch.setattr(extract, "_call_model", fake)
    return fake

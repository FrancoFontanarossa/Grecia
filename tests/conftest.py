from types import SimpleNamespace

import pytest

from app import config, db
from app.pipeline import extract


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Base nueva en un directorio temporal para cada test."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init()
    return tmp_path


@pytest.fixture
def tmp_data_dir(data_dir, monkeypatch):
    """La base de data_dir con Juan (1), Marta (2) y Laura (3) del paciente 1, y VAPID de prueba."""
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "clave-de-prueba")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@entrecasa.uy")
    with db.connect() as conn:
        conn.executemany("INSERT INTO people (id, patient_id, role, name, relation) VALUES (?, 1, ?, ?, ?)",
                         [(1, "paciente", "Juan", "paciente"), (2, "cuidador", "Marta", "esposa"),
                          (3, "familiar", "Laura", "hija")])
    return data_dir


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

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Base SQLite nueva en un directorio temporal para cada test."""
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "clave-de-prueba")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@entrecasa.uy")
    return tmp_path

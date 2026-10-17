import pytest

from app import config, db


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Base nueva en un directorio temporal para cada test."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init()
    return tmp_path

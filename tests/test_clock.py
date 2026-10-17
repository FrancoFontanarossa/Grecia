import datetime as dt

import pytest

from app import clock, db
from app.config import TZ

REAL = dt.datetime(2026, 10, 17, 19, 0, tzinfo=TZ)


@pytest.fixture
def frozen(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)


def test_starts_at_real_time(frozen):
    assert clock.offset() == dt.timedelta(0)
    assert clock.now() == REAL


def test_advance_accumulates(frozen):
    clock.advance(90)
    assert clock.advance(30) == REAL + dt.timedelta(hours=2)
    assert clock.offset() == dt.timedelta(hours=2)


def test_set_with_zone(frozen):
    assert clock.set("2026-10-13T15:50:00-03:00") == dt.datetime(2026, 10, 13, 15, 50, tzinfo=TZ)


def test_set_without_zone_is_montevideo(frozen):
    assert clock.set("2026-10-13T15:50") == dt.datetime(2026, 10, 13, 15, 50, tzinfo=TZ)


def test_set_from_utc(frozen):
    assert clock.set("2026-10-13T18:50:00+00:00") == dt.datetime(2026, 10, 13, 15, 50, tzinfo=TZ)


def test_always_montevideo(frozen):
    clock.set("2026-10-13T18:50:00+00:00")
    for value in (clock.now(), clock.advance(5)):
        assert value.tzinfo == TZ
        assert value.utcoffset() == dt.timedelta(hours=-3)


def test_real_now_is_aware_montevideo():
    assert clock._real_now().tzinfo == TZ


def test_survives_reopening_the_db(frozen):
    clock.set("2026-10-12T08:00")
    # Simula un redeploy: se vuelve a inicializar la base y se lee de nuevo desde el archivo.
    db.init()
    assert clock.now() == dt.datetime(2026, 10, 12, 8, 0, tzinfo=TZ)
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM clock_state").fetchone()[0] == 1


def test_offset_follows_real_time(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    clock.set("2026-10-12T08:00")
    monkeypatch.setattr(clock, "_real_now", lambda: REAL + dt.timedelta(minutes=10))
    assert clock.now() == dt.datetime(2026, 10, 12, 8, 10, tzinfo=TZ)

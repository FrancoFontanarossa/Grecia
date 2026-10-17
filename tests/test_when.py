import datetime as dt

import pytest

from app.config import TZ
from app.pipeline.when import TimeSaid, describe, resolve

# sábado 17/10/2026 19:20
CREATED = dt.datetime(2026, 10, 17, 19, 20, tzinfo=TZ)
NO_DICE = TimeSaid(day="no_dice")


def at(day, h, m=0):
    return dt.datetime(2026, 10, day, h, m, tzinfo=TZ)


def test_sin_nada_usa_created_at_vago():
    assert resolve(NO_DICE, None, CREATED) == (CREATED, True)


def test_hint_ahora_es_exacto():
    assert resolve(NO_DICE, "ahora", CREATED) == (CREATED, False)


@pytest.mark.parametrize("hint, expected", [
    ("esta_manana", at(17, 9)), ("esta_tarde", at(17, 16)), ("anoche", at(16, 22)), ("ayer", at(16, 12)),
])
def test_hint_cuando_el_relato_no_dice(hint, expected):
    assert resolve(NO_DICE, hint, CREATED) == (expected, True)


def test_el_relato_le_gana_al_hint():
    ts = TimeSaid(day="anteayer", part="tarde")
    assert resolve(ts, "anoche", CREATED) == (at(15, 16), True)


def test_hora_dicha_es_exacta():
    ts = TimeSaid(day="hoy", part="tarde", clock="17:00")
    assert resolve(ts, None, CREATED) == (at(17, 17), False)


def test_anoche_es_ayer_a_la_noche():
    assert resolve(TimeSaid(day="ayer", part="noche"), None, CREATED) == (at(16, 22), True)


def test_franja_sin_dia_toma_el_dia_del_hint():
    assert resolve(TimeSaid(day="no_dice", part="tarde"), "ayer", CREATED) == (at(16, 16), True)


def test_dia_de_la_semana_va_para_atras():
    assert resolve(TimeSaid(day="dia_semana", weekday="martes", part="noche"), None, CREATED) == (at(13, 22), True)


def test_nunca_en_el_futuro():
    early = at(17, 10)
    assert resolve(TimeSaid(day="hoy", part="noche"), None, early) == (early, True)


def test_hora_sin_dia_posterior_a_la_carga_fue_ayer():
    early = at(17, 9)
    assert resolve(TimeSaid(day="no_dice", clock="23:00"), None, early) == (at(16, 23), False)


def test_clock_invalido_no_valida():
    with pytest.raises(Exception):
        TimeSaid(day="hoy", clock="25:00")


@pytest.mark.parametrize("occurred, vague, text", [
    (at(16, 22), True, "anoche"),
    (at(17, 16, 30), False, "hoy 16:30"),
    (at(16, 16), True, "ayer a la tarde"),
    (at(17, 3), True, "esta madrugada"),
    (at(17, 9), True, "hoy a la mañana"),
    (at(16, 12), True, "ayer"),
    (at(15, 16), True, "anteayer a la tarde"),
    (at(13, 22), True, "el martes a la noche"),
    (at(1, 10), False, "el 01/10 10:00"),
    (at(17, 19, 7), True, "hoy"),
])
def test_describe(occurred, vague, text):
    assert describe(occurred, vague, CREATED) == text

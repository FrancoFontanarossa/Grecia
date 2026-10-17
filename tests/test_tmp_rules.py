import datetime as dt
import itertools

import pytest

from app._tmp_rules import is_reserved, mark_new
from app.config import TZ
from app.models import Event

NOW = dt.datetime(2026, 10, 17, 19, 20, tzinfo=TZ)


def ev(symptom="alucinaciones", domain="neuropsiquiatrico", speaker="cuidador", negated=False):
    return Event(domain=domain, symptom=symptom, severity=None, negated=negated, occurred_at=NOW, time_vague=True,
                 speaker_role=speaker, foreign_attribution=None, quote="x", plain="x", confidence=0.9)


@pytest.mark.parametrize("speaker, domain, requested, consent", list(itertools.product(
    ["paciente", "cuidador", "familiar"], ["neuropsiquiatrico", "impulsos", "sexual", "motor", "sueno"],
    [False, True], [False, True])))
def test_reservado_tabla_completa(speaker, domain, requested, consent):
    expected = (speaker != "paciente" and (requested or domain in {"neuropsiquiatrico", "impulsos", "sexual"})
                and consent)
    assert is_reserved(ev(domain=domain, speaker=speaker), reserved_requested=requested,
                       canal_reservado_active=consent) is expected


def test_lo_que_cuenta_juan_nunca_es_reservado():
    assert not is_reserved(ev(speaker="paciente"), reserved_requested=True, canal_reservado_active=True)


def test_alucinacion_de_marta_es_reservada_sin_pedirlo():
    assert is_reserved(ev(), reserved_requested=False, canal_reservado_active=True)


def test_primera_mencion_es_nueva():
    assert mark_new([ev()], set()) == [True]
    assert mark_new([ev()], {"alucinaciones"}) == [False]


def test_negado_y_otro_nunca_son_nuevos():
    assert mark_new([ev(negated=True), ev(symptom="otro", domain="otro")], set()) == [False, False]


def test_negado_no_cuenta_como_mencion_previa():
    assert mark_new([ev(negated=True), ev()], set()) == [False, True]


def test_repetido_en_la_misma_entrada_solo_la_primera():
    assert mark_new([ev(), ev()], set()) == [True, False]

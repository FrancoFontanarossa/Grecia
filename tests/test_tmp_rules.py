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


from app._tmp_rules import RED_TEXTS, red_check, red_from_backup  # noqa: E402


@pytest.mark.parametrize("text", [
    "se golpeó la cabeza y toma apixabán",
    "Se cayó, se pegó en la frente y después vomitó",
    "lo encontré en el piso del baño, se dio la cabeza, toma apixaban",
    "se golpeó la nuca y se desmayó un rato",
    "se dio un golpe en la cabeza y ahora le duele la cabeza",
])
def test_r1_rojo(text):
    r = red_check(text, [])
    assert r and r.rule_id == "R1" and r.missing_criterion is None and r.text == RED_TEXTS["R1"]


def test_r1_anticoagulante_del_esquema():
    r = red_check("se pegó un porrazo en la cabeza con la puerta", ["levodopa/carbidopa", "Apixabán"])
    assert r and r.missing_criterion is None


def test_r1_sin_criterio_repregunta_solo_eso():
    r = red_check("se cayó y se golpeó la cabeza", ["levodopa/carbidopa"])
    assert r and r.rule_id == "R1" and r.missing_criterion == "anticoagulante_o_signos" and "anticoagulante" in r.text


@pytest.mark.parametrize("text", [
    "se cayó de costado y se golpeó la cadera",
    "no se golpeó la cabeza, solo la rodilla",
    "le dio dolor de cabeza el sol",
    "estuvo más duro toda la tarde",
    "",
])
def test_no_es_r1(text):
    assert red_check(text, ["apixabán"]) is None


def test_rojo_del_respaldo_usa_texto_fijo():
    assert red_from_backup("R4").text == RED_TEXTS["R4"] and red_from_backup("R4").rule_id == "R4-IA"
    assert red_from_backup(None).text == RED_TEXTS[None]

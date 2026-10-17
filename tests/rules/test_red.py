import json
from pathlib import Path

import pytest

from app import db
from app.rules import red

JUAN_MEDS = ["levodopa/carbidopa", "pramipexol"]
SET = [json.loads(line) for line in (Path(__file__).parents[2] / "eval/sets/rojos.jsonl").read_text().splitlines()
       if line.strip()]


def test_set_has_15_and_15():
    assert sum(c["expect"] == "rojo" for c in SET) == 15
    assert sum(c["expect"] == "no_rojo" for c in SET) == 15


@pytest.mark.parametrize("case", [c for c in SET if c["expect"] == "rojo"], ids=lambda c: c["id"])
def test_recall_100(case):
    r = red.evaluate(case["text"], JUAN_MEDS)
    assert r is not None and r.missing_criterion is None, case["text"]
    assert r.rule_id == case["rule"]
    assert r.text == red.RED_TEXTS[case["rule"]]


@pytest.mark.parametrize("case", [c for c in SET if c["expect"] == "no_rojo"], ids=lambda c: c["id"])
def test_zero_false_reds(case):
    assert red.evaluate(case["text"], JUAN_MEDS) is None, case["text"]


@pytest.mark.parametrize("text", [
    "Se dio la cabeza contra la puerta y toma apixabán",
    "se pegó en la cabeza, toma Xarelto",
    "Se golpeó la cabeza y toma warfarina",
    "se golpeo la cabeza. Toma sintrom",
])
def test_r1_anticoagulant_variants(text):
    assert red.evaluate(text, JUAN_MEDS).rule_id == "R1"


def test_r1_anticoagulant_from_schedule():
    r = red.evaluate("se golpeó la cabeza con el ropero", ["levodopa", "apixabán"])
    assert r.rule_id == "R1" and r.missing_criterion is None


def test_r1_missing_criterion_asks_only_that():
    r = red.evaluate("Se cayó y se golpeó la cabeza", JUAN_MEDS)
    assert r.rule_id == "R1"
    assert r.missing_criterion == "anticoagulante,desmayo,vomito,dolor_de_cabeza"
    assert r.text.startswith("Para saber si es urgente")
    assert "anticoagulante" in r.text and "desmayó" in r.text


def test_r1_does_not_ask_what_was_already_denied():
    r = red.evaluate("Se golpeó la cabeza, no se desmayó ni vomitó", JUAN_MEDS)
    assert r.missing_criterion == "anticoagulante,dolor_de_cabeza"
    assert "desmay" not in r.text and "Vomitó" not in r.text


def test_r1_all_criteria_denied_is_not_red():
    text = "Se golpeó la cabeza pero no toma anticoagulantes, no se desmayó, no vomitó y no le duele la cabeza"
    assert red.evaluate(text, JUAN_MEDS) is None


@pytest.mark.parametrize("text", [
    "no se golpeó la cabeza", "No se dio la cabeza, se pegó en el brazo", "sin golpearse la cabeza",
    "se golpeó la rodilla, no la cabeza", "De golpe le dolió la cabeza",
])
def test_r1_negations_and_lookalikes(text):
    assert red.evaluate(text, JUAN_MEDS) is None


def test_r1_doubt_is_not_a_negation():
    r = red.evaluate("no sé si se golpeó la cabeza", JUAN_MEDS)
    assert r.rule_id == "R1" and r.missing_criterion


def test_r2_missing_signs_or_temperature():
    assert red.evaluate("Tiene 38,7 de fiebre", JUAN_MEDS).missing_criterion == "signos"
    assert red.evaluate("Tiene fiebre y está muy confundido", JUAN_MEDS).missing_criterion == "temperatura"
    assert red.evaluate("Tiene fiebre", JUAN_MEDS) is None
    assert red.evaluate("Tiene 38 y medio de fiebre y alucina", JUAN_MEDS).rule_id == "R2"
    assert red.evaluate("Está volando de fiebre y muy confundido", JUAN_MEDS).rule_id == "R2"


def test_r3_needs_levodopa_in_the_schedule():
    assert red.evaluate("Vomitó toda la mañana", JUAN_MEDS).rule_id == "R3"
    assert red.evaluate("Vomitó toda la mañana", ["pramipexol"]) is None


def test_r4_text_has_linea_vida():
    r = red.evaluate("me quiero morir", [])
    assert "0800 0767" in r.text and "*0767" in r.text


def test_full_red_wins_over_a_question():
    r = red.evaluate("Se golpeó la cabeza y dice que se quiere morir", JUAN_MEDS)
    assert r.rule_id == "R4" and r.missing_criterion is None


def test_check_reads_meds_from_schedule(data_dir):
    with db.connect() as conn:
        conn.execute("INSERT INTO med_schedule (patient_id, drug, times) VALUES (1, 'levodopa/carbidopa', '[]')")
    assert red.check("no puede tragar", 1).rule_id == "R3"
    assert red.check("no puede tragar", 2) is None


def test_from_backup():
    assert red.from_backup("R2").rule_id == "R2-IA"
    assert red.from_backup(None).text == red.RED_TEXTS[None]
    assert red.from_backup("inventada").rule_id == "R-IA"

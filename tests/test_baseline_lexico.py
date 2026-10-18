import datetime as dt

from app.config import TZ
from app.models import Entry
from eval import baseline_lexico as bl

CREATED = dt.datetime(2026, 10, 14, 14, 0, tzinfo=TZ)


def entry(text, role="cuidador"):
    return Entry(id=1, patient_id=1, speaker_id=2, speaker_role=role, modality="texto", raw_text=text,
                 reserved_requested=False, corrected=False, created_at=CREATED, source="app")


def test_finds_symptoms_from_the_taxonomy():
    [e] = bl.extract(entry("Hoy está muy rígido, casi no camina"))
    assert (e.domain, e.symptom, e.negated, e.speaker_role) == ("motor", "rigidez", False, "cuidador")
    assert e.foreign_attribution is None


def test_negation_by_rules():
    [e] = bl.extract(entry("No tuvo temblor en todo el día"))
    assert e.symptom == "temblor" and e.negated
    [e] = bl.extract(entry("Pasó la tarde sin temblor"))
    assert e.negated


def test_negation_does_not_cross_clauses():
    events = {e.symptom: e for e in bl.extract(entry("No se mareó, pero estaba muy cansado"))}
    assert events["mareo_al_pararse"].negated and not events["cansancio"].negated


def test_two_symptoms_and_none():
    assert {e.domain for e in bl.extract(entry("Se olvidó las llaves y después lloró un rato"))} == {"cognitivo", "animo"}
    assert bl.extract(entry("Hoy estuvo bien, salimos a pasear")) == []


def test_the_word_otro_is_not_a_symptom():
    assert bl.extract(entry("El otro día fuimos al médico")) == []


def test_time_by_keywords_with_the_same_resolver():
    [e] = bl.extract(entry("Anoche se despertó tres veces"))
    assert e.occurred_at == dt.datetime(2026, 10, 13, 22, 0, tzinfo=TZ) and e.time_vague
    [e] = bl.extract(entry("Ayer a la tarde estaba temblando"))
    assert e.occurred_at == dt.datetime(2026, 10, 13, 16, 0, tzinfo=TZ)
    [e] = bl.extract(entry("Está temblando"))
    assert e.occurred_at == CREATED and e.time_vague          # no dice: hora de carga, vaga
    [e] = bl.extract(entry("El domingo estaba temblando"))
    assert e.occurred_at.date() == dt.date(2026, 10, 11)

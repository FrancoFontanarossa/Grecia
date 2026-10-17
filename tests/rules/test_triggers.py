import datetime as dt
import json

import pytest

from app import db
from app.api.admin import inject_drop
from app.config import TZ
from app.rules import triggers
from tests.rules import steps
from tests.rules.conftest import add_entry, add_event

JUAN, MARTA, LAURA = 1, 2, 3
TUE_13 = dt.date(2026, 10, 13)


def at(day, hour, minute=0):
    return dt.datetime.combine(day if isinstance(day, dt.date) else dt.date(2026, 10, day), dt.time(hour, minute), TZ)


def rules_of(trigs):
    return [t.rule_id for t in trigs]


# ── P-DESVIO ────────────────────────────────────────────────────────────────────────────────────────────
def test_p_desvio_after_the_window_with_numbers_in_why(seeded):
    steps.load()
    inject_drop(1, steps.at16(TUE_13), 0.7)
    assert triggers.p_desvio(1, at(13, 17, 30)) == []              # la ventana todavía no terminó
    [t] = triggers.p_desvio(1, at(13, 18, 5))
    assert t.to_person_id == JUAN and t.facts["baseline"] == "estrato"
    assert t.why == f"Otras tardes de semana ≈ {triggers.fmt_approx(t.facts['median'])} pasos de 16 a 18 h; " \
                    f"hoy {triggers.fmt_int(t.facts['observed'])}."
    assert "1.300" in t.why


def test_p_desvio_combined_base_on_saturday(seeded):
    steps.load({dt.date(2026, 10, 17): 300})
    [t] = triggers.p_desvio(1, at(17, 18, 0))
    assert t.facts["baseline"] == "combinada"
    assert t.why.startswith("Otras tardes ≈ ") and t.why.endswith("hoy 300.")


def test_p_desvio_skips_doses_that_are_already_episodes(seeded):
    steps.load({TUE_13: 400})
    with db.connect() as conn:
        conn.execute("INSERT INTO episodes (patient_id, dose_time, status) VALUES (1, ?, 'abierto')",
                     (db.to_db(steps.at16(TUE_13)),))
    assert triggers.p_desvio(1, at(13, 19)) == []


# ── P-NOCHES ────────────────────────────────────────────────────────────────────────────────────────────
def night(day, *, reserved=False, symptom="despertares_nocturnos", negated=False):
    entry = add_entry(MARTA, created_at=at(day, 8))
    add_event(entry, domain="sueno", symptom=symptom, speaker_role="cuidador", occurred_at=at(day, 3),
              reserved=reserved, negated=negated)


def test_p_noches_three_nights_go_to_marta(seeded):
    for d in (11, 12, 13):
        night(d)
    [t] = triggers.p_noches(1, at(13, 10))
    assert t.to_person_id == MARTA
    assert t.facts["nights"] == ["2026-10-10", "2026-10-11", "2026-10-12"]   # las 3 am son de la noche anterior
    assert t.why == "3 noches con despertares en los últimos 7 días (sábado 10, domingo 11, lunes 12)."


def test_p_noches_needs_three_and_ignores_negated_old_and_reserved(seeded):
    night(12)
    night(13, symptom="insomnio")
    night(11, negated=True)
    night(10, reserved=True)
    night(1)                                                     # fuera de los 7 días
    assert triggers.p_noches(1, at(13, 10)) == []


# ── P-SILENCIO ──────────────────────────────────────────────────────────────────────────────────────────
def test_p_silencio_after_two_days(seeded):
    add_entry(LAURA, created_at=at(10, 20))
    assert triggers.p_silencio(1, at(12, 19)) == []
    [t] = triggers.p_silencio(1, at(12, 21))
    assert t.to_person_id == JUAN and t.facts["days"] == 2
    assert t.why == "Hace 2 días que nadie cuenta nada (el último relato fue el sábado 10/10)."


def test_p_silencio_needs_some_history(seeded):
    assert triggers.p_silencio(1, at(13, 10)) == []


# ── P-JUEGO ─────────────────────────────────────────────────────────────────────────────────────────────
def session(taken_at, taps_per_s):
    with db.connect() as conn:
        conn.execute("INSERT INTO tests (patient_id, type, metrics, raw, taken_at, source) VALUES (1, 'golpeteo', ?, '[]', ?, 'app')",
                     (json.dumps({"taps_per_s": taps_per_s, "interval_cv": 0.15, "left_right_ratio": 1.0}),
                      db.to_db(taken_at)))


def test_p_juego_slower_than_85_percent(seeded):                 # el seed trae 8 sesiones, mediana 4,5
    session(at(13, 17), 3.6)
    [t] = triggers.p_juego(1, at(13, 18))
    assert t.to_person_id == JUAN and t.facts["history_n"] == 7
    assert t.why == "Hoy 3,6 toques por segundo; tus últimas 7 veces ≈ 4,5."


def test_p_juego_similar_or_old_session_does_not_fire(seeded):
    session(at(13, 17), 4.0)                                     # 4,0 ≥ 85% de 4,5
    assert triggers.p_juego(1, at(13, 18)) == []
    assert triggers.p_juego(1, at(14, 10)) == []                 # la sesión de ayer no cuenta hoy


def test_p_juego_needs_three_sessions(data_dir):
    from data import seed
    seed.run()
    with db.connect() as conn:
        conn.execute("DELETE FROM tests")
    session(at(11, 10), 4.5)
    session(at(12, 10), 4.5)
    session(at(13, 10), 2.0)
    assert triggers.p_juego(1, at(13, 11)) == []


# ── P-REPITE ────────────────────────────────────────────────────────────────────────────────────────────
def told(speaker, role, day, symptom="rigidez", domain="motor", reserved=False):
    entry = add_entry(speaker, created_at=at(day, 19))
    add_event(entry, domain=domain, symptom=symptom, speaker_role=role, reserved=reserved)


def test_p_repite_family_twice_never_juan(seeded):
    told(MARTA, "cuidador", 11)
    told(LAURA, "familiar", 13)
    [t] = triggers.p_repite(1, at(13, 20))
    assert t.to_person_id == JUAN and t.facts == {"symptom": "rigidez", "times": 2, "window_days": 7}
    assert t.why == "En los últimos 7 días tu familia contó 2 veces algo de «rigidez»; vos todavía no lo contaste."


def test_p_repite_not_if_juan_told_it(seeded):
    told(MARTA, "cuidador", 11)
    told(LAURA, "familiar", 13)
    told(JUAN, "paciente", 1)
    assert triggers.p_repite(1, at(13, 20)) == []


def test_p_repite_ignores_reserved_events(seeded):
    told(MARTA, "cuidador", 11, symptom="alucinaciones", domain="neuropsiquiatrico", reserved=True)
    told(MARTA, "cuidador", 13, symptom="alucinaciones", domain="neuropsiquiatrico", reserved=True)
    assert triggers.p_repite(1, at(13, 20)) == []


# ── Cero filtraciones hacia Juan ────────────────────────────────────────────────────────────────────────
def test_nothing_reserved_reaches_juan_through_any_trigger(seeded):
    """Todo lo de la semana contado por la familia como reservado: ningún disparador para Juan lo nombra."""
    steps.load()
    inject_drop(1, steps.at16(TUE_13), 0.7)
    secret = ("alucinaciones", "neuropsiquiatrico", "SECRETO")
    for d in (8, 9, 10, 11, 12, 13):
        for speaker, role in ((MARTA, "cuidador"), (LAURA, "familiar")):
            entry = add_entry(speaker, "SECRETO", created_at=at(d, 9), reserved_requested=True)
            add_event(entry, domain="neuropsiquiatrico", symptom="alucinaciones", speaker_role=role,
                      occurred_at=at(d, 3), reserved=True, quote="SECRETO")
            add_event(entry, domain="sueno", symptom="despertares_nocturnos", speaker_role=role,
                      occurred_at=at(d, 3), reserved=True, quote="SECRETO")
    session(at(13, 17), 3.0)
    for now in (at(13, 18, 30), at(16, 12)):
        for t in triggers.evaluate(1, now):
            if t.to_person_id == JUAN:
                blob = (t.why + json.dumps(t.facts)).lower()
                assert not any(s.lower() in blob for s in secret), t
    assert "P-REPITE" not in rules_of(triggers.evaluate(1, at(13, 18, 30)))
    assert "P-NOCHES" not in rules_of(triggers.evaluate(1, at(13, 18, 30)))


def test_evaluate_collects_all(seeded):
    steps.load()
    inject_drop(1, steps.at16(TUE_13), 0.7)
    add_entry(LAURA, created_at=at(10, 20))
    session(at(13, 17), 3.0)
    assert rules_of(triggers.evaluate(1, at(13, 18, 30))) == ["P-DESVIO", "P-SILENCIO", "P-JUEGO"]


@pytest.mark.parametrize("n,expected", [(1312, "1.300"), (980, "980"), (1250, "1.200"), (12345, "12.300")])
def test_fmt_approx(n, expected):
    assert triggers.fmt_approx(n) == expected

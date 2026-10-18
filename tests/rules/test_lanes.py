import datetime as dt
import json

from app import clock, db
from app.config import TZ
from app.rules import lanes, med_change, red
from tests.rules.conftest import add_entry, add_event

JUAN, MARTA, LAURA, PEREIRA = 1, 2, 3, 4
WED_14 = dt.datetime(2026, 10, 14, 9, tzinfo=TZ)


def set_clock(at):
    clock.set(at.isoformat())


def stored():
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT rule_id, lane, recipients, text, reserved FROM alerts ORDER BY id")]


def hallucination(*, speaker=MARTA, role="cuidador", is_new=True, reserved=False, negated=False, when=None):
    entry = add_entry(speaker, created_at=WED_14)
    return add_event(entry, domain="neuropsiquiatrico", symptom="alucinaciones", speaker_role=role,
                     occurred_at=when or WED_14.replace(hour=1), is_new=is_new, reserved=reserved, negated=negated)


# ── med_change ──────────────────────────────────────────────────────────────────────────────────────────
def test_recent_change_is_pramipexol_11_days(seeded):
    mc, days = med_change.recent_change(1, WED_14)
    assert mc.drug == "pramipexol" and days == 11


def test_change_older_than_8_weeks_does_not_count(seeded):
    assert med_change.recent_change(1, dt.datetime(2026, 11, 29, tzinfo=TZ)) is None   # 57 días
    assert med_change.recent_change(1, dt.datetime(2026, 11, 28, tzinfo=TZ)) is not None
    assert med_change.recent_change(1, dt.datetime(2026, 10, 2, tzinfo=TZ)) is None    # antes del cambio


def test_symptom_of_the_base_weeks_is_not_a2(seeded):
    """La base del escenario (20/09–02/10) queda antes del cambio: A2 marca solo lo nuevo después."""
    set_clock(dt.datetime(2026, 9, 26, 10, tzinfo=TZ))
    entry = add_entry(JUAN, created_at=dt.datetime(2026, 9, 26, 9, tzinfo=TZ))
    ev = add_event(entry, domain="motor", symptom="rigidez", speaker_role="paciente", is_new=True,
                   occurred_at=dt.datetime(2026, 9, 26, 8, tzinfo=TZ))
    assert [a.rule_id for a in lanes.evaluate(1, [ev])] == []


# ── A1 y A2 (§5.2: alucinación nueva a 11 días del cambio de pramipexol) ───────────────────────────────
def test_new_hallucination_gives_a1_and_a2(seeded):
    set_clock(WED_14)
    alerts = lanes.evaluate(1, [hallucination()], speaker_id=MARTA)
    assert [(a.rule_id, a.lane) for a in alerts] == [("A1", "ambar"), ("A2", "ambar")]
    assert alerts[0].text == "Primera mención de alucinaciones (contado por Marta el 14/10)."
    assert alerts[1].text == "Síntoma nuevo a 11 días del cambio de pramipexol: alucinaciones."
    # Alcance de las 04:15: el ámbar no notifica a nadie; es prioridad en el informe (solo el equipo).
    assert alerts[0].recipients == [PEREIRA] and alerts[1].recipients == [PEREIRA]
    assert [json.loads(r["recipients"]) for r in stored()] == [[PEREIRA], [PEREIRA]]
    assert all(a.id > 0 for a in alerts)


def test_symptom_label_is_readable(seeded):
    set_clock(WED_14)
    entry = add_entry(MARTA, created_at=WED_14)
    ev = add_event(entry, domain="sueno", symptom="actua_suenos", speaker_role="cuidador", is_new=True)
    [a] = lanes.evaluate(1, [ev], speaker_id=MARTA)
    assert a.text == "Síntoma nuevo a 11 días del cambio de pramipexol: que actúa los sueños."


def test_reserved_hallucination_never_reaches_juan(seeded):
    set_clock(WED_14)
    alerts = lanes.evaluate(1, [hallucination(speaker=LAURA, role="familiar", reserved=True)], speaker_id=LAURA)
    assert all(a.reserved for a in alerts)
    assert all(a.recipients == [PEREIRA] for a in alerts)


def test_not_new_or_negated_gives_nothing(seeded):
    set_clock(WED_14)
    assert lanes.evaluate(1, [hallucination(is_new=False), hallucination(negated=True)]) == []


def test_a2_for_any_new_symptom_within_8_weeks(seeded):
    set_clock(WED_14)
    entry = add_entry(JUAN, created_at=WED_14)
    ev = add_event(entry, domain="autonomico", symptom="mareo_al_pararse", speaker_role="paciente", is_new=True)
    [a] = lanes.evaluate(1, [ev], speaker_id=JUAN)
    assert a.rule_id == "A2" and a.recipients == [PEREIRA]


def test_same_event_twice_does_not_duplicate(seeded):
    set_clock(WED_14)
    ev = hallucination()
    lanes.evaluate(1, [ev])
    assert lanes.evaluate(1, [ev]) == []
    assert len(stored()) == 2


# ── Rojos: marcados en el informe, sin destinatarios (alcance de las 04:15) ─────────────────────────────
def test_red_is_marked_for_the_report_and_goes_to_nobody(seeded):
    set_clock(WED_14)
    r = red.evaluate("Se cayó, se golpeó la cabeza y toma apixabán", ["levodopa"])
    assert r.text == red.RED_MESSAGE                       # el mensaje fijo de la pantalla de quien escribió
    [a] = lanes.evaluate(1, [], red=r, speaker_id=MARTA)
    assert a.lane == "rojo" and a.rule_id == "R1" and a.text == red.RED_LABELS["R1"]
    assert a.recipients == []


def test_red_question_is_not_an_alert(seeded):
    set_clock(WED_14)
    r = red.evaluate("se golpeó la cabeza", ["levodopa"])
    assert r.missing_criterion and lanes.evaluate(1, [], red=r) == []


def test_r4_shows_the_linea_vida_and_goes_to_nobody(seeded):
    set_clock(WED_14)
    r = red.evaluate("me quiero morir", [])
    assert r.text == red.R4_MESSAGE and "0800 0767" in r.text
    [a] = lanes.evaluate(1, [], red=r, speaker_id=JUAN)
    assert a.recipients == [] and a.text == red.RED_LABELS["R4"]


def test_backup_red_label(seeded):
    assert red.red_label("R2-IA") == red.RED_LABELS["R2"]
    assert red.red_label("R-IA") == red.RED_LABELS[None]


# ── A3 ──────────────────────────────────────────────────────────────────────────────────────────────────
def episode(day, hour=16):
    with db.connect() as conn:
        conn.execute("INSERT INTO episodes (patient_id, dose_time, status) VALUES (1, ?, 'abierto')",
                     (db.to_db(dt.datetime(2026, 10, day, hour, tzinfo=TZ)),))


def test_a3_three_episodes_in_7_days_same_slot(seeded):
    episode(13)
    episode(15)
    set_clock(dt.datetime(2026, 10, 15, 19, tzinfo=TZ))
    assert lanes.evaluate(1, []) == []
    episode(16)
    set_clock(dt.datetime(2026, 10, 16, 19, tzinfo=TZ))
    [team] = lanes.evaluate(1, [])                         # sin sugerencia a Juan (alcance de las 04:15)
    assert team.rule_id == "A3" and team.recipients == [PEREIRA]
    assert team.text == "3 episodios en 7 días después de la toma de las 16:00 (13/10, 15/10, 16/10)."
    assert lanes.evaluate(1, []) == []                     # una vez por tramo


def test_a3_needs_same_slot_and_window(seeded):
    episode(13)
    episode(15, hour=12)
    episode(16)
    episode(5)                                             # fuera de los 7 días
    set_clock(dt.datetime(2026, 10, 16, 19, tzinfo=TZ))
    assert lanes.evaluate(1, []) == []

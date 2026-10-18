import datetime as dt
import itertools

import pytest

from app import db
from app.config import TZ
from app.models import Alert, Event
from app.rules import consent

NOW = dt.datetime(2026, 10, 14, 10, tzinfo=TZ)
JUAN, MARTA, LAURA, PEREIRA = 1, 2, 3, 4


def event(**kw):
    base = dict(domain="motor", symptom="rigidez", severity=None, negated=False, occurred_at=None, time_vague=True,
                speaker_role="cuidador", foreign_attribution=None, quote="q", plain="p", confidence=0.9)
    return Event(**{**base, **kw})


def alert(rule_id, lane, reserved=False, patient_id=1):
    return Alert(id=1, patient_id=patient_id, lane=lane, rule_id=rule_id, recipients=[], text="t",
                 reserved=reserved, created_at=NOW)


def ids(people):
    return sorted(p.id for p in people)


# ── is_reserved (§6.4) ──────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role,domain,requested,consent_on,expected", [
    ("cuidador", "neuropsiquiatrico", False, True, True),
    ("familiar", "impulsos", False, True, True),
    ("familiar", "sexual", False, True, True),
    ("cuidador", "motor", True, True, True),
    ("cuidador", "motor", False, True, False),
    ("cuidador", "neuropsiquiatrico", False, False, False),
    ("paciente", "neuropsiquiatrico", True, True, False),
])
def test_is_reserved(role, domain, requested, consent_on, expected):
    e = event(speaker_role=role, domain=domain)
    assert consent.is_reserved(e, reserved_requested=requested, canal_reservado_active=consent_on) is expected


def test_mark_new_and_is_new():
    events = [event(symptom="rigidez"), event(symptom="rigidez"), event(symptom="temblor", negated=True),
              event(symptom="otro"), event(symptom="temblor")]
    assert consent.mark_new(events, {"insomnio"}) == [True, False, False, False, True]
    assert consent.is_new(event(symptom="insomnio"), {"insomnio"}) is False


def test_canal_reservado_active(seeded):
    assert consent.canal_reservado_active(1) is True
    assert consent.canal_reservado_active(1, MARTA) is True
    with db.connect() as conn:
        conn.execute("UPDATE consents SET enabled = 0 WHERE recipient_id = ? AND kind = 'canal_reservado'", (MARTA,))
    assert consent.canal_reservado_active(1, MARTA) is False
    assert consent.canal_reservado_active(1, LAURA) is True
    assert consent.canal_reservado_active(99) is True        # sin filas: activo (protege)


# ── recipients (alcance de las 04:15) ───────────────────────────────────────────────────────────────────
# Sin botón de pánico ni avisos a la familia: el rojo no tiene destinatarios (solo el mensaje fijo a quien escribió,
# en la respuesta del relato) y el ámbar va solo al equipo, como prioridad en el informe.
@pytest.mark.parametrize("rule", ["R1", "R2", "R3", "R4", "R1-IA", "R-IA"])
@pytest.mark.parametrize("speaker", [None, JUAN, MARTA, LAURA])
def test_red_goes_to_nobody(seeded, rule, speaker):
    assert consent.recipients(alert(rule, "rojo"), speaker_id=speaker) == []


@pytest.mark.parametrize("rule", ["A1", "A2", "A3"])
def test_amber_goes_only_to_the_team(seeded, rule):
    assert ids(consent.recipients(alert(rule, "ambar"))) == [PEREIRA]
    assert ids(consent.recipients(alert(rule, "ambar", reserved=True), speaker_id=MARTA)) == [PEREIRA]
    assert consent.recipients(alert("V1", "verde")) == []


def test_a1_ignores_the_family_avisos_consent(seeded):
    with db.connect() as conn:
        conn.execute("UPDATE consents SET enabled = 1 WHERE recipient_id = ? AND kind = 'avisos'", (MARTA,))
    assert ids(consent.recipients(alert("A1", "ambar"))) == [PEREIRA]


def test_test_patient_is_separate(seeded):
    assert consent.recipients(alert("R1", "rojo", patient_id=5)) == []
    assert JUAN not in ids(consent.recipients(alert("A1", "ambar", patient_id=5)))
    assert PEREIRA not in ids(consent.recipients(alert("A1", "ambar", patient_id=5)))


# ── Cero filtraciones hacia Juan ni la familia ──────────────────────────────────────────────────────────
RULES = ["R1", "R2", "R3", "R4", "R1-IA", "R-IA", "A1", "A2", "A3", "V1"]
LANES = ["rojo", "ambar", "verde"]


@pytest.mark.parametrize("rule,lane,speaker", list(itertools.product(RULES, LANES, [None, JUAN, MARTA, LAURA])))
@pytest.mark.parametrize("reserved", [True, False])
def test_no_alert_reaches_juan_or_the_family(seeded, rule, lane, speaker, reserved):
    got = ids(consent.recipients(alert(rule, lane, reserved=reserved), speaker_id=speaker))
    assert not {JUAN, MARTA, LAURA} & set(got)


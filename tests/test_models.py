import datetime as dt

import pytest
from pydantic import ValidationError

from app.config import TZ
from app.models import (
    Alert, BiometricSample, Deviation, Event, Explanation, GameResult, GoalDay,
    Notification, Person, Question, QuestionText, RedResult, Report, ReportTopic,
    TapEvent, Trigger,
)

NOW = dt.datetime(2026, 10, 13, 10, 30, tzinfo=TZ)


def test_event():
    e = Event(domain="motor", symptom="temblor", severity=2, negated=False,
              occurred_at=NOW, time_vague=False, speaker_role="cuidador",
              foreign_attribution="el cansancio", quote="le temblaba la mano",
              plain="Te tembló la mano", confidence=0.9)
    assert e.occurred_at.tzinfo is not None
    Event(**{**e.model_dump(), "severity": None, "occurred_at": None,
             "time_vague": True, "foreign_attribution": None})


def test_event_out_of_range_rejected():
    base = dict(domain="motor", symptom="temblor", severity=2, negated=False,
                occurred_at=NOW, time_vague=False, speaker_role="cuidador",
                foreign_attribution=None, quote="le temblaba la mano",
                plain="Te tembló la mano", confidence=0.9)
    with pytest.raises(ValidationError):
        Event(**{**base, "severity": 7})
    with pytest.raises(ValidationError):
        Event(**{**base, "confidence": 1.5})


def test_red_result():
    RedResult(rule_id="caida_golpe_cabeza", missing_criterion=None, text="Llamá al 911")


def test_biometric_sample():
    BiometricSample(patient_id=1, kind="steps", value=420, start=NOW,
                    end=NOW + dt.timedelta(minutes=30), source="atajo")


def test_deviation():
    Deviation(dose_time=NOW, window="+60/+120", observed=120, median=480.0,
              z=-2.4, pct_change=-75.0)


def test_trigger():
    Trigger(rule_id="caida_pasos_post_toma", patient_id=1, to_person_id=2,
            facts={"pct_change": -75.0}, why="Caminó 75% menos que de costumbre")


def test_explanation():
    Explanation(explained=False, by=[], reasoning="No hay nada anotado que lo explique")


def test_question_text():
    QuestionText(question="¿Cómo estuvo Juan hoy de mañana?",
                 options=["Bien", "Más lento", "No sé"])


def test_question():
    Question(id=1, person_id=2, rule_id="caida_pasos_post_toma", question="¿Cómo estuvo?",
             why="Caminó 75% menos", options=["Bien", "Más lento", "No sé"],
             url="/casa/pregunta/1", status="pendiente")


def test_game_result():
    GameResult(patient_id=1, game="tapping", taken_at=NOW,
               metrics={"taps_per_s": 4.2, "interval_cv": 0.12, "left_right_ratio": 0.95},
               vs_history="sin_historial")


def test_report():
    topic = ReportTopic(title="Movilidad", narrative="...", observed=["-75% pasos"],
                        voices={"cuidador": "lo vi lento"}, question="¿Ajustar la toma?",
                        evidence_ids=[1, 2], reserved=False)
    Report(summary="Semana estable", topics=[topic], removed_count=0)


def test_tap_event():
    TapEvent(t_ms=0, side="izq")
    TapEvent(t_ms=180, side="der")
    with pytest.raises(ValidationError):
        TapEvent(t_ms=0, side="left")


def test_person():
    Person(id=1, patient_id=1, role="paciente", name="Juan", relation="paciente")
    Person(id=2, patient_id=1, role="cuidador", name="Marta", relation="esposa",
           phone="099000000", why_walk="para ir a la feria")


def test_alert():
    Alert(id=1, patient_id=1, lane="ambar", rule_id="caidas_repetidas", recipients=[2, 3],
          text="Juan se cayó dos veces esta semana", reserved=False, created_at=NOW)


def test_goal_day():
    GoalDay(id=1, goal_id=1, date=dt.date(2026, 10, 13), value=3200, achieved=True,
            hard_day=False, notified=False)


def test_notification():
    Notification(id=1, person_id=2, kind="pregunta", title="Una pregunta", body="¿Cómo estuvo?",
                 url="/casa/pregunta/1", created_at=NOW, push_sent=True)
    Notification(id=2, person_id=3, kind="ambar", lane="ambar", title="Aviso", body="...",
                 url="/casa", created_at=NOW, push_sent=False, read_at=NOW)


def test_naive_datetime_rejected():
    naive = dt.datetime(2026, 10, 13, 10, 30)
    with pytest.raises(ValidationError):
        Deviation(dose_time=naive, window="+60/+120", observed=1, median=1, z=0, pct_change=0)
    with pytest.raises(ValidationError):
        Alert(id=1, patient_id=1, lane="rojo", rule_id="x", recipients=[], text="",
              reserved=False, created_at=naive)

# Alcance de las 04:15 y arreglos de la demo: explain solo con relatos posteriores a la toma, preguntas a Marta
# en tercera persona, etiquetas legibles, preguntas que ya pasaron, /prueba y la API técnica sin temblor.
import asyncio
import datetime as dt

from fastapi.testclient import TestClient

from app import clock, question_bank, taxonomy
from app.config import TZ
from app.models import ContextEntry, Deviation, PromptContext, Trigger
from app.pipeline import explain

DOSE = dt.datetime(2026, 10, 13, 16, tzinfo=TZ)


def ctx(entries, *, deviation=True):
    d = Deviation(dose_time=DOSE, window="16:00-18:00", observed=420, median=1300, z=-4.0, pct_change=-0.68,
                  baseline="estrato", baseline_n=12) if deviation else None
    t = Trigger(rule_id="P-DESVIO", patient_id=1, to_person_id=2, facts={}, why="w")
    return PromptContext(now=DOSE.replace(hour=18, minute=5), patient_name="Juan", recipient_role="cuidador",
                         trigger=t, deviation=d,
                         recent_entries=[ContextEntry(speaker_role="paciente", text=x, created_at=at) for x, at in entries])


def test_explain_only_uses_entries_after_the_dose():
    before = ("estuve sentado toda la tarde", DOSE - dt.timedelta(days=1))
    after = ("fui al dentista", DOSE + dt.timedelta(minutes=50))
    assert [e.text for e in explain.after_dose(ctx([before, after])).recent_entries] == ["fui al dentista"]
    assert len(explain.after_dose(ctx([before, after], deviation=False)).recent_entries) == 2


def test_explain_without_entries_after_the_dose_does_not_call_the_model():
    out = asyncio.run(explain.explain(ctx([]).trigger, ctx([("ayer llovía", DOSE - dt.timedelta(hours=20))])))
    assert out.explained is False and "posteriores a la toma" in out.reasoning


def test_question_bank_asks_marta_about_juan_in_third_person():
    q = question_bank.proactive("P-DESVIO", "Juan", "cuidador", baseline_label="otras tardes")
    assert q.question == "Notamos que Juan caminó menos que otras tardes. ¿Pasó algo?" and len(q.options) == 3
    assert question_bank.proactive("P-SUENO", "Juan", "cuidador").question == "¿Cómo pasó Juan la noche?"
    assert question_bank.proactive("P-DESVIO", "Juan", "paciente").question.startswith("Juan, hoy caminaste")


def test_symptom_label():
    assert taxonomy.symptom_label("actua_suenos") == "que actúa los sueños"
    assert taxonomy.symptom_label("rigidez") == "rigidez"
    assert all("_" not in taxonomy.symptom_label(s) for s in taxonomy.SYMPTOMS)


def test_question_from_another_day_has_passed(monkeypatch):
    from app.api import questions
    monkeypatch.setattr(clock, "now", lambda: dt.datetime(2026, 10, 14, 10, tzinfo=TZ))
    assert questions.is_past({"sent_at": "2026-10-13T18:05:00-03:00"}) is True
    assert questions.is_past({"sent_at": "2026-10-14T09:00:00-03:00"}) is False
    assert questions.is_past({"sent_at": None}) is False


def test_prueba_redirects_with_the_reset_mark(data_dir):
    from data import seed
    from app.main import app
    seed.run()
    r = TestClient(app).get("/prueba", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?prueba=1"
    assert "ec_patient=5" in r.headers["set-cookie"]


def test_technical_api_has_no_tremor_or_dyskinesia():
    from app.api import report
    assert "tremor_minutes" not in report.WEARABLE_LABELS and "dyskinesia_minutes" not in report.WEARABLE_LABELS
    assert report.WEARABLE_HOURLY == ()


def test_example_report_has_the_right_pramipexol_date():
    from app.api import report
    fake, _ = report._fake_report()
    assert "03/10" in fake.summary and "22/09" not in fake.summary

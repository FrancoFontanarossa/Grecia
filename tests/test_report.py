import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from app import clock
from app import db as base
from app.config import TZ
from app.pipeline import llm, report, report_facts
from tests.conftest import FakeSonnet

_REAL_REQUEST = report.request_regeneration   # antes de que el fixture autouse lo reemplace

FACTS = json.loads((Path(__file__).resolve().parent.parent / "scripts/fixtures/report_facts_semana.json").read_text())
SUMMARY = ("En el período 20/09 al 17/10, a 25 días del cambio de pramipexol, Marta contó dos episodios en que Juan "
           "hablaba con gente que no estaba. Después de la toma de las 16, los pasos bajaron en 3 tardes. "
           "Marta contó 3 noches con despertares. Pasos: 15 de 28 días en la meta de 4000.")


def topic(title, ids, reserved=False, **voices):
    return {"title": title, "narrative": "Un párrafo corto.", "observed": ["3 tardes"],
            "voices": {"paciente": voices.get("paciente"), "cuidador": voices.get("cuidador"),
                       "familiar": voices.get("familiar")},
            "question": "¿Cómo se siente a la tarde?", "evidence_ids": ids, "reserved": reserved}


GOOD = {"summary": SUMMARY, "topics": [
    topic("Habla con gente que no está", [205, 209], cuidador="anoche hablaba con alguien que no estaba"),
    topic("A la tarde se mueve menos", [206], paciente="me sentí trabado, me costó salir a caminar"),
    topic("Noches con despertares", [201, 203]),
]}


def test_genera_report_y_el_codigo_fuerza_reserved(monkeypatch):
    fake = FakeSonnet(GOOD)
    monkeypatch.setattr(llm, "_create", fake)
    rep = asyncio.run(report.generate(FACTS))
    assert rep.summary == SUMMARY and len(rep.topics) == 3 and rep.removed_count == 0
    assert rep.topics[0].reserved is True            # el modelo dijo False, pero 205 y 209 son reservados
    assert rep.topics[1].reserved is False
    assert rep.topics[0].voices == {"cuidador": "anoche hablaba con alguien que no estaba"}   # sin nulls
    kw = fake.calls[0]
    assert kw["output_config"] == {"effort": "medium"} and "<facts>" in kw["messages"][0]["content"]
    assert kw["system"][0]["text"].startswith("# Parkinson")


@pytest.mark.parametrize("bad", [
    {**GOOD, "topics": GOOD["topics"][:2]},                                             # dos temas
    {**GOOD, "topics": [topic("x", [999])] + GOOD["topics"][1:]},                       # id inexistente
    {**GOOD, "summary": "Muy corto."},                                                  # resumen corto
    {**GOOD, "topics": [{**GOOD["topics"][0], "narrative": "palabra " * 130}] + GOOD["topics"][1:]},
])
def test_salida_que_no_cumple_se_reintenta(monkeypatch, bad):
    fake = FakeSonnet(bad, GOOD)
    monkeypatch.setattr(llm, "_create", fake)
    assert len(asyncio.run(report.generate(FACTS)).topics) == 3 and len(fake.calls) == 2


def test_dos_fallas_son_error(monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet({**GOOD, "topics": []}))
    with pytest.raises(llm.LLMError):
        asyncio.run(report.generate(FACTS))


def test_pasa_por_el_verificador(monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    seen = {}

    def fake_verify(rep, facts, sources):
        seen["sources"] = sources
        return rep.model_copy(update={"removed_count": 2})
    monkeypatch.setattr(report, "verify", fake_verify)
    assert asyncio.run(report.generate(FACTS)).removed_count == 2 and seen["sources"] == FACTS["events"]


def test_facts_desde_la_base(tmp_data_dir):
    from app import _tmp_db as db
    clock.set("2026-10-17T18:00:00")
    with base.connect() as conn:
        conn.execute("INSERT INTO med_schedule (patient_id, drug, times, changed_at) VALUES (1, 'pramipexol', '[]', ?)",
                     (base.to_db(dt.datetime(2026, 9, 22, tzinfo=TZ)),))
        conn.execute("INSERT INTO goals (patient_id, metric, target, unit, set_by, active) VALUES (1, 'steps', 4000, 'pasos', 4, 1)")
        for day, steps in [(15, 4200), (16, 3000)]:
            conn.execute("INSERT INTO biometrics (patient_id, kind, value, start, \"end\", source) VALUES (1, 'steps', ?, ?, ?, 'seed')",
                         (steps, base.to_db(dt.datetime(2026, 10, day, 10, tzinfo=TZ)),
                          base.to_db(dt.datetime(2026, 10, day, 11, tzinfo=TZ))))
    eid = db.insert_entry(patient_id=1, speaker_id=2, modality="texto", raw_text="anoche hablaba con alguien",
                          question_id=None, occurred_hint=None, reserved_requested=False, source="app")
    db.insert_events(eid, 1, [{"domain": "neuropsiquiatrico", "symptom": "alucinaciones", "negated": False,
                               "occurred_at": dt.datetime(2026, 10, 14, 22, tzinfo=TZ), "time_vague": True,
                               "speaker_role": "cuidador", "quote": "anoche hablaba con alguien", "plain": "x",
                               "confidence": 0.9, "is_new": True, "reserved": True}])
    f = report_facts.build(1, clock.now())
    assert f["period"] == {"start": "2026-09-20", "end": "2026-10-17", "days": 28,
                           "label": "2026-09-20/2026-10-17", "text": "20/09 al 17/10"}
    assert f["steps"]["days_in_goal"] == 1 and f["steps"]["days_with_data"] == 2 and f["steps"]["goal"] == 4000
    assert f["medication"][0]["days_since_change"] == 25
    [e] = f["events"]
    assert (e["speaker_name"], e["reserved"], e["is_new"], e["days_since_med_change"]) == ("Marta", True, True, 22)
    assert f["entries_by_voice"] == {"cuidador": 1}


def test_report_guarda_en_reports(tmp_data_dir, monkeypatch):
    clock.set("2026-10-17T18:00:00")
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    monkeypatch.setattr(report_facts, "build", lambda pid, now, period=None: FACTS)
    asyncio.run(report.report(1))
    with base.connect() as conn:
        [row] = conn.execute("SELECT * FROM reports").fetchall()
    assert row["period"] == "2026-09-20/2026-10-17" and json.loads(row["content"])["summary"] == SUMMARY


def test_regeneracion_como_mucho_cada_30s_y_gana_la_ultima(monkeypatch):
    runs = []

    async def fake_report(pid, period=None):
        runs.append(pid)
    monkeypatch.setattr(report, "report", fake_report)
    monkeypatch.setattr(report, "REGEN_SECONDS", 0.2)
    monkeypatch.setattr(report, "_last_start", {})

    async def scenario():
        _REAL_REQUEST(1)
        await asyncio.sleep(0.05)          # primera corrida ya hecha
        for _ in range(5):                 # cinco pedidos seguidos → una sola corrida más, después de la ventana
            _REAL_REQUEST(1)
        await asyncio.sleep(0.1)
        assert runs == [1]                 # todavía dentro de los 0,2 s
        await asyncio.sleep(0.3)
    asyncio.run(scenario())
    assert runs == [1, 1]

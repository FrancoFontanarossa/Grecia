"""Bitácora de la revisión diaria: la nota de cada noche se limpia con las reglas del verificador del informe, el
digest trae las notas de los 7 días previos, historia=True no agenda acciones y la nota nunca llega a la familia."""
import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from app import db, plan_jobs
from app.config import TZ
from app.models import DailyNote, DailyPlan, NotePoint, PlannedAction
from app.pipeline import daily_plan as daily_plan_pipeline
from app.pipeline import report as report_pipeline
from app.pipeline import report_facts
from app.pipeline.digest import build_digest
from app.rules import note as note_rules

DAY = dt.date(2026, 10, 16)
ROOT = Path(__file__).resolve().parent.parent


def at(day: dt.date, h: int, m: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(h, m), TZ)


DIGEST = {
    "patient_id": 1,
    "ultimas_24h": {"relatos": [{"ref": "relato:7", "fecha": "2026-10-16T17:00", "cita": "me sentí trabado"}]},
    "desvios_28_dias": [{"ref": "episodio:3", "fecha": "2026-10-16", "toma": "16:00", "observado": 356,
                         "mediana_habitual": 1289.0}],
    "ultimos_14_dias": [{"ref": "dia:2026-10-16", "fecha": "2026-10-16", "pasos": 2810}],
}


# ---------------------------------------------------------------- verificador

def test_cifra_inventada_se_borra():
    note = DailyNote(text="El 16/10 caminó 356 pasos después de la toma de las 16 [episodio:3]. "
                          "Lo habitual son 1.700 pasos [episodio:3]. Contó «me sentí trabado» [relato:7].")
    clean, removed = note_rules.verify_note(note, DIGEST)
    assert "1.700" not in clean.text and removed == 1
    assert "356" in clean.text and "1.289" not in clean.text and "«me sentí trabado»" in clean.text


def test_cifras_del_digest_pasan_con_formato_de_miles_y_fecha():
    clean, removed = note_rules.verify_note(DailyNote(text="Lo habitual es 1.289 y ese día hubo 2.810 pasos "
                                                           "[episodio:3] [dia:2026-10-16]."), DIGEST)
    assert removed == 0 and "1.289" in clean.text


def test_evidencia_inexistente_se_borra():
    note = DailyNote(
        text="Contó que se sintió trabado [relato:999]. La tarde coincidió con menos pasos [episodio:3].",
        points=[NotePoint(text="Trabado a la tarde", evidence_ids=["relato:999"]),
                NotePoint(text="Sin evidencia", evidence_ids=[]),
                NotePoint(text="Tarde más quieta", evidence_ids=["episodio:3"])])
    clean, removed = note_rules.verify_note(note, DIGEST)
    assert "relato:999" not in clean.text and "[episodio:3]" in clean.text
    assert [p.text for p in clean.points] == ["Tarde más quieta"]
    assert removed == 3


def test_frase_sin_evidencia_aproximacion_cita_falsa_y_diagnostico_se_borran():
    note = DailyNote(text="Parece un wearing-off de la tarde [episodio:3]. Caminó menos. "
                          "Caminó unos 356 pasos [episodio:3]. Dijo «estoy muy mal» [relato:7].",
                     follow_up=["Mirar las tardes después de la toma de las 16", "Ver si baja a 200 pasos"])
    clean, removed = note_rules.verify_note(note, DIGEST)
    assert clean.text == "" and removed == 5
    assert clean.follow_up == ["Mirar las tardes después de la toma de las 16"]


def test_un_ref_suelto_despues_del_punto_cuenta_para_la_frase_anterior():
    clean, removed = note_rules.verify_note(DailyNote(text="La tarde fue más quieta. [episodio:3]"), DIGEST)
    assert removed == 0 and "[episodio:3]" in clean.text


# ---------------------------------------------------------------- digest y plan_jobs

def _insert_note(day: dt.date, text: str, follow_up=()):
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_notes (patient_id, date, text, points, follow_up, removed_count, created_at) "
                     "VALUES (1, ?, ?, '[]', ?, 0, ?)", (day.isoformat(), text, json.dumps(list(follow_up)),
                                                         db.to_db(at(day, 23))))


def test_el_digest_trae_las_7_notas_previas(tmp_data_dir):
    for i in range(1, 10):                          # del 07/10 al 15/10, más una de hoy
        _insert_note(DAY - dt.timedelta(days=i), f"Nota {i} [dia:{(DAY - dt.timedelta(days=i)).isoformat()}].",
                     follow_up=[f"seguir {i}"])
    _insert_note(DAY, "La de hoy.")
    digest = build_digest(1, at(DAY, 21))
    fechas = [n["fecha"] for n in digest["notas_previas"]]
    assert fechas == [(DAY - dt.timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
    assert digest["notas_previas"][-1]["seguir_mirando"] == ["seguir 1"]
    assert digest["notas_previas"][-1]["ref"] == "nota:2026-10-15"
    # lo que citaban las notas previas sigue siendo evidencia válida para la nota nueva
    assert "dia:2026-10-15" in note_rules.valid_refs(digest)
    assert "nota:2026-10-15" in note_rules.valid_refs(digest)


@pytest.fixture
def plan_falso(tmp_data_dir, monkeypatch):
    with db.connect() as conn:
        ep = conn.execute("INSERT INTO episodes (patient_id, dose_time, deviation, explanation, status) "
                          "VALUES (1, ?, ?, '{}', 'preguntado')",
                          (db.to_db(at(DAY, 16)), '{"observed": 356, "median": 1289}')).lastrowid
    plan = DailyPlan(
        note=DailyNote(text=f"La tarde del 16/10 fue más quieta [episodio:{ep}]. Inventada: 9.999 pasos [episodio:{ep}].",
                       points=[NotePoint(text="Tarde quieta", evidence_ids=[f"episodio:{ep}"])],
                       follow_up=["Las tardes después de la toma de las 16"]),
        actions=[PlannedAction(kind="golpeteo", at="16:30", to_role="paciente", reason="Un juego cortito",
                               basis=f"desvio:{ep}", evidence_ids=[f"episodio:{ep}"])])
    seen = []

    async def fake(digest):
        seen.append(digest)
        return plan
    monkeypatch.setattr(daily_plan_pipeline, "daily_plan", fake)
    plan_jobs._done.clear()
    return seen


def _rows(sql, *args):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def test_historia_guarda_la_nota_verificada_y_no_agenda_acciones(plan_falso):
    summary = asyncio.run(plan_jobs.run_plan(1, at(DAY, 23), historia=True))
    assert summary["historia"] and summary["agendadas"] == 0
    assert _rows("SELECT * FROM planned_actions") == []
    [n] = _rows("SELECT * FROM daily_notes")
    assert n["date"] == "2026-10-16" and n["removed_count"] == 1 and "9.999" not in n["text"]
    assert plan_jobs.reviewed(1, DAY)


def test_sin_historia_agenda_y_la_revision_no_se_repite(plan_falso):
    asyncio.run(plan_jobs.run_plan(1, at(DAY, 23)))
    assert [a["status"] for a in _rows("SELECT status FROM planned_actions")] == ["agendada"]
    asyncio.run(plan_jobs.plan_if_due(1, at(DAY, 23, 30)))          # el scheduler en vivo no la vuelve a hacer
    assert len(plan_falso) == 1


def test_precorrido_una_revision_por_noche_y_la_ultima_agenda(plan_falso, monkeypatch):
    from scripts import precorrer_semana as pre
    calls = []
    real = plan_jobs.run_plan

    async def spy(patient_id, now, *, historia=False):
        calls.append((now.date(), historia))
        return await real(patient_id, now, historia=historia)
    monkeypatch.setattr(plan_jobs, "run_plan", spy)
    last = DAY
    for d in (DAY - dt.timedelta(days=1), DAY):
        assert asyncio.run(pre._review(1, d, last)) in ("ok", "sin_nota")
    assert asyncio.run(pre._review(1, DAY, last)) == "ya_estaba"     # idempotente
    assert calls == [(DAY - dt.timedelta(days=1), True), (DAY, False)]


# ---------------------------------------------------------------- informe

def test_el_informe_recibe_las_notas_y_sus_cifras_no_cuentan_como_facts(tmp_data_dir):
    _insert_note(DAY, "La tarde coincidió con 4.321 pasos [dia:2026-10-16].", follow_up=["Mirar las tardes"])
    facts = report_facts.build(1, at(DAY, 23))
    notas = facts["bitacora"]["notas"]
    assert notas == [{"fecha": "16/10", "texto": "La tarde coincidió con 4.321 pasos.",
                      "seguir_mirando": ["Mirar las tardes"]}]
    assert "4.321" not in report_pipeline.allowed_numbers(facts)


# ---------------------------------------------------------------- solo equipo médico

def test_la_bitacora_solo_se_lee_en_modulos_del_equipo_medico():
    """La nota nunca llega a la familia ni a Juan: daily_notes solo se lee en la revisión, el informe y la vista
    técnica, y la parcial de la bitácora solo se incluye en /neuro/tecnica."""
    allowed = {"app/db.py", "app/plan_jobs.py", "app/pipeline/digest.py", "app/pipeline/report_facts.py",
               "app/api/plan.py"}
    readers = {p.relative_to(ROOT).as_posix() for p in (ROOT / "app").rglob("*.py")
               if "daily_notes" in p.read_text(encoding="utf-8")}
    assert readers <= allowed
    includes = {p.relative_to(ROOT).as_posix() for p in (ROOT / "app" / "web").rglob("*.html")
                if "_bitacora.html" in p.read_text(encoding="utf-8")}
    assert includes == {"app/web/neuro/tecnica.html"}
    routes = (ROOT / "app" / "web" / "routes_neuro.py").read_text(encoding="utf-8")
    assert routes.count("build_bitacora(") == 1 and "def tecnica" in routes


def test_lo_reservado_no_entra_al_digest_ni_a_la_nota(tmp_data_dir):
    with db.connect() as conn:
        entry = conn.execute("INSERT INTO entries (patient_id, speaker_id, modality, raw_text, reserved_requested, "
                             "corrected, created_at, source) VALUES (1, 2, 'texto', 'x', 1, 0, ?, 'test')",
                             (db.to_db(at(DAY, 10)),)).lastrowid
        ev = conn.execute("INSERT INTO events (entry_id, patient_id, domain, symptom, negated, time_vague, speaker_role, "
                          "quote, plain, confidence, is_new, reserved) VALUES (?, 1, 'neuropsiquiatrico', "
                          "'alucinacion', 0, 1, 'cuidador', 'hablaba con alguien que no estaba', 'x', 0.9, 1, 1)",
                          (entry,)).lastrowid
    digest = build_digest(1, at(DAY, 21))
    assert "hablaba con alguien" not in json.dumps(digest, ensure_ascii=False)
    assert f"relato:{ev}" not in note_rules.valid_refs(digest)
    clean, removed = note_rules.verify_note(
        DailyNote(text=f"Marta contó «hablaba con alguien que no estaba» [relato:{ev}]."), digest)
    assert clean.text == "" and removed == 1


def test_la_vista_tecnica_muestra_la_bitacora_rotulada(tmp_data_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from app import clock
    from app.api import _store as store
    from app.main import app

    _insert_note(DAY, "La tarde fue más quieta [dia:2026-10-16].", follow_up=["Mirar las tardes"])
    monkeypatch.setattr(clock, "now", lambda: at(DAY, 23))
    store._has_db_cache["checked"] = -1e9
    html = TestClient(app).get("/neuro/tecnica/1").text
    assert "Bitácora de la IA" in html and "redactado por IA, verificado" in html
    assert "La tarde fue más quieta." in html and "Mirar las tardes" in html


def test_una_nota_que_nombra_un_medicamento_no_tira_el_plan():
    """La frase con medicación la borra rules.note; check() no rechaza el plan entero (corrida real del 16/10)."""
    plan = DailyPlan(note=DailyNote(text="Casi caída a 13 días del cambio de pramipexol [episodio:3]. "
                                         "La tarde fue más quieta [episodio:3]."))
    daily_plan_pipeline.check(plan)
    clean, removed = note_rules.verify_note(plan.note, DIGEST)
    assert removed == 1 and clean.text == "La tarde fue más quieta [episodio:3]."

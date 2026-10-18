"""Perfil de Juan: la IA propone aprendizajes y el código los acepta solo con evidencia; nada reservado entra; los
patrones que dejan de cumplirse se retiran; render_profile es corto y va en los prompts solo con PROFILE_ENABLED.
Sin IA real: los aprendizajes se arman a mano y la revisión diaria se reemplaza por una función falsa."""
import asyncio
import datetime as dt
import json

import pytest

from app import config, db, plan_jobs
from app.config import TZ
from app.models import DailyPlan, Hypothesis, ProfileLearning
from app.pipeline import daily_plan as daily_plan_pipeline
from app.pipeline import knowledge
from app.rules import profile

DAY = dt.date(2026, 10, 16)
NOW = dt.datetime.combine(DAY, dt.time(23), TZ)


def at(day: dt.date, h: int) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(h), TZ)


@pytest.fixture
def juan(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(config, "PROFILE_ENABLED", True)
    with db.connect() as conn:
        conn.execute("INSERT INTO med_schedule (patient_id, drug, times, changed_at, change_note) VALUES "
                     "(1, 'levodopa/carbidopa', '[\"08:00\", \"12:00\", \"16:00\", \"20:00\"]', ?, 'subió')",
                     (db.to_db(at(dt.date(2026, 10, 3), 9)),))
    return tmp_data_dir


def steps(weekday: float, weekend: float):
    """28 días de pasos: 4 horas por día con el total repartido (fin de semana con otro total)."""
    with db.connect() as conn:
        conn.execute("DELETE FROM biometrics")
        for i in range(28):
            d = DAY - dt.timedelta(days=i)
            total = weekend if d.weekday() >= 5 else weekday
            for h in (9, 12, 16, 18):
                conn.execute("INSERT INTO biometrics (patient_id, kind, value, start, end, source) "
                             "VALUES (1, 'steps', ?, ?, ?, 'seed')",
                             (total / 4, db.to_db(at(d, h)), db.to_db(at(d, h) + dt.timedelta(hours=1))))


def relato(text: str, domain: str, *, speaker=1, role="paciente", reserved=False, day=DAY, hour=10) -> int:
    with db.connect() as conn:
        entry = conn.execute("INSERT INTO entries (patient_id, speaker_id, modality, raw_text, reserved_requested, "
                             "corrected, created_at, source) VALUES (1, ?, 'audio', ?, ?, 0, ?, 'test')",
                             (speaker, text, int(reserved), db.to_db(at(day, hour)))).lastrowid
        return conn.execute("INSERT INTO events (entry_id, patient_id, domain, symptom, negated, time_vague, "
                            "speaker_role, quote, plain, confidence, is_new, reserved) "
                            "VALUES (?, 1, ?, 'x', 0, 1, ?, ?, 'x', 0.9, 0, ?)",
                            (entry, domain, role, text, int(reserved))).lastrowid


PATRON = ProfileLearning(kind="patron", text="Los fines de semana camina menos",
                         hypothesis=Hypothesis(condition="fin_de_semana", metric="pasos_dia", lag_days=0,
                                               direction="menos", reason="se queda en casa"))


def items(status=None):
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM patient_profile_items ORDER BY id")]
    return [r for r in rows if status is None or r["status"] == status]


def test_patron_aceptado(juan):
    steps(weekday=4000, weekend=2000)
    accepted, rejected = profile.consider([PATRON], 1, NOW)
    assert rejected == [] and len(accepted) == 1
    [item] = items("activo")
    assert item["kind"] == "patron" and "mediana 2.000" in item["text"] and "4.000" in item["text"]
    assert "no causa" in item["text"]                    # el texto lo arma el código, no la IA


def test_patron_rechazado_sin_evidencia_estadistica(juan):
    steps(weekday=4000, weekend=3900)
    accepted, rejected = profile.consider([PATRON], 1, NOW)
    assert accepted == [] and "no pasó la prueba" in rejected[0]["reason"]
    assert items() == []


def test_vocabulario_con_un_solo_relato_rechazado_y_con_dos_aceptado(juan):
    relato("hoy ando medio trabado de las piernas", "motor")
    voc = ProfileLearning(kind="vocabulario", text="Dice trabado cuando le cuesta moverse", word="trabado",
                          domain="motor")
    accepted, rejected = profile.consider([voc], 1, NOW)
    assert accepted == [] and "1 relato" in rejected[0]["reason"]
    relato("a la tarde me sentí trabado otra vez", "motor", day=DAY - dt.timedelta(days=1))
    accepted, _ = profile.consider([voc], 1, NOW)
    assert len(accepted) == 1 and "«trabado»" in items("activo")[0]["text"]


def test_costumbre_la_recalcula_el_codigo(juan):
    for i in range(4):
        relato(f"relato {i}", "motor", speaker=2, role="cuidador", day=DAY - dt.timedelta(days=i), hour=21)
    c = ProfileLearning(kind="costumbre", text="Marta cuenta de noche", habit="hora", role="cuidador")
    accepted, _ = profile.consider([c], 1, NOW)
    assert accepted[0]["text"] == "La cuidadora suele contar a la noche (4 de 4 relatos)."


def test_aprendizaje_con_contenido_reservado_rechazado_y_nunca_en_el_perfil(juan):
    reservado = relato("hablaba con alguien que no estaba en el living", "neuropsiquiatrico", speaker=2,
                       role="cuidador", reserved=True)
    relato("anoche hablaba solo un rato", "neuropsiquiatrico", speaker=2, role="cuidador")
    relato("hablaba dormido otra vez", "neuropsiquiatrico", speaker=2, role="cuidador",
           day=DAY - dt.timedelta(days=1))
    propuestas = [
        ProfileLearning(kind="vocabulario", text="Marta dice hablaba", word="hablaba", domain="neuropsiquiatrico",
                        evidence_ids=[f"relato:{reservado}"]),
        ProfileLearning(kind="vocabulario", text="Marta usa una frase", word="que no estaba",
                        domain="neuropsiquiatrico"),
        ProfileLearning(kind="costumbre", text="Ve a alguien que no estaba en el living", habit="hora",
                        role="cuidador"),
    ]
    accepted, rejected = profile.consider(propuestas, 1, NOW)
    assert accepted == []
    assert [r["reason"] for r in rejected] == ["contenido reservado", "aparece en un relato reservado",
                                               "contenido reservado"]
    text = profile.render_profile(1, NOW)
    assert "alguien que no estaba" not in text and "living" not in text


def test_diagnostico_interpretacion_y_medicacion_rechazados(juan):
    steps(weekday=4000, weekend=2000)
    malos = [PATRON.model_copy(update={"text": "Es un wearing-off de fin de semana"}),
             PATRON.model_copy(update={"text": "Indica que la enfermedad progresa"}),
             PATRON.model_copy(update={"text": "Camina menos por el pramipexol"})]
    accepted, rejected = profile.consider(malos, 1, NOW)
    assert accepted == [] and [r["reason"] for r in rejected] == [
        "diagnóstico, medicación o causa", "interpretación clínica", "diagnóstico, medicación o causa"]


def test_patron_que_deja_de_cumplirse_pasa_a_retirado(juan):
    steps(weekday=4000, weekend=2000)
    profile.consider([PATRON], 1, NOW)
    assert profile.retest(1, NOW + dt.timedelta(days=1)) == []           # sigue: se confirma
    steps(weekday=4000, weekend=4000)
    [gone] = profile.retest(1, NOW + dt.timedelta(days=1))
    [item] = items()
    assert item["status"] == "retirado" and "no pasó la prueba" in item["retired_reason"] == gone["reason"]
    assert item["text"] not in profile.render_profile(1, NOW)


def test_maximo_10_activos_y_render_no_supera_25_lineas(juan):
    steps(weekday=4000, weekend=2000)
    with db.connect() as conn:
        for i in range(12):
            conn.execute("INSERT INTO patient_profile_items (patient_id, kind, key, text, status, created_at, "
                         "last_confirmed_at) VALUES (1, 'vocabulario', ?, ?, 'activo', ?, ?)",
                         (f"k{i}", f"Aprendizaje {i}", db.to_db(NOW), db.to_db(NOW)))
    text = profile.render_profile(1, NOW)
    assert len(text.splitlines()) <= 25
    assert "Pasos habituales" in text and "levodopa/carbidopa a las 8, 12, 16, 20" in text and "03/10" in text
    _, rejected = profile.consider([PATRON], 1, NOW)
    assert "10 aprendizajes activos" in rejected[0]["reason"]


def test_el_perfil_va_en_los_prompts_solo_con_profile_enabled(juan, monkeypatch):
    token = profile.CURRENT.set(1)
    try:
        blocks = knowledge.system_blocks("PROMPT")
        assert len(blocks) == 3 and blocks[1]["text"].startswith("<perfil_del_paciente>")
        assert blocks[0]["text"] == knowledge.knowledge() and blocks[2]["text"] == "PROMPT"
        assert len(knowledge.system_blocks("PROMPT", profile=False)) == 2           # respaldo de rojos: sin perfil
        monkeypatch.setattr(config, "PROFILE_ENABLED", False)
        assert len(knowledge.system_blocks("PROMPT")) == 2
        assert "learnings" not in daily_plan_pipeline.tool()["input_schema"]["properties"]
    finally:
        profile.CURRENT.reset(token)


def test_la_revision_en_historia_acepta_aprendizajes_y_no_agenda(juan, monkeypatch):
    steps(weekday=4000, weekend=2000)

    async def fake(digest):
        return DailyPlan(learnings=[PATRON])
    monkeypatch.setattr(daily_plan_pipeline, "daily_plan", fake)
    summary = asyncio.run(plan_jobs.run_plan(1, NOW, historia=True))
    assert len(summary["perfil"]["aceptados"]) == 1 and summary["agendadas"] == 0
    assert "learnings" in daily_plan_pipeline.tool()["input_schema"]["required"]


def test_la_vista_tecnica_muestra_lo_aprendido(juan, monkeypatch):
    from fastapi.testclient import TestClient

    from app import clock
    from app.api import _store as store
    from app.main import app

    steps(weekday=4000, weekend=2000)
    profile.consider([PATRON], 1, NOW)
    monkeypatch.setattr(clock, "now", lambda: NOW)
    store._has_db_cache["checked"] = -1e9
    html = TestClient(app).get("/neuro/tecnica/1").text
    assert "Lo que la app aprendió de Juan" in html and "propuesto por IA, aceptado solo con evidencia" in html
    assert json.loads(items()[0]["spec"])["hypothesis"]["condition"] == "fin_de_semana"

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

RAW = json.loads((Path(__file__).resolve().parent.parent / "scripts/fixtures/report_facts_semana.json").read_text())
FACTS = report_facts.present(RAW)
SUMMARY = ("En el período 20/09 al 17/10, a 25 días del cambio de pramipexol. Hay un tema para hablar en privado "
           "(tema 1). Después de la toma de las 16, los pasos bajaron en 3 tardes. "
           "Marta contó 3 noches con despertares. Pasos: 15 de 28 días en la meta de 4.000.")


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
    assert rep.topics[0].voices == {"Marta, su esposa": "anoche hablaba con alguien que no estaba"}   # claves del código
    kw = fake.calls[0]
    assert kw["output_config"] == {"effort": "medium"} and "<facts>" in kw["messages"][0]["content"]
    assert kw["system"][0]["text"].startswith("# Parkinson")


@pytest.mark.parametrize("bad", [
    {**GOOD, "topics": GOOD["topics"] + [topic("Otro", [201])]},                         # cuatro temas
    {**GOOD, "topics": [topic("x", [999])] + GOOD["topics"][1:]},                       # id inexistente
    {**GOOD, "summary": "Muy corto."},                                                  # resumen corto
    {**GOOD, "topics": [{**GOOD["topics"][0], "narrative": "palabra " * 130}] + GOOD["topics"][1:]},
])
def test_salida_que_no_cumple_se_reintenta(monkeypatch, bad):
    fake = FakeSonnet(bad, GOOD)
    monkeypatch.setattr(llm, "_create", fake)
    assert len(asyncio.run(report.generate(FACTS)).topics) == 3 and len(fake.calls) == 2


def test_dos_temas_alcanzan(monkeypatch):
    fake = FakeSonnet({**GOOD, "topics": GOOD["topics"][:2]})
    monkeypatch.setattr(llm, "_create", fake)
    assert len(asyncio.run(report.generate(FACTS)).topics) == 2 and len(fake.calls) == 1


def test_tres_fallas_duras_son_error(monkeypatch):
    fake = FakeSonnet({**GOOD, "topics": [topic("x", [999])] + GOOD["topics"][1:]})   # id inexistente: dura
    monkeypatch.setattr(llm, "_create", fake)
    with pytest.raises(llm.LLMError):
        asyncio.run(report.generate(FACTS))
    assert len(fake.calls) == report.ATTEMPTS == 3


# ── Nunca vacío: fallas blandas se guardan limpias; duras o sin IA, el informe mínimo ──

SOFT = {**GOOD, "summary": SUMMARY.replace("15 de 28", "99 de 28"),                         # cifra que no está
        "topics": [{**GOOD["topics"][0], "observed": ["unas 7 noches"], "question": "¿Pasa a la madrugada?"},
                   *GOOD["topics"][1:]]}


def test_fallas_blandas_se_guardan_limpias_por_el_verificador(tmp_data_dir, monkeypatch):
    fake = FakeSonnet(SOFT)
    monkeypatch.setattr(llm, "_create", fake)
    monkeypatch.setattr(report_facts, "build", lambda pid, now, period=None: FACTS)
    rep = asyncio.run(report.report(1))
    assert len(fake.calls) == 3 and not report.is_minimal(rep)
    assert rep.removed_count == 3                       # la oración del 99, lo observado y la pregunta
    assert "99" not in rep.summary and "Hay un tema para hablar en privado (tema 1)." in rep.summary
    assert rep.topics[0].observed == [] and rep.topics[0].question == ""
    with base.connect() as conn:
        row = conn.execute("SELECT content, removed_by_verifier FROM reports").fetchone()
    assert row["removed_by_verifier"] == 3 and json.loads(row["content"])["redaccion"] == "ia"


def test_falla_dura_guarda_el_informe_minimo(tmp_data_dir, monkeypatch):
    mezcla = _with(evidence_ids=[205, 204])                   # reservado con no reservado: dura
    monkeypatch.setattr(llm, "_create", FakeSonnet(mezcla))
    monkeypatch.setattr(report_facts, "build", lambda pid, now, period=None: FACTS)
    rep = asyncio.run(report.report(1))
    assert report.is_minimal(rep) and rep.topics == [] and rep.removed_count == 0
    assert rep.summary.startswith("El resumen redactado no está disponible")
    with base.connect() as conn:
        assert json.loads(conn.execute("SELECT content FROM reports").fetchone()["content"])["redaccion"] == "codigo"


def test_sin_respuesta_de_la_ia_guarda_el_informe_minimo(tmp_data_dir, monkeypatch):
    async def caida(**kwargs):
        raise llm.LLMError("Falta ANTHROPIC_API_KEY")
    monkeypatch.setattr(llm, "_create", caida)
    monkeypatch.setattr(report_facts, "build", lambda pid, now, period=None: FACTS)
    rep = asyncio.run(report.report(1))
    assert report.is_minimal(rep)
    with base.connect() as conn:
        assert conn.execute("SELECT count(*) FROM reports").fetchone()[0] == 1


def test_si_falla_y_ya_hay_uno_redactado_queda_ese(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(report_facts, "build", lambda pid, now, period=None: FACTS)
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    first = asyncio.run(report.report(1))                       # redactado por IA
    monkeypatch.setattr(llm, "_create", FakeSonnet(_with(evidence_ids=[205, 204])))   # después, falla dura
    again = asyncio.run(report.report(1))
    assert again == first and not report.is_minimal(again)
    with base.connect() as conn:
        rows = conn.execute("SELECT content FROM reports").fetchall()
    assert len(rows) == 1 and json.loads(rows[0]["content"])["redaccion"] == "ia"   # no se guardó el mínimo


def test_un_minimo_previo_no_cuenta_como_redactado(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(report_facts, "build", lambda pid, now, period=None: FACTS)
    report._store(1, "x", report.minimal_report())
    monkeypatch.setattr(llm, "_create", FakeSonnet(_with(evidence_ids=[205, 204])))
    assert report.is_minimal(asyncio.run(report.report(1)))


def test_verify_local_saca_evidencia_de_otra_franja_y_temas_con_titulo_falso():
    rep = report.to_report(report._Output.model_validate(
        {**GOOD, "topics": [GOOD["topics"][0], {**GOOD["topics"][1], "title": "Trabado a la tarde",
                                                 "evidence_ids": [206, 201]},
                            {**GOOD["topics"][2], "title": "Noches con 99 despertares"}]}), FACTS)
    out = report.verify_local(rep, FACTS)
    assert [t.title for t in out.topics] == ["Habla con gente que no está", "Trabado a la tarde"]
    assert out.topics[1].evidence_ids == [206] and out.removed_count == 2


def test_pasa_por_el_verificador(monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    seen = {}

    def fake_verify(rep, facts, sources):
        seen["sources"] = sources
        return rep.model_copy(update={"removed_count": 2})
    monkeypatch.setattr(report, "verify", fake_verify)          # cuando exista rules.verifier, va primero
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
    raw = report_facts.collect(1, clock.now())
    assert raw["period"] == {"start": "2026-09-20", "end": "2026-10-17", "days": 28,
                             "label": "2026-09-20/2026-10-17", "text": "20/09 al 17/10"}
    assert raw["steps"]["days_in_goal"] == 1 and raw["steps"]["days_with_data"] == 2 and raw["steps"]["goal"] == 4000
    [e] = raw["events"]
    assert (e["speaker_name"], e["reserved"], e["is_new"], e["days_since_med_change"]) == ("Marta", True, True, 22)
    f = report_facts.build(1, clock.now())
    assert f["steps"]["goal"] == "4.000" and f["steps"]["days_in_goal"] == "1"
    assert f["medication"][0]["days_since_change"] == "25" and f["medication"][0]["changed"] == "22/09"
    assert f["events"][0]["speaker_label"] == "Marta, su esposa" and f["events"][0]["date"] == "14/10"
    assert f["entries_by_voice"] == [{"voice": "Marta, su esposa", "entries": "1"}]


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



# ── Fidelidad: números, quién dijo qué, con/sin relato, franjas ──

def _with(**topic0):
    return {**GOOD, "topics": [{**GOOD["topics"][0], **topic0}] + GOOD["topics"][1:]}


@pytest.mark.parametrize("bad, why", [
    ({**GOOD, "summary": SUMMARY.replace("15 de 28", "99 de 28")}, "número que no está"),
    ({**GOOD, "summary": SUMMARY.replace("los pasos bajaron en 3 tardes", "bajaron a unos 390 pasos")}, "aproxima"),
    ({**GOOD, "summary": SUMMARY.replace("Hay un tema para hablar en privado (tema 1).", "Hay algo privado.")},
     "falta la frase del tema reservado"),
    ({**GOOD, "summary": SUMMARY + " Marta contó que hablaba con alguien que no estaba."}, "cuenta el contenido"),
    (_with(narrative="Marta contó que «hablaba con alguien que no existe»."), "cita no literal"),
    (_with(narrative="Laura dijo «anoche hablaba con alguien que no estaba»."), "cita con otro nombre"),
    (_with(narrative="«anoche hablaba con alguien que no estaba», según el registro."), "cita sin nombre"),
    (_with(narrative="Marta lo contó al mediodía."), "franja inventada"),
    ({**GOOD, "topics": GOOD["topics"][:1] + [{**GOOD["topics"][1], "narrative": "Dos tardes quedaron sin explicar."}]
      + GOOD["topics"][2:]}, "explicado"),
    (_with(voices={"paciente": "anoche hablaba con alguien que no estaba", "cuidador": None, "familiar": None}),
     "voz que no es suya"),
])
def test_fidelidad_rechaza_y_reintenta(monkeypatch, bad, why):
    fake = FakeSonnet(bad, GOOD)
    monkeypatch.setattr(llm, "_create", fake)
    asyncio.run(report.generate(FACTS))
    assert len(fake.calls) == 2, why


def test_cita_con_su_nombre_y_franja_que_esta_en_la_cita_pasan(monkeypatch):
    ok = _with(narrative="Marta, su esposa, contó el 14/10 que «anoche hablaba con alguien que no estaba». Fue de noche.")
    fake = FakeSonnet(ok)
    monkeypatch.setattr(llm, "_create", fake)
    asyncio.run(report.generate(FACTS))
    assert len(fake.calls) == 1


def test_episodios_con_y_sin_relato():
    s = FACTS["deviations_summary"]
    assert (s["count"], s["with_story"], s["without_story"], s["pct_change_range"]) == ("3", "1", "2", "69–71%")
    assert [d["story"] for d in FACTS["deviations"]] == ["sin relato", "con relato de Juan", "sin relato"]


def test_tema_reservado_no_mezcla_eventos_no_reservados(monkeypatch):
    mezcla = _with(evidence_ids=[205, 204])            # 205 reservado (Marta), 204 no (Juan)
    fake = FakeSonnet(mezcla, GOOD)
    monkeypatch.setattr(llm, "_create", fake)
    asyncio.run(report.generate(FACTS))
    assert len(fake.calls) == 2


def test_noches_las_cuenta_el_codigo_y_la_madrugada_es_de_la_noche_anterior():
    assert FACTS["nights_with_awakenings"] == {"count": "3", "dates": "11/10, 13/10 y 15/10"}
    raw = json.loads(json.dumps(RAW))
    raw["events"].append({**raw["events"][0], "id": 299, "occurred_at": "2026-10-12T04:00:00-03:00",
                          "time_vague": False, "quote": "le costó volver a dormirse"})
    assert report_facts.present(raw)["nights_with_awakenings"]["dates"] == "11/10, 13/10 y 15/10"   # misma noche


def test_habitual_no_tiene_fecha_ni_noche():
    raw = json.loads(json.dumps(RAW))
    raw["events"].append({**raw["events"][0], "id": 298, "occurred_at": None, "quote": "me levanto un par de veces"})
    e = next(x for x in report_facts.present(raw)["events"] if x["id"] == 298)
    assert (e["date"], e["habitual"], e["night"], e["part"]) == (None, True, None, None)


def test_titulo_con_franja_no_mezcla_otra_franja(monkeypatch):
    mezcla = {**GOOD, "topics": GOOD["topics"][:1] + [{**GOOD["topics"][1], "title": "Trabado a la tarde",
                                                        "evidence_ids": [206, 201]}] + GOOD["topics"][2:]}
    fake = FakeSonnet(mezcla, GOOD)                         # 201 es de noche
    monkeypatch.setattr(llm, "_create", fake)
    asyncio.run(report.generate(FACTS))
    assert len(fake.calls) == 2


def test_facts_traen_plain_para_atribuir():
    e = next(x for x in report_facts.present(RAW)["events"] if x["id"] == 207)
    assert "plain" in e


# ── verify_local: la verificación final en código ──

def _rep(summary, narrative, voices=None, ids=(205,)):
    from app.models import Report, ReportTopic
    t = ReportTopic(title="x", narrative=narrative, observed=[], voices=voices or {}, question="?",
                    evidence_ids=list(ids), reserved=True)
    return Report(summary=summary, topics=[t], removed_count=0)


def test_verify_local_borra_y_cuenta():
    rep = _rep("Hubo 3 tardes con menos pasos. Hubo 99 noches malas. Todo lo demás estuvo bien.",
               "Marta, su esposa, contó «anoche hablaba con alguien que no estaba». Laura dijo «anoche hablaba con "
               "alguien que no estaba». Alguien contó «una frase inventada».",
               voices={"Marta, su esposa": "anoche hablaba con alguien que no estaba", "Juan": "algo que no dijo"})
    out = report.verify_local(rep, FACTS)
    assert out.summary == "Hubo 3 tardes con menos pasos. Todo lo demás estuvo bien."
    assert out.topics[0].narrative == "Marta, su esposa, contó «anoche hablaba con alguien que no estaba»."
    assert out.topics[0].voices == {"Marta, su esposa": "anoche hablaba con alguien que no estaba"}
    assert out.removed_count == 4                       # 1 del resumen, 2 del párrafo, 1 voz


def test_verify_local_no_toca_lo_correcto():
    rep = _rep(SUMMARY, "Marta, su esposa, contó el 14/10 que «anoche hablaba con alguien que no estaba».")
    out = report.verify_local(rep, FACTS)
    assert out.summary == SUMMARY and out.removed_count == 0


def test_generate_pasa_por_verify_local(monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    called = {}
    real = report.verify_local

    def spy(rep, facts):
        called["yes"] = True
        return real(rep, facts)
    monkeypatch.setattr(report, "verify_local", spy)
    asyncio.run(report.generate(FACTS))
    assert called


# ── Eval del informe v2: frase privada, varias franjas y franja del evento ──

def test_la_frase_privada_no_pasa_por_el_chequeo_de_cifras(monkeypatch):
    # El "(tema 1)" lo pone el código: no es una cifra de facts. Un "1" suelto en otra frase sí se rechaza.
    sin_uno = report.allowed_numbers(FACTS) - {"1"}
    monkeypatch.setattr(report, "allowed_numbers", lambda facts: sin_uno)
    out = report._Output.model_validate(GOOD)
    report.check(out, FACTS)                                    # no lanza por el "1" de la frase privada
    rep = report.verify_local(report.to_report(out, FACTS), FACTS)
    assert "Hay un tema para hablar en privado (tema 1)." in rep.summary and rep.removed_count == 0
    otra = report._Output.model_validate({**GOOD, "summary": SUMMARY + " Hubo 1 caída."})
    with pytest.raises(report.SoftCheckError, match="'1'"):
        report.check(otra, FACTS)


def test_un_titulo_que_nombra_dos_franjas_acepta_las_dos():
    events = {e["id"]: e for e in FACTS["events"]}
    dos = report.ReportTopic(title="Tardes lentas y noches cortadas", narrative="", observed=[], voices={},
                             question="", evidence_ids=[202, 201], reserved=False)
    una = dos.model_copy(update={"title": "Noches cortadas"})
    assert report._wrong_part_ids(dos, events) == []
    assert report._wrong_part_ids(una, events) == [202]


def test_la_franja_del_evento_cuenta_como_evidencia():
    events = {e["id"]: e for e in FACTS["events"]}
    numbers = report.allowed_numbers(FACTS)
    # 201 dice "anoche" (no "a la noche"), pero el código lo ubicó de noche: la franja está respaldada.
    assert report._text_problem("A la noche se despertó.", numbers, report._evidence_text([events[201]])) is None
    # 206 no tiene franja: "a la mañana" sigue siendo inventado.
    assert "franja" in report._text_problem("A la mañana se sintió trabado.", numbers,
                                            report._evidence_text([events[206]]))

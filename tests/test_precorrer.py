import asyncio
import datetime as dt
import json
import re
from types import SimpleNamespace

import pytest

from app import clock, db, scheduler
from app.config import TZ
from app.pipeline import llm
from data import seed
from scripts import precorrer_semana as pre
from tests.test_seed import import_steps

QUESTION = {"question": "Juan, hoy caminaste menos que otras tardes. ¿Pasó algo?",
            "options": ["Estaba duro", "Me sentí bien, solo no salí", "No me acuerdo"]}


class SmartSonnet:
    """explain: explicado solo si un relato del contexto dice "trabado"; ask: una pregunta válida."""
    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["tools"][0]["name"]
        content = kwargs["messages"][0]["content"]
        if name == "registrar_explicacion":
            today = re.search(r"Ahora: \w+ (\d\d/\d\d)", content).group(1)
            m = re.search(rf'cuando="\w+ {today} [^"]*">([^<]*trabado[^<]*)</relato>', content)
            out = ({"explained": True, "by": [m.group(1)], "reasoning": "contó que se sintió trabado"} if m
                   else {"explained": False, "by": [], "reasoning": "sin relato"})
        else:
            out = QUESTION
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=out)], stop_reason="tool_use")


@pytest.fixture
def semana(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: dt.datetime(2026, 10, 18, 7, 45, tzinfo=TZ))
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "x")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:x@y.z")
    import_steps()
    seed.run()
    monkeypatch.setattr(llm, "_create", SmartSonnet())
    return data_dir


def rows(sql, *args):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def juan_questions(day: str):
    """Preguntas que se le hicieron a Juan ese día (las de días anteriores vencen: quedan 'descartada')."""
    return rows("SELECT * FROM questions WHERE to_person_id = 1 AND question != '' "
                "AND substr(sent_at, 1, 10) = ?", day)


def test_el_escenario_cumple_lo_que_necesita_la_demo():
    """data/escenario/juan.yaml (PULIDO §2): 25 a 35 relatos de las tres voces y las condiciones del guion."""
    rel = pre.RELATOS
    assert 25 <= len(rel) <= 35
    assert {r.person_id for r in rel} == {1, 2, 3}
    assert rel[0].at.date() <= dt.date(2026, 9, 21) and rel[-1].at <= pre.END
    assert all(r.at.date() != dt.date(2026, 10, 17) for r in rel)           # nada el sábado antes de la caída en vivo
    assert any(r.reserved and r.person_id == 2 for r in rel)
    tarde = lambda day: [r for r in rel if r.person_id == 1 and r.at.date() == dt.date(2026, 10, day)  # noqa: E731
                         and dt.time(12) <= r.at.time() < dt.time(18, 5)]
    assert tarde(13) == [] and tarde(16) == []                              # nadie le explica la tarde: se le pregunta
    assert any("trabado" in r.text for r in tarde(15))                      # el jueves la explica él


def test_el_yaml_se_valida(tmp_path):
    bad = tmp_path / "x.yaml"
    bad.write_text("paciente: 1\npersonas: {juan: 1}\nfin: '2026-10-16 23:00'\n"
                   "ticks: {semana_demo: {desde: '2026-10-11', hasta: '2026-10-16', horas: [8, 22]}, resto: [9]}\n"
                   "relatos:\n  - {cuando: '2026-10-12 10:00', quien: juan, cuando_paso: hoy, texto: hola}\n",
                   encoding="utf-8")
    with pytest.raises(ValueError, match="OccurredHint"):
        pre.load(bad)
    bad.write_text(bad.read_text(encoding="utf-8").replace("quien: juan, cuando_paso: hoy", "quien: pepe"), encoding="utf-8")
    with pytest.raises(ValueError, match="pepe"):
        pre.load(bad)


def test_ticks_cada_hora_en_la_semana_de_la_demo_y_tres_por_dia_antes():
    ticks = pre.ESC.ticks
    assert sum(1 for t in ticks if t.date() == dt.date(2026, 10, 13)) == 15                 # 8:05 a 22:05
    assert [t.hour for t in ticks if t.date() == dt.date(2026, 10, 1)] == [9, 14, 21]


def test_precorrer_arma_la_semana_de_la_demo(semana):
    result = asyncio.run(pre.run())
    n = len(pre.RELATOS)
    assert result["cargados"] == n
    assert len(rows("SELECT * FROM entries WHERE source = 'precorrer'")) == n
    assert clock.now().isoformat().startswith("2026-10-16T23:00")
    # §3: martes 13 sin relato → pregunta; jueves 15 Juan cuenta antes de las 18 → no; viernes 16 → pregunta
    assert len(juan_questions("2026-10-13")) == 1
    assert juan_questions("2026-10-15") == []
    assert len(juan_questions("2026-10-16")) == 1
    episodes = {r["dose_time"][:10]: r["status"] for r in rows("SELECT dose_time, status FROM episodes")}
    assert episodes == {"2026-10-13": "preguntado", "2026-10-15": "explicado", "2026-10-16": "preguntado"}
    assert any(a["rule_id"] == "A3" for a in rows("SELECT rule_id FROM alerts"))
    # las push quedaron apagadas: notificaciones guardadas, ninguna enviada; sin "Recibido" de los relatos precorridos
    assert all(n["push_sent"] == 0 for n in rows("SELECT push_sent FROM notifications"))
    assert rows("SELECT * FROM notifications WHERE kind = 'resumen'") == []


def test_precorrer_es_idempotente(semana):
    asyncio.run(pre.run())
    before = (len(rows("SELECT * FROM entries")), len(rows("SELECT * FROM questions")), len(rows("SELECT * FROM events")))
    again = asyncio.run(pre.run())
    assert again["cargados"] == 0 and again["ya_estaban"] == len(pre.RELATOS) and again["preguntas"] == []
    assert (len(rows("SELECT * FROM entries")), len(rows("SELECT * FROM questions")),
            len(rows("SELECT * FROM events"))) == before


def test_el_presupuesto_del_sabado_queda_libre_para_la_caida_en_vivo(semana):
    """Después de precorrer, el sábado 17 hasta las 15:55 Juan no recibe ninguna pregunta."""
    asyncio.run(pre.run())
    for hhmm in ("08:05", "10:05", "12:05", "14:05", "15:55"):
        clock.set(f"2026-10-17T{hhmm}:00")
        asyncio.run(scheduler.tick())
    assert juan_questions("2026-10-17") == []
    assert rows("SELECT * FROM notifications WHERE person_id = 1 AND kind = 'pregunta' "
                "AND substr(created_at, 1, 10) = '2026-10-17'") == []



def test_precorrer_termina_con_el_informe_guardado(semana, monkeypatch):
    from app.models import Report
    from app.pipeline import report
    calls = []

    async def fake_report(patient_id, period=None):
        calls.append(patient_id)
        rep = Report(summary="x", topics=[], removed_count=0)
        report._store(patient_id, "2026-09-19/2026-10-16", rep)
        return rep
    monkeypatch.setattr(report, "report", fake_report)
    result = asyncio.run(pre.run())
    assert calls == [1] and result["informe"]["ok"] is True          # una sola vez, al final
    assert len(rows("SELECT * FROM reports WHERE patient_id = 1")) == 1


def test_si_el_informe_final_falla_el_script_lo_dice(semana, monkeypatch):
    from app.pipeline import report

    async def boom(patient_id, period=None):
        raise RuntimeError("x")
    monkeypatch.setattr(report, "report", boom)
    assert asyncio.run(pre.run())["informe"] == {"ok": False}

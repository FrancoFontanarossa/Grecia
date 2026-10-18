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
    return rows("SELECT * FROM questions WHERE to_person_id = 1 AND status IN ('enviada','pendiente','respondida') "
                "AND substr(sent_at, 1, 10) = ?", day)


def test_precorrer_arma_la_semana_de_la_demo(semana):
    result = asyncio.run(pre.run())
    assert result["cargados"] == len(pre.RELATOS) == 14
    assert len(rows("SELECT * FROM entries WHERE source = 'precorrer'")) == 14
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
    assert again["cargados"] == 0 and again["ya_estaban"] == 14 and again["preguntas"] == []
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

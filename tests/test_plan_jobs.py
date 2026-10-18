"""Modo 2 en el scheduler: el plan se arma a las 21 (una vez por día), lo agendado se ejecuta a su hora y el juego
queda vinculado al episodio del desvío. La IA se reemplaza por un plan fijo."""
import asyncio
import datetime as dt

import pytest

from app import config, db, plan_jobs
from app.config import TZ
from app.models import DailyPlan, PlannedAction
from app.pipeline import daily_plan as daily_plan_pipeline


def at(day: dt.date, h: int, m: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(h, m), TZ)


DAY = dt.date(2026, 10, 16)


@pytest.fixture
def base(tmp_data_dir, monkeypatch):
    with db.connect() as conn:
        ep = conn.execute("INSERT INTO episodes (patient_id, dose_time, deviation, explanation, status) "
                          "VALUES (1, ?, ?, '{}', 'preguntado')",
                          (db.to_db(at(DAY, 16)), '{"observed": 356, "median": 1289}')).lastrowid
    plan = DailyPlan(actions=[PlannedAction(kind="golpeteo", at="16:30", to_role="paciente", reason="Un juego cortito",
                                            basis=f"desvio:{ep}", evidence_ids=[f"episodio:{ep}"])])
    calls = []

    async def fake_plan(digest):
        calls.append(digest["plan_date"])
        return plan
    monkeypatch.setattr(daily_plan_pipeline, "daily_plan", fake_plan)
    plan_jobs._done.clear()
    return {"episode": ep, "calls": calls}


def rows(sql, *args):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def test_antes_de_las_21_no_planifica_y_despues_una_sola_vez(base):
    asyncio.run(plan_jobs.plan_if_due(1, at(DAY, 20, 59)))
    assert base["calls"] == []
    asyncio.run(plan_jobs.plan_if_due(1, at(DAY, 21, 0)))
    asyncio.run(plan_jobs.plan_if_due(1, at(DAY, 22, 30)))
    assert base["calls"] == ["2026-10-17"]
    acts = rows("SELECT * FROM planned_actions")
    assert len(acts) == 1 and acts[0]["status"] == "agendada" and acts[0]["at"] == "16:30"
    assert acts[0]["why"] == "El 16/10, después de la toma de las 16: 356 pasos; lo habitual ≈ 1.289."


def test_lo_agendado_se_ejecuta_a_su_hora_y_el_juego_va_al_episodio(base):
    asyncio.run(plan_jobs.plan_if_due(1, at(DAY, 21, 0)))
    tomorrow = DAY + dt.timedelta(days=1)
    assert asyncio.run(plan_jobs.execute_due(1, at(tomorrow, 16, 29))) == []          # todavía no
    done = asyncio.run(plan_jobs.execute_due(1, at(tomorrow, 16, 30)))
    assert len(done) == 1
    assert rows("SELECT status FROM planned_actions")[0]["status"] == "ejecutada"
    n = rows("SELECT * FROM notifications WHERE person_id = 1 ORDER BY id DESC")[0]
    assert n["title"] == plan_jobs.GAME_TITLE and n["url"].startswith("/casa/golpeteo")
    assert asyncio.run(plan_jobs.execute_due(1, at(tomorrow, 17, 0))) == []           # no se repite
    with db.connect() as conn:
        tid = conn.execute("INSERT INTO tests (patient_id, type, metrics, raw, taken_at, source) "
                           "VALUES (1, 'golpeteo', '{\"taps_per_s\": 4.7}', '[]', ?, 'app')",
                           (db.to_db(at(tomorrow, 16, 32)),)).lastrowid
    assert plan_jobs.link_test(1, tid, at(tomorrow, 16, 33)) == base["episode"]
    assert rows("SELECT test_id FROM episodes")[0]["test_id"] == tid


def test_lo_que_no_se_ejecuto_vence_al_dia_siguiente(base):
    asyncio.run(plan_jobs.plan_if_due(1, at(DAY, 21, 0)))
    asyncio.run(plan_jobs.execute_due(1, at(DAY + dt.timedelta(days=2), 9, 0)))
    a = rows("SELECT status, discard_reason FROM planned_actions")[0]
    assert a == {"status": "descartada", "discard_reason": "venció sin ejecutarse"}


def test_apagado_por_defecto():
    assert config.DAILY_PLAN_ENABLED is False or __import__("os").environ.get("DAILY_PLAN_ENABLED") == "1"

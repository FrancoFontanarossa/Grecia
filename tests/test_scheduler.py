import asyncio
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app import _tmp_db as db
from app import clock, scheduler
from app import db as base
from app.config import TZ
from app.models import Deviation, Trigger
from app.notify import push
from app.pipeline import llm
from tests.conftest import FakeSonnet

DOSE = dt.datetime(2026, 10, 17, 16, 0, tzinfo=TZ)
DEV = Deviation(dose_time=DOSE, window="16:00-18:00", observed=420, median=1300.0, z=-4.1, pct_change=-0.68,
                baseline="estrato", baseline_n=8)
WHY = "Otros fines de semana, de 16 a 18 h: unos 1.300 pasos. Hoy, después de la toma de las 16: 420."
GOOD = {"question": "Juan, hoy a la tarde caminaste menos que otros días. ¿Pasó algo?",
        "options": ["Estaba duro", "Me sentí bien, solo no salí", "No me acuerdo"]}


def trigger(**over):
    base_t = {"rule_id": "P-DESVIO", "patient_id": 1, "to_person_id": 1,
              "facts": {"deviation": DEV.model_dump(mode="json"), "dose_time": DOSE.isoformat()}, "why": WHY}
    return Trigger(**{**base_t, **over})


@pytest.fixture
def at_1805(tmp_data_dir):
    clock.set("2026-10-17T18:05:00")
    return tmp_data_dir


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kw: sent.append(kw))
    db.save_subscription(person_id=1, endpoint="https://push.example/juan", p256dh="p", auth="a")
    return sent


def rows(sql):
    with base.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def run_tick(monkeypatch, *triggers):
    monkeypatch.setattr(scheduler, "evaluate", lambda pid, now: list(triggers) if pid == 1 else [])
    return asyncio.run(scheduler.tick())


def test_desvio_no_explicado_pregunta_guarda_y_manda_push(at_1805, pushes, monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))   # explain no hace falta: no hay relatos
    [qid] = run_tick(monkeypatch, trigger())

    [q] = rows("SELECT * FROM questions")
    assert (q["id"], q["status"], q["rule_id"], q["to_person_id"]) == (qid, "enviada", "P-DESVIO", 1)
    assert q["why"] == WHY and q["url"] == f"/casa/pregunta/{qid}" and json.loads(q["options"]) == GOOD["options"]
    assert q["question"] == GOOD["question"] and q["sent_at"].startswith("2026-10-17T18:05")
    [ep] = rows("SELECT * FROM episodes")
    assert ep["question_id"] == qid and ep["status"] == "preguntado" and json.loads(ep["deviation"])["observed"] == 420
    [n] = rows("SELECT * FROM notifications")
    assert (n["kind"], n["title"], n["body"], n["url"]) == ("pregunta", "Juan, una pregunta de hoy", GOOD["question"],
                                                            f"/casa/pregunta/{qid}")
    assert n["push_sent"] == 1 and len(pushes) == 1


def test_idempotente_no_pregunta_dos_veces(at_1805, pushes, monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    assert len(run_tick(monkeypatch, trigger())) == 1
    assert run_tick(monkeypatch, trigger()) == []
    assert len(rows("SELECT * FROM questions")) == 1 and len(pushes) == 1


def test_explicado_no_molesta(at_1805, pushes, monkeypatch):
    db.insert_entry(patient_id=1, speaker_id=1, modality="texto", raw_text="a la tarde fui al dentista, dos horas",
                    question_id=None, occurred_hint=None, reserved_requested=False, source="app")
    monkeypatch.setattr(llm, "_create", FakeSonnet({"explained": True, "by": ["fui al dentista"], "reasoning": "x"}))
    assert run_tick(monkeypatch, trigger()) == []
    [q] = rows("SELECT * FROM questions")
    assert q["status"] == "descartada" and rows("SELECT status FROM episodes") == [{"status": "explicado"}]
    assert pushes == [] and rows("SELECT * FROM notifications") == []
    assert run_tick(monkeypatch, trigger()) == []          # tampoco lo vuelve a evaluar


def test_presupuesto_una_pregunta_por_dia(at_1805, pushes, monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    run_tick(monkeypatch, trigger())
    otro = trigger(rule_id="P-SILENCIO", facts={}, why="Dos días sin relatos.")
    assert run_tick(monkeypatch, otro) == []
    assert len(rows("SELECT * FROM questions")) == 1


def test_silencio_nocturno(tmp_data_dir, pushes, monkeypatch, fake_sonnet):
    clock.set("2026-10-17T23:10:00")
    assert run_tick(monkeypatch, trigger()) == [] and fake_sonnet.calls == []


def test_un_disparador_que_falla_no_frena_los_demas(at_1805, pushes, monkeypatch):
    from app.pipeline import context as ctx_mod
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    real_build = ctx_mod.build

    async def build(trigger, now):
        if trigger.rule_id == "P-ROTO":
            raise RuntimeError("se rompió")
        return await real_build(trigger, now)
    monkeypatch.setattr(ctx_mod, "build", build)
    roto = trigger(rule_id="P-ROTO", to_person_id=2, facts={}, why="x")
    sent = run_tick(monkeypatch, roto, trigger())
    assert len(sent) == 1 and rows("SELECT rule_id FROM questions") == [{"rule_id": "P-DESVIO"}]


def test_persona_inexistente_se_ignora(at_1805, pushes, monkeypatch, fake_sonnet):
    assert run_tick(monkeypatch, trigger(to_person_id=999)) == [] and rows("SELECT * FROM questions") == []
    assert fake_sonnet.calls == []


def test_respuesta_de_juan_cierra_la_pregunta_y_entra_al_episodio(at_1805, pushes, monkeypatch):
    from app.main import app
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    [qid] = run_tick(monkeypatch, trigger())
    r = TestClient(app).post("/api/entries", data={"person_id": 1, "question_id": qid, "quick_reply": "Estaba duro"})
    entry_id = r.json()["entry_id"]
    [q] = rows("SELECT * FROM questions")
    assert q["status"] == "respondida" and q["answered_entry_id"] == entry_id
    [ep] = rows("SELECT * FROM episodes")
    assert ep["status"] == "respondido" and json.loads(ep["entry_ids"]) == [entry_id]


def test_respuesta_de_otra_persona_no_cierra_la_pregunta(at_1805, pushes, monkeypatch):
    from app.main import app
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    [qid] = run_tick(monkeypatch, trigger())
    TestClient(app).post("/api/entries", data={"person_id": 2, "question_id": qid, "quick_reply": "x"})
    assert rows("SELECT status FROM questions") == [{"status": "enviada"}]


def test_el_middleware_pide_tick_al_mover_el_reloj(tmp_data_dir, monkeypatch):
    from app.main import app
    kicks = []
    monkeypatch.setattr(scheduler, "kick", lambda: kicks.append(1))
    monkeypatch.setenv("ADMIN_TOKEN", "admin")
    c = TestClient(app)
    c.post("/admin/clock/advance", json={"minutes": 30}, headers={"X-Admin-Token": "admin"})
    c.get("/health")
    assert kicks == [1]


def test_el_lifespan_arranca_y_frena_el_scheduler(tmp_data_dir):
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert scheduler._task is not None and not scheduler._task.done()
    assert scheduler._task is None


def test_tick_now_es_idempotente(at_1805, pushes, monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(GOOD))
    monkeypatch.setattr(scheduler, "evaluate", lambda pid, now: [trigger()] if pid == 1 else [])

    async def twice():
        return await asyncio.gather(scheduler.tick_now(), scheduler.tick_now())
    first, second = asyncio.run(twice())
    assert sorted([len(first), len(second)]) == [0, 1] and len(rows("SELECT * FROM questions")) == 1

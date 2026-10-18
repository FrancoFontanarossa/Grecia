import asyncio
import datetime as dt

import pytest

from app import clock, db, scheduler
from app.config import TZ
from app.pipeline import llm
from app.rules import triggers
from data import mock_wearable as mw
from tests.conftest import FakeSonnet
from tests.rules.conftest import add_entry, add_event

JUAN, MARTA = 1, 2
QUESTION = {"question": "Juan, ¿cómo dormiste anoche?", "options": ["Bien", "Me desperté mucho", "No me acuerdo"]}


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def wearable(seeded):
    mw.run()
    return seeded


def test_bad_night_fires_in_the_morning_for_juan(wearable):
    [t] = triggers.p_sueno(1, at(6, 9))
    v = mw.nightly(dt.date(2026, 10, 6))["sleep_awakenings"]
    assert t.rule_id == "P-SUENO" and t.to_person_id == JUAN
    assert t.why.startswith(f"Anoche te despertaste {v} veces; lo habitual son 2. Anoche dormiste ")
    assert [a["kind"] for a in t.facts["anomalies"]] == ["sleep_awakenings", "sleep_minutes"]
    assert t.facts["night_of"] == "2026-10-06" and t.facts["source"] == "simulado"
    assert "P-SUENO" in [x.rule_id for x in triggers.evaluate(1, at(6, 9))]


@pytest.mark.parametrize("hour", [7, 12, 18, 23])
def test_only_in_the_morning(wearable, hour):
    assert triggers.p_sueno(1, at(6, hour)) == []


@pytest.mark.parametrize("day", [3, 11, 12, 13, 14, 15, 16])
def test_normal_night_does_not_fire(wearable, day):
    assert triggers.p_sueno(1, at(day, 9)) == []


def test_night_16_to_17_of_the_mock_does_not_fire(wearable):
    for hour in range(8, 12):
        assert triggers.p_sueno(1, at(17, hour, 5)) == []
        assert "P-SUENO" not in [t.rule_id for t in triggers.evaluate(1, at(17, hour, 5))]


def test_without_wearable_nothing(seeded):
    assert triggers.p_sueno(1, at(6, 9)) == []


def test_reserved_content_never_enters(wearable):
    entry = add_entry(MARTA, "SECRETO", created_at=at(6, 7), reserved_requested=True)
    add_event(entry, domain="neuropsiquiatrico", symptom="alucinaciones", speaker_role="cuidador",
              occurred_at=at(6, 3), reserved=True, quote="SECRETO")
    [t] = triggers.p_sueno(1, at(6, 9))
    blob = (t.why + str(t.facts)).lower()
    assert "secreto" not in blob and "alucin" not in blob


# ── Presupuesto: lo aplica el scheduler, como con los otros disparadores de texto ───────────────────────
def run_tick(monkeypatch):
    monkeypatch.setattr(llm, "_create", FakeSonnet(QUESTION))
    return asyncio.run(scheduler.tick())


def test_scheduler_asks_p_sueno_when_there_is_budget(wearable, monkeypatch):
    clock.set(at(6, 9).isoformat())
    [qid] = run_tick(monkeypatch)
    with db.connect() as conn:
        q = dict(conn.execute("SELECT rule_id, to_person_id, why FROM questions WHERE id = ?", (qid,)).fetchone())
    assert q["rule_id"] == "P-SUENO" and q["to_person_id"] == JUAN and q["why"].startswith("Anoche te despertaste")


def test_scheduler_respects_the_daily_question_budget(wearable, monkeypatch):
    clock.set(at(6, 9).isoformat())
    with db.connect() as conn:
        conn.execute("INSERT INTO notifications (person_id, kind, title, body, url, created_at, push_sent) "
                     "VALUES (1, 'pregunta', 't', 'b', '/', ?, 1)", (db.to_db(at(6, 8, 30)),))
    assert run_tick(monkeypatch) == []
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM questions WHERE rule_id = 'P-SUENO'").fetchone()[0] == 0

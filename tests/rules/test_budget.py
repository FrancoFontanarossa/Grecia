import datetime as dt

import pytest

from app import db
from app.config import TZ
from app.rules import budget

JUAN, MARTA, LAURA, PEREIRA = 1, 2, 3, 4
DAY = dt.datetime(2026, 10, 13, 10, tzinfo=TZ)


def sent(person_id, kind, at):
    with db.connect() as conn:
        conn.execute("INSERT INTO notifications (person_id, kind, title, body, url, created_at, push_sent) "
                     "VALUES (?, ?, 't', 'b', '/', ?, 1)", (person_id, kind, db.to_db(at)))


def test_patient_one_question_and_one_requestion_per_day(seeded):
    assert budget.allow(JUAN, "pregunta", DAY)
    sent(JUAN, "pregunta", DAY)
    assert not budget.allow(JUAN, "pregunta", DAY + dt.timedelta(hours=3))
    assert budget.allow(JUAN, "repregunta", DAY)
    sent(JUAN, "repregunta", DAY)
    assert not budget.allow(JUAN, "repregunta", DAY)
    assert budget.allow(JUAN, "pregunta", DAY + dt.timedelta(days=1))   # al otro día vuelve


def test_reds_do_not_count_and_always_go(seeded):
    sent(JUAN, "rojo", DAY)
    assert budget.allow(JUAN, "pregunta", DAY)
    sent(JUAN, "pregunta", DAY)
    assert budget.allow(JUAN, "rojo", DAY)
    assert budget.allow(JUAN, "rojo", DAY.replace(hour=3))              # ni el silencio lo frena


@pytest.mark.parametrize("person", [MARTA, LAURA])
def test_family_one_amber_push_per_day(seeded, person):
    assert budget.allow(person, "ambar", DAY)
    sent(person, "ambar", DAY)
    assert not budget.allow(person, "ambar", DAY.replace(hour=20))
    assert budget.allow(person, "logro", DAY)


def test_counts_per_person(seeded):
    sent(MARTA, "ambar", DAY)
    assert budget.allow(LAURA, "ambar", DAY)


@pytest.mark.parametrize("hour,minute,ok", [(7, 59, False), (8, 0, True), (21, 59, True), (22, 0, False), (0, 30, False)])
@pytest.mark.parametrize("kind", ["pregunta", "repregunta", "ambar", "logro", "resumen"])
def test_quiet_hours(seeded, hour, minute, ok, kind):
    assert budget.allow(MARTA, kind, DAY.replace(hour=hour, minute=minute)) is ok


def test_quiet_hours_use_montevideo_time(seeded):
    utc_23 = dt.datetime(2026, 10, 13, 23, tzinfo=dt.timezone.utc)      # 20:00 en Montevideo
    assert budget.allow(JUAN, "pregunta", utc_23)

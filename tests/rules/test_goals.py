import datetime as dt

from app import db
from app.config import TZ
from app.rules import goals

DAY = dt.date(2026, 10, 14)


def walk(day, steps, hour=10):
    s = dt.datetime.combine(day, dt.time(hour), TZ)
    with db.connect() as conn:
        conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, \'steps\', ?, ?, ?, \'atajo\')',
                     (steps, db.to_db(s), db.to_db(s + dt.timedelta(hours=1))))


def red_alert(at, acked=False):
    with db.connect() as conn:
        conn.execute("INSERT INTO alerts (patient_id, lane, rule_id, text, created_at, acked_at) VALUES (1, 'rojo', 'R1', 't', ?, ?)",
                     (db.to_db(at), db.to_db(at + dt.timedelta(hours=1)) if acked else None))


def paused_reason():
    with db.connect() as conn:
        return conn.execute("SELECT paused_reason FROM goals WHERE patient_id = 1").fetchone()[0]


def test_reached_goal(seeded):
    walk(DAY, 2500)
    walk(DAY, 1560, hour=17)
    walk(DAY + dt.timedelta(days=1), 9000)                 # otro día no suma
    g = goals.status(1, DAY)
    assert (g.value, g.achieved, g.hard_day, g.notified) == (4060, True, False, False)
    assert g.date == DAY


def test_not_reached(seeded):
    walk(DAY, 3999)
    g = goals.status(1, DAY)
    assert not g.achieved and not g.hard_day


def test_episode_day_is_hard_day(seeded):
    walk(DAY, 1200)
    with db.connect() as conn:
        conn.execute("INSERT INTO episodes (patient_id, dose_time, status) VALUES (1, ?, 'abierto')",
                     (db.to_db(dt.datetime.combine(DAY, dt.time(16), TZ)),))
    g = goals.status(1, DAY)
    assert g.hard_day and not g.achieved


def test_red_pauses_the_goal_that_day_only(seeded):
    # Alcance de las 04:15: no hay "Estoy bien"; la pausa dura el día del rojo.
    walk(DAY, 5000)
    red_alert(dt.datetime.combine(DAY, dt.time(9), TZ))
    g = goals.status(1, DAY)
    assert g.hard_day and not g.achieved                    # en pausa: no se logra aunque camine
    assert paused_reason() == "rojo"
    walk(DAY + dt.timedelta(days=1), 5000)
    g = goals.status(1, DAY + dt.timedelta(days=1))
    assert g.achieved and not g.hard_day and paused_reason() is None


def test_red_after_the_day_does_not_pause_it(seeded):
    walk(DAY, 5000)
    red_alert(dt.datetime.combine(DAY + dt.timedelta(days=1), dt.time(9), TZ))
    assert goals.status(1, DAY).achieved


def test_status_is_saved_and_keeps_notified(seeded):
    walk(DAY, 4500)
    g = goals.status(1, DAY)
    with db.connect() as conn:
        conn.execute("UPDATE goal_days SET notified = 1 WHERE id = ?", (g.id,))
    walk(DAY, 100, hour=18)
    again = goals.status(1, DAY)
    assert again.id == g.id and again.value == 4600 and again.notified
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM goal_days").fetchone()[0] == 1


def test_no_goal_is_none(seeded):
    assert goals.status(5, DAY) is None                     # el paciente de prueba no tiene meta

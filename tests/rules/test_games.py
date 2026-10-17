import datetime as dt
import json

import pytest

from app import db
from app.config import TZ
from app.models import TapEvent
from app.rules import games

NOW = dt.datetime(2026, 10, 13, 17, tzinfo=TZ)


def alternating(n, every_ms, start_side="izq"):
    sides = ["izq", "der"] if start_side == "izq" else ["der", "izq"]
    return [TapEvent(t_ms=i * every_ms, side=sides[i % 2]) for i in range(n)]


def test_metrics_regular_alternating():
    m = games.metrics(alternating(91, 222))        # 90 intervalos de 0,222 s en 19,98 s
    assert m["taps_per_s"] == pytest.approx(4.5, abs=0.01)
    assert m["interval_cv"] == 0.0
    assert m["left_right_ratio"] == pytest.approx(46 / 45, abs=0.001)


def test_metrics_irregular_intervals():
    taps = [TapEvent(t_ms=t, side=s) for t, s in [(0, "izq"), (200, "der"), (600, "izq"), (800, "der")]]
    m = games.metrics(taps)
    # intervalos 0,2 / 0,4 / 0,2: promedio 0,2667, desvío 0,0943
    assert m["taps_per_s"] == pytest.approx(3 / 0.8, abs=0.01)
    assert m["interval_cv"] == pytest.approx(0.354, abs=0.001)
    assert m["left_right_ratio"] == 1.0


def test_metrics_unordered_input_and_edge_cases():
    assert games.metrics(list(reversed(alternating(5, 250))))["taps_per_s"] == 4.0
    assert games.metrics([]) == {"taps_per_s": 0.0, "interval_cv": 0.0, "left_right_ratio": 0.0}
    assert games.metrics([TapEvent(t_ms=0, side="izq")])["taps_per_s"] == 0.0
    only_left = [TapEvent(t_ms=i * 300, side="izq") for i in range(5)]
    assert games.metrics(only_left)["left_right_ratio"] == 0.0


@pytest.mark.parametrize("today,past,expected", [
    (4.5, [4.5, 4.4, 4.6], "parecido"),
    (3.8, [4.5, 4.4, 4.6], "mas_lento"),        # 3,8 < 0,85 · 4,5 = 3,825
    (3.83, [4.5, 4.4, 4.6], "parecido"),
    (2.0, [4.5, 4.5], "sin_historial"),
    (2.0, [], "sin_historial"),
])
def test_vs_history(today, past, expected):
    assert games.vs_history(today, past) == expected


def test_score_against_seed_history(seeded):                  # 8 sesiones del seed, últimas 7 → mediana 4,5
    r = games.score(alternating(73, 278), patient_id=1, taken_at=NOW)   # ~3,6 toques/s
    assert r.game == "tapping" and r.patient_id == 1 and r.taken_at == NOW
    assert r.vs_history == "mas_lento"
    assert games.score(alternating(91, 222), patient_id=1, taken_at=NOW).vs_history == "parecido"


def test_score_uses_only_the_last_7_sessions(seeded):
    with db.connect() as conn:
        for day in range(12, 15):                                # 3 sesiones lentas recientes
            conn.execute("INSERT INTO tests (patient_id, type, metrics, raw, taken_at, source) "
                         "VALUES (1, 'golpeteo', ?, '[]', ?, 'app')",
                         (json.dumps({"taps_per_s": 3.0}), db.to_db(dt.datetime(2026, 10, day, 10, tzinfo=TZ))))
    assert games.history(1, dt.datetime(2026, 10, 16, tzinfo=TZ)) == [3.0, 3.0, 3.0, 4.5, 4.8, 4.2, 4.6]


def test_score_without_history(data_dir):
    assert games.score(alternating(91, 222), patient_id=1, taken_at=NOW).vs_history == "sin_historial"

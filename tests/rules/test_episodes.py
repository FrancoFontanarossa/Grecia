import datetime as dt
from statistics import median

import pytest

from app import db
from app.api.admin import inject_drop
from app.config import TZ
from app.rules import episodes
from tests.rules import steps

TUE_13, THU_15, FRI_16, SAT_17 = (dt.date(2026, 10, d) for d in (13, 15, 16, 17))


def test_tuesday_with_deviation_uses_stratum(seeded):
    steps.load({TUE_13: 420})
    d = episodes.deviation(1, steps.at16(TUE_13))
    assert d is not None
    assert d.baseline == "estrato"
    # 20/09 a 12/10 con toma de las 16: 23 días, 16 hábiles.
    assert d.baseline_n == 16
    weekdays = [steps.usual(dt.date(2026, 9, 20) + dt.timedelta(days=k)) for k in range(23)
                if (dt.date(2026, 9, 20) + dt.timedelta(days=k)).weekday() < 5]
    assert d.median == median(weekdays)
    assert d.observed == 420
    assert d.pct_change == pytest.approx((420 - d.median) / d.median * 100, abs=0.1)
    assert d.z <= -2.5
    assert d.window == "16:00–18:00" and d.dose_time == steps.at16(TUE_13)


def test_saturday_falls_back_to_combined_base(seeded):
    steps.load({SAT_17: 300})
    d = episodes.deviation(1, steps.at16(SAT_17))
    assert d.baseline == "combinada"
    assert d.baseline_n == 27            # 20/09 a 16/10; el estrato de fin de semana tiene solo 7
    assert episodes.baseline(1, steps.at16(SAT_17)).kind == "combinada"


def test_window_without_sync_is_none(seeded):
    steps.load({TUE_13: 420}, sync=False)
    assert episodes.deviation(1, steps.at16(TUE_13)) is None
    assert episodes.observed(1, steps.at16(TUE_13)) is None


def test_sync_that_does_not_cover_the_whole_window_is_none(seeded):
    steps.load({TUE_13: 420}, sync=False)
    steps.add_sync(dt.datetime(2026, 9, 20, tzinfo=TZ), dt.datetime(2026, 10, 13, 17, 30, tzinfo=TZ))
    assert episodes.deviation(1, steps.at16(TUE_13)) is None


def test_synced_window_without_samples_is_zero_steps(seeded):
    steps.load({TUE_13: None})
    assert episodes.observed(1, steps.at16(TUE_13)) == 0
    d = episodes.deviation(1, steps.at16(TUE_13))
    assert d.observed == 0 and d.pct_change == -100.0


def test_normal_day_is_not_a_deviation(seeded):
    steps.load()
    assert episodes.deviation(1, steps.at16(TUE_13)) is None


def test_small_drop_is_not_a_deviation(seeded):
    steps.load({TUE_13: 900})            # ~30% menos: z bajo pero la caída no llega al 40%
    assert episodes.deviation(1, steps.at16(TUE_13)) is None


def test_mad_floor_keeps_z_sane(seeded):
    # Base sin variación: MAD = 0, se usa el 10% de la mediana.
    flat = {steps.START + dt.timedelta(days=k): 1000 for k in range(28)}
    steps.load({**flat, TUE_13: 500})
    d = episodes.deviation(1, steps.at16(TUE_13))
    assert d.median == 1000 and d.z == pytest.approx((500 - 1000) / (1.4826 * 100), abs=0.01)


def test_injected_and_episode_days_are_left_out_of_the_base(seeded):
    steps.load()
    inject_drop(1, steps.at16(TUE_13), 0.7)
    with db.connect() as conn:
        conn.execute("INSERT INTO episodes (patient_id, dose_time, status) VALUES (1, ?, 'abierto')",
                     (db.to_db(steps.at16(dt.date(2026, 10, 12))),))
    base = episodes.baseline(1, steps.at16(THU_15))
    # 20/09 a 14/10: 25 días, 18 hábiles, menos el 12 (episodio) y el 13 (inyectado).
    assert base.kind == "estrato" and len(base.values) == 16


def test_three_injected_drops_of_the_demo_are_detected(seeded):
    steps.load()
    for day in (TUE_13, THU_15, FRI_16):
        inject_drop(1, steps.at16(day), 0.7)
    for day in (TUE_13, THU_15, FRI_16):
        d = episodes.deviation(1, steps.at16(day))
        assert d is not None and d.pct_change == pytest.approx(-70, abs=3)


def test_not_enough_points_is_none(seeded):
    steps.load(start=dt.date(2026, 10, 6))   # solo 7 días de historia antes del 13
    assert episodes.deviation(1, steps.at16(TUE_13)) is None


def test_only_scheduled_doses_count(seeded):
    steps.load()
    # 15:00 no es hora de toma: no hay base.
    assert episodes.baseline(1, dt.datetime(2026, 10, 13, 15, tzinfo=TZ)) is None


def test_a_wearable_sync_does_not_turn_unknown_steps_into_zero(seeded):
    """La ventana de la pulsera (scope=pulsera) no cuenta para §7.3: sin sync de pasos sigue siendo None."""
    steps.load({TUE_13: None}, sync=False)
    with db.connect() as conn:
        conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples, scope) "
                     "VALUES (1, '2026-09-19T23:00:00-03:00', '2026-10-18T00:00:00-03:00', 'x', 1, 'pulsera')")
    assert episodes.observed(1, steps.at16(TUE_13)) is None
    assert episodes.deviation(1, steps.at16(TUE_13)) is None

import datetime as dt

import pytest

from app import config
from app.config import TZ
from app.rules import biometrics
from scripts import simular_pulsera as sim

SLEEP = {"sleep_minutes", "sleep_awakenings"}


def day(d):
    return dt.date(2026, 10, d) if isinstance(d, int) else d


def kinds(patient_id, d):
    return {a["kind"] for a in biometrics.anomalies(patient_id, day(d))}


def test_summary_has_every_metric_with_value_base_and_z(wearable):
    s = biometrics.daily_summary(1, day(14))
    assert s["day"] == "2026-10-14" and s["sources"] == ["simulado"]
    assert set(s["metrics"]) == set(config.WEARABLE_CORE)
    assert all(m["source"] == "simulado" for m in s["metrics"].values())
    m = s["metrics"]["sleep_awakenings"]
    assert m["value"] == sim.nightly(day(14))["sleep_awakenings"]
    assert m["baseline_n"] == 24                                # 20/09 a 13/10
    assert m["z"] is not None


def test_less_than_10_points_has_no_z(wearable):
    s = biometrics.daily_summary(1, dt.date(2026, 9, 25))
    assert all(m["z"] is None for m in s["metrics"].values())
    assert biometrics.anomalies(1, dt.date(2026, 9, 25)) == []


def test_bad_nights_are_sleep_anomalies(wearable):
    for d in range(4, 11):
        assert kinds(1, d) == SLEEP, d



@pytest.mark.parametrize("d", [1, 2, 3, 11, 12, 13, 15, 16, 17])
def test_normal_days_have_no_anomalies(wearable, d):
    assert kinds(1, d) == set()


def test_night_13_to_14_is_short(wearable):
    assert kinds(1, 14) == {"sleep_minutes"}


def test_why_in_numbers(wearable):
    a = {x["kind"]: x for x in biometrics.anomalies(1, day(5))}
    v = sim.nightly(day(5))["sleep_awakenings"]
    assert a["sleep_awakenings"]["why"] == f"Anoche te despertaste {v} veces; lo habitual son 2."
    assert a["sleep_minutes"]["why"].startswith("Anoche dormiste ") and "lo habitual son 6 h" in a["sleep_minutes"]["why"]


def test_direction_matters(wearable):
    # Una noche con muchísimo sueño no es una anomalía (lo que importa es dormir menos).
    from app.api.biometrics import ingest_wearable
    end = dt.datetime(2026, 10, 18, 7, tzinfo=TZ)
    ingest_wearable({"device": {"vendor": "t", "model": "t", "id": "t"}, "source": "simulado",
                     "window_start": (end - dt.timedelta(hours=8)).isoformat(), "window_end": end.isoformat(),
                     "samples": [{"type": "sleep_minutes", "value": 10, "unit": "h",
                                  "start": (end - dt.timedelta(hours=8)).isoformat(), "end": end.isoformat()}]})
    m = biometrics.daily_summary(1, day(18))["metrics"]["sleep_minutes"]
    assert m["value"] == 600 and m["z"] >= 2.5 and "sleep_minutes" not in kinds(1, 18)


def test_no_data_is_empty(seeded):
    assert biometrics.daily_summary(1, day(14))["metrics"] == {}
    assert biometrics.anomalies(1, day(14)) == []


def ingest(*samples, source="pulsera", end=dt.datetime(2026, 10, 14, 7, tzinfo=TZ)):
    from app.api.biometrics import ingest_wearable
    start = end - dt.timedelta(hours=8)
    ingest_wearable({"device": {"vendor": "Acme", "model": "Band", "id": "1"}, "source": source,
                     "window_start": start.isoformat(), "window_end": (end + dt.timedelta(hours=17)).isoformat(),
                     "samples": [{"type": t, "value": v, "unit": u, "start": start.isoformat(), "end": end.isoformat()}
                                 for t, v, u in samples]})


def test_only_steps_does_not_fail(seeded):
    from tests.rules import steps
    steps.load()
    s = biometrics.daily_summary(1, day(14))
    assert s["metrics"] == {} and s["sources"] == []
    assert biometrics.anomalies(1, day(14)) == [] and biometrics.describe(s) == ""


def test_core_without_optionals_does_not_fail(wearable):
    s = biometrics.daily_summary(1, day(12))
    assert set(s["metrics"]) == set(config.WEARABLE_CORE)
    text = biometrics.describe(s)
    assert text.startswith("Pulsera, 2026-10-12:") and len(text.splitlines()) == 5
    for word in ("None", "Variabilidad", "Oxigenación", "Respiración", "temblor"):
        assert word not in text
    assert all(line.endswith("· simulado") for line in text.splitlines()[1:])


def test_describe_shows_only_what_arrived_with_its_source(seeded):
    ingest(("sleep_minutes", 6.5, "h"), ("hrv_ms", 31, "ms"), ("tremor_minutes", 40, "min"))
    s = biometrics.daily_summary(1, day(14))
    assert set(s["metrics"]) == {"sleep_minutes", "hrv_ms"}               # el temblor se guarda pero no se muestra
    assert biometrics.describe(s) == ("Pulsera, 2026-10-14:\n- Sueño: 6 h 30 min · pulsera\n"
                                      "- Variabilidad cardíaca: 31 ms · pulsera")


def test_describe_marks_out_of_the_ordinary(wearable):
    text = biometrics.describe(biometrics.daily_summary(1, day(14)))
    assert "- Sueño: 3 h" in text and "(lo habitual: 6 h" in text and ", fuera de lo habitual · simulado" in text
    assert biometrics.describe(None) == ""

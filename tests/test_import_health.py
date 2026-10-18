import datetime as dt
import json

import pytest

from app import clock, db
from app.config import TZ
from data import import_health as ih

REAL = dt.datetime(2026, 10, 17, 19, 0, tzinfo=TZ)
END = dt.date(2026, 10, 17)            # sábado


def record(start, end, value, source="iPhone de Franco", type_=ih.STEP_TYPE):
    return (f'<Record type="{type_}" sourceName="{source}" unit="count" '
            f'startDate="{start}" endDate="{end}" value="{value}"/>')


def write_export(path, records):
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE HealthData [\n<!ELEMENT HealthData (Record)*>\n]>\n'
        '<HealthData locale="es_UY">\n' + "\n".join(records) + "\n</HealthData>\n"
    )
    return str(path)


@pytest.fixture
def env(data_dir, monkeypatch):
    monkeypatch.setattr(clock, "_real_now", lambda: REAL)
    return data_dir


def rows(sql):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def daily_records(first: dt.date, last: dt.date, **kw):
    """Cada día: 300 pasos de 16:30 a 16:40 y 600 de 9:50 a 10:10 (cruza la hora)."""
    out, d = [], first
    while d <= last:
        out.append(record(f"{d} 16:30:00 -0300", f"{d} 16:40:00 -0300", 300, **kw))
        out.append(record(f"{d} 09:50:00 -0300", f"{d} 10:10:00 -0300", 600, **kw))
        d += dt.timedelta(days=1)
    return out


def test_split_by_hour_is_proportional():
    s = dt.datetime(2026, 10, 1, 9, 50, tzinfo=TZ)
    assert ih.split_by_hour(s, s + dt.timedelta(minutes=20), 600) == [
        (dt.datetime(2026, 10, 1, 9, tzinfo=TZ), 300.0), (dt.datetime(2026, 10, 1, 10, tzinfo=TZ), 300.0)]


def test_import_export_shifts_by_whole_weeks(env, tmp_path):
    # Datos reales del 01/06 al 30/06/2025 (el 30, lunes, es el día de la exportación: incompleto).
    path = write_export(tmp_path / "export.xml", daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30)) + [
        record("2025-06-10 12:00:00 -0300", "2025-06-10 12:01:00 -0300", 70, type_="HKQuantityTypeIdentifierHeartRate"),
    ])
    summary = ih.run(end=END, export=path)

    # Último día completo con el mismo día de la semana que el 17/10/2026 (sábado): 28/06/2025.
    first, last = summary["source_days"]
    assert last == dt.date(2025, 6, 28) and last.weekday() == END.weekday()
    assert first == dt.date(2025, 6, 1)
    assert (END - last).days % 7 == 0

    data = rows('SELECT value, start, "end", source FROM biometrics ORDER BY start')
    assert {r["source"] for r in data} == {"importacion"}
    assert len(data) == 28 * 3                       # 9h, 10h y 16h de cada día
    assert data[0] == {"value": 300.0, "start": "2026-09-20T09:00:00-03:00",
                       "end": "2026-09-20T10:00:00-03:00", "source": "importacion"}
    assert data[-1]["start"] == "2026-10-17T16:00:00-03:00"
    assert sum(r["value"] for r in data) == 28 * 900  # el ritmo cardíaco no entra

    assert rows("SELECT window_start, window_end, received_at, n_samples FROM biometric_syncs") == [{
        # Hasta la última hora con datos (16 a 17 h del 17/10), no hasta la medianoche: después no sabemos.
        "window_start": "2026-09-20T00:00:00-03:00", "window_end": "2026-10-17T17:00:00-03:00",
        "received_at": "2026-10-17T19:00:00-03:00", "n_samples": 84}]


def test_reimport_replaces_previous_import(env, tmp_path):
    path = write_export(tmp_path / "export.xml", daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30)))
    ih.run(end=END, export=path)
    ih.run(end=END, export=path)
    assert rows("SELECT count(*) AS n, sum(value) AS total FROM biometrics") == [{"n": 84, "total": 28 * 900}]


def test_multiple_sources_require_choosing(env, tmp_path):
    recs = (daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30))
            + daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30), source="Apple Watch"))
    path = write_export(tmp_path / "export.xml", recs)
    with pytest.raises(ih.HealthImportError, match="--source"):
        ih.run(end=END, export=path)
    assert rows("SELECT count(*) AS n FROM biometrics") == [{"n": 0}]

    ih.run(end=END, export=path, source="Apple Watch")
    assert rows("SELECT sum(value) AS total FROM biometrics") == [{"total": 28 * 900}]


def test_csv_plan_b(env, tmp_path):
    path = tmp_path / "pasos.csv"
    lines = ["start,steps"]
    d = dt.date(2025, 6, 1)
    while d <= dt.date(2025, 6, 28):
        lines += [f"{d}T16:00,120", f"{d}T10:00:00-03:00,500"]
        d += dt.timedelta(days=1)
    path.write_text("\n".join(lines) + "\n")
    summary = ih.run(end=END, csv_path=str(path))
    assert summary["source_days"] == (dt.date(2025, 6, 1), dt.date(2025, 6, 28))  # en CSV el último día cuenta
    assert rows("SELECT count(*) AS n, sum(value) AS total FROM biometrics") == [{"n": 56, "total": 28 * 620}]


def test_weekday_report_compares_window_with_rest(env, tmp_path):
    path = write_export(tmp_path / "export.xml", daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30)))
    report = ih.run(end=END, export=path)["by_weekday"]
    assert list(report) == ih.DAY_NAMES
    assert report["sábado"] == {"days": 4, "window_per_day": 300.0, "window_per_hour": 150.0,
                                "rest_per_hour": 600 / 22, "window_zero_days": 0}


def test_cli_prints_report(env, tmp_path, capsys):
    path = write_export(tmp_path / "export.xml", daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30)))
    assert ih.main([path, "--end", "2026-10-17"]) == 0
    out = capsys.readouterr().out
    assert "16 a 18" in out and "sábado" in out


def test_cli_needs_exactly_one_input(env):
    with pytest.raises(SystemExit):
        ih.main(["--end", "2026-10-17"])


def test_reimport_also_clears_injected_drops(env, tmp_path):
    from app.api.admin import inject_drop
    path = write_export(tmp_path / "export.xml", daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30)))
    ih.run(end=END, export=path)
    inject_drop(1, dt.datetime(2026, 10, 13, 16, tzinfo=TZ), 0.7)
    ih.run(end=END, export=path)
    assert rows("SELECT DISTINCT source FROM biometrics") == [{"source": "importacion"}]
    assert rows("SELECT sum(value) AS total FROM biometrics") == [{"total": 28 * 900}]


def test_export_csv_does_not_touch_db_and_imports_the_same(env, tmp_path):
    path = write_export(tmp_path / "export.xml", daily_records(dt.date(2025, 6, 1), dt.date(2025, 6, 30)))
    out = tmp_path / "pasos.csv"
    assert ih.main([path, "--end", "2026-10-17", "--export-csv", str(out)]) == 0
    assert rows("SELECT count(*) AS n FROM biometrics") == [{"n": 0}]
    lines = out.read_text().splitlines()
    assert lines[0] == "start,steps" and lines[1] == "2026-09-20T09:00:00-03:00,300.0" and len(lines) == 85

    result = ih.import_csv_text(out.read_text())
    assert result["hours"] == 84
    assert rows("SELECT sum(value) AS total FROM biometrics") == [{"total": 28 * 900}]
    assert rows("SELECT window_start, window_end FROM biometric_syncs") == [
        {"window_start": "2026-09-20T00:00:00-03:00", "window_end": "2026-10-17T17:00:00-03:00"}]


def sleep_record(start, end, value):
    return (f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" '
            f'startDate="{start}" endDate="{end}" value="HKCategoryValueSleepAnalysis{value}"/>')


def wearable_export(tmp_path):
    recs = []
    d = dt.date(2025, 6, 1)
    while d <= dt.date(2025, 6, 30):
        n = d + dt.timedelta(days=1)
        recs += [sleep_record(f"{d} 23:00:00 -0300", f"{n} 02:00:00 -0300", "AsleepCore"),
                 sleep_record(f"{n} 02:00:00 -0300", f"{n} 02:10:00 -0300", "Awake"),
                 sleep_record(f"{n} 02:10:00 -0300", f"{n} 06:40:00 -0300", "AsleepDeep"),
                 sleep_record(f"{d} 22:50:00 -0300", f"{n} 06:45:00 -0300", "InBed"),
                 record(f"{n} 00:00:00 -0300", f"{n} 23:59:00 -0300", 58,
                        type_="HKQuantityTypeIdentifierRestingHeartRate"),
                 record(f"{n} 03:00:00 -0300", f"{n} 03:01:00 -0300", 14,
                        type_="HKQuantityTypeIdentifierRespiratoryRate"),
                 record(f"{n} 04:00:00 -0300", f"{n} 04:01:00 -0300", 16,
                        type_="HKQuantityTypeIdentifierRespiratoryRate"),
                 record(f"{d} 10:00:00 -0300", f"{d} 10:05:00 -0300", 0.28,
                        type_="HKQuantityTypeIdentifierWalkingDoubleSupportPercentage"),
                 record(f"{d} 11:00:00 -0300", f"{d} 11:05:00 -0300", 3.6,
                        type_="HKQuantityTypeIdentifierWalkingSpeed"),
                 record(f"{d} 12:00:00 -0300", f"{d} 12:00:00 -0300", 72,
                        type_="HKQuantityTypeIdentifierHeartRate")]          # FC suelta: no se manda
        d = n
    return write_export(tmp_path / "export.xml", recs)


def test_export_wearable_builds_ingest_requests(env, tmp_path):
    out = tmp_path / "pulsera.jsonl"
    r = ih.export_wearable(wearable_export(tmp_path), str(out), end=END)
    assert r["found"]["HKCategoryTypeIdentifierSleepAnalysis"] == 30 * 4
    assert "HKQuantityTypeIdentifierHeartRate" not in r["found"]
    first, last = r["days"]
    assert last == END and (END - r["source_days"][1]).days % 7 == 0
    bodies = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(bodies) == r["requests"] and all(b["source"] == "importacion" for b in bodies)
    night = next(b for b in bodies if b["window_start"].startswith("2026-10-1") and
                 any(s["type"] == "sleep_minutes" for s in b["samples"]))
    by_type = {s["type"]: s for s in night["samples"]}
    assert by_type["sleep_minutes"]["value"] == 450 and by_type["sleep_awakenings"]["value"] == 1
    assert by_type["resp_rate"]["value"] == 15 and by_type["heart_rate_rest"]["unit"] == "count/min"
    assert rows("SELECT count(*) AS n FROM biometrics") == [{"n": 0}]        # no toca la base


def test_exported_requests_are_accepted_by_the_real_ingest(env, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import biometrics
    from scripts import simular_pulsera
    out = tmp_path / "pulsera.jsonl"
    ih.export_wearable(wearable_export(tmp_path), str(out), end=END)
    monkeypatch.setenv("WEARABLE_TOKEN", "t")
    app = FastAPI()
    app.include_router(biometrics.router)
    bodies = [json.loads(line) for line in out.read_text().splitlines()]
    results = simular_pulsera.send(TestClient(app), "t", bodies)
    assert sum(x["stored"] for x in results) == sum(len(b["samples"]) for b in bodies)
    assert {r["source"] for r in rows("SELECT DISTINCT source FROM biometrics")} == {"importacion"}
    assert rows("SELECT value FROM biometrics WHERE kind = 'double_support' LIMIT 1") == [{"value": 28.0}]


def test_export_wearable_cli(env, tmp_path, capsys):
    out = tmp_path / "p.jsonl"
    assert ih.main([wearable_export(tmp_path), "--end", "2026-10-17", "--export-wearable", str(out)]) == 0
    assert "Registros en la exportación" in capsys.readouterr().out and out.exists()

"""Importa la historia de pasos de la exportación de Salud del iPhone (CLAUDE.md §8).

    python -m data.import_health ruta/a/export.xml --end 2026-10-17
    python -m data.import_health --csv pasos.csv --end 2026-10-17        # plan B
    python -m data.import_health export.xml --end 2026-10-17 --export-csv pasos.csv   # solo genera el CSV

--export-wearable pulsera.jsonl (con export.xml): saca lo que hay de reloj y de marcha (sueño, FC en reposo, HRV,
respiración, velocidad, asimetría, doble apoyo y estabilidad al caminar) con el mismo corrimiento por semanas
(sus propios últimos --days días con datos), un pedido por día en el formato de POST /api/biometrics/wearable
(source="importacion"). No toca la base; se manda con: python -m scripts.simular_pulsera --archivo pulsera.jsonl

--export-csv no toca la base: escribe las horas ya corridas en un CSV para subirlo a Railway con
POST /admin/import_steps (que lo importa tal cual, sin volver a correr las fechas).

Toma HKQuantityTypeIdentifierStepCount, agrega por hora (repartiendo cada muestra entre las horas
que cubre) y corre las fechas para que los últimos `--days` días completos terminen en `--end`.
El corrimiento es de semanas enteras, así cada día cae en el mismo día de la semana que el real
(la línea de base separa hábiles de fin de semana). Escribe en biometrics (source=importacion),
reemplazando lo importado antes en esa ventana (y las caídas inyectadas sobre eso: hay que volver a
correr data/seed.py), y registra la ventana completa en biometric_syncs.

CSV del plan B: encabezado `start,steps`, una fila por hora; `start` en ISO 8601 (sin zona = Montevideo).
"""
import argparse
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from xml.etree.ElementTree import iterparse

from app import clock, config, db

STEP_TYPE = "HKQuantityTypeIdentifierStepCount"
HEALTH_DATE = "%Y-%m-%d %H:%M:%S %z"
DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
WINDOW_HOURS = range(16, 18)          # ventana de la toma de las 16 (0 a 120 min)

Sample = tuple[datetime, datetime, float, str]   # start, end, pasos, fuente


class HealthImportError(Exception):
    """Error con mensaje para la persona que corre el script."""


def read_export(path: str) -> list[Sample]:
    samples: list[Sample] = []
    context = iterparse(path, events=("start", "end"))
    _, root = next(context)
    for event, elem in context:
        if event != "end" or elem.tag != "Record":
            continue
        if elem.get("type") == STEP_TYPE:
            samples.append((
                datetime.strptime(elem.get("startDate"), HEALTH_DATE).astimezone(config.TZ),
                datetime.strptime(elem.get("endDate"), HEALTH_DATE).astimezone(config.TZ),
                float(elem.get("value")),
                elem.get("sourceName", ""),
            ))
        root.clear()   # libera memoria: export.xml puede pesar cientos de MB
    return samples


def parse_csv(lines: Iterable[str]) -> list[Sample]:
    samples: list[Sample] = []
    for row in csv.DictReader(lines):
        start = datetime.fromisoformat(row["start"])
        start = start.replace(tzinfo=config.TZ) if start.tzinfo is None else start.astimezone(config.TZ)
        samples.append((start, start + timedelta(hours=1), float(row["steps"]), "csv"))
    return samples


def read_csv(path: str) -> list[Sample]:
    with open(path, newline="") as f:
        return parse_csv(f)


def split_by_hour(start: datetime, end: datetime, value: float) -> list[tuple[datetime, float]]:
    """Reparte `value` entre las horas que cubre [start, end), proporcional al tiempo."""
    hour = start.replace(minute=0, second=0, microsecond=0)
    if end <= start:
        return [(hour, value)]
    total = (end - start).total_seconds()
    parts = []
    while hour < end:
        nxt = hour + timedelta(hours=1)
        overlap = (min(end, nxt) - max(start, hour)).total_seconds()
        if overlap > 0:
            parts.append((hour, value * overlap / total))
        hour = nxt
    return parts


def source_window(samples: list[Sample], end: date, days: int, partial_last_day: bool) -> tuple[date, date]:
    """Días reales [first, last] a importar: el último día completo con el mismo día de la semana que `end`."""
    last = max(s[0] for s in samples).date()
    if partial_last_day:
        last -= timedelta(days=1)   # el día de la exportación está incompleto
    last -= timedelta(days=(last.weekday() - end.weekday()) % 7)
    return last - timedelta(days=days - 1), last


@dataclass
class Prepared:
    first: date                      # días reales importados
    last: date
    end: date                        # último día ya corrido
    hourly: dict[datetime, float]    # hora ya corrida → pasos
    window_start: datetime
    window_end: datetime


def prepare(samples: list[Sample], *, end: date, days: int, partial_last_day: bool,
            source: str | None = None) -> Prepared:
    if not samples:
        raise HealthImportError("No hay muestras de pasos en el archivo.")
    first, last = source_window(samples, end, days, partial_last_day)
    in_window = [s for s in samples if first <= s[0].date() <= last]

    sources = Counter(s[3] for s in in_window)
    if source:
        in_window = [s for s in in_window if s[3] == source]
        if not in_window:
            raise HealthImportError(f"No hay muestras de {source!r} en {first}..{last}. Fuentes: {dict(sources)}")
    elif len(sources) > 1:
        listing = "\n".join(f"  {name!r}: {n} muestras" for name, n in sources.most_common())
        raise HealthImportError("Hay varias fuentes de pasos (sumarlas cuenta doble). Elegí una con --source:\n" + listing)

    shift = timedelta(days=(end - last).days)       # múltiplo de 7
    hourly: dict[datetime, float] = defaultdict(float)
    for start, stop, value, _ in in_window:
        for hour, part in split_by_hour(start, stop, value):
            if first <= hour.date() <= last:
                hourly[hour + shift] += part
    # La sincronización llega hasta la última hora con datos, no hasta la medianoche del último día: después de
    # esa hora no sabemos (marcarla sincronizada contaba 0 pasos y daba desvíos fantasma, §7.3).
    midnight = datetime.combine(end + timedelta(days=1), datetime.min.time(), config.TZ)
    window_end = min(midnight, max(hourly) + timedelta(hours=1)) if hourly else midnight
    return Prepared(first, last, end, dict(hourly),
                    datetime.combine(first + shift, datetime.min.time(), config.TZ), window_end)


def write(p: Prepared, patient_id: int) -> None:
    """biometrics (source=importacion), reemplazando lo importado e inyectado en la ventana, y biometric_syncs."""
    db.init()
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM biometrics WHERE patient_id = ? AND source IN ('importacion', 'inyectado') AND kind = 'steps' "
            "AND start >= ? AND start < ?",
            (patient_id, db.to_db(p.window_start), db.to_db(p.window_end)),
        )
        conn.executemany(
            'INSERT INTO biometrics (patient_id, kind, value, start, "end", source) '
            "VALUES (?, 'steps', ?, ?, ?, 'importacion')",
            [(patient_id, round(v, 1), db.to_db(h), db.to_db(h + timedelta(hours=1)))
             for h, v in sorted(p.hourly.items())],
        )
        conn.execute(
            "INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
            "VALUES (?, ?, ?, ?, ?)",
            (patient_id, db.to_db(p.window_start), db.to_db(p.window_end), db.to_db(clock.now()), len(p.hourly)),
        )


def to_csv(p: Prepared) -> str:
    out = io.StringIO()
    out.write("start,steps\n")
    for h, v in sorted(p.hourly.items()):
        out.write(f"{db.to_db(h)},{round(v, 1)}\n")
    return out.getvalue()


def summary(p: Prepared) -> dict:
    return {"source_days": (p.first, p.last), "window": (p.window_start, p.window_end), "hours": len(p.hourly),
            "by_weekday": by_weekday(p.hourly, p.window_start.date(), p.end)}


def run(*, end: date, export: str | None = None, csv_path: str | None = None, days: int = 28,
        patient_id: int = 1, source: str | None = None, export_csv: str | None = None) -> dict:
    samples = read_csv(csv_path) if csv_path else read_export(export)
    p = prepare(samples, end=end, days=days, partial_last_day=not csv_path, source=source)
    if export_csv:
        with open(export_csv, "w") as f:
            f.write(to_csv(p))
    else:
        write(p, patient_id)
    return summary(p)


def import_csv_text(text: str, patient_id: int = 1) -> dict:
    """CSV de pasos por hora ya corrido (el de --export-csv): se importa tal cual, sin correr fechas."""
    samples = parse_csv(io.StringIO(text))
    if not samples:
        raise HealthImportError("El CSV no tiene filas de pasos.")
    first, last = min(s[0] for s in samples).date(), max(s[0] for s in samples).date()
    p = prepare(samples, end=last, days=(last - first).days + 1, partial_last_day=False)
    write(p, patient_id)
    return summary(p)


def by_weekday(hourly: dict[datetime, float], first: date, last: date) -> dict[str, dict]:
    """Por día de la semana: pasos de 16 a 18 contra el resto del día (por hora, para compararlos)."""
    per_day: dict[date, list[float]] = {}
    d = first
    while d <= last:
        per_day[d] = [0.0] * 24
        d += timedelta(days=1)
    for hour, value in hourly.items():
        per_day[hour.date()][hour.hour] += value

    result = {}
    for wd, name in enumerate(DAY_NAMES):
        days = [h for d, h in per_day.items() if d.weekday() == wd]
        if not days:
            continue
        window = [sum(h[i] for i in WINDOW_HOURS) for h in days]
        rest = [sum(h) - w for h, w in zip(days, window)]
        result[name] = {
            "days": len(days),
            "window_per_day": sum(window) / len(days),
            "window_per_hour": sum(window) / len(days) / len(WINDOW_HOURS),
            "rest_per_hour": sum(rest) / len(days) / (24 - len(WINDOW_HOURS)),
            "window_zero_days": sum(1 for w in window if w == 0),
        }
    return result


def print_report(summary: dict) -> None:
    first, last = summary["source_days"]
    ws, we = summary["window"]
    print(f"Importado: {first}..{last} → {ws.date()}..{(we - timedelta(days=1)).date()} "
          f"({summary['hours']} horas con pasos)")
    print("\nPasos de 16 a 18 contra el resto del día (promedios por día de la semana):")
    print(f"{'día':<10} {'días':>4} {'16-18/día':>10} {'16-18/h':>8} {'resto/h':>8} {'16-18 en 0':>11}")
    for name, r in summary["by_weekday"].items():
        print(f"{name:<10} {r['days']:>4} {r['window_per_day']:>10.0f} {r['window_per_hour']:>8.0f} "
              f"{r['rest_per_hour']:>8.0f} {r['window_zero_days']:>6}/{r['days']}")


# ── Pulsera desde Salud (--export-wearable) ──────────────────────────────────────────────────────────────
# tipo de Salud → (kind, unidad que se manda, factor). Los "%" de Salud vienen como fracción (0,28 = 28%).
WEARABLE_TYPES = {
    "HKQuantityTypeIdentifierRestingHeartRate": ("heart_rate_rest", "count/min", 1),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": ("hrv_ms", "ms", 1),
    "HKQuantityTypeIdentifierOxygenSaturation": ("spo2_pct", "%", 100),
    "HKQuantityTypeIdentifierWalkingSpeed": ("walking_speed", "km/h", 1),
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage": ("walking_asymmetry", "%", 100),
    "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage": ("double_support", "%", 100),
    "HKQuantityTypeIdentifierAppleWalkingSteadiness": ("steadiness", "%", 100),
}
RESP_TYPE = "HKQuantityTypeIdentifierRespiratoryRate"          # muchas por noche: se manda el promedio
SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"           # segmentos: se suman y se cuentan por noche
ASLEEP = {"HKCategoryValueSleepAnalysisAsleep", "HKCategoryValueSleepAnalysisAsleepUnspecified",
          "HKCategoryValueSleepAnalysisAsleepCore", "HKCategoryValueSleepAnalysisAsleepDeep",
          "HKCategoryValueSleepAnalysisAsleepREM"}
AWAKE = "HKCategoryValueSleepAnalysisAwake"
NIGHTLY_WEARABLE = {"heart_rate_rest", "hrv_ms", "spo2_pct", "resp_rate", "sleep_minutes", "sleep_awakenings"}

Raw = tuple[str, float, datetime, datetime]                    # kind, valor (en su unidad), inicio, fin


def _night(t: datetime) -> date:
    """Día en que se despierta: lo de las 18 a las 12 del día siguiente es de esa noche."""
    return (t - timedelta(hours=12)).date() + timedelta(days=1)


def read_wearable(path: str) -> tuple[list[Raw], Counter]:
    """Muestras de reloj y marcha de export.xml, y cuántos registros de cada tipo de Salud había."""
    found: Counter = Counter()
    raw: list[Raw] = []
    resp: dict[date, list[tuple[float, datetime, datetime]]] = defaultdict(list)
    sleep: dict[date, list[tuple[str, datetime, datetime]]] = defaultdict(list)
    context = iterparse(path, events=("start", "end"))
    _, root = next(context)
    for event, elem in context:
        if event != "end" or elem.tag != "Record":
            continue
        kind = elem.get("type")
        if kind in WEARABLE_TYPES or kind in (RESP_TYPE, SLEEP_TYPE):
            found[kind] += 1
            start = datetime.strptime(elem.get("startDate"), HEALTH_DATE).astimezone(config.TZ)
            end = datetime.strptime(elem.get("endDate"), HEALTH_DATE).astimezone(config.TZ)
            if kind in WEARABLE_TYPES:
                name, _, factor = WEARABLE_TYPES[kind]
                raw.append((name, float(elem.get("value")) * factor, start, end))
            elif kind == RESP_TYPE:
                resp[_night(start)].append((float(elem.get("value")), start, end))
            else:
                sleep[_night(end)].append((elem.get("value"), start, end))
        root.clear()
    for day, values in resp.items():
        raw.append(("resp_rate", sum(v for v, _, _ in values) / len(values), min(s for _, s, _ in values),
                    max(e for _, _, e in values)))
    for day, segments in sleep.items():
        asleep = [(s, e) for v, s, e in segments if v in ASLEEP]
        if not asleep:
            continue
        start, end = min(s for s, _ in asleep), max(e for _, e in asleep)
        raw.append(("sleep_minutes", sum((e - s).total_seconds() for s, e in asleep) / 60, start, end))
        raw.append(("sleep_awakenings", sum(1 for v, _, _ in segments if v == AWAKE), start, end))
    return raw, found


WEARABLE_UNITS_OUT = {name: unit for name, unit, _ in WEARABLE_TYPES.values()} | {
    "resp_rate": "count/min", "sleep_minutes": "min", "sleep_awakenings": "count"}


def _day_of(kind: str, start: datetime, end: datetime) -> date:
    return end.date() if kind in NIGHTLY_WEARABLE else start.date()


def export_wearable(export: str, out: str, *, end: date, days: int = 28) -> dict:
    """Escribe en `out` un pedido de POST /api/biometrics/wearable por día, con las fechas corridas por semanas
    enteras para que los últimos `days` días con datos de reloj terminen en `end`."""
    from app.api.biometrics import WearableError, normalize
    from app.models import WearableSample
    raw, found = read_wearable(export)
    if not raw:
        raise HealthImportError("La exportación no tiene datos de reloj ni de marcha.")
    watch = [r for r in raw if r[0] in NIGHTLY_WEARABLE] or raw
    last = max(_day_of(k, s, e) for k, _, s, e in watch) - timedelta(days=1)   # el último día está incompleto
    last -= timedelta(days=(last.weekday() - end.weekday()) % 7)
    first = last - timedelta(days=days - 1)
    shift = timedelta(days=(end - last).days)
    by_day: dict[date, list[dict]] = defaultdict(list)
    skipped = 0
    for kind, value, start, stop in raw:
        day = _day_of(kind, start, stop)
        if not first <= day <= last:
            continue
        sample = {"type": kind, "value": round(value, 3), "unit": WEARABLE_UNITS_OUT[kind],
                  "start": (start + shift).isoformat(), "end": (stop + shift).isoformat()}
        try:
            normalize(WearableSample.model_validate(sample))
        except WearableError:
            skipped += 1
            continue
        by_day[day + shift].append(sample)
    exported: Counter = Counter()
    with open(out, "w") as f:
        for day in sorted(by_day):
            samples = by_day[day]
            exported.update(s["type"] for s in samples)
            ws = min(datetime.fromisoformat(s["start"]) for s in samples)
            we = max(datetime.fromisoformat(s["end"]) for s in samples)
            f.write(json.dumps({"device": {"vendor": "Apple", "model": "Salud (exportación)", "id": "export.xml"},
                                "source": "importacion", "window_start": ws.isoformat(),
                                "window_end": max(we, ws + timedelta(minutes=1)).isoformat(),
                                "samples": samples}, ensure_ascii=False) + "\n")
    return {"found": dict(found), "exported": dict(exported), "skipped": skipped, "requests": len(by_day),
            "source_days": (first, last), "days": (first + shift, end)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa pasos de la exportación de Salud.")
    parser.add_argument("export", nargs="?", help="ruta a export.xml")
    parser.add_argument("--csv", dest="csv_path", help="plan B: CSV con start,steps por hora")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="último día, AAAA-MM-DD")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--patient-id", type=int, default=1)
    parser.add_argument("--source", help="sourceName a usar si hay varias fuentes")
    parser.add_argument("--export-csv", help="no escribe en la base: genera este CSV para POST /admin/import_steps")
    parser.add_argument("--export-wearable", help="no escribe en la base: genera este JSONL para /api/biometrics/wearable")
    args = parser.parse_args(argv)
    if args.export_wearable:
        if not args.export:
            parser.error("--export-wearable necesita export.xml")
        try:
            r = export_wearable(args.export, args.export_wearable, end=args.end, days=args.days)
        except HealthImportError as e:
            print(e, file=sys.stderr)
            return 1
        (f0, l0), (f1, l1) = r["source_days"], r["days"]
        print(f"Registros en la exportación: {r['found']}")
        skipped = f", {r['skipped']} descartadas por inválidas" if r["skipped"] else ""
        print(f"Pulsera: {f0}..{l0} → {f1}..{l1}, {r['requests']} pedidos, muestras {r['exported']}{skipped}")
        print(f"\nJSONL escrito en {args.export_wearable} (la base no se tocó). Para mandarlo:\n"
              f"  python -m scripts.simular_pulsera --archivo {args.export_wearable} --url …")
        return 0
    if bool(args.export) == bool(args.csv_path):
        parser.error("pasá export.xml o --csv (uno de los dos)")
    try:
        result = run(end=args.end, export=args.export, csv_path=args.csv_path, days=args.days,
                     patient_id=args.patient_id, source=args.source, export_csv=args.export_csv)
    except HealthImportError as e:
        print(e, file=sys.stderr)
        return 1
    print_report(result)
    if args.export_csv:
        print(f"\nCSV escrito en {args.export_csv} (la base no se tocó).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

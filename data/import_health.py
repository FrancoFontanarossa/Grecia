"""Importa la historia de pasos de la exportación de Salud del iPhone (CLAUDE.md §8).

    python -m data.import_health ruta/a/export.xml --end 2026-10-17
    python -m data.import_health --csv pasos.csv --end 2026-10-17        # plan B

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
import sys
from collections import Counter, defaultdict
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


def read_csv(path: str) -> list[Sample]:
    samples: list[Sample] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            start = datetime.fromisoformat(row["start"])
            start = start.replace(tzinfo=config.TZ) if start.tzinfo is None else start.astimezone(config.TZ)
            samples.append((start, start + timedelta(hours=1), float(row["steps"]), "csv"))
    return samples


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


def run(*, end: date, export: str | None = None, csv_path: str | None = None, days: int = 28,
        patient_id: int = 1, source: str | None = None) -> dict:
    samples = read_csv(csv_path) if csv_path else read_export(export)
    if not samples:
        raise HealthImportError("No hay muestras de pasos en el archivo.")
    first, last = source_window(samples, end, days, partial_last_day=not csv_path)
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

    window_start = datetime.combine(first + shift, datetime.min.time(), config.TZ)
    window_end = datetime.combine(end + timedelta(days=1), datetime.min.time(), config.TZ)
    db.init()
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM biometrics WHERE patient_id = ? AND source IN ('importacion', 'inyectado') AND kind = 'steps' "
            "AND start >= ? AND start < ?",
            (patient_id, db.to_db(window_start), db.to_db(window_end)),
        )
        conn.executemany(
            'INSERT INTO biometrics (patient_id, kind, value, start, "end", source) '
            "VALUES (?, 'steps', ?, ?, ?, 'importacion')",
            [(patient_id, round(v, 1), db.to_db(h), db.to_db(h + timedelta(hours=1)))
             for h, v in sorted(hourly.items())],
        )
        conn.execute(
            "INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
            "VALUES (?, ?, ?, ?, ?)",
            (patient_id, db.to_db(window_start), db.to_db(window_end), db.to_db(clock.now()), len(hourly)),
        )
    return {"source_days": (first, last), "window": (window_start, window_end), "hours": len(hourly),
            "by_weekday": by_weekday(hourly, first + shift, end)}


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa pasos de la exportación de Salud.")
    parser.add_argument("export", nargs="?", help="ruta a export.xml")
    parser.add_argument("--csv", dest="csv_path", help="plan B: CSV con start,steps por hora")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="último día, AAAA-MM-DD")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--patient-id", type=int, default=1)
    parser.add_argument("--source", help="sourceName a usar si hay varias fuentes")
    args = parser.parse_args(argv)
    if bool(args.export) == bool(args.csv_path):
        parser.error("pasá export.xml o --csv (uno de los dos)")
    try:
        summary = run(end=args.end, export=args.export, csv_path=args.csv_path, days=args.days,
                      patient_id=args.patient_id, source=args.source)
    except HealthImportError as e:
        print(e, file=sys.stderr)
        return 1
    print_report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

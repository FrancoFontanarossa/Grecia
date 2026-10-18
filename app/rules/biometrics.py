# Resumen diario de la pulsera (simulada, CLAUDE.md §8) contra la propia base de Juan. Mismo método que el
# desvío (§7.3): mediana de los 28 días previos, z = (x − mediana) / (1,4826 · MAD) con MAD mínimo (10% de la
# mediana; 1% en SpO2, que se mueve poco), y sin z con menos de 10 puntos. Anomalía: |z| ≥ 2,5 en la dirección
# que importa. El "por qué" lo arma el código, con cifras.
from datetime import date, datetime, time, timedelta
from statistics import mean, median

from app import config, db
from app.config import TZ

# when: "noche" = del día en que se despierta (la muestra termina ese día); "dia" = del día en que empieza.
# agg: cómo se junta un día con varias muestras. bad: qué dirección es la que importa.
METRICS = {
    "sleep_minutes":      {"label": "minutos de sueño", "when": "noche", "agg": "sum", "bad": "low"},
    "sleep_awakenings":   {"label": "despertares", "when": "noche", "agg": "sum", "bad": "high"},
    "heart_rate_rest":    {"label": "pulso en reposo", "when": "noche", "agg": "mean", "bad": "high"},
    "hrv_ms":             {"label": "variabilidad cardíaca (ms)", "when": "noche", "agg": "mean", "bad": "low"},
    "spo2_pct":           {"label": "oxigenación (%)", "when": "noche", "agg": "mean", "bad": "low", "mad_floor": 0.01},
    "resp_rate":          {"label": "respiraciones por minuto", "when": "noche", "agg": "mean", "bad": "high"},
    "active_minutes":     {"label": "minutos activos", "when": "dia", "agg": "sum", "bad": "low"},
    "tremor_minutes":     {"label": "minutos de temblor", "when": "dia", "agg": "sum", "bad": "high"},
    "dyskinesia_minutes": {"label": "minutos de movimientos involuntarios", "when": "dia", "agg": "sum", "bad": "high"},
}
Z_THRESHOLD = abs(config.DEVIATION_Z_MAX)


def fmt_int(n: float) -> str:          # igual que rules.triggers.fmt_int (triggers importa este módulo)
    return f"{round(n):,}".replace(",", ".")


def _hours(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _why(kind: str, value: float, med: float) -> str:
    v, m = fmt_int(value), fmt_int(med)
    return {
        "sleep_awakenings": f"Anoche te despertaste {v} veces; lo habitual son {m}.",
        "sleep_minutes": f"Anoche dormiste {_hours(value)}; lo habitual son {_hours(med)}.",
        "heart_rate_rest": f"Anoche tu pulso en reposo fue de {v} por minuto; lo habitual es {m}.",
        "hrv_ms": f"Anoche tu variabilidad cardíaca fue de {v} ms; lo habitual es {m}.",
        "spo2_pct": f"Anoche tu oxigenación fue de {v}%; lo habitual es {m}%.",
        "resp_rate": f"Anoche respiraste {v} veces por minuto; lo habitual son {m}.",
        "active_minutes": f"Ese día estuviste activo {v} minutos; lo habitual son {m}.",
        "tremor_minutes": f"Ese día la pulsera midió {v} minutos de temblor; lo habitual son {m}.",
        "dyskinesia_minutes": f"Ese día la pulsera midió {v} minutos de movimientos involuntarios; lo habitual son {m}.",
    }[kind]


def _by_day(patient_id: int, first: date, last: date) -> tuple[dict[str, dict[date, float]], set[str]]:
    """Valor de cada métrica por día entre first y last (los dos incluidos), y las fuentes."""
    lo = db.to_db(datetime.combine(first - timedelta(days=1), time(0), TZ))
    hi = db.to_db(datetime.combine(last + timedelta(days=2), time(0), TZ))
    kinds = list(METRICS)
    with db.connect() as conn:
        rows = conn.execute(
            f'SELECT kind, value, start, "end", source FROM biometrics WHERE patient_id = ? '
            f"AND kind IN ({','.join('?' * len(kinds))}) AND start >= ? AND start < ?", (patient_id, *kinds, lo, hi)
        ).fetchall()
    raw: dict[str, dict[date, list[float]]] = {k: {} for k in kinds}
    sources = set()
    for r in rows:
        meta = METRICS[r["kind"]]
        stamp = db.from_db(r["end"] if meta["when"] == "noche" else r["start"])
        if meta["when"] == "noche" and stamp.time() == time(0):
            stamp -= timedelta(seconds=1)          # una noche que termina justo a las 00:00 es del día anterior
        d = stamp.date()
        if first <= d <= last:
            raw[r["kind"]].setdefault(d, []).append(r["value"])
            sources.add(r["source"])
    out = {k: {d: (sum(vs) if METRICS[k]["agg"] == "sum" else mean(vs)) for d, vs in days.items()}
           for k, days in raw.items()}
    return out, sources


def _z(value: float, base: list[float], floor: float) -> float | None:
    if len(base) < config.DEVIATION_MIN_POINTS:
        return None
    med = median(base)
    mad = max(median(abs(v - med) for v in base), floor * med)
    if mad <= 0:
        return None
    return round((value - med) / (config.DEVIATION_MAD_SCALE * mad), 2)


def daily_summary(patient_id: int, day: date) -> dict:
    """{day, sources, metrics: {kind: {label, value, baseline_median, baseline_n, z}}} con las métricas que tienen
    dato ese día. Base: los 28 días previos con dato; con menos de 10, z = None."""
    first = day - timedelta(days=config.DEVIATION_BASELINE_DAYS)
    values, sources = _by_day(patient_id, first, day)
    metrics = {}
    for kind, meta in METRICS.items():
        if day not in values[kind]:
            continue
        base = [v for d, v in values[kind].items() if d < day]
        metrics[kind] = {
            "label": meta["label"],
            "value": round(values[kind][day], 1),
            "baseline_median": round(median(base), 1) if base else None,
            "baseline_n": len(base),
            "z": _z(values[kind][day], base, meta.get("mad_floor", config.DEVIATION_MAD_FLOOR)),
        }
    return {"day": day.isoformat(), "sources": sorted(sources), "metrics": metrics}


def anomalies(patient_id: int, day: date) -> list[dict]:
    """Métricas de ese día fuera de lo normal (|z| ≥ 2,5 en la dirección que importa), con su "por qué"."""
    out = []
    for kind, m in daily_summary(patient_id, day)["metrics"].items():
        z, bad = m["z"], METRICS[kind]["bad"]
        if z is None or not ((bad == "high" and z >= Z_THRESHOLD) or (bad == "low" and z <= -Z_THRESHOLD)):
            continue
        out.append({"kind": kind, "label": m["label"], "value": m["value"], "baseline_median": m["baseline_median"],
                    "baseline_n": m["baseline_n"], "z": z, "direction": bad,
                    "why": _why(kind, m["value"], m["baseline_median"])})
    return out

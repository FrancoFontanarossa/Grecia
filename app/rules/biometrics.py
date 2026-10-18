# Resumen diario de la pulsera (CLAUDE.md §8) contra la propia base de Juan. Funciona con cualquier subconjunto:
# solo aparecen las métricas que llegaron ese día, cada una con su source. Temblor y discinesia no se resumen. Mismo método que el
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
    "walking_speed":      {"label": "velocidad al caminar (m/s)", "when": "dia", "agg": "mean", "bad": "low"},
    "walking_asymmetry":  {"label": "asimetría al caminar (%)", "when": "dia", "agg": "mean", "bad": "high"},
    "double_support":     {"label": "doble apoyo al caminar (%)", "when": "dia", "agg": "mean", "bad": "high"},
    "steadiness":         {"label": "estabilidad al caminar (%)", "when": "dia", "agg": "mean", "bad": "low"},
}
assert not set(METRICS) & set(config.WEARABLE_NOT_SHOWN)
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
        "walking_speed": f"Ese día caminaste a {_fmt(kind, value)}; lo habitual es {_fmt(kind, med)}.",
        "walking_asymmetry": f"Ese día la asimetría al caminar fue de {v}%; lo habitual es {m}%.",
        "double_support": f"Ese día el doble apoyo al caminar fue de {v}%; lo habitual es {m}%.",
        "steadiness": f"Ese día la estabilidad al caminar fue de {v}%; lo habitual es {m}%.",
    }[kind]


def _by_day(patient_id: int, first: date, last: date) -> tuple[dict[str, dict[date, float]], dict]:
    """Valor de cada métrica por día entre first y last (los dos incluidos), y las fuentes de cada (métrica, día)."""
    lo = db.to_db(datetime.combine(first - timedelta(days=1), time(0), TZ))
    hi = db.to_db(datetime.combine(last + timedelta(days=2), time(0), TZ))
    kinds = list(METRICS)
    with db.connect() as conn:
        rows = conn.execute(
            f'SELECT kind, value, start, "end", source FROM biometrics WHERE patient_id = ? '
            f"AND kind IN ({','.join('?' * len(kinds))}) AND start >= ? AND start < ?", (patient_id, *kinds, lo, hi)
        ).fetchall()
    raw: dict[str, dict[date, list[float]]] = {k: {} for k in kinds}
    sources: dict[tuple[str, date], set[str]] = {}
    for r in rows:
        meta = METRICS[r["kind"]]
        stamp = db.from_db(r["end"] if meta["when"] == "noche" else r["start"])
        if meta["when"] == "noche" and stamp.time() == time(0):
            stamp -= timedelta(seconds=1)          # una noche que termina justo a las 00:00 es del día anterior
        d = stamp.date()
        if first <= d <= last:
            raw[r["kind"]].setdefault(d, []).append(r["value"])
            sources.setdefault((r["kind"], d), set()).add(r["source"])
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
    """{day, sources, metrics: {kind: {label, value, source, baseline_median, baseline_n, z}}} con las métricas que
    tienen dato ese día (las que no llegaron no aparecen). Base: los 28 días previos con dato; con menos de 10,
    z = None; sin ningún día previo, baseline_median = None."""
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
            "source": ", ".join(sorted(sources[(kind, day)])),
            "baseline_median": round(median(base), 1) if base else None,
            "baseline_n": len(base),
            "z": _z(values[kind][day], base, meta.get("mad_floor", config.DEVIATION_MAD_FLOOR)),
        }
    used = sorted({s for (k, d), ss in sources.items() if d == day and k in metrics for s in ss})
    return {"day": day.isoformat(), "sources": used, "metrics": metrics}


def _fmt(kind: str, value: float) -> str:
    if kind == "sleep_minutes":
        return _hours(value)
    if kind == "sleep_awakenings":
        return f"{fmt_int(value)} {'vez' if round(value) == 1 else 'veces'}"
    if kind in ("heart_rate_rest", "resp_rate"):
        return f"{fmt_int(value)} por minuto"
    if kind == "active_minutes":
        return f"{fmt_int(value)} min"
    if kind == "hrv_ms":
        return f"{fmt_int(value)} ms"
    if kind == "walking_speed":
        return f"{value:.1f} m/s".replace(".", ",")
    return f"{fmt_int(value)}%"


_TITLES = {"sleep_minutes": "Sueño", "sleep_awakenings": "Despertares", "heart_rate_rest": "Pulso en reposo",
           "hrv_ms": "Variabilidad cardíaca", "spo2_pct": "Oxigenación", "resp_rate": "Respiración",
           "active_minutes": "Minutos activos", "walking_speed": "Velocidad al caminar",
           "walking_asymmetry": "Asimetría al caminar", "double_support": "Doble apoyo al caminar",
           "steadiness": "Estabilidad al caminar"}


def describe(summary: dict | None) -> str:
    """Texto del biometric_summary para el contexto de explain, ask e informe: una línea por métrica presente,
    con lo habitual solo si hay base, "fuera de lo habitual" si es una anomalía, y su source. "" si no hay nada."""
    if not summary or not summary.get("metrics"):
        return ""
    lines = []
    for kind, m in summary["metrics"].items():
        line = f"- {_TITLES[kind]}: {_fmt(kind, m['value'])}"
        if m.get("baseline_median") is not None:
            line += f" (lo habitual: {_fmt(kind, m['baseline_median'])})"
        z, bad = m.get("z"), METRICS[kind]["bad"]
        if z is not None and ((bad == "high" and z >= Z_THRESHOLD) or (bad == "low" and z <= -Z_THRESHOLD)):
            line += ", fuera de lo habitual"
        lines.append(f"{line} · {m['source']}")
    return f"Pulsera, {summary['day']}:\n" + "\n".join(lines)


def anomalies(patient_id: int, day: date) -> list[dict]:
    """Métricas de ese día fuera de lo normal (|z| ≥ 2,5 en la dirección que importa), con su "por qué"."""
    out = []
    for kind, m in daily_summary(patient_id, day)["metrics"].items():
        z, bad = m["z"], METRICS[kind]["bad"]
        if z is None or not ((bad == "high" and z >= Z_THRESHOLD) or (bad == "low" and z <= -Z_THRESHOLD)):
            continue
        out.append({"kind": kind, "label": m["label"], "value": m["value"], "source": m["source"],
                    "baseline_median": m["baseline_median"],
                    "baseline_n": m["baseline_n"], "z": z, "direction": bad,
                    "why": _why(kind, m["value"], m["baseline_median"])})
    return out

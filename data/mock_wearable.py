"""Pulsera simulada de Juan (CLAUDE.md §8, "Pulsera (simulada)"): 28 días, del 20/09 al 17/10/2026.

    python -m data.mock_wearable          # o POST /admin/seed_wearable

Determinístico (mismos valores en cada corrida) y rotulado source="simulado". Idempotente: reemplaza lo
simulado antes y registra la ventana en biometric_syncs con scope="pulsera" (no cuenta como sync de pasos).

Coherente con data/escenario/juan.yaml:
  - 20/09–03/10 y 11/10–17/10: valores base normales.
  - Noches que terminan el 04/10 al 10/10 (las del habla y las patadas dormido): más despertares y menos sueño.
  - 13, 15 y 16/10: más temblor de 16 a 18 h (las tardes de la caída de pasos).
  - La noche del 16 al 17 es NORMAL: P-SUENO no puede gastar la pregunta del sábado.

Las métricas de una noche (sueño, despertares, FC en reposo, HRV, SpO2, respiración) van de 23:00 a 07:00 y son
del día en que se despierta; los minutos activos, del día; temblor y discinesia, por hora.
"""
import random
from datetime import date, datetime, time, timedelta

from app import clock, config, db

PATIENT_ID = 1
START, END = date(2026, 9, 20), date(2026, 10, 17)
BAD_NIGHTS = (date(2026, 10, 4), date(2026, 10, 10))          # mañanas después de una noche mala
TREMOR_DAYS = {date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 16)}
TREMOR_HOURS = (16, 17)                                       # 16 a 18 h, después de la toma de las 16
DOSE_HOURS = (8, 12, 16, 20)

NIGHTLY = ("sleep_minutes", "sleep_awakenings", "heart_rate_rest", "hrv_ms", "spo2_pct", "resp_rate")
DAILY = ("active_minutes",)
HOURLY = ("tremor_minutes", "dyskinesia_minutes")
KINDS = NIGHTLY + DAILY + HOURLY
# Despertares de una noche normal: mediana 2 y MAD 1 (una noche de 3 es normal; una de 6 no).
AWAKENINGS = [2, 1, 3, 2, 3, 1, 2, 3, 1, 2]


def _rng(*key) -> random.Random:
    return random.Random("|".join(map(str, key)))


def _at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), config.TZ)


def is_bad_night(day: date) -> bool:
    return BAD_NIGHTS[0] <= day <= BAD_NIGHTS[1]


def nightly(day: date) -> dict[str, float]:
    """Valores de la noche que termina la mañana de `day`."""
    r = _rng("noche", day)
    i = (day - START).days
    bad = is_bad_night(day)
    return {
        "sleep_minutes": 235 + r.randint(-10, 20) if bad else 395 + r.randint(-25, 25),
        "sleep_awakenings": r.choice([6, 7]) if bad else AWAKENINGS[i % len(AWAKENINGS)],
        "heart_rate_rest": 63 + r.randint(-2, 2),
        "hrv_ms": 28 + r.randint(-3, 3),
        "spo2_pct": r.choice([95, 96, 96, 97]),
        "resp_rate": 15 + r.choice([-1, 0, 0, 1]),
    }


def hourly(day: date, hour: int) -> dict[str, float]:
    r = _rng("hora", day, hour)
    awake = 7 <= hour <= 22
    tremor = (24 + r.randint(0, 8)) if day in TREMOR_DAYS and hour in TREMOR_HOURS else \
             (2 + r.randint(0, 3)) if awake else r.choice([0, 0, 1])
    dyskinesia = r.randint(2, 5) if hour - 1 in DOSE_HOURS else (r.choice([0, 0, 1]) if awake else 0)
    return {"tremor_minutes": tremor, "dyskinesia_minutes": dyskinesia}


def samples() -> list[tuple[str, float, datetime, datetime]]:
    """(kind, valor, inicio, fin) de los 28 días."""
    out = []
    day = START
    while day <= END:
        night_start, night_end = _at(day - timedelta(days=1), 23), _at(day, 7)
        out += [(k, v, night_start, night_end) for k, v in nightly(day).items()]
        out.append(("active_minutes", 50 + _rng("dia", day).randint(-12, 12), _at(day, 0), _at(day + timedelta(days=1), 0)))
        for hour in range(24):
            out += [(k, v, _at(day, hour), _at(day, hour) + timedelta(hours=1)) for k, v in hourly(day, hour).items()]
        day += timedelta(days=1)
    return out


def window() -> tuple[datetime, datetime]:
    return _at(START - timedelta(days=1), 23), _at(END + timedelta(days=1), 0)


def run(patient_id: int = PATIENT_ID) -> dict:
    db.init()
    rows = samples()
    ws, we = window()
    with db.connect() as conn:
        conn.execute("DELETE FROM biometrics WHERE patient_id = ? AND source = 'simulado'", (patient_id,))
        conn.execute("DELETE FROM biometric_syncs WHERE patient_id = ? AND scope = ?", (patient_id, db.SYNC_SCOPE_WEARABLE))
        conn.executemany('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) '
                         "VALUES (?, ?, ?, ?, ?, 'simulado')",
                         [(patient_id, k, v, db.to_db(s), db.to_db(e)) for k, v, s, e in rows])
        conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples, scope) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (patient_id, db.to_db(ws), db.to_db(we), db.to_db(clock.now()), len(rows), db.SYNC_SCOPE_WEARABLE))
    by_kind = {k: sum(1 for r in rows if r[0] == k) for k in KINDS}
    return {"samples": len(rows), "by_kind": by_kind, "window_start": ws.isoformat(), "window_end": we.isoformat()}


if __name__ == "__main__":
    result = run()
    print(f"Pulsera simulada: {result['samples']} muestras ({result['window_start']} → {result['window_end']})")
    for kind, n in result["by_kind"].items():
        print(f"  {kind}: {n}")

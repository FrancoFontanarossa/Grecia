"""Simulador de la pulsera de Juan: genera 28 días (20/09–17/10/2026) y los MANDA a POST /api/biometrics/wearable,
un día por pedido, como lo haría un dispositivo de verdad. No escribe en la base: la ingesta es la real.

    .venv/bin/python -m scripts.simular_pulsera                                   # contra http://localhost:8000
    .venv/bin/python -m scripts.simular_pulsera --url https://… --token "$WEARABLE_TOKEN"
    .venv/bin/python -m scripts.simular_pulsera --archivo pulsera.jsonl            # manda pedidos ya armados
                                                                                  # (import_health --export-wearable)

El token sale de --token, o de WEARABLE_TOKEN / ATAJO_TOKEN (también del .env). Determinístico y rotulado
source="simulado" (device.vendor="simulador"); reenviarlo no duplica nada.

Coherente con data/escenario/juan.yaml (cada noche es del día en que se despierta):
  - Base normal. Noches que terminan del 04/10 al 10/10 (las del habla y las patadas dormido): 6–7 despertares
    y 3 h 30–3 h 50 de sueño.
  - Noche del 13 al 14: mala ("se levantó cuatro veces", cuenta Marta el 14): 4 despertares y poco sueño.
  - Noches del 12 al 13, 15 al 16 y 16 al 17: normales (esos días Juan necesita su pregunta de la tarde).
  - 13, 15 y 16/10: más temblor de 16 a 18 h (las tardes de la caída de pasos).
"""
import argparse
import json
import os
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Montevideo")
PATH = "/api/biometrics/wearable"
DEVICE = {"vendor": "simulador", "model": "pulsera-juan", "id": "sim-001"}

START, END = date(2026, 9, 20), date(2026, 10, 17)
BAD_WEEK = (date(2026, 10, 4), date(2026, 10, 10))           # mañanas después de una noche mala
SHORT_NIGHT = date(2026, 10, 14)                             # la noche del 13 al 14
TREMOR_DAYS = {date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 16)}
TREMOR_HOURS = (16, 17)                                      # 16 a 18 h, después de la toma de las 16
DOSE_HOURS = (8, 12, 16, 20)
# Despertares de una noche normal: mediana 2 y MAD 1 (una noche de 3 es normal; una de 6 no).
AWAKENINGS = [2, 1, 3, 2, 3, 1, 2, 3, 1, 2]
UNITS = {"sleep_minutes": "min", "sleep_awakenings": "count", "heart_rate_rest": "bpm", "hrv_ms": "ms",
         "spo2_pct": "%", "resp_rate": "count/min", "active_minutes": "min", "tremor_minutes": "min",
         "dyskinesia_minutes": "min"}


def _rng(*key) -> random.Random:
    return random.Random("|".join(map(str, key)))


def _at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), TZ)


def is_bad_night(day: date) -> bool:
    return BAD_WEEK[0] <= day <= BAD_WEEK[1]


def nightly(day: date) -> dict[str, float]:
    """Valores de la noche que termina la mañana de `day`."""
    r = _rng("noche", day)
    i = (day - START).days
    if is_bad_night(day):
        sleep, awakenings = 210 + r.randint(0, 20), r.choice([6, 7])
    elif day == SHORT_NIGHT:
        sleep, awakenings = 190 + r.randint(0, 15), 4
    else:
        sleep, awakenings = 395 + r.randint(-25, 25), AWAKENINGS[i % len(AWAKENINGS)]
    return {
        "sleep_minutes": sleep,
        "sleep_awakenings": awakenings,
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


def _sample(kind: str, value: float, start: datetime, end: datetime) -> dict:
    return {"type": kind, "value": value, "unit": UNITS[kind], "start": start.isoformat(), "end": end.isoformat()}


def day_payload(day: date) -> dict:
    """El pedido de un día: la noche que terminó esa mañana, los minutos activos del día y cada hora."""
    night_start, night_end = _at(day - timedelta(days=1), 23), _at(day, 7)
    samples = [_sample(k, v, night_start, night_end) for k, v in nightly(day).items()]
    samples.append(_sample("active_minutes", 50 + _rng("dia", day).randint(-12, 12), _at(day, 0),
                           _at(day + timedelta(days=1), 0)))
    for hour in range(24):
        start = _at(day, hour)
        samples += [_sample(k, v, start, start + timedelta(hours=1)) for k, v in hourly(day, hour).items()]
    return {"device": DEVICE, "source": "simulado", "window_start": night_start.isoformat(),
            "window_end": _at(day + timedelta(days=1), 0).isoformat(), "samples": samples}


def payloads(first: date = START, last: date = END) -> list[dict]:
    return [day_payload(first + timedelta(days=k)) for k in range((last - first).days + 1)]


def send(http, token: str, bodies: list[dict]) -> list[dict]:
    """Manda cada pedido. `http` es un httpx.Client (o el TestClient de FastAPI). Corta en el primer error."""
    results = []
    for body in bodies:
        r = http.post(PATH, json=body, headers={"X-Device-Token": token})
        if r.status_code != 200:
            raise RuntimeError(f"{body['window_start'][:10]}: HTTP {r.status_code} {r.text}")
        results.append(r.json())
    return results


def _token(arg: str | None) -> str | None:
    if arg:
        return arg
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    return os.environ.get("WEARABLE_TOKEN") or os.environ.get("ATAJO_TOKEN")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulador de la pulsera de Juan (manda por HTTP).")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", help="X-Device-Token (si no, WEARABLE_TOKEN o ATAJO_TOKEN)")
    parser.add_argument("--desde", type=date.fromisoformat, default=START)
    parser.add_argument("--hasta", type=date.fromisoformat, default=END)
    parser.add_argument("--archivo", help="JSONL con pedidos ya armados (uno por línea) en vez de simular")
    args = parser.parse_args(argv)
    token = _token(args.token)
    if not token:
        print("Falta el token: --token o WEARABLE_TOKEN/ATAJO_TOKEN en el entorno o el .env", file=sys.stderr)
        return 1
    if args.archivo:
        bodies = [json.loads(line) for line in Path(args.archivo).read_text().splitlines() if line.strip()]
    else:
        bodies = payloads(args.desde, args.hasta)
    with httpx.Client(base_url=args.url, timeout=30) as http:
        try:
            results = send(http, token, bodies)
        except (RuntimeError, httpx.HTTPError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    stored = sum(r["stored"] for r in results)
    print(f"{len(results)} pedidos a {args.url}{PATH}: {sum(r['received'] for r in results)} muestras, "
          f"{stored} nuevas, {sum(r['duplicates'] for r in results)} repetidas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

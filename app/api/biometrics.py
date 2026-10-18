# POST /api/biometrics/atajo: pasos del Atajo de iOS. POST /api/biometrics/wearable: datos de una pulsera
# (CLAUDE.md §8 y §11). La ingesta es real; el dispositivo puede ser un simulador (source="simulado").
import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, Header, HTTPException
from pydantic import ValidationError

from app import clock, config, db
from app.models import AtajoPayload, WearablePayload

router = APIRouter()


def _check_token(token: str | None) -> None:
    expected = os.environ.get("ATAJO_TOKEN")
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Token del Atajo inválido")


@router.post("/api/biometrics/atajo")
def atajo(payload: AtajoPayload, x_atajo_token: str | None = Header(default=None)):
    _check_token(x_atajo_token)
    # En DEMO_MODE el iPhone manda horas reales: se corren al reloj de la demo.
    shift = clock.offset() if os.environ.get("DEMO_MODE") == "1" else timedelta(0)
    patient_id = config.ATAJO_PATIENT_ID
    with db.connect() as conn:
        conn.executemany(
            'INSERT OR IGNORE INTO biometrics (patient_id, kind, value, start, "end", source) '
            "VALUES (?, ?, ?, ?, ?, 'atajo')",
            [(patient_id, s.kind, s.value, db.to_db(s.start + shift), db.to_db(s.end + shift))
             for s in payload.samples],
        )
        conn.execute(
            "INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
            "VALUES (?, ?, ?, ?, ?)",
            (patient_id, db.to_db(payload.window_start + shift), db.to_db(payload.window_end + shift),
             db.to_db(clock.now()), len(payload.samples)),
        )
    return {"received": len(payload.samples)}


# ── Pulsera ─────────────────────────────────────────────────────────────────────────────────────────────
MINUTES = {"min": 1, "h": 60, "s": 1 / 60}
PERCENT = {"%": 1}
# Por tipo: unidad → factor a la unidad canónica (la primera), y el rango válido ya normalizado.
WEARABLE_UNITS: dict[str, tuple[dict[str, float], float, float]] = {
    "sleep_minutes": (MINUTES, 0, 1440),
    "sleep_awakenings": ({"count": 1}, 0, 100),
    "heart_rate_rest": ({"count/min": 1, "bpm": 1}, 20, 250),
    "hrv_ms": ({"ms": 1, "s": 1000}, 0, 500),
    "spo2_pct": (PERCENT, 50, 100),
    "resp_rate": ({"count/min": 1, "rpm": 1}, 3, 60),
    "active_minutes": (MINUTES, 0, 1440),
    "tremor_minutes": (MINUTES, 0, 1440),
    "dyskinesia_minutes": (MINUTES, 0, 1440),
    "walking_speed": ({"m/s": 1, "km/h": 1 / 3.6, "km/hr": 1 / 3.6}, 0, 5),
    "walking_asymmetry": (PERCENT, 0, 100),
    "double_support": (PERCENT, 0, 100),
    "steadiness": (PERCENT, 0, 100),
}


class WearableError(ValueError):
    """El pedido no sirve; el mensaje se devuelve tal cual en el 422."""


def _wearable_token_ok(token: str | None) -> bool:
    expected = os.environ.get("WEARABLE_TOKEN") or os.environ.get("ATAJO_TOKEN")
    return bool(expected and token and secrets.compare_digest(token, expected))


def normalize(sample) -> float:
    """Valor en la unidad canónica de su tipo, o WearableError con qué está mal."""
    if sample.type == "steps":
        raise WearableError("type 'steps': los pasos entran por POST /api/biometrics/atajo o la importación de Salud")
    if sample.type not in WEARABLE_UNITS:
        raise WearableError(f"type {sample.type!r} no válido; tiene que ser uno de: {', '.join(WEARABLE_UNITS)}")
    units, lo, hi = WEARABLE_UNITS[sample.type]
    if sample.unit not in units:
        raise WearableError(f"unit {sample.unit!r} no válida para {sample.type}; usar {' o '.join(units)}")
    value = sample.value * units[sample.unit]
    if not lo <= value <= hi:
        canonical = next(iter(units))
        raise WearableError(f"{sample.type} = {round(value, 2)} {canonical} fuera de rango ({lo} a {hi})")
    if sample.end < sample.start:
        raise WearableError(f"{sample.type}: end ({sample.end.isoformat()}) es anterior a start")
    return value


def ingest_wearable(payload: WearablePayload | dict, patient_id: int = config.ATAJO_PATIENT_ID) -> dict:
    """Valida y normaliza todas las muestras (si una no sirve, no se guarda ninguna), guarda las nuevas con el
    source del dispositivo (un reenvío no duplica) y registra la ventana en biometric_syncs con scope="pulsera".
    Las fechas se guardan como vienen: el dispositivo manda la hora en la que pasó cada cosa."""
    try:
        p = payload if isinstance(payload, WearablePayload) else WearablePayload.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise WearableError(f"{'.'.join(map(str, first['loc']))}: {first['msg']}") from exc
    if p.window_end <= p.window_start:
        raise WearableError("window_end tiene que ser posterior a window_start")
    rows = []
    for i, s in enumerate(p.samples):
        try:
            value = normalize(s)
        except WearableError as exc:
            raise WearableError(f"samples[{i}]: {exc}") from None
        rows.append((patient_id, s.type, round(value, 3), db.to_db(s.start), db.to_db(s.end), p.source))
    with db.connect() as conn:
        stored = conn.executemany(
            'INSERT OR IGNORE INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (?, ?, ?, ?, ?, ?)',
            rows).rowcount
        conn.execute(
            "INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples, scope) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (patient_id, db.to_db(p.window_start), db.to_db(p.window_end), db.to_db(clock.now()), len(rows),
             db.SYNC_SCOPE_WEARABLE))
    return {"received": len(rows), "stored": stored, "duplicates": len(rows) - stored}


@router.post("/api/biometrics/wearable")
def wearable(payload: dict, x_device_token: str | None = Header(default=None)):
    if not _wearable_token_ok(x_device_token):
        raise HTTPException(status_code=401, detail="Token del dispositivo inválido")
    try:
        return ingest_wearable(payload)
    except WearableError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

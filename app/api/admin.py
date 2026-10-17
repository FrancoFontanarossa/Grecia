# Admin de la demo (CLAUDE.md §11): reloj, caída inyectada, snapshot y restore. Todo con X-Admin-Token.
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from app import clock, config, db


class NoSyncError(Exception):
    """No hay un registro en biometric_syncs que cubra la ventana: no se sabe cuántos pasos hubo."""


def inject_drop(patient_id: int, dose_time: datetime, pct: float) -> int:
    """Multiplica por (1 − pct) los pasos de las muestras que empiezan en [toma, toma + 120 min)
    y las rotula source=inyectado. Las ya inyectadas no se tocan (aplicarla dos veces no la duplica).
    Devuelve cuántas muestras cambió."""
    start = db.to_db(dose_time)
    end = db.to_db(dose_time + timedelta(minutes=config.DEVIATION_WINDOW_MINUTES))
    with db.connect() as conn:
        covered = conn.execute(
            "SELECT 1 FROM biometric_syncs WHERE patient_id = ? AND window_start <= ? AND window_end >= ?",
            (patient_id, start, end),
        ).fetchone()
        if not covered:
            raise NoSyncError
        return conn.execute(
            "UPDATE biometrics SET value = value * ?, source = 'inyectado' "
            "WHERE patient_id = ? AND kind = 'steps' AND source != 'inyectado' AND start >= ? AND start < ?",
            (1 - pct, patient_id, start, end),
        ).rowcount


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected or not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Token de admin inválido")


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


class AdvanceBody(BaseModel):
    minutes: float


class SetBody(BaseModel):
    iso: str


class InjectDropBody(BaseModel):
    patient_id: int
    dose_time: AwareDatetime
    pct: float = Field(gt=0, le=1)


@router.get("/clock/state")   # /admin/clock queda para el panel HTML
def get_clock():
    return {"now": clock.now().isoformat(), "offset_seconds": clock.offset().total_seconds()}


@router.post("/clock/advance")
def advance(body: AdvanceBody):
    return {"now": clock.advance(body.minutes).isoformat()}


@router.post("/clock/set")
def set_clock(body: SetBody):
    try:
        return {"now": clock.set(body.iso).isoformat()}
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Fecha inválida: {body.iso!r} (usar ISO 8601)")


@router.post("/inject_drop")
def post_inject_drop(body: InjectDropBody):
    try:
        inject_drop(body.patient_id, body.dose_time, body.pct)
    except NoSyncError:
        raise HTTPException(status_code=409, detail="No hay pasos sincronizados que cubran esa ventana")
    return {"ok": True}


@router.post("/snapshot")
def snapshot():
    db.snapshot()
    return {"ok": True}


@router.post("/restore")
def restore():
    try:
        db.restore()
    except FileNotFoundError:
        raise HTTPException(status_code=409, detail="No hay snapshot guardado: primero POST /admin/snapshot")
    return {"ok": True}

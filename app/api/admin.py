# Admin de la demo (CLAUDE.md §11): reloj, snapshot y restore. Todo con el encabezado X-Admin-Token.
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app import clock, db


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected or not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Token de admin inválido")


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


class AdvanceBody(BaseModel):
    minutes: float


class SetBody(BaseModel):
    iso: str


@router.get("/clock")
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

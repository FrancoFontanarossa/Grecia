# GET /api/push/vapid-public-key: la clave pública VAPID que la PWA usa como applicationServerKey.
import os

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/push/vapid-public-key")
def vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY")
    if not key:
        raise HTTPException(503, "Falta VAPID_PUBLIC_KEY en el servidor")
    return {"key": key}

from fastapi import APIRouter, HTTPException

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])


@router.post("/notifications/{notification_id}/read")
def read(notification_id: int):
    if not store.mark_notification_read(notification_id):
        raise HTTPException(404, "No encontramos ese aviso.")
    return {"ok": True}

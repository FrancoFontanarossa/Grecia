# POST /api/alerts/{alert_id}/ack: el botón "Estoy bien" de la pantalla de emergencia.
from fastapi import APIRouter, HTTPException

from app import clock, db
from app.rules import goals

router = APIRouter()


@router.post("/api/alerts/{alert_id}/ack")
def ack(alert_id: int):
    """Marca el aviso como atendido (la primera vez cuenta) y recalcula la meta de hoy, que levanta la
    pausa si ya no queda ningún rojo sin atender."""
    now = clock.now()
    with db.connect() as conn:
        row = conn.execute("SELECT patient_id, acked_at FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No existe ese aviso")
        if row["acked_at"] is None:
            conn.execute("UPDATE alerts SET acked_at = ? WHERE id = ?", (db.to_db(now), alert_id))
        acked_at = row["acked_at"] or db.to_db(now)
    goals.status(row["patient_id"], now.date())          # recalcula la pausa
    return {"ok": True, "acked_at": db.from_db(acked_at).isoformat(), "goal_paused": goals.paused(row["patient_id"])}

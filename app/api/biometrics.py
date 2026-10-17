# POST /api/biometrics/atajo: pasos del Atajo de iOS (CLAUDE.md §8 y §11).
import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, Header, HTTPException

from app import clock, config, db
from app.models import AtajoPayload

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

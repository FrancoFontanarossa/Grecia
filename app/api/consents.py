from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])


class ConsentIn(BaseModel):
    recipient_id: int
    kind: Literal["avisos", "logros", "canal_reservado"]
    enabled: bool


@router.get("/consents/{patient_id}")
def get_consents(patient_id: int):
    if not store.people(patient_id):
        raise HTTPException(404, "No encontramos a ese paciente.")
    return {"patient_id": patient_id, "consents": store.consents(patient_id), "simulated": True}


@router.post("/consents/{patient_id}")
def set_consent(patient_id: int, body: ConsentIn):
    recipient = store.person(body.recipient_id)
    if not recipient or recipient["patient_id"] != patient_id:
        raise HTTPException(404, "No encontramos a esa persona.")
    # TODO(contrato): guardar en la tabla consents (rules.consent la lee).
    store.set_consent(patient_id, body.recipient_id, body.kind, body.enabled)
    return get_consents(patient_id)

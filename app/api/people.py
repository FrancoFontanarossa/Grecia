from fastapi import APIRouter, Cookie

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])


@router.get("/people")
def list_people(patient_id: int | None = None, ec_patient: int | None = Cookie(default=None)):
    """Personas del paciente activo, para "¿Quién sos?". El paciente activo sale de ?patient_id o de la cookie."""
    pid = patient_id or ec_patient or store.JUAN_PATIENT_ID
    return store.people(pid)

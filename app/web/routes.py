"""Páginas de la app de la casa (PWA) e infraestructura de la PWA: /sw.js, /manifest.webmanifest, /static."""
import mimetypes

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.api import _store as store
from app.api.hoy import build_hoy
from app.web import STATIC_DIR, templates

router = APIRouter(include_in_schema=False)
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


# ---------------------------------------------------------------- infraestructura PWA

@router.get("/sw.js")
def service_worker():
    # Desde la raíz para que el service worker controle toda la app.
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@router.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/static/{path:path}")
def static(path: str):
    # Servido por ruta (y no con app.mount) para no tocar app/main.py más que con include_router.
    target = (STATIC_DIR / path).resolve()
    if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": "public, max-age=300"})


# ---------------------------------------------------------------- helpers

def current_person(ec_person: str | None) -> dict | None:
    try:
        return store.person(int(ec_person)) if ec_person else None
    except ValueError:
        return None


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, ctx)


# ---------------------------------------------------------------- ¿Quién sos?

@router.get("/")
def selector(request: Request, ec_patient: str | None = Cookie(default=None)):
    try:
        patient_id = int(ec_patient) if ec_patient else store.JUAN_PATIENT_ID
    except ValueError:
        patient_id = store.JUAN_PATIENT_ID
    people = store.people(patient_id) or store.people(store.JUAN_PATIENT_ID)
    return render(request, "casa/selector.html", people=people, patient_id=patient_id,
                  is_test=patient_id == store.TEST_PATIENT_ID)


@router.get("/prueba")
def prueba(request: Request):
    """QR del jurado: crea o reutiliza el paciente de prueba y abre ¿Quién sos?."""
    patient_id = store.test_patient_id()
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("ec_patient", str(patient_id), max_age=31536000, samesite="lax")
    resp.delete_cookie("ec_person")
    return resp


# ---------------------------------------------------------------- inicio según el rol

_HOME = {"paciente": "casa/juan_inicio.html", "cuidador": "casa/marta_hoy.html", "familiar": "casa/laura_resumen.html"}


@router.get("/casa")
def casa(request: Request, parcial: int = 0, ec_person: str | None = Cookie(default=None)):
    person = current_person(ec_person)
    if not person:
        return RedirectResponse("/", status_code=303)
    if person["role"] == "neurologo":
        return RedirectResponse(f"/neuro/informe/{person['patient_id']}", status_code=303)
    hoy = build_hoy(person["id"])
    name = _HOME[person["role"]]
    if parcial:
        name = name.replace(".html", "_contenido.html")
    return render(request, name, hoy=hoy, person=person, simulated=hoy.get("simulated"))

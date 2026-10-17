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


# ---------------------------------------------------------------- contar algo y "Anoté esto"

# OccurredHint del contrato (app/models.py), en el orden de los chips.
HINTS = [("ahora", "Ahora"), ("esta_manana", "Esta mañana"), ("esta_tarde", "Esta tarde"), ("anoche", "Anoche"), ("ayer", "Ayer")]

DOMAIN_LABELS = {
    "motor": "Movimiento", "sueno": "Sueño", "neuropsiquiatrico": "Percepción", "animo": "Ánimo",
    "cognitivo": "Memoria y atención", "autonomico": "Cuerpo", "dolor": "Dolor", "deglucion": "Tragar",
    "caidas": "Caídas", "impulsos": "Impulsos", "sexual": "Intimidad", "otro": "Otro",
}


def _visit_label() -> str:
    from app.web import MESES

    return f"{store.NEXT_VISIT.day} de {MESES[store.NEXT_VISIT.month - 1]}"


@router.get("/casa/contar")
def contar(request: Request, modo: str = "", question_id: int | None = None, corregir: int | None = None,
           ec_person: str | None = Cookie(default=None)):
    person = current_person(ec_person)
    if not person:
        return RedirectResponse("/", status_code=303)
    patient = store.patient_person(person["patient_id"]) or person
    is_patient = person["role"] == "paciente"
    if modo == "escribir":
        start_mode = "escribir"
    elif is_patient:
        start_mode = "grabar"  # Juan tocó "Contame cómo estás": ya empieza a grabar
    else:
        start_mode = "listo"   # la familia primero elige "¿cuándo pasó?"
    back_url = f"/casa/pregunta/{question_id}" if question_id else "/casa"
    return render(request, "casa/contar_juan.html" if is_patient else "casa/contar_familia.html",
                  person=person, patient=patient, question_id=question_id, correct_id=corregir,
                  start_mode=start_mode, back_url=back_url, hints=HINTS, doctor=store.DOCTOR)


@router.get("/casa/pregunta/{question_id}")
def pregunta(request: Request, question_id: int, ec_person: str | None = Cookie(default=None)):
    from app.api.questions import get_question

    person = current_person(ec_person)
    if not person:
        return RedirectResponse(f"/?next=/casa/pregunta/{question_id}", status_code=303)
    q = get_question(question_id)
    return render(request, "casa/pregunta.html", person=person, q=q, simulated=q.get("simulated"))


@router.get("/casa/golpeteo")
def golpeteo(request: Request, desde: str = "", ec_person: str | None = Cookie(default=None)):
    person = current_person(ec_person)
    if not person:
        return RedirectResponse("/", status_code=303)
    return render(request, "casa/golpeteo.html", person=person, desde_pregunta=desde == "pregunta")


# Pasos genéricos y seguros mientras rules.red no traiga los suyos (texto fijo, sin IA).
# TODO(contrato): reemplazar por los pasos fijos de cada regla (R1–R4) cuando existan en app/rules/red.py.
_RED_STEPS = [
    "Llamá ahora a tu emergencia móvil y contá lo que pasó.",
    "Quedate con {name} hasta que llegue la ayuda.",
    "Tené a mano la lista de remedios que toma.",
]


@router.get("/casa/emergencia/{alert_id}")
def emergencia(request: Request, alert_id: int, entry: int | None = None, ec_person: str | None = Cookie(default=None)):
    person = current_person(ec_person)
    if not person:
        return RedirectResponse("/", status_code=303)
    patient = store.patient_person(person["patient_id"]) or person
    # La alerta de la tabla alerts (texto fijo de la regla). Si no está (alert_id 0), la pantalla usa el
    # RedResult que devolvió POST /api/entries, guardado en el teléfono.
    row = store.alert(alert_id) if alert_id else None
    if row and person["id"] not in row["recipients"] and person["role"] != "neurologo":
        row = None  # no es para esta persona
    alert = {"id": alert_id, "text": row["text"] if row else None, "missing_criterion": None}
    name = "él" if person["role"] == "paciente" else patient["name"]
    steps = [s.format(name=name) for s in _RED_STEPS]
    if person["role"] == "paciente":
        steps[1] = "Quedate quieto y avisale a alguien de tu casa."
    return render(request, "casa/emergencia.html", person=person, alert=alert, entry_id=entry, steps=steps)


@router.get("/casa/permisos")
def permisos(request: Request, ec_person: str | None = Cookie(default=None)):
    person = current_person(ec_person)
    if not person:
        return RedirectResponse("/", status_code=303)
    consents = store.consents(person["patient_id"])
    by_person: dict[int, list] = {}
    for c in consents:
        if c["kind"] in ("avisos", "logros"):
            by_person.setdefault(c["recipient_id"], []).append(c)
    kind_labels = {"avisos": ("Avisos para mirar", "Cuando algo cambia y conviene prestarle atención"),
                   "logros": ("Logros", "Cuando llegás a tu meta de pasos")}
    return render(request, "casa/permisos.html", person=person, patient_id=person["patient_id"], consents=consents,
                  by_person=list(by_person.items()), kind_labels=kind_labels, simulated=True)


@router.get("/casa/anote/{entry_id}")
def anote(request: Request, entry_id: int, ec_person: str | None = Cookie(default=None)):
    person = current_person(ec_person)
    if not person:
        return RedirectResponse("/", status_code=303)
    return render(request, "casa/anote.html", person=person, entry_id=entry_id, doctor=store.DOCTOR,
                  visit_label=_visit_label(), domain_labels=DOMAIN_LABELS)

import datetime as dt

from fastapi import APIRouter, HTTPException

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])


def greeting(now: dt.datetime, name: str) -> str:
    h = now.hour
    if 6 <= h < 12:
        saludo = "Buenos días"
    elif 12 <= h < 20:
        saludo = "Buenas tardes"
    else:
        saludo = "Buenas noches"
    return f"{saludo}, {name}"


def _last_understood(person_id: int) -> tuple[dict | None, bool]:
    # TODO(contrato): reemplazar por el último evento de la base (events de las entries de esta persona).
    snaps = [s for s in store._read_json("entries", {}).values() if s.get("person_id") == person_id and s.get("understood")]
    if snaps:
        last = max(snaps, key=lambda s: s["entry_id"])
        return last["understood"][0], False
    if person_id == 1:
        return {"plain": "anoche dormiste mal y te despertaste tres veces.", "when": "Anoche", "domain": "sueno"}, True
    return None, False


def build_hoy(person_id: int) -> dict:
    person = store.person(person_id)
    if not person:
        raise HTTPException(404, "No encontramos a esa persona.")
    now = store.now()
    patient_id = person["patient_id"]
    patient = store.patient_person(patient_id) or person
    today = store.daily_steps(patient_id, now.date(), 1)[0]
    unread = [n for n in store.notifications(person_id) if not n.get("read_at")]
    simulated = not store.clock_is_real()

    data = {
        "now": now.isoformat(),
        "role": person["role"],
        "person": {"id": person["id"], "name": person["name"], "patient_id": patient_id},
        "patient": {"id": patient_id, "name": patient["name"]},
        "greeting": greeting(now, person["name"]),
        "steps_today": today["value"] or 0,
        "goal": store.GOAL_STEPS,
        "next_dose": store.next_dose(now),
        "pending_question": None,  # TODO(contrato): questions con status enviada/pendiente para esta persona
        "last_understood": None,
        "notifications_unread": len(unread),
        "notifications": unread[-5:],
        "test_today": any(t["taken_at"][:10] == now.date().isoformat() and t.get("source") != "seed"
                          for t in store.tests_history(patient_id)),
        "next_visit": store.NEXT_VISIT.isoformat(),
        "doctor": store.DOCTOR,
        "simulated": True,  # TODO(contrato): False cuando todo salga de app.db
    }
    last, _ = _last_understood(person_id)
    data["last_understood"] = last
    if person["role"] in ("cuidador", "familiar"):
        data.update(_family(person, patient, now))
    return data


def _family(person: dict, patient: dict, now: dt.datetime) -> dict:
    patient_id = person["patient_id"]
    week = store.daily_steps(patient_id, now.date(), 7)
    name = patient["name"]
    is_juan = patient_id == store.JUAN_PATIENT_ID
    # TODO(contrato): alerts del carril ámbar con destinatario = esta persona (rules.consent.recipients).
    alerts = []
    if is_juan and person["role"] == "cuidador":
        alerts = [{
            "id": 1, "lane": "ambar", "rule_id": "A1",
            "text": f"Esta semana pasó dos veces que {name} dijo ver gente en el patio de noche.",
            "what_to_do": "no hace falta discutirle. Si vuelve a pasar, contalo acá. "
                          f"Ya está en el resumen para la {store.DOCTOR}.",
            "evidence": [{"label": "Vos · mié 21:40", "entry_id": None}, {"label": "Vos · vie 22:10", "entry_id": None}],
            "created_at": now.isoformat(),
        }]
    # TODO(contrato): goal_days con notified=True; texto fijo de rules.goals con cifras del código.
    logros = []
    if is_juan:
        logros = [{"date": "2026-10-15", "time": "18:20", "steps": 4060,
                   "text": f"{name} llegó a su meta: 4.060 pasos."}]
    achieved = sum(1 for d in week if d["achieved"])
    return {
        "alerts": alerts,
        "week_steps": [{"date": d["date"], "value": d["value"], "achieved": d["achieved"], "episode": d["episode"]}
                       for d in week],
        "logros": logros,
        # TODO(contrato): cifras de la semana calculadas por código (noches con despertares, episodios, relatos por voz).
        "week_facts": {
            "goal_days": achieved, "days": len(week), "bad_nights": 3 if is_juan else 0,
            "entries_patient": 6 if is_juan else 0, "entries_family": 3 if is_juan else 0,
            "line": ("Durmió mal 3 noches. El martes, jueves y viernes caminó mucho menos a la tarde; "
                     "el jueves lo explicó él.") if is_juan else "Todavía no hay datos de esta semana.",
        },
    }


@router.get("/hoy/{person_id}")
def hoy(person_id: int):
    return build_hoy(person_id)

import datetime as dt

from fastapi import APIRouter, HTTPException

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def greeting(now: dt.datetime, name: str) -> str:
    h = now.hour
    saludo = "Buenos días" if 6 <= h < 12 else ("Buenas tardes" if 12 <= h < 20 else "Buenas noches")
    return f"{saludo}, {name}"


def build_hoy(person_id: int) -> dict:
    person = store.person(person_id)
    if not person:
        raise HTTPException(404, "No encontramos a esa persona.")
    now = store.now()
    real = store.has_db()
    patient_id = person["patient_id"]
    patient = store.patient_person(patient_id) or person
    today = store.daily_steps(patient_id, now.date(), 1, until=now)[0]
    unread = store.notifications(person_id, unread_only=True)
    # Desde las 04:15 los datos raros se le preguntan a Marta: su pregunta pendiente también se ve en Hoy.
    pq = store.pending_question(person_id) if person["role"] in ("paciente", "cuidador") else None

    data = {
        "now": now.isoformat(),
        "role": person["role"],
        "person": {"id": person["id"], "name": person["name"], "patient_id": patient_id},
        "patient": {"id": patient_id, "name": patient["name"]},
        "greeting": greeting(now, person["name"]),
        "steps_today": today["value"] or 0,
        "goal": store.goal_target(patient_id),
        "next_dose": store.next_dose(patient_id, now),
        "pending_question": {"id": pq["id"], "question": pq["question"], "url": pq["url"]} if pq else None,
        "last_understood": store.last_understood(person_id),
        "notifications_unread": len(unread),
        "notifications": unread[-5:],
        "test_today": any(t["taken_at"][:10] == now.date().isoformat() for t in store.tests_history(patient_id)
                          if t.get("source") not in ("seed",)),
        "next_visit": store.NEXT_VISIT.isoformat(),
        "doctor": store.DOCTOR,
        "simulated": not real,
    }
    if person["role"] in ("cuidador", "familiar"):
        data.update(_family(person, patient, now, real))
    return data


def _family(person: dict, patient: dict, now: dt.datetime, real: bool) -> dict:
    patient_id = person["patient_id"]
    name = patient["name"]
    week = store.daily_steps(patient_id, now.date(), 7, until=now)
    week_start = dt.datetime.combine(now.date() - dt.timedelta(days=6), dt.time(0), now.tzinfo)
    achieved = sum(1 for d in week if d["achieved"])

    if real:
        # Alcance de las 04:15: la familia no recibe rojos ni ámbar (el ámbar es prioridad en el informe).
        alerts: list[dict] = []
        goal = store.goal_target(patient_id)
        logros = [{"date": l["date"], "time": l["time"], "steps": l["steps"],
                   "text": f"{name} llegó a su meta: {_miles(l['steps'])} pasos."}   # texto fijo, cifras del código
                  for l in store.logros(patient_id, now.date() - dt.timedelta(days=6))]
        by_role = store.entries_count_by_role(patient_id, week_start)
        nights = store.bad_nights(patient_id, week_start)
        eps = [e for e in store.episodes(patient_id) if e["dose_time"] >= week_start.isoformat()]
        line = _week_line(nights, eps, name, achieved, len(week), goal)
        facts = {"goal_days": achieved, "days": len(week), "bad_nights": nights,
                 "entries_patient": by_role.get("paciente", 0),
                 "entries_family": by_role.get("cuidador", 0) + by_role.get("familiar", 0), "line": line}
    else:
        is_juan = patient_id == store.JUAN_PATIENT_ID
        alerts = []
        logros = ([{"date": "2026-10-15", "time": "18:20", "steps": 4060, "text": f"{name} llegó a su meta: 4.060 pasos."}]
                  if is_juan else [])
        facts = {"goal_days": achieved, "days": len(week), "bad_nights": 3 if is_juan else 0,
                 "entries_patient": 6 if is_juan else 0, "entries_family": 3 if is_juan else 0,
                 "line": ("Durmió mal 3 noches. El martes, jueves y viernes caminó mucho menos a la tarde; "
                          "el jueves lo explicó él.") if is_juan else "Todavía no hay datos de esta semana."}
    return {
        "alerts": alerts,
        "week_steps": [{"date": d["date"], "value": d["value"], "achieved": d["achieved"], "episode": d["episode"]}
                       for d in week],
        "logros": logros,
        "week_facts": facts,
    }


def _miles(n) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def _week_line(nights: int, eps: list[dict], name: str, achieved: int, days: int, goal: int) -> str:
    """Resumen de la semana para la familia: armado por código con cifras del código (sin IA)."""
    parts = []
    if nights:
        parts.append(f"Durmió mal {nights} {'noche' if nights == 1 else 'noches'}.")
    if eps:
        dias = [DIAS[dt.datetime.fromisoformat(e["dose_time"]).weekday()] for e in eps]
        explained = [d for d, e in zip(dias, eps) if (e.get("explanation") or {}).get("explained") or e.get("entry_ids") not in (None, "[]", [])]
        listado = ", ".join(dias[:-1]) + (" y " if len(dias) > 1 else "") + dias[-1]
        frase = f"El {listado} caminó bastante menos después de una toma"
        if explained:
            frase += f"; {'lo explicó él' if len(explained) == 1 else 'algunas veces lo explicó él'}"
        parts.append(frase + ".")
    if not parts:
        parts.append(f"Llegó a la meta de {_miles(goal)} pasos {achieved} de {days} días." if days else
                     "Todavía no hay datos de esta semana.")
    return " ".join(parts)


@router.get("/hoy/{person_id}")
def hoy(person_id: int):
    return build_hoy(person_id)

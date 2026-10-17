"""GET /api/patients/{id}/report y /technical: el informe (Report de pipeline.report, ya verificado) y los
metadatos que calcula el código (cifras, medicación, fuentes, pasos, golpeteo, avisos, evidencia)."""
import datetime as dt
import statistics

from fastapi import APIRouter, HTTPException

from app.api import _store as store
from app.models import Report

router = APIRouter(prefix="/api", tags=["neuro"])

PERIOD_DAYS = 28
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _period(now: dt.datetime) -> tuple[dt.date, dt.date]:
    end = now.date()
    return end - dt.timedelta(days=PERIOD_DAYS - 1), end


def _fake_report() -> tuple[Report, dict]:
    """Sin base ni pipeline.report: el informe del lienzo de diseño, rotulado como ejemplo."""
    report = Report(
        summary=("Desde que se subió el pramipexol, el 22/09, la semana de Juan se mantuvo estable hasta la última: "
                 "el martes 13, el jueves 15 y el viernes 16 se movió bastante menos en las dos horas siguientes a la toma "
                 "de las 16. El jueves él lo explicó: «me sentí trabado, me costó salir a caminar»; los otros dos días "
                 "quedaron sin explicación. En la misma semana apareció algo nuevo: Marta contó dos veces que Juan ve "
                 "personas que no están durante la noche, y lo marcó para hablarlo en privado. Juan no lo mencionó. "
                 "Durmió mal tres de siete noches y llegó a su meta de pasos 15 de 28 días. El juego de golpeteo se "
                 "mantuvo estable."),
        topics=[
            {"title": "Ve personas que no están, de noche",
             "narrative": ("Es la primera vez en el historial. Aparece a los 22 días del aumento de pramipexol y solo en el "
                           "relato de Marta, que lo cuenta las dos veces de noche y con confusión al despertar. Juan, "
                           "consultado por el sueño en la misma semana, habla de «sueños raros» y no menciona ver a nadie. "
                           "No hay fiebre ni caídas registradas esos días."),
             "observed": ["Nuevo desde el 22/09", "2 relatos de Marta"],
             "voices": {"paciente": "Duermo bastante bien. A veces sueño cosas raras.",
                        "cuidador": "Anoche se levantó dos veces medio confundido, me dijo que había un hombre en el patio."},
             "question": "¿Desde cuándo pasa y qué hace usted cuando los ve?", "evidence_ids": [101, 102, 103], "reserved": True},
            {"title": "Menos actividad después de la toma de las 16",
             "narrative": ("En las cuatro semanas previas, entre las 16 y las 18 h Juan caminaba unos 1.300 pasos. Esta "
                           "semana bajó a la mitad o menos tres veces en cinco días. Cuando la app le preguntó el jueves, "
                           "contó que se sintió trabado. Ningún otro tramo del día muestra el mismo patrón."),
             "observed": ["3 episodios · 1 explicado"],
             "voices": {"paciente": "Me sentí trabado, me costó salir a caminar."},
             "question": "¿Cómo se siente una o dos horas después de la pastilla de la tarde?", "evidence_ids": [104],
             "reserved": False},
            {"title": "Sueño interrumpido",
             "narrative": ("Tres de las últimas siete noches tuvieron despertares: Juan lo contó dos veces por la mañana y "
                           "Marta una vez por la noche. En dos de esas tres, al día siguiente caminó menos de lo habitual. "
                           "Una de las noches coincide con un relato de Marta sobre visiones (tema 1)."),
             "observed": ["3 de 7 noches"], "voices": {}, "question": "", "evidence_ids": [105, 102], "reserved": False},
        ],
        removed_count=2,
    )
    evidence = {
        101: {"name": "Marta", "role": "cuidador", "at": "2026-10-14T21:40:00-03:00", "reserved": True,
              "quote": "Anoche se levantó dos veces medio confundido, me dijo que había un hombre en el patio."},
        102: {"name": "Marta", "role": "cuidador", "at": "2026-10-16T22:10:00-03:00", "reserved": True,
              "quote": "Otra vez se despertó diciendo que había gente en el patio."},
        103: {"name": "Juan", "role": "paciente", "at": "2026-10-15T10:05:00-03:00", "reserved": False,
              "quote": "Duermo bastante bien. A veces sueño cosas raras."},
        104: {"name": "Juan", "role": "paciente", "at": "2026-10-15T18:20:00-03:00", "reserved": False,
              "quote": "Me sentí trabado, me costó salir a caminar."},
        105: {"name": "Juan", "role": "paciente", "at": "2026-10-17T09:12:00-03:00", "reserved": False,
              "quote": "Me desperté tres veces anoche."},
    }
    return report, evidence


def _evidence_label(e: dict) -> str:
    at = dt.datetime.fromisoformat(e["at"])
    return f"{e['name']} · {DIAS[at.weekday()]} {at.day}, {at:%H:%M}"


def build_report(patient_id: int) -> dict:
    patient = store.patient_person(patient_id)
    if not patient:
        raise HTTPException(404, "No encontramos a ese paciente.")
    now = store.now()
    start, end = _period(now)
    since = dt.datetime.combine(start, dt.time(0), now.tzinfo)
    real = store.has_db()

    # ---------------------------------------------------------- informe redactado (pipeline.report + verificador)
    generated_at = None
    rep = store.latest_report(patient_id) if real else None
    if rep and rep.get("content"):
        report = Report.model_validate(rep["content"])
        generated_at = rep["created_at"]
        ids = sorted({i for t in report.topics for i in t.evidence_ids})
        evidence = {i: {"name": r["name"], "role": r["role"], "at": r["occurred_at"] or r["created_at"],
                        "quote": r["quote"], "reserved": bool(r["reserved"])}
                    for i, r in store.evidence(ids).items()}
        report_simulated = False
    else:
        # TODO(contrato): sin un informe en la tabla reports todavía (pipeline.report de Guada), ejemplo rotulado.
        report, evidence = _fake_report()
        report_simulated = True

    # ---------------------------------------------------------- cifras del código
    days = store.daily_steps(patient_id, end, PERIOD_DAYS, until=now)
    with_data = [d for d in days if d["value"] is not None]
    goal = store.goal_target(patient_id)
    tests = [t for t in store.tests_history(patient_id) if t["taken_at"][:10] >= start.isoformat()]
    rates = [t["metrics"].get("taps_per_s") for t in tests if t["metrics"].get("taps_per_s")]
    tapping = None
    if rates:
        recent = statistics.median(rates[-3:])
        before = statistics.median(rates[:-3]) if len(rates) > 3 else None
        trend = "estable" if before is None or abs(recent - before) / before < 0.15 else ("más lento" if recent < before else "más rápido")
        tapping = {"median": round(statistics.median(rates), 1), "trend": trend, "n": len(rates)}

    meds = []
    for m in store.medications(patient_id):
        label = m["drug"].capitalize()
        if m["times"]:
            label += " · " + " · ".join(t.split(":")[0].lstrip("0") or "0" for t in m["times"]) + " h"
        changed = None
        if m.get("changed_at"):
            cd = dt.datetime.fromisoformat(m["changed_at"]).date()
            changed = {"date": cd.isoformat(), "days_ago": (now.date() - cd).days}
        meds.append({"label": label, "drug": m["drug"], "changed": changed, "note": m.get("change_note")})

    by_role = store.entries_count_by_role(patient_id, since) if real else {"paciente": 9, "cuidador": 5}
    people = {p["role"]: p["name"] for p in store.people(patient_id)}
    alerts = store.alerts_period(patient_id, since) if real else [
        {"id": 1, "lane": "ambar", "rule_id": "A1", "text": "Alucinaciones nocturnas", "created_at": "2026-10-16T22:10:00-03:00",
         "reserved": 1}]
    sources = store.biometric_sources(patient_id) if real else {"importacion": 672, "inyectado": 6}

    return {
        "report": report.model_dump(),
        "meta": {
            "patient": {"id": patient_id, "name": patient["name"]},
            "period": {"start": start.isoformat(), "end": end.isoformat(), "days": PERIOD_DAYS},
            "visit": {"date": store.NEXT_VISIT.isoformat(), "doctor": store.DOCTOR},
            "medications": meds,
            "sources": {"entries_by_role": by_role, "names": people, "tests": len(tests), "biometrics": sources},
            "daily_steps": days,
            "phone": {"avg_steps": round(statistics.fmean([d["value"] for d in with_data])) if with_data else None,
                      "goal": goal, "goal_days": sum(1 for d in days if d["achieved"]), "days_with_data": len(with_data),
                      "tapping": tapping},
            "alerts": [{"id": a["id"], "lane": a["lane"], "rule_id": a["rule_id"], "text": a["text"],
                        "created_at": a["created_at"], "reserved": bool(a.get("reserved"))} for a in alerts],
            "evidence": {str(i): {**e, "label": _evidence_label(e)} for i, e in evidence.items()},
            "generated_at": generated_at,
            "now": now.isoformat(),
        },
        "simulated": report_simulated or not real,
        "report_simulated": report_simulated,
    }


@router.get("/patients/{patient_id}/report")
def report(patient_id: int):
    return build_report(patient_id)


# ---------------------------------------------------------------- vista técnica

def _fake_hourly(start: dt.date, end: dt.date) -> list[dict]:
    """Sin base: pasos por hora de ejemplo con la forma de la serie real (rotulados)."""
    import math

    shape = {7: 120, 8: 260, 9: 380, 10: 420, 11: 300, 12: 180, 13: 150, 14: 260, 15: 300, 16: 640, 17: 660,
             18: 380, 19: 220, 20: 120, 21: 60}
    out = []
    d = start
    while d <= end:
        for h, v in shape.items():
            factor = 1 + 0.12 * math.sin(d.toordinal() * 1.7 + h)
            if d in store._FAKE_EPISODES and h in (16, 17):
                factor *= 0.3
            out.append({"hour": f"{d.isoformat()}T{h:02d}", "value": round(v * factor),
                        "injected": d in store._FAKE_EPISODES and h in (16, 17), "n": 4})
        d += dt.timedelta(days=1)
    return out


def build_technical(patient_id: int) -> dict:
    patient = store.patient_person(patient_id)
    if not patient:
        raise HTTPException(404, "No encontramos a ese paciente.")
    now = store.now()
    start, end = _period(now)
    real = store.has_db()
    hourly = store.hourly_steps(patient_id, start, end) if real else _fake_hourly(start, end)
    doses = store.dose_times(patient_id)
    # Pasos en la ventana de 2 h después de cada toma, por día (lo que mira el desvío, §7.3).
    windows: dict[str, list[dict]] = {t: [] for t in doses}
    by_hour = {h["hour"]: h for h in hourly}
    d = start
    while d <= end:
        for t in doses:
            h0 = int(t[:2])
            hs = [by_hour.get(f"{d.isoformat()}T{h:02d}") for h in (h0, h0 + 1)]
            if any(hs):
                windows[t].append({"date": d.isoformat(), "value": sum(x["value"] for x in hs if x),
                                   "injected": any(x and x["injected"] for x in hs)})
        d += dt.timedelta(days=1)
    eps = store.episodes(patient_id) if real else [
        {"dose_time": f"{e.isoformat()}T16:00:00-03:00", "status": "explicado" if e.day == 15 else "sin_explicar",
         "deviation": None} for e in sorted(store._FAKE_EPISODES)]
    tests = [{"taken_at": t["taken_at"], "taps_per_s": t["metrics"].get("taps_per_s"),
              "interval_cv": t["metrics"].get("interval_cv"), "source": t.get("source")}
             for t in store.tests_history(patient_id)]
    return {
        "patient": {"id": patient_id, "name": patient["name"]},
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "doses": doses,
        "hourly": hourly,
        "post_dose": windows,
        "episodes": [{"dose_time": e["dose_time"], "status": e["status"], "deviation": e.get("deviation")} for e in eps],
        "tests": tests,
        "sources": store.biometric_sources(patient_id) if real else {"ejemplo": len(hourly)},
        "simulated": not real,
    }


@router.get("/patients/{patient_id}/technical")
def technical(patient_id: int):
    return build_technical(patient_id)

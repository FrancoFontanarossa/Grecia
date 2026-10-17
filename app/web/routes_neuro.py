"""Web de la neuróloga (/neuro/...) y panel de la demo (/admin/clock). La lógica del admin es de Franco
(app/api/admin.py); esta página solo llama a sus endpoints con el X-Admin-Token."""
import statistics

from fastapi import APIRouter, Request

from app.api import _store as store
from app.api.report import build_report, build_technical
from app.web import templates

router = APIRouter(include_in_schema=False)


def _post_dose_chart(report: dict, tech: dict) -> dict | None:
    """Gráfico chico del tema "después de la toma": la toma con más episodios, últimos 7 días, y la mediana
    del período sin los días con episodio. Todo calculado por código."""
    topics = report["report"]["topics"]
    idx = next((i for i, t in enumerate(topics) if any(w in t["title"].lower() for w in ("toma", "actividad", "pasos"))), None)
    if idx is None or not tech["post_dose"]:
        return None
    ep_by_dose: dict[str, set] = {}
    for e in tech["episodes"]:
        ep_by_dose.setdefault(e["dose_time"][11:16], set()).add(e["dose_time"][:10])
    dose = max(tech["post_dose"], key=lambda d: len(ep_by_dose.get(d, ())))
    series = tech["post_dose"][dose]
    if not series:
        return None
    eps = ep_by_dose.get(dose, set())
    normal = [p["value"] for p in series if p["date"] not in eps and not p["injected"]]
    median = statistics.median(normal) if normal else 0
    days = [{"date": p["date"], "value": p["value"], "episode": p["date"] in eps or p["injected"]} for p in series[-7:]]
    top = max([median] + [d["value"] for d in days]) or 1
    h = int(dose[:2])
    return {"topic_index": idx, "window": f"{h} y {h + 2} h", "median": round(median), "max": top * 1.15, "days": days}


@router.get("/neuro/informe/{patient_id}")
def informe(request: Request, patient_id: int, parcial: int = 0):
    r = build_report(patient_id)
    post_dose = _post_dose_chart(r, build_technical(patient_id))
    name = "neuro/informe_contenido.html" if parcial else "neuro/informe.html"
    return templates.TemplateResponse(request, name, {"r": r, "post_dose": post_dose, "tab": "informe"})


@router.get("/neuro/tecnica/{patient_id}")
def tecnica(request: Request, patient_id: int):
    r = build_report(patient_id)
    t = build_technical(patient_id)
    return templates.TemplateResponse(request, "neuro/tecnica.html", {"r": r, "t": t, "tab": "tecnica",
                                                                       "simulated": t["simulated"]})


@router.get("/admin/clock")
def admin_clock(request: Request):
    people = [p for pid in (store.JUAN_PATIENT_ID, store.test_patient_id()) for p in store.people(pid)
              if p["role"] != "neurologo"]
    return templates.TemplateResponse(request, "admin/clock.html", {"people": people})

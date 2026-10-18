"""Modo 2: GET /api/patients/{id}/plan (lo que planificó el sistema, con hipótesis y descartes),
POST /admin/plan/run/{id} (generarlo ahora, con X-Admin-Token) y build_bitacora (las notas de la revisión diaria
para /neuro/tecnica: solo equipo médico, nunca en rutas de la familia)."""
import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException

from app import clock, config, db
from app.api.admin import require_admin
from app.models import Hypothesis, HypothesisResult
from app.rules import plan as plan_rules

router = APIRouter(tags=["plan"])
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _ref_label(conn, ref: str) -> dict:
    kind, _, raw = ref.partition(":")
    out = {"ref": ref, "label": ref, "quote": None}
    try:
        if kind == "dia":
            d = dt.date.fromisoformat(raw)
            out["label"] = f"Día · {DIAS[d.weekday()]} {d:%d/%m}"
        elif kind == "relato":
            r = conn.execute("SELECT ev.quote, en.created_at, p.name FROM events ev JOIN entries en ON en.id = ev.entry_id "
                             "JOIN people p ON p.id = en.speaker_id WHERE ev.id = ?", (int(raw),)).fetchone()
            if r:
                t = db.from_db(r["created_at"])
                out.update(label=f"{r['name']} · {DIAS[t.weekday()]} {t:%d/%m %H:%M}", quote=r["quote"])
        elif kind == "episodio":
            r = conn.execute("SELECT dose_time FROM episodes WHERE id = ?", (int(raw),)).fetchone()
            if r:
                t = db.from_db(r["dose_time"])
                out["label"] = f"Desvío · {DIAS[t.weekday()]} {t:%d/%m}, toma de las {t:%H}"
        elif kind == "juego":
            r = conn.execute("SELECT taken_at FROM tests WHERE id = ?", (int(raw),)).fetchone()
            if r:
                t = db.from_db(r["taken_at"])
                out["label"] = f"Juego · {DIAS[t.weekday()]} {t:%d/%m %H:%M}"
        elif kind == "nota":
            d = dt.date.fromisoformat(raw)
            out.update(label=f"Nota · {DIAS[d.weekday()]} {d:%d/%m}", anchor=f"nota-{raw}")
        elif kind == "alerta":
            r = conn.execute("SELECT rule_id, created_at FROM alerts WHERE id = ?", (int(raw),)).fetchone()
            if r:
                out["label"] = f"Aviso {r['rule_id']} · {db.from_db(r['created_at']):%d/%m}"
    except (ValueError, TypeError):
        pass
    return out


def build_plan(patient_id: int, plan_date: str | None = None) -> dict:
    with db.connect() as conn:
        if plan_date is None:
            row = conn.execute("SELECT max(plan_date) FROM (SELECT plan_date FROM planned_actions WHERE patient_id = ? "
                               "UNION SELECT plan_date FROM hypotheses WHERE patient_id = ?)", (patient_id, patient_id)).fetchone()
            plan_date = row[0]
        if plan_date is None:
            return {"enabled": config.DAILY_PLAN_ENABLED, "plan_date": None, "actions": [], "discarded": [],
                    "hypotheses": []}
        people = {r["id"]: dict(r) for r in conn.execute("SELECT id, name, role FROM people WHERE patient_id = ?",
                                                         (patient_id,))}
        actions = [dict(r) for r in conn.execute(
            "SELECT * FROM planned_actions WHERE patient_id = ? AND plan_date = ? ORDER BY status = 'descartada', at",
            (patient_id, plan_date))]
        hyps = [dict(r) for r in conn.execute("SELECT * FROM hypotheses WHERE patient_id = ? AND plan_date = ? ORDER BY id",
                                              (patient_id, plan_date))]
        for a in actions:
            p = people.get(a["to_person_id"]) or {}
            a["to_name"], a["to_role"] = p.get("name"), p.get("role")
            a["evidence"] = [_ref_label(conn, ref) for ref in json.loads(a["evidence_ids"] or "[]")]
    for h in hyps:
        res = HypothesisResult(hypothesis=Hypothesis(condition=h["condition"], metric=h["metric"], lag_days=h["lag_days"],
                                                     direction=h["direction"], reason=h["reason"]),
                               passed=bool(h["passed"]), mediana_con=h["mediana_con"], n_con=h["n_con"],
                               mediana_sin=h["mediana_sin"], n_sin=h["n_sin"], discard_reason=h["discard_reason"])
        try:
            h["text"] = plan_rules.result_text(res)
        except ValueError:          # fuera del vocabulario: no hay texto con cifras
            h["text"] = None
        h["passed"] = bool(h["passed"])
    return {"enabled": config.DAILY_PLAN_ENABLED, "plan_date": plan_date,
            "actions": [a for a in actions if a["status"] != "descartada"],
            "discarded": [a for a in actions if a["status"] == "descartada"],
            "hypotheses": hyps, "source_note": "Sueño y pulso: pulsera simulada. Coincidencia en el tiempo, no causa."}


def build_bitacora(patient_id: int, limit: int = 28) -> list[dict]:
    """Las notas de la bitácora, de la más nueva a la más vieja, con la evidencia de cada oración y de cada punto
    lista para mostrar (etiqueta y, si es un relato, la cita)."""
    from app.rules.note import REF, sentences
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT date, text, points, follow_up, removed_count, created_at FROM daily_notes WHERE patient_id = ? "
            "ORDER BY date DESC LIMIT ?", (patient_id, limit))]
        out = []
        for r in rows:
            d = dt.date.fromisoformat(r["date"])
            parts = [{"text": " ".join(REF.sub("", s).split()).replace(" .", "."),
                      "evidence": [_ref_label(conn, ref) for ref in dict.fromkeys(REF.findall(s))]}
                     for s in sentences(r["text"])]
            points = [{"text": p["text"], "evidence": [_ref_label(conn, ref) for ref in p.get("evidence_ids", [])]}
                      for p in json.loads(r["points"] or "[]")]
            out.append({"date": r["date"], "label": f"{DIAS[d.weekday()]} {d:%d/%m}", "parts": parts, "points": points,
                        "follow_up": json.loads(r["follow_up"] or "[]"), "removed_count": r["removed_count"]})
    return out


@router.get("/api/patients/{patient_id}/plan")
def get_plan(patient_id: int, date: str | None = None):
    return build_plan(patient_id, date)


@router.post("/admin/plan/run/{patient_id}", dependencies=[Depends(require_admin)])
async def run_plan_now(patient_id: int, force: bool = False):
    """Genera el plan de mañana ya (sin esperar a las 21). Con force=1 reemplaza el que hubiera para esa fecha."""
    from app import plan_jobs

    now = clock.now()
    plan_date = (now.date() + dt.timedelta(days=1)).isoformat()
    with db.connect() as conn:
        exists = any(conn.execute(f"SELECT 1 FROM {t} WHERE patient_id = ? AND plan_date = ? LIMIT 1",
                                  (patient_id, plan_date)).fetchone() for t in ("hypotheses", "planned_actions"))
        if exists and not force:
            raise HTTPException(409, f"Ya hay un plan para el {plan_date}: usá force=1 para rehacerlo")
        if force:
            conn.execute("DELETE FROM hypotheses WHERE patient_id = ? AND plan_date = ?", (patient_id, plan_date))
            conn.execute("DELETE FROM planned_actions WHERE patient_id = ? AND plan_date = ?", (patient_id, plan_date))
    summary = await plan_jobs.run_plan(patient_id, now)
    return {**summary, "plan": build_plan(patient_id, plan_date)}

# Modo 2: el resumen que ve la IA para planificar mañana. Lo arma el CÓDIGO desde la base: la IA nunca ve la base
# cruda. Cada cosa lleva su `ref` ("relato:<id>", "episodio:<id>", "juego:<id>", "alerta:<id>", "dia:<fecha>"), que es
# lo único que la IA puede citar como evidencia (rules.plan.validate lo vuelve a chequear contra la base).
# Lo reservado NO entra: el plan puede tener acciones para el paciente. Solo se dice cuántos relatos se omitieron.
import json
from datetime import date, datetime, timedelta
from statistics import median

from app import config, db
from app.config import TZ
from app.rules import biometrics, plan as plan_rules

FRANJAS = ("08-10", "12-14", "16-18", "20-22")       # las dos horas después de cada toma del escenario
QUOTE_CHARS = 140


def _short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= QUOTE_CHARS else text[:QUOTE_CHARS - 1] + "…"


def build_digest(patient_id: int, now: datetime) -> dict:
    now = now.astimezone(TZ)
    today = now.date()
    first28, last = plan_rules.window(now)
    first14 = today - timedelta(days=13)
    plan_date = today + timedelta(days=1)
    lo24 = db.to_db(now - timedelta(hours=24))
    days = plan_rules.daily_data(patient_id, first28, last)

    with db.connect() as conn:
        patient = conn.execute("SELECT name FROM people WHERE id = ?", (patient_id,)).fetchone()
        meds = [dict(r) for r in conn.execute(
            "SELECT drug, changed_at, change_note FROM med_schedule WHERE patient_id = ? AND changed_at IS NOT NULL",
            (patient_id,))]
        relatos = [dict(r) for r in conn.execute(
            "SELECT ev.id, ev.domain, ev.symptom, ev.negated, ev.quote, en.created_at, p.role FROM events ev "
            "JOIN entries en ON en.id = ev.entry_id JOIN people p ON p.id = en.speaker_id "
            "WHERE ev.patient_id = ? AND ev.reserved = 0 AND en.created_at >= ? ORDER BY en.created_at", (patient_id, lo24))]
        reservados = conn.execute(
            "SELECT count(*) FROM events ev JOIN entries en ON en.id = ev.entry_id WHERE ev.patient_id = ? "
            "AND ev.reserved = 1 AND en.created_at >= ?", (patient_id, db.to_db(datetime.combine(first14, datetime.min.time(), TZ)))
        ).fetchone()[0]
        episodes = [dict(r) for r in conn.execute(
            "SELECT id, dose_time, deviation, status FROM episodes WHERE patient_id = ? AND dose_time >= ? ORDER BY dose_time",
            (patient_id, db.to_db(datetime.combine(first28, datetime.min.time(), TZ))))]
        tests = [dict(r) for r in conn.execute(
            "SELECT id, taken_at, metrics FROM tests WHERE patient_id = ? AND taken_at >= ? ORDER BY taken_at",
            (patient_id, lo24))]
        alerts = [dict(r) for r in conn.execute(
            "SELECT id, lane, rule_id, text FROM alerts WHERE patient_id = ? AND reserved = 0 AND created_at >= ?",
            (patient_id, lo24))]
        pending = [dict(r) for r in conn.execute(
            "SELECT sent_at, rule_id, question FROM questions WHERE patient_id = ? AND status IN ('pendiente', 'enviada') "
            "AND question != '' AND sent_at >= ?", (patient_id, db.to_db(datetime.combine(first14, datetime.min.time(), TZ))))]
        used = {r["kind"]: r["n"] for r in conn.execute(
            "SELECT kind, count(*) AS n FROM planned_actions WHERE patient_id = ? AND plan_date = ? "
            "AND status != 'descartada' GROUP BY kind", (patient_id, plan_date.isoformat()))}

    def ep_view(e):
        dev = json.loads(e["deviation"]) if e["deviation"] else {}
        t = db.from_db(e["dose_time"])
        return {"ref": f"episodio:{e['id']}", "fecha": t.date().isoformat(), "toma": f"{t:%H:%M}",
                "observado": dev.get("observed"), "mediana_habitual": dev.get("median"), "estado": e["status"]}

    # Línea de base de 28 días (mediana) para pasos del día y por franja.
    steps_day = [sum(d["steps_hour"].values()) for d in days.values() if d["steps_hour"]]
    def franja(d, f):
        h0, h1 = (int(x) for x in f.split("-"))
        return sum(v for h, v in d["steps_hour"].items() if h0 <= h < h1)
    base = {"pasos_dia": round(median(steps_day)) if steps_day else None,
            **{f"pasos_{f}": round(median([franja(d, f) for d in days.values() if d["steps_hour"]])) if steps_day else None
               for f in FRANJAS}}

    rows14 = []
    for i in range(14):
        d = first14 + timedelta(days=i)
        dd = days.get(d)
        if dd is None:
            continue
        wear = biometrics.daily_summary(patient_id, d)["metrics"]
        sueno = {k: {"valor": m["value"], "habitual": m["baseline_median"], "fuente": m["source"]}
                 for k, m in wear.items() if k in ("sleep_awakenings", "sleep_minutes", "heart_rate_rest")}
        rows14.append({
            "ref": f"dia:{d.isoformat()}", "fecha": d.isoformat(), "dia_semana": d.weekday(),
            "pasos": round(sum(dd["steps_hour"].values())) if dd["steps_hour"] else None,
            "pasos_franjas": {f: round(franja(dd, f)) for f in FRANJAS} if dd["steps_hour"] else None,
            "desvios_franja": sorted(dd["franjas_desvio"]),
            "sueno_pulsera": sueno or None,
            "golpeteo_tps": round(median(dd["tps"]), 1) if dd["tps"] else None,
            "relatos_por_tema": dd["domains"], "voces": sorted(dd["roles"]),
        })

    return {
        "patient_id": patient_id,
        "paciente": patient["name"] if patient else "el paciente",
        "ahora": now.isoformat(timespec="minutes"),
        "plan_date": plan_date.isoformat(),
        "ventana": {"desde": first28.isoformat(), "hasta": last.isoformat()},
        "cambios_de_medicacion": [{"medicamento": m["drug"], "fecha": db.from_db(m["changed_at"]).date().isoformat(),
                                   "hace_dias": (today - db.from_db(m["changed_at"]).date()).days, "nota": m["change_note"]}
                                  for m in meds],
        "ultimas_24h": {
            "relatos": [{"ref": f"relato:{r['id']}", "fecha": r["created_at"][:16], "hablante": r["role"],
                         "tema": r["domain"], "sintoma": r["symptom"], "negado": bool(r["negated"]), "cita": _short(r["quote"])}
                        for r in relatos],
            "golpeteo": [{"ref": f"juego:{t['id']}", "fecha": t["taken_at"][:16],
                          "tps": json.loads(t["metrics"]).get("taps_per_s")} for t in tests],
            "avisos": [{"ref": f"alerta:{a['id']}", "carril": a["lane"], "regla": a["rule_id"], "texto": a["text"]}
                       for a in alerts],
        },
        "desvios_28_dias": [ep_view(e) for e in episodes],
        "linea_de_base_28_dias": base,
        "ultimos_14_dias": rows14,
        "preguntas_sin_respuesta": [{"fecha": q["sent_at"][:16], "regla": q["rule_id"], "pregunta": q["question"]}
                                    for q in pending],
        "limite_de_manana": {"preguntas_usadas": used.get("pregunta", 0) + used.get("seguimiento", 0),
                             "preguntas_max": config.DAILY_MAX_QUESTIONS,
                             "juegos_usados": used.get("golpeteo", 0), "juegos_max": config.DAILY_MAX_GAME_INVITES},
        "relatos_reservados_omitidos": reservados,
        "fuentes": "pasos del iPhone; sueño y pulso de la pulsera (simulado)",
    }

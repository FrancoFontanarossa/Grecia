# Los facts del informe (CLAUDE.md §5.5): todo lo que tiene una cifra lo calcula el código acá, desde la base.
# El modelo solo redacta con esto; el verificador compara contra esto mismo.
import datetime as dt
import json
import statistics

from app import db, taxonomy

PERIOD_DAYS = 28


def _period(now: dt.datetime, period: str | None) -> tuple[dt.date, dt.date]:
    if period:
        start, end = period.split("/")
        return dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    end = now.date()
    return end - dt.timedelta(days=PERIOD_DAYS - 1), end


def _day(value: str | None) -> str | None:
    return db.from_db(value).date().isoformat() if value else None


def build(patient_id: int, now: dt.datetime, period: str | None = None) -> dict:
    start, end = _period(now, period)
    since = db.to_db(dt.datetime.combine(start, dt.time(0), now.tzinfo))
    until = db.to_db(dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0), now.tzinfo))
    with db.connect() as conn:
        patient = conn.execute("SELECT name FROM people WHERE id = ?", (patient_id,)).fetchone()
        meds = conn.execute("SELECT drug, times, changed_at, change_note FROM med_schedule WHERE patient_id = ?",
                            (patient_id,)).fetchall()
        steps = conn.execute(
            "SELECT substr(start, 1, 10) AS day, SUM(value) AS total FROM biometrics"
            " WHERE patient_id = ? AND kind = 'steps' AND start >= ? AND start < ? GROUP BY day ORDER BY day",
            (patient_id, since, until)).fetchall()
        goal = conn.execute("SELECT target FROM goals WHERE patient_id = ? AND metric = 'steps' AND active = 1",
                            (patient_id,)).fetchone()
        episodes = conn.execute("SELECT * FROM episodes WHERE patient_id = ? AND dose_time >= ? AND dose_time < ?"
                                " ORDER BY dose_time", (patient_id, since, until)).fetchall()
        tests = conn.execute("SELECT metrics, taken_at FROM tests WHERE patient_id = ? AND type = 'golpeteo'"
                             " AND taken_at < ? ORDER BY taken_at", (patient_id, until)).fetchall()
        voices = conn.execute(
            "SELECT p.role, COUNT(*) AS n FROM entries e JOIN people p ON p.id = e.speaker_id"
            " WHERE e.patient_id = ? AND e.created_at >= ? AND e.created_at < ? GROUP BY p.role",
            (patient_id, since, until)).fetchall()
        alerts = conn.execute("SELECT lane, rule_id, text, reserved, created_at FROM alerts"
                              " WHERE patient_id = ? AND created_at >= ? AND created_at < ? ORDER BY created_at",
                              (patient_id, since, until)).fetchall()
        events = conn.execute(
            "SELECT ev.*, e.created_at AS told_at, p.name AS speaker_name, p.relation AS speaker_relation"
            " FROM events ev JOIN entries e ON e.id = ev.entry_id JOIN people p ON p.id = e.speaker_id"
            " WHERE ev.patient_id = ? AND e.created_at >= ? AND e.created_at < ? ORDER BY e.created_at",
            (patient_id, since, until)).fetchall()

    target = goal["target"] if goal else None
    daily = [{"date": r["day"], "steps": round(r["total"])} for r in steps]
    in_goal = [d for d in daily if target and d["steps"] >= target]

    rates = [(t["taken_at"], json.loads(t["metrics"]).get("taps_per_s")) for t in tests]
    rates = [(at, r) for at, r in rates if r is not None]
    in_period = [r for at, r in rates if at >= since]
    tapping = None
    if rates:
        tapping = {"sessions_in_period": len(in_period), "sessions_total": len(rates),
                   "median_taps_per_s": round(statistics.median(r for _, r in rates), 1),
                   "last_taps_per_s": round(rates[-1][1], 1), "last_date": _day(rates[-1][0])}

    deviations = []
    for ep in episodes:
        dev = json.loads(ep["deviation"]) if ep["deviation"] else {}
        exp = json.loads(ep["explanation"]) if ep["explanation"] else {}
        dose = db.from_db(ep["dose_time"])
        deviations.append({"date": dose.date().isoformat(), "dose": f"{dose:%H:%M}",
                           "observed_steps": dev.get("observed"), "usual_steps": dev.get("median"),
                           "pct_change": dev.get("pct_change"), "explained": bool(exp.get("explained")),
                           "explained_by": exp.get("by") or [], "status": ep["status"],
                           "entry_ids": json.loads(ep["entry_ids"] or "[]")})

    medication = []
    for m in meds:
        item = {"drug": m["drug"], "times": json.loads(m["times"] or "[]")}
        if m["changed_at"]:
            changed = db.from_db(m["changed_at"]).date()
            item.update(changed_at=changed.isoformat(), days_since_change=(end - changed).days, note=m["change_note"])
        medication.append(item)

    changes = [db.from_db(m["changed_at"]).date() for m in meds if m["changed_at"]]
    last_change = max(changes) if changes else None

    def days_since_change(e) -> int | None:
        when = db.from_db(e["occurred_at"] or e["told_at"]).date()
        return (when - last_change).days if last_change and when >= last_change else None

    return {
        "patient": {"id": patient_id, "name": patient["name"] if patient else None},
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1,
                   "label": f"{start.isoformat()}/{end.isoformat()}", "text": f"{start:%d/%m} al {end:%d/%m}"},
        "medication": medication,
        "steps": {"goal": target, "days_with_data": len(daily), "days_in_goal": len(in_goal),
                  "median_daily": round(statistics.median(d["steps"] for d in daily)) if daily else None,
                  "daily": daily},
        "deviations": deviations,
        "tapping": tapping,
        "entries_by_voice": {r["role"]: r["n"] for r in voices},
        "alerts": [{"lane": a["lane"], "rule_id": a["rule_id"], "date": _day(a["created_at"]), "text": a["text"],
                    "reserved": bool(a["reserved"])} for a in alerts],
        "events": [{"id": e["id"], "told_at": e["told_at"], "occurred_at": e["occurred_at"],
                    "time_vague": bool(e["time_vague"]), "speaker": e["speaker_role"],
                    "speaker_name": e["speaker_name"], "speaker_relation": e["speaker_relation"],
                    "domain": e["domain"], "domain_label": taxonomy.label(e["domain"]), "symptom": e["symptom"],
                    "negated": bool(e["negated"]), "foreign_attribution": e["foreign_attribution"],
                    "quote": e["quote"], "is_new": bool(e["is_new"]), "reserved": bool(e["reserved"]),
                    "days_since_med_change": days_since_change(e)}
                   for e in events],
    }

# Los facts del informe (CLAUDE.md §5.5): todo lo que tiene una cifra lo calcula el código acá, desde la base.
# build() junta los datos crudos; present() los deja como strings listos para copiar ("1.300", "69–71%", "13/10"):
# el modelo no redondea ni calcula, y el validador de report exige que cada número del texto esté literal acá.
import datetime as dt
import json
import statistics

from app import config, db, taxonomy
from app.pipeline.when import part_of
from app.rules.triggers import fmt_dec, fmt_int

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
    return present(collect(patient_id, now, period))


def collect(patient_id: int, now: dt.datetime, period: str | None = None) -> dict:
    """Datos crudos del período (números como números)."""
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
        notes = conn.execute("SELECT date, text, follow_up FROM daily_notes WHERE patient_id = ? AND date >= ? "
                             "AND date <= ? ORDER BY date", (patient_id, start.isoformat(), end.isoformat())).fetchall()

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
        "events": [{"id": e["id"], "entry_id": e["entry_id"], "told_at": e["told_at"], "occurred_at": e["occurred_at"],
                    "time_vague": bool(e["time_vague"]), "speaker": e["speaker_role"],
                    "speaker_name": e["speaker_name"], "speaker_relation": e["speaker_relation"],
                    "domain": e["domain"], "domain_label": taxonomy.label(e["domain"]), "symptom": e["symptom"],
                    "negated": bool(e["negated"]), "foreign_attribution": e["foreign_attribution"],
                    "quote": e["quote"], "plain": e["plain"], "is_new": bool(e["is_new"]), "reserved": bool(e["reserved"]),
                    "days_since_med_change": days_since_change(e)}
                   for e in events],
        "daily_notes": [{"date": n["date"], "text": n["text"], "follow_up": json.loads(n["follow_up"] or "[]")}
                        for n in notes if n["text"]] if config.BITACORA_ENABLED else [],
        "wearable_week": wearable_week(patient_id, end),
    }


# ── Pulsera: la última semana contra los 28 días previos (mediana por noche o por día) ─────────────────────
WEARABLE_WEEK_DAYS = 7
# kind → (etiqueta, unidad); el sueño va en horas.
WEARABLE_WEEK_LABELS = {"sleep_minutes": ("Sueño por noche", "h"), "sleep_awakenings": ("Despertares por noche", ""),
                        "heart_rate_rest": ("Frecuencia en reposo", "lpm"), "active_minutes": ("Minutos activos por día", "min")}


def wearable_week(patient_id: int, end: dt.date) -> dict | None:
    """Mediana de cada métrica central de la pulsera en los últimos 7 días y en los 28 anteriores. None sin datos."""
    from app.rules import biometrics

    week_start = end - dt.timedelta(days=WEARABLE_WEEK_DAYS - 1)
    base_start = week_start - dt.timedelta(days=config.DEVIATION_BASELINE_DAYS)
    values, sources = biometrics._by_day(patient_id, base_start, end)
    metrics, used = [], set()
    for kind in config.WEARABLE_CORE:
        week = [v for d, v in values.get(kind, {}).items() if d >= week_start]
        base = [v for d, v in values.get(kind, {}).items() if d < week_start]
        if not week:
            continue
        used |= {s for (k, d), ss in sources.items() if k == kind for s in ss}
        metrics.append({"kind": kind, "week": statistics.median(week), "week_days": len(week),
                        "baseline": statistics.median(base) if base else None, "baseline_days": len(base)})
    if not metrics:
        return None
    return {"week_start": week_start.isoformat(), "week_end": end.isoformat(), "baseline_start": base_start.isoformat(),
            "baseline_end": (week_start - dt.timedelta(days=1)).isoformat(), "sources": sorted(used),
            "simulated": "simulado" in used, "metrics": metrics}


def _num(x: float) -> str:
    return fmt_int(x) if round(x, 1) == round(x) else fmt_dec(x)


def present_wearable(raw: dict | None) -> dict | None:
    """La semana de la pulsera como strings ("6,1" horas, "3" despertares) con su rótulo."""
    if not raw:
        return None

    def value(kind: str, v: float | None) -> str | None:
        if v is None:
            return None
        return fmt_dec(v / 60) if kind == "sleep_minutes" else _num(v)

    rotulo = "pulsera · simulado" if raw["simulated"] else "pulsera"
    return {
        "label": "según la pulsera (simulado)" if raw["simulated"] else "según la pulsera",
        "rotulo": rotulo, "simulated": raw["simulated"],
        "week": f"{_ddmm(raw['week_start'])} al {_ddmm(raw['week_end'])}",
        "baseline": f"{_ddmm(raw['baseline_start'])} al {_ddmm(raw['baseline_end'])}",
        "metrics": [{"kind": m["kind"], "label": WEARABLE_WEEK_LABELS[m["kind"]][0], "unit": WEARABLE_WEEK_LABELS[m["kind"]][1],
                     "week": value(m["kind"], m["week"]), "baseline": value(m["kind"], m["baseline"]),
                     "week_days": str(m["week_days"]), "baseline_days": str(m["baseline_days"])}
                    for m in raw["metrics"]],
    }


# ── Presentación: strings listos para copiar ──────────────────────────────────────────────────────────

_DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _ddmm(iso: str | None) -> str | None:
    return dt.date.fromisoformat(iso[:10]).strftime("%d/%m") if iso else None


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1] if items else ""


def _range(values: list[float], fmt, suffix: str = "") -> str | None:
    if not values:
        return None
    lo, hi = fmt(min(values)), fmt(max(values))
    return f"{lo}{suffix}" if lo == hi else f"{lo}–{hi}{suffix}"


# La etiqueta como sustantivo, para contar ("7 relatos sobre actuar los sueños", no "de que actúa los sueños").
_SYMPTOM_NOUNS = {"actua_suenos": "actuar los sueños"}


def symptom_noun(symptom: str) -> str:
    label = taxonomy.symptom_label(symptom)
    return _SYMPTOM_NOUNS.get(symptom) or (label[4:] if label.startswith("que ") else label)


def _label(role: str, name: str | None, relation: str | None) -> str:
    if role == "paciente" or not relation:
        return name or role
    return f"{name}, su {relation}"


def present(raw: dict) -> dict:
    """Facts crudos → facts para el modelo: cada cifra como string, cada voz con su nombre."""
    events = raw.get("events", [])
    patient_name = (raw.get("patient") or {}).get("name") or "el paciente"
    voices = {"paciente": patient_name}
    for e in events:
        voices.setdefault(e["speaker"], _label(e["speaker"], e.get("speaker_name"), e.get("speaker_relation")))

    def event_date(e) -> str:
        return (e.get("occurred_at") or e["told_at"])[:10]

    def night_of(e) -> str | None:
        """La noche a la que pertenece un evento de sueño: una madrugada es de la noche anterior."""
        occurred = e.get("occurred_at")
        if not occurred or e["domain"] != "sueno":
            return None
        when = db.from_db(occurred)
        day = when.date() - dt.timedelta(days=1) if when.hour < 12 else when.date()
        return day.strftime("%d/%m")

    out_events = []
    for e in events:
        occurred = e.get("occurred_at")
        vague = bool(e.get("time_vague"))
        out_events.append({
            "id": e["id"], "speaker": e["speaker"], "speaker_label": voices[e["speaker"]],
            "date": _ddmm(occurred[:10]) if occurred else None, "told_date": _ddmm(e["told_at"]),
            "habitual": occurred is None,
            "time": db.from_db(occurred).strftime("%H:%M") if occurred and not vague else None,
            "part": part_of(db.from_db(occurred) if occurred else None, vague),
            "night": night_of(e),
            "domain_label": e.get("domain_label") or taxonomy.label(e["domain"]), "symptom": e["symptom"],
            "symptom_label": taxonomy.symptom_label(e["symptom"]),   # para leer: "que actúa los sueños"
            "negated": e["negated"], "foreign_attribution": e.get("foreign_attribution"), "quote": e["quote"],
            "plain": e.get("plain"),
            "is_new": e["is_new"], "reserved": e["reserved"],
            "days_since_med_change": None if e.get("days_since_med_change") is None else str(e["days_since_med_change"]),
        })
    nights = sorted({ev["night"] for ev, raw_e in zip(out_events, events)
                     if ev["night"] and not ev["negated"] and not ev["reserved"]
                     and raw_e["symptom"] in ("despertares_nocturnos", "insomnio", "actua_suenos")},
                    key=lambda d: (d[3:], d[:2]))
    nights_summary = {"count": str(len(nights)), "dates": _join(nights)} if nights else None

    # Conteos por síntoma (lo afirmado, no lo negado), para que "1 caída" o "2 relatos de…" sean verificables.
    by_symptom: dict[tuple[str, bool], list[dict]] = {}
    for ev in out_events:
        if not ev["negated"]:
            by_symptom.setdefault((ev["symptom"], bool(ev["reserved"])), []).append(ev)
    event_counts = [{"symptom": sym, "symptom_label": taxonomy.symptom_label(sym), "symptom_noun": symptom_noun(sym),
                     "domain_label": evs[0]["domain_label"],
                     "count": str(len(evs)),
                     "dates": _join(sorted({ev["date"] or ev["told_date"] for ev in evs}, key=lambda d: (d[3:], d[:2]))),
                     "reserved": reserved}
                    for (sym, reserved), evs in sorted(by_symptom.items())]

    deviations = []
    for d in raw.get("deviations", []):
        # Relato sobre ese episodio: la respuesta a la pregunta (entry_ids) o lo que lo explicó (explained_by).
        answered = set(d.get("entry_ids") or [])
        by = d.get("explained_by") or []
        stories = [e for e in events if (e.get("entry_id") is not None and e["entry_id"] in answered)
                   or any(q and (q in e["quote"] or e["quote"] in q) for q in by)]
        start = int(d["dose"][:2])
        deviations.append({
            "date": _ddmm(d["date"]), "weekday": _DAYS[dt.date.fromisoformat(d["date"]).weekday()],
            "dose": str(start), "window": f"{start} a {start + 2} h",
            "steps_after_dose": None if d.get("observed_steps") is None else fmt_int(d["observed_steps"]),
            "usual_steps": None if d.get("usual_steps") is None else fmt_int(d["usual_steps"]),
            "pct_change": None if d.get("pct_change") is None else f"{fmt_int(abs(_pct(d['pct_change'])))}%",
            "story": f"con relato de {voices[stories[0]['speaker']].split(',')[0]}" if stories else "sin relato",
            "story_quote": stories[0]["quote"] if stories else None,
        })
    summary = None
    if deviations:
        raw_devs = raw["deviations"]
        with_story = sum(1 for d in deviations if d["story_quote"])
        summary = {
            "count": str(len(deviations)), "dates": _join([d["date"] for d in deviations]),
            "pct_change_range": _range([abs(_pct(d["pct_change"])) for d in raw_devs if d.get("pct_change") is not None],
                                       fmt_int, "%"),
            "steps_after_dose_range": _range([d["observed_steps"] for d in raw_devs if d.get("observed_steps") is not None],
                                             fmt_int),
            "with_story": str(with_story), "without_story": str(len(deviations) - with_story),
        }

    st = raw.get("steps") or {}
    tp = raw.get("tapping")
    return {
        "patient": {"name": patient_name},
        "period": {"label": raw["period"]["label"], "text": raw["period"]["text"],
                   "days": str(raw["period"].get("days", ""))},
        "voices": voices,
        "medication": [{"drug": m["drug"],
                        "times": _join([t.split(":")[0].lstrip("0") or "0" for t in m.get("times", [])]),
                        "changed": _ddmm(m.get("changed_at")),
                        "days_since_change": None if m.get("days_since_change") is None else str(m["days_since_change"]),
                        "note": m.get("note")} for m in raw.get("medication", [])],
        "steps": {"goal": None if st.get("goal") is None else fmt_int(st["goal"]),
                  "days_with_data": str(st.get("days_with_data", 0)), "days_in_goal": str(st.get("days_in_goal", 0)),
                  "median_daily": None if st.get("median_daily") is None else fmt_int(st["median_daily"]),
                  "daily": [{"date": _ddmm(d["date"]), "steps": fmt_int(d["steps"])} for d in st.get("daily", [])]},
        "deviations": deviations,
        "deviations_summary": summary,
        "nights_with_awakenings": nights_summary,
        "event_counts": event_counts,
        "deviations_in_previous_weeks": str(raw.get("deviations_in_previous_weeks", "")) or None,
        "tapping": None if not tp else {
            "sessions_in_period": str(tp["sessions_in_period"]), "median_taps_per_s": fmt_dec(tp["median_taps_per_s"]),
            "last_taps_per_s": fmt_dec(tp["last_taps_per_s"]), "last_date": _ddmm(tp.get("last_date"))},
        "entries_by_voice": [{"voice": voices.get(role, role), "entries": str(n)}
                             for role, n in (raw.get("entries_by_voice") or {}).items()],
        "alerts": [{"rule_id": a["rule_id"], "lane": a["lane"], "date": _ddmm(a.get("date")), "text": a["text"],
                    "reserved": a["reserved"]} for a in raw.get("alerts", [])],
        "events": out_events,
        "bitacora": _bitacora(raw.get("daily_notes") or []),
        "wearable_week": present_wearable(raw.get("wearable_week")),
    }


BITACORA_USE = ("Notas de la revisión diaria (redactadas por IA y verificadas por el código), una por noche. Son el "
                "hilo conductor del período: qué se fue anotando y retomando. No son evidencia ni fuente de cifras: "
                "las cifras y las citas salen del resto de facts.")


def _bitacora(notes: list[dict]) -> dict | None:
    """Las notas del período, sin los refs del digest (otro espacio de ids). Sus cifras no cuentan como facts."""
    if not notes:
        return None
    from app.rules.note import REF

    def clean(text: str) -> str:
        return " ".join(REF.sub("", text).split()).replace(" .", ".").replace(" ,", ",")
    return {"uso": BITACORA_USE, "notas": [{"fecha": _ddmm(n["date"]), "texto": clean(n["text"]),
                                           "seguir_mirando": n["follow_up"]} for n in notes]}


def _pct(value: float) -> float:
    """Deviation.pct_change viene como fracción (-0.68) o como porcentaje (-68): siempre porcentaje."""
    return value * 100 if abs(value) <= 1 else value

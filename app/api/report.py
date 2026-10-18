"""GET /api/patients/{id}/report y /technical: el informe (Report de pipeline.report, ya verificado) y los
metadatos que calcula el código (cifras, medicación, fuentes, pasos, golpeteo, avisos, evidencia)."""
import datetime as dt
import json
import re
import statistics

from fastapi import APIRouter, HTTPException

from app.api import _store as store
from app.config import TZ
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
        summary=("Desde que se subió el pramipexol, el 03/10, la semana de Juan se mantuvo estable hasta la última: "
                 "el martes 13, el jueves 15 y el viernes 16 se movió bastante menos en las dos horas siguientes a la toma "
                 "de las 16. El jueves él lo explicó: «me sentí trabado, me costó salir a caminar»; los otros dos días "
                 "quedaron sin explicación. En la misma semana apareció algo nuevo: Marta contó dos veces que Juan ve "
                 "personas que no están durante la noche, y lo marcó para hablarlo en privado. Juan no lo mencionó. "
                 "Durmió mal tres de siete noches y llegó a su meta de pasos 15 de 28 días. El juego de golpeteo se "
                 "mantuvo estable."),
        topics=[
            {"title": "Ve personas que no están, de noche",
             "narrative": ("Es la primera vez en el historial. Aparece a los 11 días del aumento de pramipexol y solo en el "
                           "relato de Marta, que lo cuenta las dos veces de noche y con confusión al despertar. Juan, "
                           "consultado por el sueño en la misma semana, habla de «sueños raros» y no menciona ver a nadie. "
                           "No hay fiebre ni caídas registradas esos días."),
             "observed": ["Nuevo desde el 03/10", "2 relatos de Marta"],
             "voices": {"Juan": "Duermo bastante bien. A veces sueño cosas raras.",
                        "Marta, su esposa": "Anoche se levantó dos veces medio confundido, me dijo que había un hombre en el patio."},
             "question": "¿Desde cuándo pasa y qué hace usted cuando los ve?", "evidence_ids": [101, 102, 103], "reserved": True},
            {"title": "Menos actividad después de la toma de las 16",
             "narrative": ("En las cuatro semanas previas, entre las 16 y las 18 h Juan caminaba unos 1.300 pasos. Esta "
                           "semana bajó a la mitad o menos tres veces en cinco días. Cuando la app le preguntó el jueves, "
                           "contó que se sintió trabado. Ningún otro tramo del día muestra el mismo patrón."),
             "observed": ["3 episodios · 1 explicado"],
             "voices": {"Juan": "Me sentí trabado, me costó salir a caminar."},
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
    verification_note = None
    rep = store.latest_report(patient_id) if real else None
    if rep and rep.get("content"):
        report = Report.model_validate(rep["content"])
        generated_at = rep["created_at"]
        ids = sorted({i for t in report.topics for i in t.evidence_ids})
        evidence = {i: {"name": r["name"], "role": r["role"], "at": r["occurred_at"] or r["created_at"],
                        "quote": r["quote"], "reserved": bool(r["reserved"]),
                        "vague": bool(r["occurred_at"] and r["time_vague"])}   # hora vaga: solo la fecha
                    for i, r in store.evidence(ids).items()}
        report_simulated = False
        report_status = "listo"
        if rep["content"].get("redaccion") == "codigo":
            # Informe mínimo (pipeline.report): la IA no pudo redactarlo; las cifras del código se muestran igual.
            report_status = "sin_redaccion"
            verification_note = ("Este informe no tiene texto redactado por IA: lo que se ve son datos y cifras "
                                 "calculados por código.")
    elif real:
        # Base real sin informe todavía (pipeline.report lo genera en segundo plano): vacío, nunca el de ejemplo.
        report, evidence = Report(summary="", topics=[], removed_count=0), {}
        report_simulated = False
        report_status = "pendiente"
    else:
        # Sin base (desarrollo): el informe del lienzo de diseño, rotulado como ejemplo.
        report, evidence = _fake_report()
        report_simulated = True
        report_status = "ejemplo"

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
        # Informe v2 (docs/PULIDO.md §3): todo calculado por código, sin IA.
        "avisos": notices(alerts, meds),
        "lo_que_notamos": noticed(patient_id, start, end, now) if real else [],
        "pulsera": wearable_week(patient_id, end) if real else None,
        "cobertura": coverage(patient_id, start, end, now) if real else None,
        "desde_el_cambio": since_change(patient_id, now) if real else None,
        "lo_que_no_sabemos": unknowns(patient_id, start, end, now) if real else None,
        "simulated": report_simulated or not real,
        "report_simulated": report_simulated,
        "report_status": report_status,     # listo | sin_redaccion (informe mínimo, sin IA) | pendiente (base real,
                                            # sin informe aún) | ejemplo (sin base)
        "verification_note": verification_note,
    }


# ================================================================ informe v2: cifras del código
# Cobertura, "Desde el cambio" y "Lo que no sabemos". Leen la base directo (app.db) y no llaman a la IA.

AFTERNOON_DOSE = "16:00"     # la toma que mira el escenario (CLAUDE.md §3)
MIN_DAYS = 5                 # menos días de un lado: la comparación no es "suficiente"
MIN_TESTS = 3
_ROLE_ORDER = {"paciente": 0, "cuidador": 1, "familiar": 2}
_WAKE_SYMPTOMS = ("despertares_nocturnos", "insomnio")


def _db():
    from app import db

    return db


def _day_bounds(d: dt.date, tz) -> tuple[str, str]:
    db = _db()
    start = dt.datetime.combine(d, dt.time(0), tz)
    return db.to_db(start), db.to_db(start + dt.timedelta(days=1))


def _days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _miles(n) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def _ddmm(d) -> str:
    d = dt.date.fromisoformat(str(d)[:10])
    return f"{d.day:02d}/{d.month:02d}"


# Las claves de taxonomy.py van sin tildes; para leer, en castellano.
_SYMPTOM_TEXT = {"apatia": "apatía", "sudoracion": "sudoración", "deglucion": "problemas para tragar",
                 "actua_suenos": "que actúa los sueños", "despertares_nocturnos": "despertares de noche",
                 "somnolencia_diurna": "somnolencia de día", "confusion": "confusión", "cansancio": "cansancio",
                 "estrenimiento": "estreñimiento", "caida": "caída", "mareo_al_pararse": "mareo al pararse"}


def _symptom_text(symptom: str) -> str:
    from app import taxonomy

    return _SYMPTOM_TEXT.get(symptom) or taxonomy.symptom_label(symptom)


def _days_with_steps(conn, patient_id: int, days: list[dt.date], now: dt.datetime) -> set[dt.date]:
    """Días con pasos: los cubre una ventana de biometric_syncs (hasta ahora si es hoy) o tienen muestras."""
    db = _db()
    # Solo las ventanas de pasos (Atajo e importación): las de la pulsera tienen scope y no cuentan (§7.3).
    has_scope = "scope" in {r[1] for r in conn.execute("PRAGMA table_info(biometric_syncs)")}
    only_steps = " AND scope IS NULL" if has_scope else ""
    syncs = [(db.from_db(r["window_start"]), db.from_db(r["window_end"])) for r in conn.execute(
        "SELECT window_start, window_end FROM biometric_syncs WHERE patient_id = ?" + only_steps, (patient_id,))]
    with_samples = {dt.date.fromisoformat(r[0]) for r in conn.execute(
        "SELECT DISTINCT substr(start, 1, 10) FROM biometrics WHERE patient_id = ? AND kind = 'steps'", (patient_id,))}
    out = set()
    for d in days:
        lo = dt.datetime.combine(d, dt.time(0), now.tzinfo)
        hi = min(lo + dt.timedelta(days=1), now)
        if d in with_samples or any(ws <= lo and we >= hi for ws, we in syncs):
            out.add(d)
    return out


def coverage(patient_id: int, start: dt.date, end: dt.date, now: dt.datetime) -> dict:
    """Cobertura del período: días con pasos sincronizados, mediciones por fuente, relatos por voz y golpeteo."""
    db = _db()
    days = _days(start, end)
    lo, _ = _day_bounds(start, now.tzinfo)
    _, hi = _day_bounds(end, now.tzinfo)
    with db.connect() as conn:
        covered = _days_with_steps(conn, patient_id, days, now)
        sources = {r["source"]: r["n"] for r in conn.execute(
            "SELECT source, COUNT(*) AS n FROM biometrics WHERE patient_id = ? AND kind = 'steps' AND start >= ? AND start < ? "
            "GROUP BY source ORDER BY source", (patient_id, lo, hi))}
        voices = [dict(r) for r in conn.execute(
            "SELECT p.id AS person_id, p.name AS nombre, p.role AS rol, COUNT(e.id) AS n FROM entries e "
            "JOIN people p ON p.id = e.speaker_id WHERE e.patient_id = ? AND e.created_at >= ? AND e.created_at < ? "
            "GROUP BY p.id", (patient_id, lo, hi))]
        tests = conn.execute("SELECT COUNT(*) FROM tests WHERE patient_id = ? AND taken_at >= ? AND taken_at < ?",
                             (patient_id, lo, hi)).fetchone()[0]
    voices.sort(key=lambda v: (_ROLE_ORDER.get(v["rol"], 9), -v["n"]))
    parts = [f"Pasos: {len(covered)} de {len(days)} días sincronizados"]
    parts.append("relatos: " + (", ".join(f"{v['nombre']} {v['n']}" for v in voices) if voices else "ninguno"))
    parts.append(f"golpeteo: {tests} {'sesión' if tests == 1 else 'sesiones'}")
    return {
        "periodo": {"desde": start.isoformat(), "hasta": end.isoformat(), "dias": len(days)},
        "pasos": {"dias_con_datos": len(covered), "dias_total": len(days), "mediciones_por_fuente": sources},
        "relatos": {"total": sum(v["n"] for v in voices), "por_voz": voices},
        "golpeteo": {"sesiones": tests},
        "texto": " · ".join(parts),
    }


def _median_row(clave, etiqueta, unidad, before: list[float], after: list[float], min_n: int, decimals=0) -> dict:
    def med(xs):
        if not xs:
            return None
        m = statistics.median(xs)
        return round(m, decimals) if decimals else round(m)

    a, b = med(before), med(after)
    pct = round((b - a) / a * 100, 1) if a not in (None, 0) and b is not None else None
    return {"clave": clave, "etiqueta": etiqueta, "unidad": unidad, "antes": a, "despues": b, "cambio_pct": pct,
            "n_antes": len(before), "n_despues": len(after),
            "suficiente": len(before) >= min_n and len(after) >= min_n}


def _rate_row(clave, etiqueta, unidad, n_before: int, n_after: int, days_before: int, days_after: int) -> dict:
    def per_week(n, days):
        return round(n / days * 7, 1) if days > 0 else None

    return {"clave": clave, "etiqueta": etiqueta, "unidad": unidad,
            "antes": per_week(n_before, days_before), "despues": per_week(n_after, days_after), "cambio_pct": None,
            "n_antes": n_before, "n_despues": n_after,
            "suficiente": days_before >= MIN_DAYS and days_after >= MIN_DAYS}


def since_change(patient_id: int, now: dt.datetime) -> dict | None:
    """Antes contra después del último cambio de medicación (med_schedule.changed_at). None si no hubo cambio."""
    db = _db()
    today = now.date()
    with db.connect() as conn:
        med = conn.execute("SELECT drug, changed_at, change_note FROM med_schedule WHERE patient_id = ? AND changed_at IS NOT NULL "
                           "AND changed_at <= ? ORDER BY changed_at DESC LIMIT 1", (patient_id, db.to_db(now))).fetchone()
        if not med:
            return None
        change = db.from_db(med["changed_at"]).date()
        first = conn.execute("SELECT MIN(substr(start, 1, 10)) FROM biometrics WHERE patient_id = ? AND kind = 'steps'",
                             (patient_id,)).fetchone()[0]
        first_day = min(dt.date.fromisoformat(first), change) if first else change
        before_days = [d for d in _days(first_day, change - dt.timedelta(days=1))]
        after_days = _days(change, today)
        covered = _days_with_steps(conn, patient_id, before_days + after_days, now)

        # Pasos por día completo (hoy no cuenta: está a medias).
        daily = {dt.date.fromisoformat(r["d"]): r["v"] for r in conn.execute(
            "SELECT substr(start, 1, 10) AS d, SUM(value) AS v FROM biometrics WHERE patient_id = ? AND kind = 'steps' "
            "GROUP BY d", (patient_id,))}
        def steps(days):
            return [daily.get(d, 0.0) for d in days if d in covered and d < today]

        # Pasos en la ventana de 2 h después de la toma de la tarde, por día (si la ventana ya terminó).
        h0 = int(AFTERNOON_DOSE[:2])
        window = {dt.date.fromisoformat(r["d"]): r["v"] for r in conn.execute(
            "SELECT substr(start, 1, 10) AS d, SUM(value) AS v FROM biometrics WHERE patient_id = ? AND kind = 'steps' "
            "AND substr(start, 12, 2) >= ? AND substr(start, 12, 2) < ? GROUP BY d", (patient_id, f"{h0:02d}", f"{h0 + 2:02d}"))}
        window_closed = lambda d: d < today or now.hour >= h0 + 2  # noqa: E731
        def window_steps(days):
            return [window.get(d, 0.0) for d in days if d in covered and window_closed(d)]

        taps = [(db.from_db(r["taken_at"]).date(), json.loads(r["metrics"]).get("taps_per_s")) for r in conn.execute(
            "SELECT taken_at, metrics FROM tests WHERE patient_id = ? AND taken_at <= ?", (patient_id, db.to_db(now)))]

        def event_dates(where: str, args: tuple) -> list[dt.date]:
            rows = conn.execute(
                "SELECT DISTINCT substr(COALESCE(ev.occurred_at, en.created_at), 1, 10) AS d, ev.entry_id FROM events ev "
                "JOIN entries en ON en.id = ev.entry_id WHERE ev.patient_id = ? AND ev.negated = 0 AND " + where,
                (patient_id, *args)).fetchall()
            return [dt.date.fromisoformat(r["d"]) for r in rows]

        marks = ",".join("?" * len(_WAKE_SYMPTOMS))
        nights = set(event_dates(f"ev.domain = 'sueno' AND ev.symptom IN ({marks})", _WAKE_SYMPTOMS))
        neuro = event_dates("ev.domain = 'neuropsiquiatrico'", ())

    split = lambda xs: ([d for d in xs if first_day <= d < change], [d for d in xs if change <= d <= today])  # noqa: E731
    nights_b, nights_a = split(sorted(nights))
    neuro_b, neuro_a = split(neuro)
    taps_b = [v for d, v in taps if v is not None and first_day <= d < change]
    taps_a = [v for d, v in taps if v is not None and change <= d <= today]
    h_label = f"{h0} a {h0 + 2} h"
    return {
        "medicamento": med["drug"],
        "fecha": change.isoformat(),
        "hace_dias": (today - change).days,
        "nota": med["change_note"],
        "antes": {"desde": first_day.isoformat(), "hasta": (change - dt.timedelta(days=1)).isoformat(), "dias": len(before_days)},
        "despues": {"desde": change.isoformat(), "hasta": today.isoformat(), "dias": len(after_days)},
        "filas": [
            _median_row("pasos_dia", "Pasos por día (mediana)", "pasos", steps(before_days), steps(after_days), MIN_DAYS),
            _median_row("pasos_16_18", f"Pasos de {h_label} (mediana)", "pasos",
                        window_steps(before_days), window_steps(after_days), MIN_DAYS),
            _median_row("golpeteo", "Golpeteo (toques por segundo, mediana)", "toques/s", taps_b, taps_a, MIN_TESTS, decimals=1),
            _rate_row("noches_despertares", "Noches con despertares contadas (por semana)", "noches/semana",
                      len(nights_b), len(nights_a), len(before_days), len(after_days)),
            _rate_row("relatos_neuropsiquiatricos", "Relatos de alucinaciones o confusión (por semana)", "relatos/semana",
                      len(neuro_b), len(neuro_a), len(before_days), len(after_days)),
        ],
        "metodo": (f"Antes: días previos al cambio dentro de la historia disponible; después: desde el cambio hasta hoy. "
                   f"Pasos y golpeteo en mediana por día; relatos y noches por semana. 'suficiente' es falso con menos de "
                   f"{MIN_DAYS} días (o {MIN_TESTS} sesiones) de un lado."),
    }


def unknowns(patient_id: int, start: dt.date, end: dt.date, now: dt.datetime) -> dict:
    """Lo que no sabemos: días sin pasos, preguntas sin respuesta y lo que contó solo la familia."""
    from app import taxonomy

    db = _db()
    days = _days(start, end)
    lo, _ = _day_bounds(start, now.tzinfo)
    _, hi = _day_bounds(end, now.tzinfo)
    with db.connect() as conn:
        covered = _days_with_steps(conn, patient_id, days, now)
        questions = [dict(r) for r in conn.execute(
            "SELECT id, sent_at, rule_id, question, status FROM questions WHERE patient_id = ? "
            "AND status IN ('pendiente', 'enviada') AND (sent_at IS NULL OR (sent_at >= ? AND sent_at < ?)) ORDER BY sent_at",
            (patient_id, lo, hi))]
        rows = [dict(r) for r in conn.execute(
            "SELECT ev.id, ev.domain, ev.symptom, ev.speaker_role, ev.reserved, p.name, "
            "COALESCE(ev.occurred_at, en.created_at) AS at FROM events ev JOIN entries en ON en.id = ev.entry_id "
            "JOIN people p ON p.id = en.speaker_id WHERE ev.patient_id = ? AND ev.negated = 0 "
            "AND en.created_at >= ? AND en.created_at < ? ORDER BY at", (patient_id, lo, hi))]
    missing = [d for d in days if d not in covered]
    patient_symptoms = {r["symptom"] for r in rows if r["speaker_role"] == "paciente"}
    family: dict[str, dict] = {}
    for r in rows:
        if r["speaker_role"] == "paciente" or r["symptom"] in patient_symptoms:
            continue
        f = family.setdefault(r["symptom"], {"dominio": r["domain"], "dominio_label": taxonomy.label(r["domain"]),
                                             "sintoma": r["symptom"], "veces": 0, "quien": [], "ultima": None,
                                             "evidence_ids": [], "reservado": False})
        f["veces"] += 1
        if r["name"] not in f["quien"]:
            f["quien"].append(r["name"])
        f["ultima"] = max(f["ultima"] or "", r["at"][:10])
        f["evidence_ids"].append(r["id"])
        f["reservado"] = f["reservado"] or bool(r["reserved"])
    solo_familia = sorted(family.values(), key=lambda f: (not f["reservado"], -f["veces"], f["sintoma"]))

    textos = []
    if missing:
        listado = ", ".join(_ddmm(d) for d in missing[:6]) + ("…" if len(missing) > 6 else "")
        textos.append(f"Sin pasos sincronizados {len(missing)} {'día' if len(missing) == 1 else 'días'}: {listado}.")
    if questions:
        fechas = ", ".join(_ddmm(q["sent_at"]) for q in questions if q["sent_at"])
        n = len(questions)
        textos.append(f"{n} {'pregunta' if n == 1 else 'preguntas'} del sistema {'quedó' if n == 1 else 'quedaron'} "
                      f"sin respuesta" + (f" ({fechas})." if fechas else "."))
    patient_name = next((r["name"] for r in rows if r["speaker_role"] == "paciente"), None) or \
        (store.patient_person(patient_id) or {}).get("name", "el paciente")
    # En los textos, solo lo que pesa: repetido (2 o más) o reservado. El resto se cuenta en una línea;
    # la lista completa queda en `solo_la_familia`.
    shown = [f for f in solo_familia if f["veces"] >= 2 or f["reservado"]]
    for f in shown:
        quien = " y ".join(f["quien"])
        veces = f"{f['veces']} {'vez' if f['veces'] == 1 else 'veces'}"
        textos.append(f"{quien} contó {_symptom_text(f['sintoma'])} {veces}; {patient_name} no lo mencionó.")
    rest = len(solo_familia) - len(shown)
    if rest:
        textos.append(f"Y {rest} {'tema más' if rest == 1 else 'temas más'} que contó la familia una sola vez.")
    return {
        "dias_sin_pasos": [d.isoformat() for d in missing],
        "preguntas_sin_respuesta": [{"id": q["id"], "fecha": q["sent_at"], "regla": q["rule_id"], "pregunta": q["question"],
                                     "estado": q["status"]} for q in questions],
        "solo_la_familia": solo_familia,
        "textos": textos,
    }


# ================================================================ avisos con etiqueta (sin "Ámbar"/"Rojo")
# Un punto de color y una etiqueta que dice por qué importa. Los textos de los avisos los guarda rules.lanes; acá solo
# se presentan: A2 en una fila, A1 con la fecha del relato y los días desde el cambio en días de calendario.

NOTICE_LABELS = {"rojo": "Puede ser urgente", "A1": "Primera vez", "A2": "Nuevo desde el cambio", "A3": "Se repite"}
_A1 = re.compile(r"^Primera mención de (.+) \(contado por (.+) el \d\d/\d\d\)\.?$")
_A2 = re.compile(r"^Síntoma nuevo a -?\d+ días? del cambio de (.+?): (.+?)\.?$")


def _local_date(value: str) -> dt.date:
    return dt.datetime.fromisoformat(value).astimezone(TZ).date()


def _plain_symptom(label: str) -> str:
    return label[4:] if label.startswith("que ") else label


def notices(alerts: list[dict], meds: list[dict]) -> list[dict]:
    """Avisos del período para el informe, en orden: urgentes, primera vez, nuevos desde el cambio (una fila), se repite."""
    changes = {m["drug"]: dt.date.fromisoformat(m["changed"]["date"]) for m in meds if m.get("changed")}
    urgent, first, repeats, a2 = [], [], [], []
    for a in alerts:
        date = _local_date(a["created_at"])
        item = {"kind": "rojo" if a["lane"] == "rojo" else a["rule_id"], "fecha": date.isoformat(),
                "texto": a["text"], "reserved": bool(a.get("reserved"))}
        if a["lane"] == "rojo":
            item["texto"] = a["text"].split(":")[0]
            urgent.append(item)
        elif a["rule_id"] == "A1":
            m = _A1.match(a["text"])
            if m:   # la fecha del relato (created_at), no la de la noche a la que se refiere
                item["texto"] = f"Primera mención de {m.group(1)} (contado por {m.group(2)} el {_ddmm(date)})."
            first.append(item)
        elif a["rule_id"] == "A2":
            m = _A2.match(a["text"])
            drug, label = (m.group(1), _plain_symptom(m.group(2))) if m else (None, a["text"])
            change = changes.get(drug) or (max(changes.values()) if changes else None)
            a2.append({"fecha": date.isoformat(), "sintoma": label, "reserved": item["reserved"], "change": change,
                       "dias": (date - change).days if change else None})
        elif a["rule_id"] == "A3":
            repeats.append(item)
    out = urgent + first
    if a2:
        labels = list(dict.fromkeys(x["sintoma"] for x in a2))      # sin repetir, en orden de aparición
        change = a2[0]["change"]
        head = f"Síntomas nuevos desde el cambio del {_ddmm(change)}" if change else "Síntomas nuevos desde el cambio"
        out.append({"kind": "A2", "fecha": a2[0]["fecha"], "texto": f"{head}: {', '.join(labels)}.",
                    "reserved": any(x["reserved"] for x in a2),
                    "detalle": [{k: x[k] for k in ("fecha", "sintoma", "dias", "reserved")} for x in a2]})
    out += repeats
    for item in out:
        item["etiqueta"] = NOTICE_LABELS.get(item["kind"], "Para mirar")
    return out


# ================================================================ lo que notamos y lo que nos contaron
# Una fila por episodio (desvío después de una toma) o pregunta proactiva del período. Todo por código: qué detectó
# (con sus cifras), a quién se le preguntó, la respuesta literal y si quedó explicado.

_RULE_WHAT = {"P-NOCHES": "Noches malas contadas", "P-SILENCIO": "Días sin relatos", "P-JUEGO": "Golpeteo más lento",
              "P-REPITE": "Algo que se repite", "P-SUENO": "Noche distinta", "P-PATRON": "Patrón de la revisión diaria"}
_EXPLAINED = {"explicado", "respondido"}


def noticed(patient_id: int, start: dt.date, end: dt.date, now: dt.datetime) -> list[dict]:
    db = _db()
    lo, _ = _day_bounds(start, now.tzinfo)
    _, hi = _day_bounds(end, now.tzinfo)
    with db.connect() as conn:
        people = {r["id"]: dict(r) for r in conn.execute("SELECT id, name, role FROM people WHERE patient_id = ?",
                                                          (patient_id,))}
        episodes = [dict(r) for r in conn.execute(
            "SELECT * FROM episodes WHERE patient_id = ? AND dose_time >= ? AND dose_time < ? ORDER BY dose_time",
            (patient_id, lo, hi))]
        questions = {r["id"]: dict(r) for r in conn.execute(
            "SELECT * FROM questions WHERE patient_id = ? AND sent_at >= ? AND sent_at < ? ORDER BY sent_at",
            (patient_id, lo, hi))}

        def entry(entry_id):
            if not entry_id:
                return None
            e = conn.execute("SELECT id, speaker_id, raw_text, created_at FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if not e:
                return None
            ev = conn.execute("SELECT id, reserved FROM events WHERE entry_id = ? ORDER BY id LIMIT 1", (entry_id,)).fetchone()
            return {**dict(e), "event_id": ev["id"] if ev else None, "reserved": bool(ev and ev["reserved"])}

        rows = []
        seen_questions = set()
        for ep in episodes:
            dev = json.loads(ep["deviation"]) if ep["deviation"] else {}
            exp = json.loads(ep["explanation"]) if ep["explanation"] else {}
            dose = db.from_db(ep["dose_time"])
            q = questions.get(ep["question_id"]) if ep["question_id"] else None
            if q:
                seen_questions.add(q["id"])
            what = f"Después de la toma de las {dose.hour}"
            if dev.get("observed") is not None:
                what += f": {_miles(dev['observed'])} pasos"
                if dev.get("median") is not None:
                    what += f"; lo habitual ≈ {_miles(dev['median'])}"
            answer = entry(q["answered_entry_id"]) if q and q.get("answered_entry_id") else None
            if answer is None:
                answer = next((x for x in (entry(i) for i in json.loads(ep["entry_ids"] or "[]")) if x), None)
            by = exp.get("by") or []
            rows.append(_noticed_row(dose, "P-DESVIO", what, "pasos del teléfono", people.get(q["to_person_id"]) if q else None,
                                     q, answer, by if exp.get("explained") else [],
                                     explained=ep["status"] in _EXPLAINED or bool(exp.get("explained")), people=people))
        for q in questions.values():
            if q["id"] in seen_questions or q["rule_id"] == "P-DESVIO":
                continue
            if not q["question"]:     # explicado por lo que ya contaron: no se preguntó
                continue
            answer = entry(q.get("answered_entry_id"))
            source = "pulsera · simulado" if q["rule_id"] == "P-SUENO" and _wearable_simulated(conn, patient_id) else (
                "pulsera" if q["rule_id"] == "P-SUENO" else None)
            what = _RULE_WHAT.get(q["rule_id"], q["rule_id"]) + (f": {q['why']}" if q["why"] else "")
            rows.append(_noticed_row(db.from_db(q["sent_at"]), q["rule_id"], what, source, people.get(q["to_person_id"]),
                                     q, answer, [], explained=answer is not None, people=people))
    rows.sort(key=lambda r: r["at"])
    return rows


def _wearable_simulated(conn, patient_id: int) -> bool:
    return conn.execute("SELECT 1 FROM biometrics WHERE patient_id = ? AND source = 'simulado' LIMIT 1",
                        (patient_id,)).fetchone() is not None


def _noticed_row(at: dt.datetime, rule_id: str, what: str, source: str | None, to: dict | None, q: dict | None,
                 answer: dict | None, explained_by: list[str], *, explained: bool, people: dict) -> dict:
    asked = to["name"] if to else None
    if answer:
        who = people.get(answer["speaker_id"], {}).get("name", "")
        reply = {"cita": answer["raw_text"], "quien": who, "event_id": answer["event_id"], "reserved": answer["reserved"],
                 "label": _evidence_label({"name": who, "at": answer["created_at"]})}
    elif explained_by:
        reply = {"cita": explained_by[0], "quien": None, "event_id": None, "reserved": False, "label": "Lo que ya habían contado"}
    else:
        reply = None
    return {"at": at.isoformat(), "fecha": at.date().isoformat(), "regla": rule_id, "detecto": what, "fuente": source,
            "pregunta_a": asked if q and q.get("question") else None,
            "pregunta": q["question"] if q and q.get("question") else None,
            "respuesta": reply, "resultado": "explicado" if explained else "sin explicar"}


def wearable_week(patient_id: int, end: dt.date) -> dict | None:
    """La semana de la pulsera para la sección de datos (mismo cálculo que los facts de pipeline.report)."""
    from app.pipeline import report_facts

    return report_facts.present_wearable(report_facts.wearable_week(patient_id, end))


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
        "pulsera": wearable_series(patient_id, start, end, now) if real else None,
        "simulated": not real,
    }


# ================================================================ pulsera (vista técnica)
# Métricas de data/mock_wearable.py (franco/pulsera). Las noches van de las 23 del día anterior a las 7: cada una
# se identifica por el día en que termina. Si no hay muestras, las listas quedan vacías.

WEARABLE_NIGHTLY = ("sleep_minutes", "sleep_awakenings", "heart_rate_rest", "hrv_ms", "spo2_pct", "resp_rate")
WEARABLE_DAILY = ("active_minutes",)
# Temblor y discinesia no se muestran (CLAUDE.md §8: requieren algoritmos validados). La ingesta los acepta, pero la
# API técnica no los devuelve: por eso no hay series por hora.
WEARABLE_HOURLY: tuple[str, ...] = ()
WEARABLE_LABELS = {
    "sleep_minutes": ("Sueño", "min"), "sleep_awakenings": ("Despertares", "veces"),
    "heart_rate_rest": ("Frecuencia cardíaca en reposo", "lpm"), "hrv_ms": ("Variabilidad cardíaca (HRV)", "ms"),
    "spo2_pct": ("Saturación de oxígeno", "%"), "resp_rate": ("Respiración", "rpm"),
    "active_minutes": ("Minutos activos", "min"),
}


def wearable_series(patient_id: int, start: dt.date, end: dt.date, now: dt.datetime) -> dict:
    """Series de la pulsera para la vista técnica: por noche, por día y por hora, con su fuente y cantidad."""
    db = _db()
    lo, _ = _day_bounds(start - dt.timedelta(days=1), now.tzinfo)     # la primera noche empieza el día anterior
    _, hi = _day_bounds(end, now.tzinfo)
    kinds = WEARABLE_NIGHTLY + WEARABLE_DAILY + WEARABLE_HOURLY
    marks = ",".join("?" * len(kinds))
    with db.connect() as conn:
        rows = conn.execute(
            f'SELECT kind, value, start, "end", source FROM biometrics WHERE patient_id = ? AND kind IN ({marks}) '
            f"AND start >= ? AND start < ? AND start <= ? ORDER BY start", (patient_id, *kinds, lo, hi, db.to_db(now))).fetchall()
    nights: dict[str, dict] = {}
    days: dict[str, dict] = {}
    hours: dict[str, dict] = {}
    count: dict[str, int] = {}
    sources: set[str] = set()
    for r in rows:
        k, v = r["kind"], r["value"]
        count[k] = count.get(k, 0) + 1
        sources.add(r["source"])
        if k in WEARABLE_NIGHTLY:
            night = r["end"][:10]
            if start.isoformat() <= night <= end.isoformat():
                nights.setdefault(night, {"date": night})[k] = v
        elif k in WEARABLE_DAILY:
            days.setdefault(r["start"][:10], {"date": r["start"][:10]})[k] = v
        else:
            hours.setdefault(r["start"][:13], {"hour": r["start"][:13]})[k] = v
    # Perfil por hora del día (promedio del período): donde se ve el temblor de 16 a 18 h.
    profile = []
    for h in range(24):
        hh = [x for key, x in hours.items() if key[11:13] == f"{h:02d}"]
        profile.append({"hour": h, **{k: round(statistics.fmean([x[k] for x in hh if k in x]), 1)
                                      for k in WEARABLE_HOURLY if any(k in x for x in hh)}})
    return {
        "fuentes": sorted(sources),
        "simulado": "simulado" in sources,
        "mediciones": count,
        "etiquetas": {k: {"texto": t, "unidad": u} for k, (t, u) in WEARABLE_LABELS.items()},
        "noches": [nights[k] for k in sorted(nights)],
        "dias": [days[k] for k in sorted(days)],
        "por_hora": [hours[k] for k in sorted(hours)],
        "perfil_hora": profile if hours else [],
    }


@router.get("/patients/{patient_id}/technical")
def technical(patient_id: int):
    return build_technical(patient_id)

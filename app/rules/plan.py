# Modo 2 (plan diario): "libre para pensar, atada para actuar, obligada a mostrar la evidencia".
# La IA propone hipótesis y acciones (pipeline.daily_plan). Este módulo, código puro con tests, decide:
#   test_hypothesis: mide la métrica en TODOS los días con la condición y en TODOS los días sin ella (con el lag).
#                    Pasa solo con ≥ HYPOTHESIS_MIN_DAYS de cada lado y una diferencia entre medianas de al menos
#                    HYPOTHESIS_MIN_DIFF en la dirección declarada. Así la IA no puede elegir a dedo los días.
#   validate:        una acción se agenda solo si su base es un desvío del código o una hipótesis que pasó, su
#                    evidencia existe (del paciente y de la ventana), la hora está entre 08 y 22 de mañana, respeta
#                    el límite diario y nada reservado va al paciente.
# Relaciona por coincidencia en el tiempo; nunca afirma causa.
import json
import re
from datetime import date, datetime, time, timedelta
from statistics import median

from app import config, db
from app.config import TZ
from app.models import DailyPlan, Hypothesis, HypothesisResult, PlannedAction
from app.rules import biometrics

DOMAINS = {"motor", "sueno", "neuropsiquiatrico", "animo", "cognitivo", "autonomico", "dolor", "deglucion",
           "caidas", "impulsos", "sexual", "otro"}
ROLES = {"paciente", "cuidador", "familiar"}
_FRANJA = re.compile(r"^(\d{2})-(\d{2})$")
NIGHT_WAKE_SYMPTOMS = config.SYMPTOMS_NIGHT_WAKINGS


# ================================================================ datos por día (de la base, sin IA)

def _day_bounds(first: date, last: date) -> tuple[str, str]:
    return (db.to_db(datetime.combine(first, time(0), TZ)),
            db.to_db(datetime.combine(last + timedelta(days=1), time(0), TZ)))


def daily_data(patient_id: int, first: date, last: date) -> dict[date, dict]:
    """Todo lo que miden las hipótesis, por día. Lo reservado no entra (el plan puede ir al paciente)."""
    lo, hi = _day_bounds(first, last)
    days = {first + timedelta(days=i): {"steps_hour": {}, "domains": {}, "roles": set(), "franjas_desvio": set(),
                                         "tps": [], "sleep_relato": False}
            for i in range((last - first).days + 1)}
    with db.connect() as conn:
        for r in conn.execute("SELECT start, value FROM biometrics WHERE patient_id = ? AND kind = 'steps' "
                              "AND start >= ? AND start < ?", (patient_id, lo, hi)):
            t = db.from_db(r["start"])
            if t.date() in days:
                h = days[t.date()]["steps_hour"]
                h[t.hour] = h.get(t.hour, 0.0) + r["value"]
        for r in conn.execute(
                "SELECT ev.domain, ev.symptom, p.role, COALESCE(ev.occurred_at, en.created_at) AS at FROM events ev "
                "JOIN entries en ON en.id = ev.entry_id JOIN people p ON p.id = en.speaker_id WHERE ev.patient_id = ? "
                "AND ev.negated = 0 AND ev.reserved = 0 AND COALESCE(ev.occurred_at, en.created_at) >= ? "
                "AND COALESCE(ev.occurred_at, en.created_at) < ?", (patient_id, lo, hi)):
            d = db.from_db(r["at"]).date()
            if d in days:
                days[d]["domains"][r["domain"]] = days[d]["domains"].get(r["domain"], 0) + 1
                if r["symptom"] in NIGHT_WAKE_SYMPTOMS:
                    days[d]["sleep_relato"] = True
        for r in conn.execute("SELECT p.role, en.created_at FROM entries en JOIN people p ON p.id = en.speaker_id "
                              "WHERE en.patient_id = ? AND en.created_at >= ? AND en.created_at < ?", (patient_id, lo, hi)):
            d = db.from_db(r["created_at"]).date()
            if d in days:
                days[d]["roles"].add(r["role"])
        for r in conn.execute("SELECT dose_time FROM episodes WHERE patient_id = ? AND dose_time >= ? AND dose_time < ?",
                              (patient_id, lo, hi)):
            t = db.from_db(r["dose_time"])
            end = (t + timedelta(minutes=config.DEVIATION_WINDOW_MINUTES)).hour
            days[t.date()]["franjas_desvio"].add(f"{t.hour:02d}-{end:02d}")
        for r in conn.execute("SELECT taken_at, metrics FROM tests WHERE patient_id = ? AND taken_at >= ? AND taken_at < ?",
                              (patient_id, lo, hi)):
            d = db.from_db(r["taken_at"]).date()
            tps = json.loads(r["metrics"]).get("taps_per_s")
            if d in days and tps is not None:
                days[d]["tps"].append(tps)
    wear, _ = biometrics._by_day(patient_id, first, last)
    for d, v in wear.get("sleep_awakenings", {}).items():
        if d in days:
            days[d]["awakenings"] = v
    for d, v in wear.get("sleep_minutes", {}).items():
        if d in days:
            days[d]["sleep_minutes"] = v
    return days


# ================================================================ condiciones y métricas

def _parse(kind: str, value: str) -> tuple[str, str | None]:
    name, _, arg = value.partition(":")
    if kind == "condition":
        ok = (name in ("noche_mala", "golpeteo_lento", "fin_de_semana") and not arg) or \
             (name == "relato_dominio" and arg in DOMAINS) or (name == "relato_de" and arg in ROLES) or \
             (name == "desvio_franja" and bool(_FRANJA.match(arg)))
    else:
        ok = (name in ("pasos_dia", "golpeteo_tps", "despertares") and not arg) or \
             (name == "pasos_franja" and bool(_FRANJA.match(arg))) or (name == "relatos_dominio" and arg in DOMAINS)
    if not ok:
        raise ValueError(f"{'condición' if kind == 'condition' else 'métrica'} fuera del vocabulario: {value!r}")
    return name, arg or None


def condition_days(condition: str, days: dict[date, dict]) -> set[date]:
    name, arg = _parse("condition", condition)
    if name == "noche_mala":
        aw = [d["awakenings"] for d in days.values() if "awakenings" in d]
        sl = [d["sleep_minutes"] for d in days.values() if "sleep_minutes" in d]
        aw_cut = max(3.0, 1.5 * median(aw)) if aw else None
        sl_cut = 0.8 * median(sl) if sl else None
        return {k for k, d in days.items()
                if (aw_cut is not None and d.get("awakenings", 0) >= aw_cut)
                or (sl_cut is not None and "sleep_minutes" in d and d["sleep_minutes"] <= sl_cut)
                or d["sleep_relato"]}
    if name == "relato_dominio":
        return {k for k, d in days.items() if d["domains"].get(arg)}
    if name == "relato_de":
        return {k for k, d in days.items() if arg in d["roles"]}
    if name == "desvio_franja":
        return {k for k, d in days.items() if arg in d["franjas_desvio"]}
    if name == "golpeteo_lento":
        all_tps = [v for d in days.values() for v in d["tps"]]
        if not all_tps:
            return set()
        cut = config.GAME_SLOWER_RATIO * median(all_tps)
        return {k for k, d in days.items() if d["tps"] and median(d["tps"]) < cut}
    return {k for k in days if k.weekday() >= 5}                  # fin_de_semana


def metric_value(metric: str, d: dict) -> float | None:
    """El valor de la métrica ese día, o None si no hay dato (ese día no cuenta de ningún lado)."""
    name, arg = _parse("metric", metric)
    if name == "pasos_dia":
        return sum(d["steps_hour"].values()) if d["steps_hour"] else None
    if name == "pasos_franja":
        if not d["steps_hour"]:
            return None
        h0, h1 = (int(x) for x in arg.split("-"))
        return sum(v for h, v in d["steps_hour"].items() if h0 <= h < h1)
    if name == "golpeteo_tps":
        return median(d["tps"]) if d["tps"] else None
    if name == "despertares":
        return d.get("awakenings")
    return float(d["domains"].get(arg, 0))                         # relatos_dominio


# ================================================================ prueba de hipótesis

def window(now: datetime) -> tuple[date, date]:
    last = now.astimezone(TZ).date()
    return last - timedelta(days=config.DAILY_PLAN_WINDOW_DAYS - 1), last


def test_hypothesis(h: Hypothesis, patient_id: int, ventana: tuple[date, date],
                    days: dict[date, dict] | None = None) -> HypothesisResult:
    """Métrica en todos los días con la condición (corrida lag_days) contra todos los días sin ella."""
    def fail(reason, mc=None, nc=0, ms=None, ns=0):
        return HypothesisResult(hypothesis=h, passed=False, mediana_con=mc, n_con=nc, mediana_sin=ms, n_sin=ns,
                                discard_reason=reason)
    try:
        _parse("condition", h.condition)
        _parse("metric", h.metric)
    except ValueError as exc:
        return fail(str(exc))
    first, last = ventana
    days = days if days is not None else daily_data(patient_id, first, last)
    cond = condition_days(h.condition, days)
    con, sin = [], []
    for d in sorted(days):
        prev = d - timedelta(days=h.lag_days)
        if prev not in days:
            continue
        v = metric_value(h.metric, days[d])
        if v is None:
            continue
        (con if prev in cond else sin).append(v)
    mc = round(median(con), 1) if con else None
    ms = round(median(sin), 1) if sin else None
    n = config.HYPOTHESIS_MIN_DAYS
    if len(con) < n:
        return fail(f"solo {len(con)} {'día' if len(con) == 1 else 'días'} con la condición", mc, len(con), ms, len(sin))
    if len(sin) < n:
        return fail(f"solo {len(sin)} {'día' if len(sin) == 1 else 'días'} sin la condición", mc, len(con), ms, len(sin))
    if ms == 0:
        diff = 0.0 if mc == 0 else (1.0 if mc > 0 else -1.0)
    else:
        diff = (mc - ms) / abs(ms)
    signed = diff if h.direction == "mas" else -diff
    if signed < 0:
        return fail(f"dirección contraria ({round(abs(diff) * 100)}% {'más' if diff > 0 else 'menos'})",
                    mc, len(con), ms, len(sin))
    if signed < config.HYPOTHESIS_MIN_DIFF:
        return fail(f"diferencia {round(abs(diff) * 100)}%", mc, len(con), ms, len(sin))
    return HypothesisResult(hypothesis=h, passed=True, mediana_con=mc, n_con=len(con), mediana_sin=ms, n_sin=len(sin))


# ================================================================ textos con cifras (los pone el código)

CONDITION_TEXT = {"noche_mala": "después de una noche mala", "golpeteo_lento": "con el juego más lento",
                  "fin_de_semana": "de fin de semana"}
METRIC_TEXT = {"pasos_dia": ("pasos en el día", "pasos"), "golpeteo_tps": ("toques por segundo", "toques/s"),
               "despertares": ("despertares", "despertares")}


def condition_text(condition: str, lag: int) -> str:
    name, arg = _parse("condition", condition)
    base = CONDITION_TEXT.get(name) or {
        "relato_dominio": f"con un relato de {arg}", "relato_de": f"en que contó algo el {arg}",
        "desvio_franja": f"con menos pasos de {arg.replace('-', ' a ')} h"}[name]
    return f"los días siguientes a los días {base}" if lag == 1 else f"los días {base}"


def metric_text(metric: str) -> tuple[str, str]:
    name, arg = _parse("metric", metric)
    if name == "pasos_franja":
        return f"pasos de {arg.replace('-', ' a ')} h", "pasos"
    if name == "relatos_dominio":
        return f"relatos de {arg}", "relatos"
    return METRIC_TEXT[name]


def _num(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:,.0f}".replace(",", ".") if abs(x) >= 10 else f"{x:.1f}".replace(".", ",")


def result_text(r: HypothesisResult) -> str:
    """'Los días después de una noche mala: mediana 2.900 pasos en el día (n=6); el resto: 4.100 (n=20).'"""
    what, unit = metric_text(r.hypothesis.metric)
    when = condition_text(r.hypothesis.condition, r.hypothesis.lag_days)
    return (f"{when[0].upper()}{when[1:]}: mediana {_num(r.mediana_con)} {what} (n={r.n_con}); "
            f"el resto: {_num(r.mediana_sin)} (n={r.n_sin}).")


# ================================================================ validación de acciones

def _ref_ok(conn, ref: str, patient_id: int, first: date, last: date) -> tuple[bool, bool]:
    """(existe en el paciente y la ventana, es reservado)."""
    kind, _, raw = ref.partition(":")
    lo, hi = _day_bounds(first, last)
    if kind == "dia":
        try:
            return first <= date.fromisoformat(raw) <= last, False
        except ValueError:
            return False, False
    if not raw.isdigit():
        return False, False
    sql = {
        "relato": "SELECT ev.reserved AS r FROM events ev JOIN entries en ON en.id = ev.entry_id WHERE ev.id = ? "
                  "AND ev.patient_id = ? AND en.created_at >= ? AND en.created_at < ?",
        "episodio": "SELECT 0 AS r FROM episodes WHERE id = ? AND patient_id = ? AND dose_time >= ? AND dose_time < ?",
        "juego": "SELECT 0 AS r FROM tests WHERE id = ? AND patient_id = ? AND taken_at >= ? AND taken_at < ?",
        "alerta": "SELECT reserved AS r FROM alerts WHERE id = ? AND patient_id = ? AND created_at >= ? AND created_at < ?",
    }.get(kind)
    if sql is None:
        return False, False
    row = conn.execute(sql, (int(raw), patient_id, lo, hi)).fetchone()
    return (row is not None, bool(row and row["r"]))


def _episode_why(conn, episode_id: int) -> str | None:
    row = conn.execute("SELECT dose_time, deviation FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if not row:
        return None
    dev = json.loads(row["deviation"]) if row["deviation"] else None
    t = db.from_db(row["dose_time"])
    if not dev:
        return f"El {t:%d/%m} hubo menos pasos después de la toma de las {t:%H}."
    return (f"El {t:%d/%m}, después de la toma de las {t:%H}: {_num(dev.get('observed'))} pasos; "
            f"lo habitual ≈ {_num(dev.get('median'))}.")


def validate(plan: DailyPlan, digest: dict, now: datetime,
             results: list[HypothesisResult] | None = None) -> tuple[list[dict], list[dict]]:
    """(agendadas, descartadas_con_motivo). Cada una: la acción, to_person_id, why (con cifras del código) y,
    si se descarta, discard_reason. Las 'nada' no se agendan ni se descartan."""
    patient_id = digest["patient_id"]
    first, last = date.fromisoformat(digest["ventana"]["desde"]), date.fromisoformat(digest["ventana"]["hasta"])
    plan_date = date.fromisoformat(digest["plan_date"])
    if results is None:
        days = daily_data(patient_id, first, last)
        results = [test_hypothesis(h, patient_id, (first, last), days) for h in plan.hypotheses]
    lo_h, hi_h = (time.fromisoformat(x) for x in config.PLAN_HOURS)
    scheduled, discarded = [], []
    with db.connect() as conn:
        people = {r["role"]: r["id"] for r in conn.execute(
            "SELECT id, role FROM people WHERE patient_id = ? ORDER BY id", (patient_id,)).fetchall()[::-1]}
        used: dict[tuple[int, str], int] = {}
        for r in conn.execute("SELECT to_person_id, kind FROM planned_actions WHERE patient_id = ? AND plan_date = ? "
                              "AND status != 'descartada'", (patient_id, plan_date.isoformat())):
            key = (r["to_person_id"], "juego" if r["kind"] == "golpeteo" else "pregunta")
            used[key] = used.get(key, 0) + 1

        for a in plan.actions:
            if a.kind == "nada":
                continue
            row = {**a.model_dump(), "to_person_id": people.get(a.to_role), "why": None}

            def drop(reason):
                discarded.append({**row, "discard_reason": reason})

            # 1. base: un desvío del código o una hipótesis que pasó la prueba
            b_kind, _, b_arg = a.basis.partition(":")
            if b_kind == "desvio" and b_arg.isdigit():
                ok, _ = _ref_ok(conn, f"episodio:{b_arg}", patient_id, first, last)
                if not ok:
                    drop("el desvío no existe en la ventana"); continue
                row["why"] = _episode_why(conn, int(b_arg))
            elif b_kind == "hipotesis" and b_arg.isdigit() and int(b_arg) < len(results):
                res = results[int(b_arg)]
                if not res.passed:
                    drop(f"la hipótesis no pasó la prueba ({res.discard_reason})"); continue
                row["why"] = result_text(res) + " Es una coincidencia en el tiempo, no una causa."
            else:
                drop("sin base válida (ni desvío del código ni hipótesis)"); continue
            # 2. evidencia: al menos una, y todas del paciente y de la ventana
            if not a.evidence_ids:
                drop("sin evidencia"); continue
            checks = [_ref_ok(conn, ref, patient_id, first, last) for ref in a.evidence_ids]
            if not all(ok for ok, _ in checks):
                bad = [ref for ref, (ok, _) in zip(a.evidence_ids, checks) if not ok]
                drop(f"evidencia que no existe o no es de la ventana: {', '.join(bad)}"); continue
            # 3. nada reservado al paciente
            if a.to_role == "paciente" and any(res for _, res in checks):
                drop("tiene algo reservado y va al paciente"); continue
            if row["to_person_id"] is None:
                drop(f"no hay {a.to_role} para este paciente"); continue
            # 4. hora: mañana entre 08:00 y 22:00
            try:
                at = time.fromisoformat(a.at)
            except ValueError:
                drop(f"hora inválida ({a.at!r})"); continue
            if not (lo_h <= at <= hi_h):
                drop(f"fuera de horario ({a.at}; va entre {config.PLAN_HOURS[0]} y {config.PLAN_HOURS[1]})"); continue
            # 5. límite diario
            bucket = "juego" if a.kind == "golpeteo" else "pregunta"
            limit = config.DAILY_MAX_GAME_INVITES if bucket == "juego" else config.DAILY_MAX_QUESTIONS
            key = (row["to_person_id"], bucket)
            if used.get(key, 0) >= limit:
                drop(f"excede el límite diario ({limit} {'invitación al juego' if bucket == 'juego' else 'pregunta'})")
                continue
            used[key] = used.get(key, 0) + 1
            row["at"] = at.strftime("%H:%M")
            scheduled.append(row)
    return scheduled, discarded

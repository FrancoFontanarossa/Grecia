# Disparadores proactivos (CLAUDE.md §6.2). El "why" lo arma el código, con cifras; ask solo redacta.
# Lo reservado nunca entra a un disparador (ni a su why ni a sus facts).
import json
from datetime import datetime, timedelta
from statistics import median

from app import config, db, taxonomy
from app.config import TZ
from app.models import Trigger
from app.rules import biometrics, episodes, games

DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
FAMILY = ("cuidador", "familiar")


# ── Formato de cifras para el "por qué te pregunto" ─────────────────────────────────────────────────────
def fmt_int(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def fmt_approx(n: float) -> str:
    """≈ redondeado: a la centena desde 1.000, a la decena por debajo."""
    return fmt_int(round(n, -2) if n >= 1000 else round(n, -1))


def fmt_dec(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def part_of_day(hour: int) -> str:
    return "mañanas" if 5 <= hour < 11 else "mediodías" if hour < 14 else "tardes" if hour < 20 else "noches"


def deviation_why(d, *, weekend: bool) -> str:
    start = d.dose_time.astimezone(TZ)
    end = start + timedelta(minutes=config.DEVIATION_WINDOW_MINUTES)
    others = f"Otras {part_of_day(start.hour)}"
    if d.baseline == "estrato":
        others += " de fin de semana" if weekend else " de semana"
    return f"{others} ≈ {fmt_approx(d.median)} pasos de {start.hour} a {end.hour} h; hoy {fmt_int(d.observed)}."


# ── Personas ────────────────────────────────────────────────────────────────────────────────────────────
# Alcance de las 04:15: los disparadores biométricos (P-DESVIO, P-SUENO, P-JUEGO) le preguntan a la cuidadora
# (Marta), con el motivo en cifras y en tercera persona; su respuesta entra como relato. P-SILENCIO y P-REPITE
# siguen siendo para el paciente y P-NOCHES ya iba a Marta.
BIOMETRIC_ASKS = "cuidador"


def _person(conn, patient_id: int, role: str) -> int | None:
    row = conn.execute("SELECT id FROM people WHERE patient_id = ? AND role = ? ORDER BY id LIMIT 1",
                       (patient_id, role)).fetchone()
    return row["id"] if row else None


def _patient_name(conn, patient_id: int) -> str:
    row = conn.execute("SELECT name FROM people WHERE id = ? AND role = 'paciente'", (patient_id,)).fetchone()
    return row["name"] if row else "el paciente"


# ── Disparadores ────────────────────────────────────────────────────────────────────────────────────────
def p_desvio(patient_id: int, now: datetime) -> list[Trigger]:
    """Tomas de hoy cuya ventana ya terminó, que todavía no son episodio y tienen desvío. Se le pregunta a Marta."""
    day_start = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    with db.connect() as conn:
        caregiver = _person(conn, patient_id, BIOMETRIC_ASKS)
        doses = [db.from_db(r["scheduled_at"]) for r in conn.execute(
            "SELECT scheduled_at FROM doses WHERE patient_id = ? AND scheduled_at >= ? AND scheduled_at < ? "
            "ORDER BY scheduled_at", (patient_id, db.to_db(day_start), db.to_db(day_start + timedelta(days=1))))]
        done = {r["t"] for r in conn.execute(
            "SELECT substr(dose_time, 1, 16) AS t FROM episodes WHERE patient_id = ?", (patient_id,))}
    out = []
    for dose in doses:
        if caregiver is None or episodes.window(dose)[1] > now or db.to_db(dose)[:16] in done:
            continue
        d = episodes.deviation(patient_id, dose)
        if d is None:
            continue
        out.append(Trigger(rule_id="P-DESVIO", patient_id=patient_id, to_person_id=caregiver,
                           facts=d.model_dump(mode="json"),
                           why=deviation_why(d, weekend=dose.weekday() in episodes.WEEKEND)))
    return out


def _told_at(row) -> datetime:
    return db.from_db(row["occurred_at"] or row["created_at"])


def p_noches(patient_id: int, now: datetime) -> list[Trigger]:
    since = now - timedelta(days=config.NIGHTS_WINDOW_DAYS)
    keys = sorted(config.SYMPTOMS_NIGHT_WAKINGS)
    with db.connect() as conn:
        caregiver = _person(conn, patient_id, "cuidador")
        rows = conn.execute(
            f"SELECT e.occurred_at, en.created_at FROM events e JOIN entries en ON en.id = e.entry_id "
            f"WHERE e.patient_id = ? AND e.reserved = 0 AND e.negated = 0 "
            f"AND e.symptom IN ({','.join('?' * len(keys))})", (patient_id, *keys)).fetchall()
    # Un despertar a las 3 de la mañana es de la noche anterior.
    nights = sorted({(_told_at(r) - timedelta(hours=12)).date() for r in rows if since <= _told_at(r) <= now})
    if caregiver is None or len(nights) < config.NIGHTS_COUNT:
        return []
    listed = ", ".join(f"{DAY_NAMES[n.weekday()]} {n.day}" for n in nights)
    return [Trigger(rule_id="P-NOCHES", patient_id=patient_id, to_person_id=caregiver,
                    facts={"nights": [n.isoformat() for n in nights], "window_days": config.NIGHTS_WINDOW_DAYS},
                    why=f"{len(nights)} noches con despertares en los últimos {config.NIGHTS_WINDOW_DAYS} días "
                        f"({listed}).")]


def p_silencio(patient_id: int, now: datetime) -> list[Trigger]:
    with db.connect() as conn:
        patient = _person(conn, patient_id, "paciente")
        row = conn.execute("SELECT max(created_at) AS last FROM entries WHERE patient_id = ? AND created_at <= ?",
                           (patient_id, db.to_db(now))).fetchone()
    if patient is None or row["last"] is None:      # sin ningún relato todavía no hay silencio que medir
        return []
    last = db.from_db(row["last"])
    days = (now - last).days
    if days < config.SILENCE_DAYS:
        return []
    return [Trigger(rule_id="P-SILENCIO", patient_id=patient_id, to_person_id=patient,
                    facts={"last_entry_at": last.isoformat(), "days": days},
                    why=f"Hace {days} días que nadie cuenta nada (el último relato fue el "
                        f"{DAY_NAMES[last.weekday()]} {last:%d/%m}).")]


def p_juego(patient_id: int, now: datetime) -> list[Trigger]:
    day = now.astimezone(TZ).date().isoformat()
    with db.connect() as conn:
        caregiver = _person(conn, patient_id, BIOMETRIC_ASKS)
        name = _patient_name(conn, patient_id)
        row = conn.execute("SELECT metrics, taken_at FROM tests WHERE patient_id = ? AND type = 'golpeteo' "
                           "AND substr(taken_at, 1, 10) = ? AND taken_at <= ? ORDER BY taken_at DESC LIMIT 1",
                           (patient_id, day, db.to_db(now))).fetchone()
    if caregiver is None or row is None:
        return []
    today = json.loads(row["metrics"])["taps_per_s"]
    history = games.history(patient_id, db.from_db(row["taken_at"]))
    if games.vs_history(today, history) != "mas_lento":
        return []
    med = median(history)
    return [Trigger(rule_id="P-JUEGO", patient_id=patient_id, to_person_id=caregiver,
                    facts={"taps_per_s": today, "history_median": med, "history_n": len(history)},
                    why=f"Hoy {name} hizo {fmt_dec(today)} toques por segundo en el juego; sus últimas "
                        f"{len(history)} veces ≈ {fmt_dec(med)}.")]


def p_repite(patient_id: int, now: datetime) -> list[Trigger]:
    """Mismo síntoma contado 2 veces en 7 días por la familia y nunca por el paciente. Ignora lo reservado."""
    since = db.to_db(now - timedelta(days=config.REPEAT_WINDOW_DAYS))
    with db.connect() as conn:
        patient = _person(conn, patient_id, "paciente")
        family = conn.execute(
            "SELECT e.symptom, count(DISTINCT e.entry_id) AS n FROM events e JOIN entries en ON en.id = e.entry_id "
            "WHERE e.patient_id = ? AND e.reserved = 0 AND e.negated = 0 AND e.symptom != 'otro' "
            "AND e.speaker_role IN ('cuidador', 'familiar') AND en.created_at >= ? AND en.created_at <= ? "
            "GROUP BY e.symptom HAVING n >= ? ORDER BY e.symptom",
            (patient_id, since, db.to_db(now), config.REPEAT_COUNT)).fetchall()
        told_by_patient = {r["symptom"] for r in conn.execute(
            "SELECT DISTINCT symptom FROM events WHERE patient_id = ? AND speaker_role = 'paciente' AND negated = 0",
            (patient_id,))}
    if patient is None:
        return []
    return [Trigger(rule_id="P-REPITE", patient_id=patient_id, to_person_id=patient,
                    facts={"symptom": r["symptom"], "times": r["n"], "window_days": config.REPEAT_WINDOW_DAYS},
                    why=f"En los últimos {config.REPEAT_WINDOW_DAYS} días tu familia contó {r['n']} veces algo de "
                        f"«{taxonomy.symptom_label(r['symptom'])}»; vos todavía no lo contaste.")
            for r in family if r["symptom"] not in told_by_patient]


def p_sueno(patient_id: int, now: datetime) -> list[Trigger]:
    """La noche que pasó, según la pulsera: despertares o sueño fuera de lo normal (rules.biometrics).
    A la mañana y para Marta. No lleva relatos: nada reservado puede entrar."""
    local = now.astimezone(TZ)
    start, end = config.SLEEP_TRIGGER_HOURS
    if not start <= local.hour < end:
        return []
    found = [a for a in biometrics.anomalies(patient_id, local.date()) if a["kind"] in config.SLEEP_TRIGGER_KINDS]
    if not found:
        return []
    with db.connect() as conn:
        caregiver = _person(conn, patient_id, BIOMETRIC_ASKS)
        name = _patient_name(conn, patient_id)
    if caregiver is None:
        return []
    found.sort(key=lambda a: config.SLEEP_TRIGGER_KINDS.index(a["kind"]))   # primero los despertares
    facts = {"night_of": local.date().isoformat(), "source": ", ".join(sorted({a["source"] for a in found})),
             "anomalies": [{k: a[k] for k in ("kind", "value", "source", "baseline_median", "baseline_n", "z")}
                           for a in found]}
    return [Trigger(rule_id="P-SUENO", patient_id=patient_id, to_person_id=caregiver, facts=facts,
                    why=" ".join(sleep_why(a, name) for a in found))]


def sleep_why(a: dict, name: str) -> str:
    """El "por qué" de P-SUENO para Marta, en tercera persona (las cifras, de rules.biometrics)."""
    if a["kind"] == "sleep_awakenings":
        return f"Anoche {name} se despertó {fmt_int(a['value'])} veces; lo habitual son {fmt_int(a['baseline_median'])}."
    if a["kind"] == "sleep_minutes":
        return (f"Anoche {name} durmió {biometrics._hours(a['value'])}; "
                f"lo habitual son {biometrics._hours(a['baseline_median'])}.")
    return a["why"]


RULES = (p_desvio, p_noches, p_silencio, p_juego, p_repite, p_sueno)


def evaluate(patient_id: int, now: datetime) -> list[Trigger]:
    """Todos los disparadores que se cumplen ahora. Que cada uno genere como máximo una Question por día
    lo controla el scheduler (ARQUITECTURA §4.4); P-DESVIO ya saltea las tomas que son episodio."""
    return [t for rule in RULES for t in rule(patient_id, now)]

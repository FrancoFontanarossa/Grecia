# Carriles y avisos (CLAUDE.md §6.1 y §6.3): rojos, A1, A2 y A3. Los guarda en `alerts` con sus
# destinatarios (rules.consent) y los devuelve; notify solo entrega. Verde no genera aviso: va al informe.
import json
from datetime import datetime, timedelta

from app import clock, config, db
from app.config import TZ
from app.models import Alert, RedResult
from app.rules import consent, med_change

A3_SUGGESTION = "¿Querés que le avisemos a tu neuróloga para adelantar la consulta?"


def _save(patient_id: int, lane: str, rule_id: str, text: str, *, reserved: bool, speaker_id: int | None,
          now: datetime) -> Alert:
    draft = Alert(id=0, patient_id=patient_id, lane=lane, rule_id=rule_id, recipients=[], text=text,
                  reserved=reserved, created_at=now)
    to = [p.id for p in consent.recipients(draft, speaker_id=speaker_id)]
    with db.connect() as conn:
        alert_id = conn.execute(
            "INSERT INTO alerts (patient_id, lane, rule_id, recipients, text, reserved, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (patient_id, lane, rule_id, json.dumps(to), text, int(reserved), db.to_db(now))).lastrowid
    return draft.model_copy(update={"id": alert_id, "recipients": to})


def _exists(patient_id: int, rule_id: str, text: str) -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM alerts WHERE patient_id = ? AND rule_id = ? AND text = ? LIMIT 1",
                            (patient_id, rule_id, text)).fetchone() is not None


def _events(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT e.*, en.speaker_id, en.created_at AS told_at, p.name AS speaker_name "
            f"FROM events e JOIN entries en ON en.id = e.entry_id LEFT JOIN people p ON p.id = en.speaker_id "
            f"WHERE e.id IN ({','.join('?' * len(ids))}) ORDER BY e.id", ids)]


def _label(symptom: str) -> str:
    return symptom.replace("_", " ")


def event_alerts(patient_id: int, new_events: list[int], now: datetime) -> list[Alert]:
    """A1 (alucinación o delirio nuevo) y A2 (síntoma nuevo dentro de las 8 semanas de un cambio)."""
    out = []
    for e in _events(new_events):
        if e["negated"] or not e["is_new"] or e["patient_id"] != patient_id:
            continue
        when = db.from_db(e["occurred_at"] or e["told_at"])
        reserved = bool(e["reserved"])
        candidates = []
        if e["symptom"] in config.SYMPTOMS_A1:
            who = e["speaker_name"] or e["speaker_role"]
            candidates.append(("A1", f"Primera mención de {_label(e['symptom'])} (contado por {who} el "
                                     f"{when.astimezone(TZ):%d/%m})."))
        change = med_change.recent_change(patient_id, when)
        if change:
            mc, days = change
            candidates.append(("A2", f"Síntoma nuevo a {days} días del cambio de {mc.drug}: {_label(e['symptom'])}."))
        for rule_id, text in candidates:
            if not _exists(patient_id, rule_id, text):
                out.append(_save(patient_id, "ambar", rule_id, text, reserved=reserved,
                                 speaker_id=e["speaker_id"], now=now))
    return out


def episode_alerts(patient_id: int, now: datetime) -> list[Alert]:
    """A3: 3 episodios en 7 días en el mismo tramo (hora de la toma). Al equipo, y la sugerencia a Juan."""
    since = now - timedelta(days=config.EPISODES_WINDOW_DAYS)
    with db.connect() as conn:
        rows = conn.execute("SELECT dose_time FROM episodes WHERE patient_id = ? AND dose_time >= ? AND dose_time <= ? "
                            "ORDER BY dose_time", (patient_id, db.to_db(since), db.to_db(now))).fetchall()
    by_slot: dict[str, list[datetime]] = {}
    for r in rows:
        t = db.from_db(r["dose_time"])
        by_slot.setdefault(f"{t:%H:%M}", []).append(t)
    out = []
    for slot, times in sorted(by_slot.items()):
        if len(times) < config.EPISODES_COUNT:
            continue
        text = (f"{len(times)} episodios en {config.EPISODES_WINDOW_DAYS} días después de la toma de las {slot} "
                f"({', '.join(f'{t:%d/%m}' for t in times)}).")
        if _a3_slot_alerted(patient_id, slot, since):   # uno por tramo cada 7 días
            continue
        out.append(_save(patient_id, "ambar", "A3", text, reserved=False, speaker_id=None, now=now))
        out.append(_save(patient_id, "ambar", "A3-sugerencia", A3_SUGGESTION, reserved=False, speaker_id=None, now=now))
    return out


def _a3_slot_alerted(patient_id: int, slot: str, since: datetime) -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM alerts WHERE patient_id = ? AND rule_id = 'A3' AND created_at >= ? "
                            "AND text LIKE ? LIMIT 1", (patient_id, db.to_db(since), f"%toma de las {slot} %")
                            ).fetchone() is not None


def red_alert(patient_id: int, red: RedResult, *, speaker_id: int | None, now: datetime) -> Alert | None:
    """Un rojo completo (sin criterio faltante) es un aviso de carril rojo con su texto fijo."""
    if red.missing_criterion is not None:
        return None
    return _save(patient_id, "rojo", red.rule_id, red.text, reserved=False, speaker_id=speaker_id, now=now)


def evaluate(patient_id: int, new_events: list[int], *, red: RedResult | None = None,
             speaker_id: int | None = None) -> list[Alert]:
    """Contrato de §11. `new_events` son los ids en `events` de lo que se acaba de guardar; `red` es el
    resultado de rules.red.check (o del respaldo) sobre ese mismo relato; `speaker_id`, quien lo contó."""
    now = clock.now()
    alerts = []
    if red is not None and (a := red_alert(patient_id, red, speaker_id=speaker_id, now=now)):
        alerts.append(a)
    alerts += event_alerts(patient_id, new_events, now)
    alerts += episode_alerts(patient_id, now)
    return alerts

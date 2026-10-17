# Acceso a datos de las pantallas (app y web).
# Hoy no existen app/db.py, app/clock.py, app/rules/ ni app/pipeline/: todo lo que falta sale de
# datos falsos con la forma del contrato (CLAUDE.md §11–§12), marcados `simulated=True` y
# rotulados en pantalla. Cuando aparezca la pieza real, se reemplaza SOLO este archivo.
import datetime as dt
import json
import os
import threading
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("America/Montevideo")
except Exception:  # Windows sin tzdata
    TZ = dt.timezone(dt.timedelta(hours=-3), "America/Montevideo")

try:  # TODO(contrato): reemplazar cuando exista app.config.TZ en main
    from app.config import TZ  # type: ignore  # noqa: F811
except Exception:
    pass

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "./data"))
_lock = threading.Lock()

# Paciente de Juan y paciente de prueba (CLAUDE.md §3).
JUAN_PATIENT_ID = 1
TEST_PATIENT_ID = 2


# ---------------------------------------------------------------- reloj

def now() -> dt.datetime:
    """La hora de la demo. Nunca datetime.now()."""
    try:
        from app import clock  # type: ignore

        return clock.now()
    except Exception:
        # TODO(contrato): reemplazar cuando exista app.clock.now(). Hora fija del sábado de la demo.
        return dt.datetime(2026, 10, 17, 17, 10, tzinfo=TZ)


def clock_is_real() -> bool:
    try:
        from app import clock  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


# ---------------------------------------------------------------- personas
# TODO(contrato): reemplazar cuando exista app.db con la tabla people (los crea data/seed.py).
_PEOPLE = [
    {"id": 1, "patient_id": 1, "role": "paciente", "name": "Juan", "relation": "Soy el paciente",
     "why_walk": "llegar a la plaza a ver a mis nietos"},
    {"id": 2, "patient_id": 1, "role": "cuidador", "name": "Marta", "relation": "Esposa · vive con Juan"},
    {"id": 3, "patient_id": 1, "role": "familiar", "name": "Laura", "relation": "Hija · vive en Salto"},
    {"id": 4, "patient_id": 1, "role": "neurologo", "name": "Dra. Pereira", "relation": "Neuróloga"},
    {"id": 11, "patient_id": 2, "role": "paciente", "name": "Paciente de prueba", "relation": "Soy el paciente"},
    {"id": 12, "patient_id": 2, "role": "cuidador", "name": "Familiar de prueba", "relation": "Vivo con el paciente"},
    {"id": 14, "patient_id": 2, "role": "neurologo", "name": "Neuróloga de prueba", "relation": "Neuróloga"},
]


def people(patient_id: int) -> list[dict]:
    return [dict(p) for p in _PEOPLE if p["patient_id"] == patient_id]


def person(person_id: int) -> dict | None:
    for p in _PEOPLE:
        if p["id"] == person_id:
            return dict(p)
    return None


def patient_person(patient_id: int) -> dict | None:
    return next((p for p in people(patient_id) if p["role"] == "paciente"), None)


def test_patient_id() -> int:
    # TODO(contrato): crear o reutilizar el "Paciente de prueba" en la base cuando exista app.db.
    return TEST_PATIENT_ID


# ---------------------------------------------------------------- esquema de tomas y meta
# TODO(contrato): reemplazar por med_schedule y goals de app.db.
DOSE_TIMES = ["08:00", "12:00", "16:00", "20:00"]
GOAL_STEPS = 4000
PRAMIPEXOL_CHANGED = dt.date(2026, 9, 22)
NEXT_VISIT = dt.date(2026, 10, 28)
DOCTOR = "Dra. Pereira"


def next_dose(at: dt.datetime) -> str | None:
    hhmm = at.strftime("%H:%M")
    return next((t for t in DOSE_TIMES if t > hhmm), DOSE_TIMES[0])


# ---------------------------------------------------------------- pasos (fallback)
# Serie de ejemplo del lienzo de diseño: 28 días del 20/09 al 17/10. Episodios: 13, 15 y 16/10.
_DAILY = [4210, 3980, 4350, 3890, 4120, 3760, 4480, 4020, 3650, 3910, 4230, 3580, 3870, 4100,
          3720, 3540, 3960, 4050, 3480, 3820, 3990, 4300, 4120, 2650, 4410, 4060, 2380, 2840]
_EPISODE_DAYS = {dt.date(2026, 10, 13), dt.date(2026, 10, 15), dt.date(2026, 10, 16)}


def daily_steps(patient_id: int, end: dt.date, days: int) -> list[dict]:
    # TODO(contrato): sumar biometrics(kind=steps) por día cuando exista app.db.
    start = dt.date(2026, 9, 20)
    out = []
    for i in range(days):
        d = end - dt.timedelta(days=days - 1 - i)
        idx = (d - start).days
        value = _DAILY[idx] if 0 <= idx < len(_DAILY) else None
        out.append({"date": d.isoformat(), "value": value, "achieved": bool(value and value >= GOAL_STEPS),
                    "episode": d in _EPISODE_DAYS, "med_change": d == PRAMIPEXOL_CHANGED})
    return out


# ---------------------------------------------------------------- notificaciones y suscripciones push
# TODO(contrato): reemplazar por las tablas push_subscriptions y notifications de app.db.
# Mientras tanto se guardan en un JSON dentro de DATA_DIR (en Railway es el volumen: sobrevive al redeploy).

def _json_path(name: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"{name}.fallback.json"


def _read_json(name: str, default):
    path = _json_path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(name: str, value) -> None:
    path = _json_path(name)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def save_push_subscription(person_id: int, subscription: dict) -> None:
    keys = subscription.get("keys") or {}
    row = {"person_id": person_id, "endpoint": subscription["endpoint"], "p256dh": keys.get("p256dh"),
           "auth": keys.get("auth"), "created_at": now().isoformat()}
    with _lock:
        rows = [r for r in _read_json("push_subscriptions", []) if r["endpoint"] != row["endpoint"]]
        rows.append(row)
        _write_json("push_subscriptions", rows)


def push_subscriptions(person_id: int) -> list[dict]:
    return [r for r in _read_json("push_subscriptions", []) if r["person_id"] == person_id]


def delete_push_subscription(endpoint: str) -> None:
    with _lock:
        rows = [r for r in _read_json("push_subscriptions", []) if r["endpoint"] != endpoint]
        _write_json("push_subscriptions", rows)


def notifications(person_id: int) -> list[dict]:
    return [n for n in _read_json("notifications", []) if n["person_id"] == person_id]


def add_notification(person_id: int, kind: str, title: str, body: str, url: str, push_sent: bool) -> dict:
    with _lock:
        rows = _read_json("notifications", [])
        row = {"id": max([r["id"] for r in rows], default=0) + 1, "person_id": person_id, "kind": kind,
               "lane": None, "title": title, "body": body, "url": url, "created_at": now().isoformat(),
               "push_sent": push_sent, "read_at": None}
        rows.append(row)
        _write_json("notifications", rows)
        return row


def mark_notification_read(notification_id: int) -> bool:
    with _lock:
        rows = _read_json("notifications", [])
        for r in rows:
            if r["id"] == notification_id:
                r["read_at"] = now().isoformat()
                _write_json("notifications", rows)
                return True
    return False


# ---------------------------------------------------------------- consentimientos
# TODO(contrato): reemplazar por la tabla consents de app.db.
_CONSENT_KINDS = ["avisos", "logros", "canal_reservado"]


def consents(patient_id: int) -> list[dict]:
    saved = _read_json("consents", {})
    out = []
    for p in people(patient_id):
        if p["role"] in ("paciente", "neurologo"):
            continue
        for kind in _CONSENT_KINDS:
            if kind == "canal_reservado" and p["role"] == "paciente":
                continue
            key = f"{patient_id}:{p['id']}:{kind}"
            out.append({"recipient_id": p["id"], "recipient_name": p["name"], "kind": kind,
                        "enabled": saved.get(key, True)})
    return out


def set_consent(patient_id: int, recipient_id: int, kind: str, enabled: bool) -> None:
    with _lock:
        saved = _read_json("consents", {})
        saved[f"{patient_id}:{recipient_id}:{kind}"] = bool(enabled)
        _write_json("consents", saved)


# ---------------------------------------------------------------- entradas (para "Anoté esto")
# TODO(contrato): reemplazar por GET /api/entries/{id} de Guada (propuesto) o por la tabla entries.

def save_entry_snapshot(entry: dict) -> None:
    with _lock:
        rows = _read_json("entries", {})
        rows[str(entry["entry_id"])] = entry
        _write_json("entries", rows)


def entry_snapshot(entry_id: int) -> dict | None:
    return _read_json("entries", {}).get(str(entry_id))


def next_entry_id() -> int:
    rows = _read_json("entries", {})
    return max([int(k) for k in rows], default=0) + 1


# ---------------------------------------------------------------- golpeteo
# TODO(contrato): reemplazar por la tabla tests de app.db.

def tests_history(patient_id: int) -> list[dict]:
    saved = [t for t in _read_json("tests", []) if t["patient_id"] == patient_id]
    if patient_id == JUAN_PATIENT_ID:
        base = now().date()
        fake = [{"patient_id": patient_id, "taken_at": dt.datetime.combine(base - dt.timedelta(days=7 - i),
                                                                           dt.time(10, 30), TZ).isoformat(),
                 "metrics": {"taps_per_s": v}, "source": "seed"}
                for i, v in enumerate([6.1, 5.9, 5.7, 5.2, 5.6, 6.0])]
        saved = fake + saved
    return sorted(saved, key=lambda t: t["taken_at"])


def save_test(row: dict) -> None:
    with _lock:
        rows = _read_json("tests", [])
        rows.append(row)
        _write_json("tests", rows)

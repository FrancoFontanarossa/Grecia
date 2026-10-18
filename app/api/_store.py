# Acceso a datos de las pantallas (app y web), en un solo lugar.
# Si existe app.db (Franco) y la base tiene personas, todo sale de SQLite con el esquema de CLAUDE.md §12.
# Si no, sale de datos de ejemplo con la forma del contrato, marcados `simulated` y rotulados en pantalla.
import datetime as dt
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    from app.config import TZ  # type: ignore
except Exception:  # sin tzdata (Windows) o sin config
    TZ = dt.timezone(dt.timedelta(hours=-3), "America/Montevideo")

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "./data")
_lock = threading.Lock()

JUAN_PATIENT_ID = 1
TEST_PATIENT_ID = 5          # data/seed.py: Paciente de prueba = 5, Familiar de prueba = 6
DOSE_TIMES = ["08:00", "12:00", "16:00", "20:00"]
GOAL_STEPS = 4000
PRAMIPEXOL_CHANGED = dt.date(2026, 10, 3)
NEXT_VISIT = dt.date(2026, 10, 28)
DOCTOR = "Dra. Pereira"


# ================================================================ conexión

def _db_module():
    try:
        from app import db  # type: ignore

        return db if hasattr(db, "connect") else None
    except Exception:
        return None


_has_db_cache = {"value": False, "checked": -1e9}


def has_db() -> bool:
    """Hay base real con personas (el seed ya corrió). Se revisa como mucho cada 5 s (reloj del proceso,
    no de la demo: es solo un caché)."""
    import time

    if time.monotonic() - _has_db_cache["checked"] < 5:
        return _has_db_cache["value"]
    db = _db_module()
    value = False
    if db:
        try:
            with db.connect() as conn:
                value = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0] > 0
        except Exception:
            value = False
    _has_db_cache.update(value=value, checked=time.monotonic())
    return value


@contextmanager
def _conn():
    db = _db_module()
    with db.connect() as conn:
        yield conn


def _iso(value: dt.datetime) -> str:
    db = _db_module()
    if db and hasattr(db, "to_db"):
        return db.to_db(value)
    return value.astimezone(TZ).isoformat(timespec="seconds")


def _loads(value, default):
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


# ================================================================ reloj

def now() -> dt.datetime:
    """La hora de la demo. Nunca datetime.now()."""
    try:
        from app import clock  # type: ignore

        return clock.now()
    except Exception:
        # TODO(contrato): sin app.clock, hora fija del sábado de la demo.
        return dt.datetime(2026, 10, 17, 17, 10, tzinfo=TZ)


def clock_is_real() -> bool:
    try:
        from app import clock  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


# ================================================================ personas

_RELATION_DISPLAY = {"paciente": "Paciente", "esposa": "Esposa", "esposo": "Esposo",
                     "hija": "Hija", "hijo": "Hijo", "familiar": "Familiar", "neuróloga": "Neuróloga"}

_FAKE_PEOPLE = [
    {"id": 1, "patient_id": 1, "role": "paciente", "name": "Juan", "relation": "paciente",
     "why_walk": "llegar a la plaza a ver a sus nietos"},
    {"id": 2, "patient_id": 1, "role": "cuidador", "name": "Marta", "relation": "esposa"},
    {"id": 3, "patient_id": 1, "role": "familiar", "name": "Laura", "relation": "hija"},
    {"id": 4, "patient_id": 1, "role": "neurologo", "name": "Dra. Pereira", "relation": "neuróloga"},
    {"id": 5, "patient_id": 5, "role": "paciente", "name": "Paciente de prueba", "relation": "paciente"},
    {"id": 6, "patient_id": 5, "role": "cuidador", "name": "Familiar de prueba", "relation": "familiar"},
]


def _decorate(p: dict, patient_name: str) -> dict:
    p = dict(p)
    p["relation_label"] = _RELATION_DISPLAY.get(p.get("relation", ""), p.get("relation", "").capitalize()).format(p=patient_name)
    return p


def people(patient_id: int) -> list[dict]:
    if has_db():
        with _conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM people WHERE patient_id = ? ORDER BY id", (patient_id,))]
    else:
        rows = [dict(p) for p in _FAKE_PEOPLE if p["patient_id"] == patient_id]
    patient_name = next((r["name"] for r in rows if r["role"] == "paciente"), "")
    return [_decorate(r, patient_name) for r in rows]


def person(person_id: int) -> dict | None:
    if has_db():
        with _conn() as c:
            r = c.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
        if not r:
            return None
        p = dict(r)
    else:
        p = next((dict(x) for x in _FAKE_PEOPLE if x["id"] == person_id), None)
        if not p:
            return None
    return _decorate(p, (patient_person(p["patient_id"]) or {}).get("name", "") if p["role"] != "paciente" else p["name"])


def patient_person(patient_id: int) -> dict | None:
    if has_db():
        with _conn() as c:
            r = c.execute("SELECT * FROM people WHERE patient_id = ? AND role = 'paciente'", (patient_id,)).fetchone()
        return dict(r) if r else None
    return next((dict(p) for p in _FAKE_PEOPLE if p["patient_id"] == patient_id and p["role"] == "paciente"), None)


def test_patient_id() -> int:
    if has_db():
        with _conn() as c:
            r = c.execute("SELECT id FROM people WHERE role = 'paciente' AND name = 'Paciente de prueba'").fetchone()
        if r:
            return r[0]
    return TEST_PATIENT_ID


# ================================================================ tomas, meta y medicación

def dose_times(patient_id: int) -> list[str]:
    if has_db():
        with _conn() as c:
            r = c.execute("SELECT times FROM med_schedule WHERE patient_id = ? AND drug LIKE 'levodopa%'",
                          (patient_id,)).fetchone()
        times = _loads(r["times"], []) if r else []
        if times:
            return sorted(times)
    return DOSE_TIMES if patient_id == JUAN_PATIENT_ID else []


def next_dose(patient_id: int, at: dt.datetime) -> str | None:
    times = dose_times(patient_id)
    if not times:
        return None
    hhmm = at.strftime("%H:%M")
    return next((t for t in times if t > hhmm), times[0])


def goal_target(patient_id: int) -> int:
    if has_db():
        with _conn() as c:
            r = c.execute("SELECT target FROM goals WHERE patient_id = ? AND metric = 'steps' AND active = 1",
                          (patient_id,)).fetchone()
        if r:
            return int(r["target"])
    return GOAL_STEPS


def medications(patient_id: int) -> list[dict]:
    if has_db():
        with _conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM med_schedule WHERE patient_id = ?", (patient_id,))]
        return [{"drug": r["drug"], "times": _loads(r["times"], []),
                 "changed_at": r["changed_at"], "change_note": r["change_note"]} for r in rows]
    if patient_id != JUAN_PATIENT_ID:
        return []
    return [{"drug": "levodopa/carbidopa", "times": DOSE_TIMES, "changed_at": None, "change_note": None},
            {"drug": "pramipexol", "times": [], "changed_at": "2026-10-03T09:00:00-03:00", "change_note": "subido"}]


# ================================================================ pasos

_FAKE_DAILY = [4210, 3980, 4350, 3890, 4120, 3760, 4480, 4020, 3650, 3910, 4230, 3580, 3870, 4100,
               3720, 3540, 3960, 4050, 3480, 3820, 3990, 4300, 4120, 2650, 4410, 4060, 2380, 2840]
_FAKE_EPISODES = {dt.date(2026, 10, 13), dt.date(2026, 10, 15), dt.date(2026, 10, 16)}


def episode_days(patient_id: int) -> set[dt.date]:
    if has_db():
        with _conn() as c:
            rows = c.execute("SELECT dose_time FROM episodes WHERE patient_id = ?", (patient_id,)).fetchall()
        return {dt.datetime.fromisoformat(r[0]).date() for r in rows}
    return _FAKE_EPISODES if patient_id == JUAN_PATIENT_ID else set()


def daily_steps(patient_id: int, end: dt.date, days: int, until: dt.datetime | None = None) -> list[dict]:
    """Pasos por día (de `end - days + 1` a `end`). Con base: suma de biometrics(kind=steps) hasta `until`."""
    start_day = end - dt.timedelta(days=days - 1)
    goal = goal_target(patient_id)
    eps = episode_days(patient_id)
    values: dict[dt.date, float] = {}
    if has_db():
        lo = _iso(dt.datetime.combine(start_day, dt.time(0), TZ))
        hi = _iso(until or dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0), TZ))
        with _conn() as c:
            for r in c.execute("SELECT substr(start, 1, 10) AS d, SUM(value) AS v FROM biometrics "
                               "WHERE patient_id = ? AND kind = 'steps' AND start >= ? AND start < ? GROUP BY d",
                               (patient_id, lo, hi)):
                values[dt.date.fromisoformat(r["d"])] = r["v"]
    elif patient_id == JUAN_PATIENT_ID:
        base = dt.date(2026, 9, 20)
        for i, v in enumerate(_FAKE_DAILY):
            values[base + dt.timedelta(days=i)] = v
    out = []
    for i in range(days):
        d = start_day + dt.timedelta(days=i)
        v = values.get(d)
        out.append({"date": d.isoformat(), "value": round(v) if v is not None else None,
                    "achieved": bool(v is not None and v >= goal), "episode": d in eps,
                    "med_change": d == PRAMIPEXOL_CHANGED})
    return out


def steps_between(patient_id: int, start: dt.datetime, end: dt.datetime) -> float | None:
    if not has_db():
        return None
    with _conn() as c:
        r = c.execute("SELECT SUM(value) FROM biometrics WHERE patient_id = ? AND kind = 'steps' AND start >= ? AND start < ?",
                      (patient_id, _iso(start), _iso(end))).fetchone()
    return r[0]


def hourly_steps(patient_id: int, start_day: dt.date, end_day: dt.date) -> list[dict]:
    """Pasos por hora del período (vista técnica). Solo con base real."""
    if not has_db():
        return []
    lo = _iso(dt.datetime.combine(start_day, dt.time(0), TZ))
    hi = _iso(dt.datetime.combine(end_day + dt.timedelta(days=1), dt.time(0), TZ))
    with _conn() as c:
        rows = c.execute("SELECT substr(start, 1, 13) AS h, SUM(value) AS v, MAX(source = 'inyectado') AS inj, COUNT(*) AS n "
                         "FROM biometrics WHERE patient_id = ? AND kind = 'steps' AND start >= ? AND start < ? GROUP BY h ORDER BY h",
                         (patient_id, lo, hi)).fetchall()
    return [{"hour": r["h"], "value": round(r["v"]), "injected": bool(r["inj"]), "n": r["n"]} for r in rows]


def biometric_sources(patient_id: int) -> dict:
    if not has_db():
        return {}
    with _conn() as c:
        rows = c.execute("SELECT source, COUNT(*) AS n FROM biometrics WHERE patient_id = ? AND kind = 'steps' GROUP BY source",
                         (patient_id,)).fetchall()
    return {r["source"]: r["n"] for r in rows}


# ================================================================ JSON de respaldo (sin base)

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


# ================================================================ suscripciones push y notificaciones

def save_push_subscription(person_id: int, subscription: dict) -> None:
    keys = subscription.get("keys") or {}
    endpoint, p256dh, auth = subscription["endpoint"], keys.get("p256dh", ""), keys.get("auth", "")
    if _db_module():
        with _conn() as c:
            c.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
            c.execute("INSERT INTO push_subscriptions (person_id, endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?)",
                      (person_id, endpoint, p256dh, auth, _iso(now())))
        return
    try:  # TEMPORAL: base provisoria de Guada (app/_tmp_db.py) hasta que esté app/db.py
        from app import _tmp_db  # type: ignore

        _tmp_db.delete_subscription(endpoint)
        _tmp_db.save_subscription(person_id=person_id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        return
    except ImportError:
        pass
    with _lock:
        rows = [r for r in _read_json("push_subscriptions", []) if r["endpoint"] != endpoint]
        rows.append({"person_id": person_id, "endpoint": endpoint, "p256dh": p256dh, "auth": auth,
                     "created_at": now().isoformat()})
        _write_json("push_subscriptions", rows)


def push_subscriptions(person_id: int) -> list[dict]:
    if _db_module():
        with _conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM push_subscriptions WHERE person_id = ?", (person_id,))]
    return [r for r in _read_json("push_subscriptions", []) if r["person_id"] == person_id]


def delete_push_subscription(endpoint: str) -> None:
    if _db_module():
        with _conn() as c:
            c.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        return
    with _lock:
        _write_json("push_subscriptions", [r for r in _read_json("push_subscriptions", []) if r["endpoint"] != endpoint])


def notifications(person_id: int, unread_only: bool = False) -> list[dict]:
    if _db_module():
        sql = "SELECT * FROM notifications WHERE person_id = ?" + (" AND read_at IS NULL" if unread_only else "")
        with _conn() as c:
            return [dict(r) for r in c.execute(sql + " ORDER BY id", (person_id,))]
    rows = [n for n in _read_json("notifications", []) if n["person_id"] == person_id]
    return [n for n in rows if not n.get("read_at")] if unread_only else rows


def add_notification(person_id: int, kind: str, title: str, body: str, url: str, push_sent: bool) -> dict:
    if _db_module():
        with _conn() as c:
            cur = c.execute("INSERT INTO notifications (person_id, kind, title, body, url, created_at, push_sent) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)", (person_id, kind, title, body, url, _iso(now()), int(push_sent)))
            return {"id": cur.lastrowid}
    with _lock:
        rows = _read_json("notifications", [])
        row = {"id": max([r["id"] for r in rows], default=0) + 1, "person_id": person_id, "kind": kind, "lane": None,
               "title": title, "body": body, "url": url, "created_at": now().isoformat(), "push_sent": push_sent,
               "read_at": None}
        rows.append(row)
        _write_json("notifications", rows)
        return row


def mark_notification_read(notification_id: int) -> bool:
    if _db_module():
        with _conn() as c:
            return c.execute("UPDATE notifications SET read_at = ? WHERE id = ?",
                             (_iso(now()), notification_id)).rowcount > 0
    with _lock:
        rows = _read_json("notifications", [])
        for r in rows:
            if r["id"] == notification_id:
                r["read_at"] = now().isoformat()
                _write_json("notifications", rows)
                return True
    return False


# ================================================================ consentimientos

_CONSENT_KINDS = ["avisos", "logros", "canal_reservado"]


def consents(patient_id: int) -> list[dict]:
    family = [p for p in people(patient_id) if p["role"] in ("cuidador", "familiar")]
    saved: dict[str, bool] = {}
    if has_db():
        with _conn() as c:
            for r in c.execute("SELECT recipient_id, kind, enabled FROM consents WHERE patient_id = ?", (patient_id,)):
                saved[f"{r['recipient_id']}:{r['kind']}"] = bool(r["enabled"])
    else:
        saved = {k.split(":", 1)[1]: v for k, v in _read_json("consents", {}).items() if k.startswith(f"{patient_id}:")}
    return [{"recipient_id": p["id"], "recipient_name": p["name"], "kind": kind,
             "enabled": saved.get(f"{p['id']}:{kind}", not has_db())}
            for p in family for kind in _CONSENT_KINDS]


def set_consent(patient_id: int, recipient_id: int, kind: str, enabled: bool) -> None:
    if has_db():
        with _conn() as c:
            c.execute("INSERT INTO consents (patient_id, recipient_id, kind, enabled, granted_at) VALUES (?, ?, ?, ?, ?) "
                      "ON CONFLICT (patient_id, recipient_id, kind) DO UPDATE SET enabled = excluded.enabled, "
                      "granted_at = excluded.granted_at", (patient_id, recipient_id, kind, int(enabled), _iso(now())))
        return
    with _lock:
        saved = _read_json("consents", {})
        saved[f"{patient_id}:{recipient_id}:{kind}"] = bool(enabled)
        _write_json("consents", saved)


# ================================================================ relatos, eventos y preguntas

def save_entry_snapshot(entry: dict) -> None:
    """Solo para el modo temporal sin entries.py (app/api/_dev_entries.py)."""
    with _lock:
        rows = _read_json("entries", {})
        rows[str(entry["entry_id"])] = entry
        _write_json("entries", rows)


def entry_snapshot(entry_id: int) -> dict | None:
    return _read_json("entries", {}).get(str(entry_id))


def next_entry_id() -> int:
    rows = _read_json("entries", {})
    return max([int(k) for k in rows], default=0) + 1


def last_understood(person_id: int) -> dict | None:
    """Lo último que se anotó de lo que contó ESTA persona (nunca lo de otro: no filtra lo reservado)."""
    if has_db():
        with _conn() as c:
            r = c.execute("SELECT ev.plain, ev.domain, ev.occurred_at FROM events ev JOIN entries en ON en.id = ev.entry_id "
                          "WHERE en.speaker_id = ? AND ev.negated = 0 ORDER BY ev.id DESC LIMIT 1", (person_id,)).fetchone()
        return {"plain": r["plain"], "domain": r["domain"], "when": ""} if r else None
    snaps = [s for s in _read_json("entries", {}).values() if s.get("person_id") == person_id and s.get("understood")]
    if snaps:
        return max(snaps, key=lambda s: s["entry_id"])["understood"][0]
    if person_id == 1:
        return {"plain": "anoche dormiste mal y te despertaste tres veces.", "when": "Anoche", "domain": "sueno"}
    return None


def pending_question(person_id: int) -> dict | None:
    if not has_db():
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM questions WHERE to_person_id = ? AND status IN ('pendiente', 'enviada') "
                      "ORDER BY id DESC LIMIT 1", (person_id,)).fetchone()
    return _question_row(r) if r else None


def question(question_id: int) -> dict | None:
    if not has_db():
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        if not r:
            return None
        q = _question_row(r)
        ep = c.execute("SELECT deviation FROM episodes WHERE question_id = ?", (question_id,)).fetchone()
    q["deviation"] = _loads(ep["deviation"], None) if ep else None
    return q


def _question_row(r) -> dict:
    q = dict(r)
    q["options"] = _loads(q.get("options"), [])
    q["person_id"] = q.pop("to_person_id", None)
    return q


def entries_count_by_role(patient_id: int, since: dt.datetime) -> dict[str, int]:
    if not has_db():
        return {}
    with _conn() as c:
        rows = c.execute("SELECT p.role, COUNT(*) AS n FROM entries e JOIN people p ON p.id = e.speaker_id "
                         "WHERE e.patient_id = ? AND e.created_at >= ? GROUP BY p.role", (patient_id, _iso(since))).fetchall()
    return {r["role"]: r["n"] for r in rows}


def bad_nights(patient_id: int, since: dt.datetime) -> int:
    """Noches con despertares contadas (dominio sueño, no negado), por fecha."""
    if not has_db():
        return 0
    with _conn() as c:
        r = c.execute("SELECT COUNT(DISTINCT substr(COALESCE(ev.occurred_at, en.created_at), 1, 10)) FROM events ev "
                      "JOIN entries en ON en.id = ev.entry_id WHERE ev.patient_id = ? AND ev.domain = 'sueno' "
                      "AND ev.negated = 0 AND en.created_at >= ?", (patient_id, _iso(since))).fetchone()
    return r[0] or 0


def alerts_for(person_id: int, patient_id: int, since: dt.datetime | None = None) -> list[dict]:
    """Avisos cuyo destinatario es esta persona (las reglas ya decidieron a quién; acá no se decide nada)."""
    if not has_db():
        return []
    sql = "SELECT * FROM alerts WHERE patient_id = ?" + (" AND created_at >= ?" if since else "") + " ORDER BY id DESC"
    args = (patient_id, _iso(since)) if since else (patient_id,)
    with _conn() as c:
        rows = [dict(r) for r in c.execute(sql, args)]
    out = []
    for r in rows:
        r["recipients"] = _loads(r["recipients"], [])
        if person_id in r["recipients"]:
            out.append(r)
    return out


def alerts_period(patient_id: int, since: dt.datetime) -> list[dict]:
    if not has_db():
        return []
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM alerts WHERE patient_id = ? AND created_at >= ? ORDER BY id",
                                           (patient_id, _iso(since)))]


def alert(alert_id: int) -> dict | None:
    if not has_db():
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not r:
        return None
    a = dict(r)
    a["recipients"] = _loads(a["recipients"], [])
    return a


def logros(patient_id: int, since: dt.date) -> list[dict]:
    if not has_db():
        if patient_id != JUAN_PATIENT_ID:
            return []
        return [{"date": "2026-10-15", "time": None, "steps": 4060}]
    with _conn() as c:
        rows = c.execute("SELECT gd.date, gd.value FROM goal_days gd JOIN goals g ON g.id = gd.goal_id "
                         "WHERE g.patient_id = ? AND gd.achieved = 1 AND gd.notified = 1 AND gd.date >= ? ORDER BY gd.date",
                         (patient_id, since.isoformat())).fetchall()
    return [{"date": r["date"], "time": None, "steps": round(r["value"])} for r in rows]


def evidence(event_ids: list[int]) -> dict[int, dict]:
    """Datos para los chips de evidencia del informe: quién, cuándo y la cita literal."""
    if not event_ids or not has_db():
        return {}
    marks = ",".join("?" * len(event_ids))
    with _conn() as c:
        rows = c.execute(f"SELECT ev.id, ev.quote, ev.occurred_at, ev.time_vague, ev.reserved, en.created_at, en.raw_text, p.name, p.role "
                         f"FROM events ev JOIN entries en ON en.id = ev.entry_id JOIN people p ON p.id = en.speaker_id "
                         f"WHERE ev.id IN ({marks})", event_ids).fetchall()
    return {r["id"]: dict(r) for r in rows}


def episodes(patient_id: int) -> list[dict]:
    if not has_db():
        return []
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM episodes WHERE patient_id = ? ORDER BY dose_time", (patient_id,))]
    for r in rows:
        r["deviation"] = _loads(r["deviation"], None)
        r["explanation"] = _loads(r["explanation"], None)
    return rows


def latest_report(patient_id: int) -> dict | None:
    if not has_db():
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM reports WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient_id,)).fetchone()
    if not r:
        return None
    rep = dict(r)
    rep["content"] = _loads(rep["content"], None)
    return rep


# ================================================================ golpeteo

def tests_history(patient_id: int) -> list[dict]:
    if has_db():
        with _conn() as c:
            rows = [dict(r) for r in c.execute("SELECT taken_at, metrics, source FROM tests WHERE patient_id = ? ORDER BY taken_at",
                                               (patient_id,))]
        for r in rows:
            r["metrics"] = _loads(r["metrics"], {})
        return rows
    saved = [t for t in _read_json("tests", []) if t["patient_id"] == patient_id]
    if patient_id == JUAN_PATIENT_ID:
        base = now().date()
        saved = [{"patient_id": patient_id, "taken_at": dt.datetime.combine(base - dt.timedelta(days=7 - i), dt.time(10), TZ).isoformat(),
                  "metrics": {"taps_per_s": v}, "source": "seed"}
                 for i, v in enumerate([4.5, 4.3, 4.7, 4.4, 4.6, 4.2])] + saved
    return sorted(saved, key=lambda t: t["taken_at"])


def save_test(row: dict) -> None:
    if has_db():
        with _conn() as c:
            c.execute("INSERT INTO tests (patient_id, type, metrics, raw, taken_at, source) VALUES (?, 'golpeteo', ?, ?, ?, ?)",
                      (row["patient_id"], json.dumps(row["metrics"]), json.dumps(row["raw"]), row["taken_at"], row["source"]))
        return
    with _lock:
        rows = _read_json("tests", [])
        rows.append(row)
        _write_json("tests", rows)

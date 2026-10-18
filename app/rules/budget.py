# Presupuesto contra la fatiga (CLAUDE.md §6.5). Cuenta lo ya mandado en `notifications` ese día.
from datetime import datetime

from app import db
from app.config import TZ

# Alcance de las 04:15: las push son solo para recabar información (preguntas). Los avisos no notifican; la
# invitación al juego del plan diario tiene su propio límite (config.DAILY_MAX_GAME_INVITES, rules.plan).
QUIET_START, QUIET_END = 22, 8                     # silencio de 22 a 8 para todo menos rojo
PATIENT_DAILY = {"pregunta": 1, "repregunta": 1}   # Juan, por día (P-SILENCIO, P-REPITE)
FAMILY_DAILY = {"pregunta": 1}                     # Marta: 1 pregunta por día (datos raros: P-DESVIO, P-SUENO…)


def quiet_hours(now: datetime) -> bool:
    hour = now.astimezone(TZ).hour
    return hour >= QUIET_START or hour < QUIET_END


def _sent_today(person_id: int, kind: str, now: datetime) -> int:
    with db.connect() as conn:
        return conn.execute(
            "SELECT count(*) FROM notifications WHERE person_id = ? AND kind = ? AND substr(created_at, 1, 10) = ?",
            (person_id, kind, now.astimezone(TZ).date().isoformat())).fetchone()[0]


def _role(person_id: int) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT role FROM people WHERE id = ?", (person_id,)).fetchone()
    return row["role"] if row else None


def allow(person_id: int, kind: str, now: datetime) -> bool:
    """¿Se puede mandar ahora una notificación de `kind` a esta persona? El rojo siempre sale."""
    if kind == "rojo":
        return True
    if quiet_hours(now):
        return False
    role = _role(person_id)
    limits = PATIENT_DAILY if role == "paciente" else FAMILY_DAILY if role in ("cuidador", "familiar") else {}
    if kind in limits:
        return _sent_today(person_id, kind, now) < limits[kind]
    return True

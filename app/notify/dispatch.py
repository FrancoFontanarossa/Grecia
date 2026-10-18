# Reparte por push los avisos que ya decidieron las reglas (rules.lanes guarda cada Alert con sus destinatarios,
# calculados por rules.consent). notify no decide a quién: solo por dónde y con qué texto (ARQUITECTURA §6).
# Rojo: inmediato, sin presupuesto ni silencio. Ámbar a la familia: una push por día (rules.budget), sin detalle
# clínico en el cuerpo (se ve en la pantalla bloqueada). Ámbar al equipo: no hay push, va al informe y la bandeja.
import asyncio
import logging

from app import clock, db, notify
from app.models import Alert
from app.rules import budget

log = logging.getLogger("entrecasa.dispatch")

AMBER_FAMILY_TITLE = "Algo para mirar"
AMBER_FAMILY_BODY = "Hay algo nuevo en Hoy."
SUGGESTION_TITLE = "Una sugerencia"


def _people(ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    with db.connect() as conn:
        rows = conn.execute(f"SELECT id, role, name, patient_id FROM people WHERE id IN ({', '.join('?' * len(ids))})",
                            ids).fetchall()
    return {r["id"]: dict(r) for r in rows}


def _patient_name(patient_id: int) -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT name FROM people WHERE id = ?", (patient_id,)).fetchone()
    return row["name"] if row else "el paciente"


async def dispatch(alerts: list[Alert]) -> int:
    """Manda las push de estos avisos. Devuelve cuántas notificaciones creó."""
    sent = 0
    for alert in alerts:
        people = await asyncio.to_thread(_people, alert.recipients)
        patient = await asyncio.to_thread(_patient_name, alert.patient_id)
        for pid in alert.recipients:
            person = people.get(pid)
            if person is None or person["role"] == "neurologo":
                continue          # el equipo lo ve en el informe y la bandeja
            if alert.lane == "rojo":
                await notify.send(pid, "rojo", f"Rojo · {patient}", alert.text, f"/casa/emergencia/{alert.id}",
                                  lane="rojo")
            elif alert.lane == "ambar":
                now = await asyncio.to_thread(clock.now)
                if not await asyncio.to_thread(budget.allow, pid, "ambar", now):
                    log.info("presupuesto: el ámbar %s queda en Hoy sin push para %s", alert.id, pid)
                    continue
                if person["role"] == "paciente":   # la sugerencia de A3; nunca algo reservado
                    await notify.send(pid, "ambar", SUGGESTION_TITLE, alert.text, "/casa", lane="ambar")
                else:
                    await notify.send(pid, "ambar", AMBER_FAMILY_TITLE, AMBER_FAMILY_BODY, "/casa", lane="ambar")
            else:
                continue
            sent += 1
    return sent

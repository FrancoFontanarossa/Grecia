# Reparto de los avisos que ya decidieron las reglas (rules.lanes guarda cada Alert con sus destinatarios,
# calculados por rules.consent). Alcance de las 04:15: Entrecasa no es un botón de pánico ni un canal con la
# neuróloga, así que ningún aviso manda push. El rojo solo muestra su mensaje fijo a quien escribió (respuesta de
# POST /api/entries) y el ámbar es prioridad en el informe. Las push quedan para las preguntas (scheduler).
import logging

from app.models import Alert

log = logging.getLogger("entrecasa.dispatch")


async def dispatch(alerts: list[Alert]) -> int:
    """No manda nada: los avisos quedan en `alerts` para el informe. Devuelve cuántas notificaciones creó (0)."""
    for alert in alerts:
        log.info("aviso %s (%s, %s) queda para el informe, sin push", alert.id, alert.lane, alert.rule_id)
    return 0

# Bandeja: toda notificación queda en `notifications`, haya llegado la push o no (ARQUITECTURA §4.9).
import asyncio
import logging

from pydantic import TypeAdapter

from app import _tmp_db as db  # TEMPORAL: app.db de Franco
from app.models import Lane, Notification, NotificationKind
from app.notify.push import send_push

log = logging.getLogger(__name__)
_kind = TypeAdapter(NotificationKind)


async def send(person_id: int, kind: NotificationKind, title: str, body: str, url: str,
               lane: Lane | None = None) -> Notification:
    """Guarda la notificación y después intenta la push a todas las suscripciones de la persona.
    No decide a quién avisar (eso es rules/). Una push que falla nunca lanza error hacia arriba."""
    _kind.validate_python(kind)   # un kind fuera del contrato es un error de programación: falla antes de guardar
    row = await asyncio.to_thread(db.insert_notification, person_id=person_id, kind=kind, lane=lane,
                                  title=title, body=body, url=url)
    notification = Notification.model_validate(row)

    try:
        subscriptions = await asyncio.to_thread(db.subscriptions_for, person_id)
        results = await asyncio.gather(*(
            send_push({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                      title, body, url)
            for s in subscriptions
        ), return_exceptions=True)
        if any(r is True for r in results):
            await asyncio.to_thread(db.mark_push_sent, notification.id)
            notification.push_sent = True
    except Exception:
        log.exception("No se pudo entregar la push de la notificación %s", notification.id)
    return notification

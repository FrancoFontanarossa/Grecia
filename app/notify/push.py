# Web Push con pywebpush (sync, por eso va en asyncio.to_thread). Solo entrega: no decide a quién.
import asyncio
import json
import logging
import os

from pywebpush import WebPushException, webpush

from app import _tmp_db as db  # TEMPORAL: app.db de Franco

log = logging.getLogger(__name__)

PUSH_TTL_SECONDS = 24 * 60 * 60   # con ttl=0 Apple descarta la push si el teléfono no está en línea en ese momento


async def send_push(subscription: dict, title: str, body: str, url: str) -> bool:
    """Manda una push a una suscripción ({endpoint, keys: {p256dh, auth}}). True si salió.
    Si el servicio de push responde 404 o 410, la suscripción ya no sirve y se borra."""
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    subject = os.environ.get("VAPID_SUBJECT")
    if not private_key or not subject:
        log.warning("Faltan VAPID_PRIVATE_KEY o VAPID_SUBJECT: no se manda la push")
        return False
    payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
    try:
        await asyncio.to_thread(
            webpush,
            subscription_info=subscription,
            data=payload,
            vapid_private_key=private_key,
            vapid_claims={"sub": subject},   # dict nuevo en cada llamada: pywebpush le agrega aud y exp
            ttl=PUSH_TTL_SECONDS,
            headers={"Urgency": "high"},
            timeout=10,
        )
        return True
    except WebPushException as exc:
        if exc.status_code in (404, 410):
            log.info("Suscripción vencida (%s), se borra: %s", exc.status_code, subscription.get("endpoint"))
            await asyncio.to_thread(db.delete_subscription, subscription["endpoint"])
        else:
            log.warning("Falló la push: %s", exc)
        return False
    except Exception:
        log.exception("Error inesperado al mandar la push")
        return False

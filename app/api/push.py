import inspect
import json
import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["app"])
log = logging.getLogger("entrecasa.push")


class Subscribe(BaseModel):
    person_id: int
    subscription: dict


@router.post("/push/subscribe")
def subscribe(body: Subscribe):
    if not store.person(body.person_id):
        raise HTTPException(404, "No encontramos a esa persona.")
    if not body.subscription.get("endpoint"):
        raise HTTPException(422, "Suscripción sin endpoint.")
    store.save_push_subscription(body.person_id, body.subscription)
    return {"ok": True}


# TEMPORAL: borrar cuando exista notify.send (Guada). Sirve para el Hito 0: manda una push de prueba.
@router.post("/push/test/{person_id}")
async def push_test(person_id: int, url: str = "/casa"):
    person = store.person(person_id)
    if not person:
        raise HTTPException(404, "No encontramos a esa persona.")
    title = f"{person['name']}, esto es una prueba"
    body = "Si ves esto, los avisos de Neuro funcionan."
    try:
        from app import notify  # type: ignore

        if hasattr(notify, "send"):
            n = notify.send(person_id, "resumen", title, body, url)
            if inspect.isawaitable(n):
                n = await n
            return {"ok": True, "via": "notify.send",
                    "push_sent": getattr(n, "push_sent", None),
                    "subscriptions": len(store.push_subscriptions(person_id))}
    except ImportError:
        pass
    return {"ok": True, "via": "temporal", **_send_temporal(person_id, title, body, url)}


def _send_temporal(person_id: int, title: str, body: str, url: str) -> dict:
    from pywebpush import WebPushException, webpush

    private_key = os.environ.get("VAPID_PRIVATE_KEY", "")
    subject = os.environ.get("VAPID_SUBJECT", "mailto:entrecasa@example.com")
    if not private_key:
        raise HTTPException(500, "Falta VAPID_PRIVATE_KEY.")
    subs = store.push_subscriptions(person_id)
    sent, errors = 0, []
    for s in subs:
        try:
            webpush(
                subscription_info={"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                ttl=3600,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                store.delete_push_subscription(s["endpoint"])
            errors.append(f"{status}: {e}")
            log.warning("push falló: %s", e)
    store.add_notification(person_id, "resumen", title, body, url, push_sent=sent > 0)
    return {"subscriptions": len(subs), "sent": sent, "errors": errors}

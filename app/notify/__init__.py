# notify entrega lo que las reglas ya decidieron: notify.send(person_id, kind, title, body, url) -> Notification
from app.notify.inbox import send

__all__ = ["send"]

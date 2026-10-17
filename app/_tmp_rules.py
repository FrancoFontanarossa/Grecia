# TEMPORAL: reemplazar por las reglas de Franco en app/rules/ (consent, lanes) cuando existan. Código puro, con tests.
from app.models import Event

RESERVED_DOMAINS = {"neuropsiquiatrico", "impulsos", "sexual"}


def is_reserved(event: Event, *, reserved_requested: bool, canal_reservado_active: bool) -> bool:
    """CLAUDE.md §6.4: solo lo que cuenta la familia, si lo pidió o si el dominio es sensible, y con el consentimiento."""
    return (event.speaker_role in {"cuidador", "familiar"}
            and (reserved_requested or event.domain in RESERVED_DOMAINS)
            and canal_reservado_active)


def mark_new(events: list[Event], already_mentioned: set[str]) -> list[bool]:
    """is_new: primera mención (no negada) del síntoma en la historia del paciente. "otro" nunca es nuevo:
    no se puede comparar. Dentro de una misma entrada, solo la primera aparición cuenta."""
    seen = set(already_mentioned)
    flags = []
    for e in events:
        new = not e.negated and e.symptom != "otro" and e.symptom not in seen
        if not e.negated:
            seen.add(e.symptom)
        flags.append(new)
    return flags

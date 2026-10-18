"""Línea de base sin IA (CLAUDE.md §13): búsqueda por palabras sobre app/taxonomy.py + negación por reglas.

Misma salida que pipeline.extract: list[Event]. Sin atribución ajena (una búsqueda por palabras no la ve) y
la hora por palabras clave, resuelta con el mismo código que la extracción (pipeline.when.resolve).
"""
import re

from app import taxonomy
from app.models import Entry, Event
from app.pipeline.when import TimeSaid, resolve
from app.rules.text import fold

NEGATORS = {"no", "nunca", "sin"}
NEGATION_WINDOW = 3          # palabras antes de la mención, dentro de la misma frase
_WEEKDAYS = {"lunes": "lunes", "martes": "martes", "miercoles": "miercoles", "jueves": "jueves",
             "viernes": "viernes", "sabado": "sabado", "domingo": "domingo"}

# Formas de la taxonomía (clave y sinónimos), de la más larga a la más corta; "otro" no es un síntoma.
FORMS = [(form, key) for form, key in taxonomy._FORMS if key != "otro" and form]


def _negated(text: str, start: int) -> bool:
    clause = re.split(r"[.,]", text[:start])[-1].split()
    return any(w in NEGATORS for w in clause[-NEGATION_WINDOW:])


def time_said(t: str) -> TimeSaid:
    if re.search(r"\b(anoche|esta noche|ayer de noche|ayer a la noche)\b", t):
        return TimeSaid(day="ayer", part="noche")
    if re.search(r"\b(esta manana|hoy a la manana)\b", t):
        return TimeSaid(day="hoy", part="manana")
    if re.search(r"\besta tarde\b", t):
        return TimeSaid(day="hoy", part="tarde")
    if re.search(r"\bhoy\b", t):
        return TimeSaid(day="hoy")
    if re.search(r"\banteayer\b", t):
        return TimeSaid(day="anteayer")
    if re.search(r"\bayer\b", t):
        part = "tarde" if re.search(r"\bayer a la (tarde|tardecita)\b", t) else \
               "manana" if re.search(r"\bayer a la manana\b", t) else None
        return TimeSaid(day="ayer", part=part)
    for word, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{word}\b", t):
            return TimeSaid(day="dia_semana", weekday=weekday)
    return TimeSaid(day="no_dice")


def extract(entry: Entry) -> list[Event]:
    t = fold(entry.raw_text)
    taken: list[tuple[int, int]] = []
    found: dict[str, Event] = {}
    occurred_at, time_vague = resolve(time_said(t), entry.occurred_hint, entry.created_at)
    for form, key in FORMS:
        for m in re.finditer(rf"\b{re.escape(form)}\b", t):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue                                   # ya lo cubre una forma más larga
            taken.append((m.start(), m.end()))
            if key in found:
                continue
            found[key] = Event(
                domain=taxonomy.SYMPTOMS[key], symptom=key, severity=None, negated=_negated(t, m.start()),
                occurred_at=occurred_at, time_vague=time_vague, speaker_role=entry.speaker_role,
                foreign_attribution=None, quote=m.group(0), plain=m.group(0), confidence=1.0,
            )
    return list(found.values())

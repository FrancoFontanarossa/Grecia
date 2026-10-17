# Normalización de texto para las reglas: minúsculas, sin tildes, con los cortes de frase marcados
# ("." y ",") para que una negación no salte de una frase a otra. Los decimales "38,5" quedan "38d5".
import re
import unicodedata

_NEGATORS = re.compile(r"\b(no|sin|ni|nunca|tampoco|jamas)\b")
_NOT_A_NEGATION = re.compile(r"\bno (se|sabemos|sabe|se sabe) si\b")      # "no sé si se golpeó": duda, no negación
_CLAUSE_BREAK = re.compile(r"[.,]| y | pero | aunque | despues | luego ")


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"(\d)[.,](\d)", r"\1d\2", t)
    t = re.sub(r"[.;:!?\n]+", " . ", t)
    t = t.replace(",", " , ")
    t = re.sub(r"[^a-z0-9.,\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def negated(t: str, pos: int) -> bool:
    """¿La frase que termina en `pos` está negada? Mira hasta 4 palabras antes, dentro de la misma frase."""
    clause = _CLAUSE_BREAK.split(" " + t[:pos])[-1]
    if _NOT_A_NEGATION.search(clause):
        return False
    return bool(_NEGATORS.search(" ".join(clause.split()[-4:])))


def affirmed(pattern: re.Pattern, t: str) -> bool:
    """Hay al menos una mención de `pattern` que no está negada."""
    return any(not negated(t, m.start()) for m in pattern.finditer(t))


def mentioned(pattern: re.Pattern, t: str) -> bool:
    return bool(pattern.search(t))

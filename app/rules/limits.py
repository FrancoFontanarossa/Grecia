# Límites (CLAUDE.md §7.6): si el relato pide algo sobre medicación, dosis, estadio, diagnóstico o pronóstico,
# se responde con un texto fijo y se anota igual. Nunca lo contesta el modelo.
import re

from app.rules.text import fold

LIMIT_TEXT = "Eso lo decide tu neuróloga. Lo anoto para que lo lleves a la consulta."

_DRUG = (r"(levodopa|carbidopa|sinemet|madopar|prolopa|stalevo|pramipexol|mirapex|ropinirol|rotigotina|rasagilina|"
         r"safinamida|amantadina|entacapona|apomorfina|clonazepam|rivotril|quetiapina|clozapina|melatonina|"
         r"pastillas?|comprimidos?|remedios?|medicacion|medicamentos?|dosis|gotas|parche)")
_ART = r"((el|la|los|las|un|una|unas|unos|media|otra|mas) )?"
# Cambiar algo de la medicación, en primera persona o con un modal: "le subo el pramipexol", "¿puedo dejar la
# levodopa?", "¿le doy media pastilla más?", "¿me conviene adelantar la pastilla?". No "le cambiaron la medicación".
_ACTION_1ST = r"(subo|bajo|aumento|saco|dejo|suspendo|cambio|adelanto|atraso|corro|doy|agrego|tomo|parto)"
_ACTION_INF = (r"(subir|bajar|aumentar|sacar|dejar|suspender|cambiar|adelantar|atrasar|correr|dar|agregar|tomar|"
               r"partir|reducir)(le|les|me|se|lo|la|selo|sela|melo|mela)?")
_MODAL = (r"(puedo|podemos|podria|podriamos|conviene|convendria|me conviene|le conviene|deberia|deberiamos|"
          r"tengo que|tenemos que|hay que|habria que|es mejor|seria mejor)")

PATTERNS = {
    "medicacion": re.compile(
        rf"\b((le|les|me|se lo|se la) )?{_ACTION_1ST} {_ART}{_DRUG}\b"
        rf"|\b{_MODAL} {_ACTION_INF} {_ART}{_DRUG}\b"
        rf"|\bse (lo|la) (saco|bajo|subo|dejo|suspendo|cambio|doy)\b"
        rf"|\b{_ACTION_1ST} {_ART}{_DRUG}\b"),
    "dosis": re.compile(r"\bcuant[oa]s? (miligramos|mg|pastillas|comprimidos|gotas|dosis)\b|\bque dosis\b"
                        r"|\bcuanto (le )?(doy|damos|tomo|tiene que tomar)\b"),
    "estadio": re.compile(r"\b(en )?que (etapa|estadio|fase|grado)\b|\b(es|esta|ya es|ya esta) (un )?parkinson avanzado\b"
                          r"|\bque tan avanzad[oa]\b|\besta (muy )?avanzad[oa]\b"),
    "diagnostico": re.compile(r"\b(tiene|tendra|sera|es) parkinson\b|\bque enfermedad tiene\b"),
    "pronostico": re.compile(r"\bcuanto (tiempo )?(mas )?(le queda|va a poder|va a durar|vive|falta)\b"
                             r"|\bcuanto tiempo mas\b|\b(se va a curar|tiene cura|va a empeorar|cuantos anos le quedan)\b"),
}
# Solo dentro de una pregunta: "¿es por el pramipexol?" (no "el cardiólogo dice que es por las pastillas") y la
# primera del plural, que es igual en presente y en pasado ("¿le bajamos la dosis?" / "le bajamos la dosis").
_IN_QUESTION = re.compile(
    rf"\b(es|sera|puede ser) (por|culpa de|culpa del) {_ART}{_DRUG}\b"
    rf"|\b(subimos|bajamos|aumentamos|sacamos|dejamos|suspendemos|cambiamos|adelantamos|atrasamos|damos|agregamos)"
    rf" {_ART}{_DRUG}\b")


def _plain(text: str) -> str:
    """Pliega el texto marcando antes el pretérito: "tomó" no es "tomo" ("se tomó la pastilla" es un relato)."""
    return fold(re.sub(r"ó\b", "o3", text.lower()))


def _questions(text: str) -> list[str]:
    return [_plain(q) for q in re.findall(r"¿?[^.?!¿]*\?", text)]


def matches(text: str) -> list[str]:
    """Qué pide el texto (medicacion, dosis, estadio, diagnostico, pronostico), o [] si nada."""
    t = _plain(text)
    found = [name for name, p in PATTERNS.items() if p.search(t)]
    if "medicacion" not in found and any(_IN_QUESTION.search(q) for q in _questions(text)):
        found.append("medicacion")
    return found


def check(text: str) -> str | None:
    """El texto fijo de §7.6 si el relato pide medicación, dosis, estadio, diagnóstico o pronóstico; si no, None."""
    return LIMIT_TEXT if matches(text) else None

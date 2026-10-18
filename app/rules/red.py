# Rojos R1 a R4 (CLAUDE.md §6.3) por reglas, antes del LLM. Textos fijos: nunca los escribe el modelo.
# check() devuelve un RedResult con missing_criterion=None si es rojo, o con missing_criterion y la
# repregunta de solo ese criterio si falta un dato, o None si no hay nada.
import re

from app import db
from app.models import RedResult
from app.rules.text import affirmed, fold, mentioned

# Alcance (04:15): Entrecasa no es un botón de pánico. El único efecto de un rojo es este mensaje fijo en la
# pantalla de quien escribió el relato; en el informe queda marcado con su etiqueta (RED_LABELS).
RED_MESSAGE = ("Esto puede ser urgente. Neuro no es un servicio de emergencias: si es urgente, "
               "llamá a tu emergencia móvil.")
# VERIFICAR NÚMERO de la Línea Vida antes de la demo (CLAUDE.md §16.8).
R4_MESSAGE = "Si estás pensando en hacerte daño, llamá a la Línea Vida: 0800 0767 o *0767, las 24 horas."
RED_TEXTS = {"R1": RED_MESSAGE, "R2": RED_MESSAGE, "R3": RED_MESSAGE, "R4": R4_MESSAGE, None: RED_MESSAGE}
# Lo que se marca en el informe: nombra los signos, no un tema reservado (§6.4).
RED_LABELS = {
    "R1": "Caída con golpe en la cabeza y un signo de alarma",
    "R2": "Fiebre con signos de alarma",
    "R3": "Medicación que no entra (vómitos o no poder tragar)",
    "R4": "Ideas de muerte o de hacerse daño",
    None: "Posible señal de alarma (respaldo con IA)",
}


def red_label(rule_id: str) -> str:
    """Etiqueta del rojo para el informe; "R1-IA" usa la de R1."""
    return RED_LABELS.get(rule_id.removesuffix("-IA"), RED_LABELS[None])

# R1: repregunta de solo los criterios que faltan (los que el relato ya negó no se preguntan).
R1_CRITERIA_QUESTIONS = {
    "anticoagulante": "¿Toma algún anticoagulante, como Eliquis, Xarelto o Sintrom?",
    "desmayo": "¿Se desmayó o perdió el conocimiento?",
    "vomito": "¿Vomitó después del golpe?",
    "dolor_de_cabeza": "¿Le duele la cabeza?",
}
R2_QUESTIONS = {
    "temperatura": "¿Cuánto le marcó el termómetro?",
    "signos": "¿Está muy rígido, confundido o ve cosas que no están?",
}
_ASK_PREFIX = "Para saber si es urgente: "

# ── Patrones (sobre texto plegado: sin tildes, en minúscula) ─────────────────────────────────────────────
_HEAD = r"(cabeza|frente|nuca|craneo|sien)"
_HEAD_HIT = re.compile(
    rf"\b(golpe\w*|peg\w*|choc\w*|porrazo|trompazo|lastim\w*|partio|abrio)\b(\s+[^\s.,]+){{0,6}}?\s+{_HEAD}\b"
    rf"|\bse (la |lo )?dio ([^\s.,]+ ){{0,4}}?{_HEAD}\b"
    rf"|\b{_HEAD} (contra|en) (el|la) (piso|suelo|mesa|pared|puerta|cama|mueble|cordon|vereda|banadera|inodoro)\b"
    r"|\bchichon\b"
)
# "le dio dolor de cabeza", "de golpe le dolió la cabeza", "le da vueltas la cabeza" no son golpes:
# se sacan antes de buscar el golpe.
_HEAD_NOT_HIT = re.compile(rf"\b(dolor|dolores) de {_HEAD}|\b(duele|dolio|dolia|doliendo) (mucho |un poco )?la {_HEAD}"
                           rf"|\bvueltas? (la )?{_HEAD}|\bcefalea\b|\bde golpe\b")
_ANTICOAG = re.compile(r"\b(apixaban|eliquis|rivaroxaban|xarelto|dabigatran|pradaxa|edoxaban|lixiana|warfarina|"
                       r"coumadin|acenocumarol|sintrom|heparina|enoxaparina|clexane|anticoagul\w*)\b")
_LOST_CONSCIOUSNESS = re.compile(r"\b(desmay\w*|perdio el conocimiento|perdio la conciencia|inconsciente|"
                                 r"no respondia|sin sentido)\b")
_VOMIT = re.compile(r"\b(vomit\w*|devolv\w* (todo|la comida|lo que)|devuelv\w* (todo|la comida|lo que))")
_HEADACHE = re.compile(r"\b(dolor|dolores) de cabeza\b|\b(duele|dolio|dolia) (mucho |un poco )?la cabeza\b|\bcefalea\b")

_FEVER = re.compile(r"\b(fiebre|febril|temperatura|grados|termometro)\b")
_FEVER_HIGH_WORDS = re.compile(r"\b(fiebre alta|mucha fiebre|volando de fiebre|hirviendo)\b")
_TEMPERATURE = re.compile(r"\b(3[5-9]|4[0-2])(?:d(\d))?( y medio)?\b")
_RIGID = re.compile(r"\b(rigid\w*|ties[oa]|agarrotad\w*|muy dur[oa]|no se (puede|podia|pudo) mover)\b")
_CONFUSED = re.compile(r"\b(confundid\w*|confusion|desorientad\w*|no sab\w* donde (esta|estaba)|"
                       r"dice cosas sin sentido|deliri\w*|delira\w*)\b")
_HALLUCINATION = re.compile(r"\b(alucin\w*|ve (gente|cosas|personas|animales)|veia (gente|cosas|personas|animales)|"
                            r"empezo a ver|habla\w* con (alguien|gente) que no (esta|estaba)|oye voces|escucha voces)\b")

_CANT_SWALLOW = re.compile(r"\b(no (puede|pudo|podia|logra|logro) tragar|no traga|"
                           r"(las pastillas|la pastilla|los remedios|la medicacion) no (le )?(bajan|baja|pasan|pasa)|"
                           r"se (le )?(atora|atoran|traba|traban|queda|quedan) (en la garganta|la pastilla|las pastillas)|"
                           r"escupe (la|las) pastill\w*)")
_LEVODOPA = re.compile(r"\b(levodopa|carbidopa|sinemet|madopar|prolopa|benserazida|stalevo)\b")

_SUICIDE = re.compile(
    r"\b(me|se|te) quier\w* morir\b|\bquier\w* morir(me|se)?\b|\bganas de morir(me|se)?\b"
    r"|\bno quier\w* (seguir )?vivir\b|\bmatar(me|se)\b|\b(me|se) (voy|va) a matar\b|\b(me|se) quier\w* matar\b"
    r"|\bsuicid\w*|\bquitar(me|se) la vida\b|\bterminar con todo\b|\bmejor (estar|estaria) muert[oa]\b"
    r"|\bojala no (me )?despiert\w*|\bpara que seguir viviendo\b|\bno vale la pena vivir\b"
)


def _red(rule_id: str) -> RedResult:
    return RedResult(rule_id=rule_id, missing_criterion=None, text=RED_TEXTS[rule_id])


def _ask(rule_id: str, criteria: list[str], questions: dict[str, str]) -> RedResult:
    return RedResult(rule_id=rule_id, missing_criterion=",".join(criteria),
                     text=_ASK_PREFIX + " ".join(questions[c] for c in criteria))


def _r1(t: str, meds: list[str]) -> RedResult | None:
    if not affirmed(_HEAD_HIT, _HEAD_NOT_HIT.sub(" ", t)):
        return None
    if any(_ANTICOAG.search(fold(m)) for m in meds):
        return _red("R1")
    checks = {"anticoagulante": _ANTICOAG, "desmayo": _LOST_CONSCIOUSNESS, "vomito": _VOMIT,
              "dolor_de_cabeza": _HEADACHE}
    if any(affirmed(p, t) for p in checks.values()):
        return _red("R1")
    missing = [c for c, p in checks.items() if not mentioned(p, t)]     # lo que el relato negó no se pregunta
    return _ask("R1", missing, R1_CRITERIA_QUESTIONS) if missing else None


def _temperature_high(t: str) -> bool | None:
    """True si hay ≥38 °C cerca de una mención de fiebre, False si todas las cifras son menores, None si no dice."""
    if affirmed(_FEVER_HIGH_WORDS, t):
        return True
    values = []
    for m in _TEMPERATURE.finditer(t):
        near = t[max(0, m.start() - 30):m.end() + 30]
        if _FEVER.search(near):
            values.append(int(m.group(1)) + (int(m.group(2)) / 10 if m.group(2) else 0) + (0.5 if m.group(3) else 0))
    return max(values) >= 38 if values else None


def _r2(t: str) -> RedResult | None:
    if not affirmed(_FEVER, t):
        return None
    high = _temperature_high(t)
    signs = any(affirmed(p, t) for p in (_RIGID, _CONFUSED, _HALLUCINATION))
    if high is False:
        return None
    if high and signs:
        return _red("R2")
    if high:
        return _ask("R2", ["signos"], R2_QUESTIONS)
    return _ask("R2", ["temperatura"], R2_QUESTIONS) if signs else None


def _r3(t: str, meds: list[str]) -> RedResult | None:
    if not any(_LEVODOPA.search(fold(m)) for m in meds):
        return None
    return _red("R3") if affirmed(_VOMIT, t) or affirmed(_CANT_SWALLOW, t) else None


def _r4(t: str) -> RedResult | None:
    return _red("R4") if affirmed(_SUICIDE, t) else None


def evaluate(text: str, meds: list[str]) -> RedResult | None:
    """Reglas puras sobre el texto y los fármacos del esquema. Un rojo completo gana sobre una repregunta;
    entre rojos, el orden es R4, R1, R2, R3."""
    t = fold(text)
    results = [r for r in (_r4(t), _r1(t, meds), _r2(t), _r3(t, meds)) if r is not None]
    reds = [r for r in results if r.missing_criterion is None]
    return (reds or results or [None])[0]


def patient_meds(patient_id: int) -> list[str]:
    with db.connect() as conn:
        return [r["drug"] for r in conn.execute("SELECT drug FROM med_schedule WHERE patient_id = ?", (patient_id,))]


def check(text: str, patient: int) -> RedResult | None:
    """Contrato de §11: `patient` es el patient_id; los fármacos salen de med_schedule."""
    return evaluate(text, patient_meds(patient))


def from_backup(suspected_rule: str | None) -> RedResult:
    """Rojo que subió el respaldo con IA (solo sube): texto fijo de la regla sospechada o el genérico."""
    rule = suspected_rule if suspected_rule in RED_TEXTS else None
    return RedResult(rule_id=f"{rule or 'R'}-IA", missing_criterion=None, text=RED_TEXTS[rule])

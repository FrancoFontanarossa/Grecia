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


# ── Rojos ───────────────────────────────────────────────────────────────────────────────────────────────
# TEMPORAL: solo R1 por reglas (rules.red de Franco hará R1 a R4). Los textos son fijos: nunca los escribe el modelo.
import re  # noqa: E402

from app.models import RedResult  # noqa: E402
from app.taxonomy import _fold  # noqa: E402

RED_TEXTS = {
    "R1": "Golpe en la cabeza con anticoagulante, desmayo, vómitos o dolor de cabeza: necesita que lo vea un médico "
          "ahora. Llamá a la emergencia móvil.",
    "R2": "Fiebre con mucha rigidez, confusión o alucinaciones que aparecieron de golpe: necesita atención médica "
          "ahora. Llamá a la emergencia móvil.",
    "R3": "Si no puede tragar o vomita la medicación, la levodopa no está entrando: llamá a la emergencia móvil.",
    "R4": "Lo que contás es muy importante y hay alguien para escucharte: llamá ya a la Línea Vida, "
          "0800 0767 o *0767, gratis y a toda hora.",   # verificar el número antes de la demo
    None: "Lo que contaste puede ser una señal de alarma. Si te preocupa, llamá a la emergencia móvil.",
}
R1_MISSING_QUESTION = "¿Toma algún anticoagulante? ¿Se desmayó, vomitó o le duele la cabeza después del golpe?"

_HEAD_HIT = re.compile(r"\b(golpe\w*|peg\w*|dio|choc\w*|porrazo)\b.{0,40}\b(cabeza|frente|nuca)\b"
                       r"|\b(cabeza|frente|nuca)\b.{0,25}\b(golpe\w*|peg\w*|choc\w*)\b")
_NO_HEAD_HIT = re.compile(r"\bno se (golpeo|pego|dio)\b.{0,20}\b(cabeza|frente|nuca)\b")
_ANTICOAG = re.compile(r"\b(apixaban|rivaroxaban|dabigatran|edoxaban|warfarina|acenocumarol|heparina|anticoagul\w*)\b")
_LOST_CONSCIOUSNESS = re.compile(r"\b(se desmay\w*|desmay\w*|perdio el conocimiento|inconsciente|no respondia)\b")
_VOMIT = re.compile(r"\bvomit\w*\b")
_HEADACHE = re.compile(r"\b(dolor de cabeza|le duele la cabeza|me duele la cabeza|cefalea)\b")


def red_check(text: str, meds: list[str]) -> RedResult | None:
    """R1 por reglas. Golpe en la cabeza + (anticoagulante, desmayo, vómito o dolor de cabeza) → rojo.
    Golpe sin ninguno de esos datos → RedResult con missing_criterion (se pregunta solo eso)."""
    t = _fold(text)
    hit_text = _HEADACHE.sub(" ", t)   # "le dio dolor de cabeza" no es un golpe
    if not _HEAD_HIT.search(hit_text) or _NO_HEAD_HIT.search(t):
        return None
    anticoag = bool(_ANTICOAG.search(t)) or any(_ANTICOAG.search(_fold(m)) for m in meds)
    if anticoag or _LOST_CONSCIOUSNESS.search(t) or _VOMIT.search(t) or _HEADACHE.search(t):
        return RedResult(rule_id="R1", missing_criterion=None, text=RED_TEXTS["R1"])
    return RedResult(rule_id="R1", missing_criterion="anticoagulante_o_signos", text=R1_MISSING_QUESTION)


def red_from_backup(suspected_rule: str | None) -> RedResult:
    """Rojo que subió el respaldo con IA: texto fijo de la regla sospechada (o el genérico)."""
    return RedResult(rule_id=f"{suspected_rule or 'R'}-IA", missing_criterion=None, text=RED_TEXTS[suspected_rule])

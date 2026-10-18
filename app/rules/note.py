# Verificador de la nota de la revisión diaria (bitácora). Mismas reglas que verify_local del informe
# (app/pipeline/report.py): se borra la frase con una cifra que no está en el digest, una aproximación, una cita que
# no es literal o una palabra prohibida (diagnóstico, medicación, on/off, causa). Además, como la nota es prosa:
#   · cada oración del texto tiene que citar al menos un ref válido entre corchetes ("[relato:12]"); sin evidencia se
#     borra, y con un ref que no está en el digest también;
#   · un punto sin evidencia, o con un ref que no existe, se borra entero;
#   · un "seguir mirando" con una cifra ajena o una palabra prohibida se borra.
# Lo borrado se cuenta en removed_count. La nota es solo para el equipo médico (nunca va a la familia ni a Juan).
import json
import re

from app.models import DailyNote, NotePoint
from app.pipeline.daily_plan import FORBIDDEN
from app.pipeline.report import _APPROX, _NUMBER, _QUOTED
from app.taxonomy import _fold

REF = re.compile(r"\[?\b((?:relato|episodio|juego|alerta|dia|nota):[0-9A-Za-z\-]+)\]?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SKIP_KEYS = {"ref", "refs_citados", "patient_id"}       # los ids de los refs no son cifras que la nota pueda usar


def _walk(value, key=None):
    if key in _SKIP_KEYS:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, key)
    else:
        yield value


def _number_forms(x) -> set[str]:
    if isinstance(x, bool) or x is None:
        return set()
    if isinstance(x, float) and not x.is_integer():
        forms = {repr(x), f"{x:.1f}", str(round(x))}
        return forms | {f.replace(".", ",") for f in forms}
    n = int(x)
    return {str(n), f"{n:,}".replace(",", ".")}


def allowed_numbers(digest: dict) -> set[str]:
    """Las cifras que la nota puede escribir: las del digest (números y textos), con fechas también como dd/mm."""
    out: set[str] = set()
    for v in _walk(digest):
        if isinstance(v, (int, float)):
            out |= _number_forms(v)
        elif isinstance(v, str):
            out |= set(_NUMBER.findall(REF.sub(" ", v)))
            for y, m, d in _ISO_DATE.findall(v):
                out |= {f"{d}/{m}", f"{int(d)}/{int(m)}", f"{int(d)}/{m}", f"{d}/{int(m)}"}
    return out


def valid_refs(digest: dict) -> set[str]:
    refs = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("ref"), str):
                refs.add(value["ref"])
            refs.update(value.get("refs_citados") or [])      # lo que citaban las notas previas (ya verificado)
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(digest)
    return refs


def quotes(digest: dict) -> list[str]:
    out = []

    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("cita", "texto") and isinstance(v, str):
                    out.append(v.rstrip("…"))
                else:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(digest)
    return out


def problem(text: str, numbers: set[str], refs: set[str], cites: list[str], *, need_ref: bool) -> str | None:
    """Por qué una frase de la nota no pasa (None si pasa)."""
    found = REF.findall(text)
    if need_ref and not found:
        return "sin evidencia"
    bad = [r for r in found if r not in refs]
    if bad:
        return f"evidencia que no existe: {', '.join(bad)}"
    bare = REF.sub(" ", text)
    for n in _NUMBER.findall(bare):
        if n not in numbers:
            return f"cifra que no está en el resumen: {n}"
    folded = _fold(bare)
    if _APPROX.search(folded):
        return "aproxima una cifra"
    if FORBIDDEN.search(folded):
        return "diagnostica, habla de medicación o de causa"
    for m in _QUOTED.finditer(bare):
        quote = next(g for g in m.groups() if g)
        if not any(quote in c for c in cites):
            return f"la cita «{quote}» no es literal"
    return None


def sentences(text: str) -> list[str]:
    """Oraciones; un fragmento que es solo refs ("[relato:3].") se pega a la oración anterior."""
    out: list[str] = []
    for s in _SENTENCE.split((text or "").strip()):
        if not s:
            continue
        if out and not REF.sub("", s).strip(" .;,"):
            out[-1] = f"{out[-1]} {s}"
        else:
            out.append(s)
    return out


def verify_note(note: DailyNote, digest: dict) -> tuple[DailyNote, int]:
    """(nota limpia, cantidad de cosas borradas)."""
    numbers, refs, cites = allowed_numbers(digest), valid_refs(digest), quotes(digest)
    removed = 0
    kept = []
    for s in sentences(note.text):
        if problem(s, numbers, refs, cites, need_ref=True):
            removed += 1
        else:
            kept.append(s)
    points = []
    for p in note.points:
        if (not p.evidence_ids or any(e not in refs for e in p.evidence_ids)
                or problem(p.text, numbers, refs, cites, need_ref=False)):
            removed += 1
        else:
            points.append(NotePoint(text=p.text.strip(), evidence_ids=list(dict.fromkeys(p.evidence_ids))))
    follow = []
    for f in note.follow_up:
        if not f.strip():
            continue
        if problem(f, numbers, refs, cites, need_ref=False):
            removed += 1
        else:
            follow.append(f.strip())
    return DailyNote(text=" ".join(kept), points=points, follow_up=follow), removed


def to_row(note: DailyNote) -> dict:
    return {"text": note.text, "points": json.dumps([p.model_dump() for p in note.points], ensure_ascii=False),
            "follow_up": json.dumps(note.follow_up, ensure_ascii=False)}

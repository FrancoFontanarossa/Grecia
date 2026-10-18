# pipeline.report(patient_id, period) -> Report (CLAUDE.md §5.5 y §11). El código calcula los facts
# (report_facts.build), Sonnet redacta el resumen y los tres temas, el código fuerza `reserved` y descarta ids que no
# existen, y el verificador (rules.verifier de Franco) borra cifras y citas que no coinciden. Se guarda en `reports`.
# Regeneración en segundo plano: como mucho una vez cada 30 s por paciente, y gana la última.
import asyncio
import json
import logging
import re
import time
from pathlib import Path

from pydantic import BaseModel

from app import _tmp_rules, clock, db
from app.models import Report, ReportTopic
from app.pipeline import knowledge, llm, report_facts
from app.taxonomy import _fold

try:                                   # el verificador es de Franco; mientras no esté, el stub TEMPORAL
    from app.rules import verifier as _verifier  # type: ignore
    verify = _verifier.verify
except ImportError:
    verify = _tmp_rules.verify_stub

log = logging.getLogger("entrecasa.report")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "report.md"
SUMMARY_WORDS = (30, 160)
NARRATIVE_WORDS = 120
REGEN_SECONDS = 30
VOICES = ("paciente", "cuidador", "familiar")

_nullable_str = {"anyOf": [{"type": "string"}, {"type": "null"}]}
TOOL = {
    "name": "redactar_informe",
    "description": "Redacta el resumen del período y los tres temas del informe para la neuróloga.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "topics": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "narrative": {"type": "string"},
                    "observed": {"type": "array", "items": {"type": "string"}},
                    "voices": {"type": "object", "properties": {v: _nullable_str for v in VOICES},
                               "required": list(VOICES), "additionalProperties": False},
                    "question": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                    "reserved": {"type": "boolean"},
                },
                "required": ["title", "narrative", "observed", "voices", "question", "evidence_ids", "reserved"],
                "additionalProperties": False,
            }},
        },
        "required": ["summary", "topics"],
        "additionalProperties": False,
    },
}


class _Topic(BaseModel):
    title: str
    narrative: str
    observed: list[str]
    voices: dict[str, str | None]
    question: str
    evidence_ids: list[int]
    reserved: bool


class _Output(BaseModel):
    summary: str
    topics: list[_Topic]


def prompt() -> str:
    return knowledge.strip_comment(PROMPT_PATH.read_text(encoding="utf-8"))


def user_message(facts: dict) -> str:
    text = json.dumps(facts, ensure_ascii=False, indent=1, default=str).replace("</facts>", "</ facts>")
    return f"<facts>\n{text}\n</facts>"


# Números: fechas dd/mm como un solo token; el resto, enteros o decimales con . o ,
_NUMBER = re.compile(r"\d{1,2}/\d{1,2}|\d+(?:[.,]\d+)*")
_APPROX = re.compile(r"\b(unos|unas|alrededor de|aproximadamente|cerca de|casi|mas de|menos de|mas o menos)\s+\d")
_EXPLAINED = re.compile(r"\bexplicad\w*|\bsin explicar\b|\bsin explicacion\w*")
_PARTS = {"mediodia": re.compile(r"\bmediodia\b"), "madrugada": re.compile(r"\bmadrugada\b"),
          "manana": re.compile(r"\b(a|por) la manana\b"), "noche": re.compile(r"\b(a|por) la noche\b|\bde noche\b")}
_QUOTED = re.compile(r"«([^»]+)»|“([^”]+)”|\"([^\"]+)\"")


def _strings(value, skip=("label",)) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() if k not in skip for s in _strings(v, skip)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, skip)]
    return []                       # números crudos e ids no cuentan: las cifras van como strings


def allowed_numbers(facts: dict) -> set[str]:
    return {n for text in _strings(facts) for n in _NUMBER.findall(text)}


def _unquote(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().strip('"\'“”«»').strip()
    return value or None


def _texts(t: _Topic) -> list[str]:
    return [t.title, t.narrative, t.question, *t.observed]


_PRIVATE_WORDS = ("alucin", "delir", "gente que no", "alguien que no", "personas que no", "confund", "confusion",
                  "impuls", "apuest", "compuls", "sexual", "deseo")


def private_sentence(indices: list[int]) -> str:
    """La única frase del resumen sobre lo reservado (CLAUDE.md §6.4)."""
    if len(indices) == 1:
        return f"Hay un tema para hablar en privado (tema {indices[0]})."
    nums = ", ".join(str(i) for i in indices[:-1]) + f" y {indices[-1]}"
    return f"Hay {len(indices)} temas para hablar en privado (temas {nums})."


def check_private_summary(out: "_Output", events: dict) -> None:
    """Con un tema reservado, el resumen solo dice que existe: ni su contenido, ni quién lo contó, ni cuándo."""
    reserved_ids = {i for i, e in events.items() if e.get("reserved")}
    indices = [n for n, t in enumerate(out.topics, 1)
               if t.reserved or set(t.evidence_ids) & reserved_ids]
    if not indices:
        return
    summary, folded = out.summary, _fold(out.summary)
    sentence = private_sentence(indices)
    if sentence not in summary:
        raise ValueError(f"el resumen tiene que decir, tal cual: «{sentence}»")
    rest = _fold(summary.replace(sentence, " "))
    private = [events[i] for t in (out.topics[n - 1] for n in indices) for i in t.evidence_ids if i in events]
    public = [e for i, e in events.items() if i not in reserved_ids]
    leaks = [w for w in _PRIVATE_WORDS if w in rest]
    leaks += [e["quote"] for e in private if _fold(e["quote"]) in rest]
    leaks += [t.title for n, t in enumerate(out.topics, 1) if n in indices and _fold(t.title) in rest]
    public_dates = {d for e in public for d in (e.get("date"), e.get("told_date")) if d}
    leaks += [d for e in private for d in (e.get("date"), e.get("told_date"))
              if d and d not in public_dates and d in rest]
    public_speakers = {e.get("speaker_label") for e in public}
    leaks += [e["speaker_label"] for e in private
              if e.get("speaker_label") and e["speaker_label"] not in public_speakers
              and _fold(e["speaker_label"].split(",")[0]) in rest]
    if leaks:
        raise ValueError(f"el resumen cuenta algo del tema reservado ({leaks[0]!r}); solo puede decir «{sentence}»")
    del folded


_TITLE_PARTS = {"tarde": {"tarde"}, "noche": {"noche", "madrugada"}, "madrugada": {"madrugada", "noche"},
                "manana": {"manana"}, "mediodia": {"mediodia"}}
_TITLE_PART_WORDS = re.compile(r"\b(tardes?|noches?|nocturn\w*|madrugadas?|mananas?|mediodia)\b")


def _title_part(title: str) -> str | None:
    m = _TITLE_PART_WORDS.search(_fold(title))
    if not m:
        return None
    w = m.group(1)
    return "noche" if w.startswith("noch") or w.startswith("noctur") else w.rstrip("s")


def check(out: _Output, facts: dict) -> None:
    """Forma y fidelidad que exige el código. ValueError → reintento."""
    words = len(out.summary.split())
    if not SUMMARY_WORDS[0] <= words <= SUMMARY_WORDS[1]:
        raise ValueError(f"el resumen tiene {words} palabras")
    if len(out.topics) != 3:
        raise ValueError(f"tienen que ser tres temas, vinieron {len(out.topics)}")
    events = {e["id"]: e for e in facts.get("events", [])}
    labels = facts.get("voices", {})
    numbers = allowed_numbers(facts)
    all_text = " ".join(_fold(q["quote"] + " " + (q.get("time") or "")) for q in events.values())

    def check_text(text: str, where: str, evidence_text: str) -> None:
        folded = _fold(text)
        for n in _NUMBER.findall(text):
            if n not in numbers:
                raise ValueError(f"{where}: el número {n!r} no está en facts")
        if _APPROX.search(folded):
            raise ValueError(f"{where}: aproxima una cifra")
        if _EXPLAINED.search(folded):
            raise ValueError(f"{where}: habla de explicado/sin explicar (decí 'con relato' o 'sin relato')")
        for word, pattern in _PARTS.items():
            if pattern.search(folded) and word not in evidence_text:
                raise ValueError(f"{where}: pone una franja ({word}) que no está en los eventos")

    check_text(out.summary, "resumen", all_text)
    check_private_summary(out, events)
    for t in out.topics:
        unknown = set(t.evidence_ids) - events.keys()
        if unknown:
            raise ValueError(f"«{t.title}» cita ids que no existen: {sorted(unknown)}")
        part = _title_part(t.title)
        if part:
            other = [i for i in t.evidence_ids if events[i].get("part") and events[i]["part"] not in _TITLE_PARTS[part]]
            if other:
                raise ValueError(f"«{t.title}» nombra la {part} pero incluye eventos de otra franja: {other}")
        kinds = {bool(events[i].get("reserved")) for i in t.evidence_ids}
        if kinds == {True, False}:
            raise ValueError(f"«{t.title}» mezcla eventos reservados y no reservados: un tema reservado junta solo "
                             "eventos reservados")
        if len(t.narrative.split()) > NARRATIVE_WORDS:
            raise ValueError(f"el párrafo de «{t.title}» es demasiado largo")
        evidence_text = " ".join(_fold(events[i]["quote"] + " " + (events[i].get("time") or "")) for i in t.evidence_ids)
        for text in _texts(t):
            check_text(text, f"«{t.title}»", evidence_text)
        # Cada cita del párrafo: literal de un evento y con el nombre de quien la dijo en la misma frase.
        for sentence in re.split(r"(?<=[.;])\s+", t.narrative):
            for m in _QUOTED.finditer(sentence):
                quote = next(g for g in m.groups() if g)
                owners = [e for e in events.values() if quote in e["quote"]]
                if not owners:
                    raise ValueError(f"«{t.title}»: la cita «{quote}» no es literal de ningún evento")
                names = {labels.get(e["speaker"], e["speaker"]).split(",")[0] for e in owners}
                if not any(name in sentence for name in names):
                    raise ValueError(f"«{t.title}»: la cita «{quote}» no dice quién la contó ({', '.join(names)})")
        for role, quote in t.voices.items():
            quote = _unquote(quote)
            if quote and not any(quote in e["quote"] for e in events.values() if e["speaker"] == role):
                raise ValueError(f"«{t.title}»: la voz de {role} («{quote}») no es una cita literal de un evento "
                                 f"de esa voz; copiá exacta una `quote` de un evento con speaker={role}")


def to_report(out: _Output, facts: dict) -> Report:
    """Salida del modelo → Report. `reserved` lo decide el código: si un evento del tema es reservado, el tema lo es.
    Las claves de voices las arma el código con los datos: "Juan", "Marta, su esposa"."""
    reserved_ids = {e["id"] for e in facts.get("events", []) if e.get("reserved")}
    labels = facts.get("voices", {})
    topics = [ReportTopic(
        title=t.title.strip(), narrative=t.narrative.strip(), observed=[o.strip() for o in t.observed if o.strip()],
        voices={labels.get(k, k): _unquote(v) for k, v in t.voices.items() if k in VOICES and _unquote(v)},
        question=t.question.strip(), evidence_ids=list(dict.fromkeys(t.evidence_ids)),
        reserved=t.reserved or bool(set(t.evidence_ids) & reserved_ids),
    ) for t in out.topics]
    return Report(summary=out.summary.strip(), topics=topics, removed_count=0)


async def generate(facts: dict) -> Report:
    """Facts → Report verificado. Lanza llm.LLMError si la IA no pudo redactarlo."""
    out = await llm.call_tool(prompt(), TOOL, user_message(facts), _Output, check=lambda o: check(o, facts),
                              max_tokens=8000, effort="medium")
    draft = to_report(out, facts)
    return verify(draft, facts, facts.get("events", []))


def _store(patient_id: int, period: str, rep: Report) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO reports (patient_id, period, content, removed_by_verifier, created_at) VALUES (?, ?, ?, ?, ?)",
            (patient_id, period, rep.model_dump_json(), rep.removed_count, db.to_db(clock.now())))
        return cur.lastrowid


async def report(patient_id: int, period: str | None = None) -> Report:
    """Calcula los facts del período (por defecto, las 4 semanas hasta hoy), redacta, verifica y guarda."""
    now = await asyncio.to_thread(clock.now)
    facts = await asyncio.to_thread(report_facts.build, patient_id, now, period)
    rep = await generate(facts)
    await asyncio.to_thread(_store, patient_id, facts["period"]["label"], rep)
    return rep


# ── Regeneración en segundo plano ──────────────────────────────────────────────────────────────────────

_dirty: dict[int, bool] = {}
_last_start: dict[int, float] = {}
_runners: dict[int, asyncio.Task] = {}


async def _runner(patient_id: int) -> None:
    try:
        while _dirty.get(patient_id):
            wait = _last_start.get(patient_id, -REGEN_SECONDS) + REGEN_SECONDS - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _dirty[patient_id] = False          # lo que llegue mientras redacta marca otra vuelta: gana la última
            _last_start[patient_id] = time.monotonic()
            try:
                await report(patient_id)
                log.info("informe del paciente %s regenerado", patient_id)
            except Exception as exc:
                log.error("no se pudo regenerar el informe del paciente %s (%s)", patient_id, type(exc).__name__)
    finally:
        _runners.pop(patient_id, None)


def request_regeneration(patient_id: int) -> None:
    """Pide regenerar el informe (por ejemplo, cuando entra un evento). No bloquea."""
    _dirty[patient_id] = True
    if patient_id not in _runners:
        _runners[patient_id] = asyncio.get_running_loop().create_task(_runner(patient_id))

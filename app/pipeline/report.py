# pipeline.report(patient_id, period) -> Report (CLAUDE.md §5.5 y §11). El código calcula los facts
# (report_facts.build), Sonnet redacta el resumen y los tres temas, el código fuerza `reserved` y descarta ids que no
# existen, y el verificador (rules.verifier de Franco) borra cifras y citas que no coinciden. Se guarda en `reports`.
# La neuróloga nunca ve el informe vacío: si después de los intentos la salida solo falla reglas blandas, se guarda
# limpia por verify_local (cuenta lo borrado); si falla una regla dura o la IA no responde, se guarda un informe
# mínimo armado por código, sin texto redactado.
# Regeneración en segundo plano: como mucho una vez cada 30 s por paciente, y gana la última.
import asyncio
import json
import logging
import re
import time
from pathlib import Path

from pydantic import BaseModel

from app import clock, db
from app.models import Report, ReportTopic
from app.pipeline import knowledge, llm, report_facts
from app.taxonomy import _fold

try:                                   # el verificador de Franco (rules.verifier), si ya está
    from app.rules import verifier as _verifier  # type: ignore
    verify = _verifier.verify
except ImportError:
    verify = None

log = logging.getLogger("entrecasa.report")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "report.md"
SUMMARY_WORDS = (30, 160)
NARRATIVE_WORDS = 120
TOPICS = (2, 3)
ATTEMPTS = 3                     # el informe tiene un intento más que el resto de los usos de llm.call_tool
REGEN_SECONDS = 30
MINIMAL_SUMMARY = ("El resumen redactado no está disponible: esta vez la IA no pudo redactarlo cumpliendo las "
                   "comprobaciones del código. Las cifras de esta página (pasos, medicación, cobertura, lo que no "
                   "sabemos y alertas) las calcula el código y están al día.")
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


class HardCheckError(ValueError):
    """Regla dura: ids que no existen, eventos reservados mezclados con no reservados o el resumen cuenta lo
    reservado. Esa salida nunca se guarda."""


class SoftCheckError(ValueError):
    """Regla blanda: largo, número de temas, cifras, aproximaciones, franjas, citas y voces. Si se agotan los
    intentos, la salida se guarda igual y verify_local borra (y cuenta) lo que no cierra."""


def _text_problem(text: str, numbers: set[str], evidence_text: str) -> str | None:
    """Por qué un texto no cumple las reglas de cifras, aproximaciones, explicado y franjas (None si cumple)."""
    folded = _fold(text)
    for n in _NUMBER.findall(text):
        if n not in numbers:
            return f"el número {n!r} no está en facts"
    if _APPROX.search(folded):
        return "aproxima una cifra"
    if _EXPLAINED.search(folded):
        return "habla de explicado/sin explicar (decí 'con relato' o 'sin relato')"
    for word, pattern in _PARTS.items():
        if pattern.search(folded) and word not in evidence_text:
            return f"pone una franja ({word}) que no está en los eventos"
    return None


def _evidence_text(evs) -> str:
    return " ".join(_fold(e["quote"] + " " + (e.get("time") or "")) for e in evs)


def _quote_problem(sentence: str, events, labels: dict) -> str | None:
    """Cada cita: literal de un evento y con el nombre de quien la dijo en la misma frase."""
    for m in _QUOTED.finditer(sentence):
        quote = next(g for g in m.groups() if g)
        owners = [e for e in events if quote in e["quote"]]
        if not owners:
            return f"la cita «{quote}» no es literal de ningún evento"
        names = {labels.get(e["speaker"], e["speaker"]).split(",")[0] for e in owners}
        if not any(name in sentence for name in names):
            return f"la cita «{quote}» no dice quién la contó ({', '.join(names)})"
    return None


def _wrong_part_ids(t, events: dict) -> list[int]:
    """Ids de la evidencia de otra franja que la que nombra el título."""
    part = _title_part(t.title)
    if not part:
        return []
    return [i for i in t.evidence_ids if i in events and events[i].get("part")
            and events[i]["part"] not in _TITLE_PARTS[part]]


def check(out: _Output, facts: dict) -> None:
    """Forma y fidelidad que exige el código. HardCheckError o SoftCheckError (los dos son ValueError) → reintento.
    Primero las duras: si una falla, el error es duro aunque también fallen blandas."""
    events = {e["id"]: e for e in facts.get("events", [])}
    labels = facts.get("voices", {})

    # ── Duras ──
    for t in out.topics:
        unknown = set(t.evidence_ids) - events.keys()
        if unknown:
            raise HardCheckError(f"«{t.title}» cita ids que no existen: {sorted(unknown)}")
        kinds = {bool(events[i].get("reserved")) for i in t.evidence_ids}
        if kinds == {True, False}:
            raise HardCheckError(f"«{t.title}» mezcla eventos reservados y no reservados: un tema reservado junta "
                                 "solo eventos reservados")
    try:
        check_private_summary(out, events)
    except ValueError as exc:
        raise HardCheckError(str(exc)) from exc

    # ── Blandas ──
    words = len(out.summary.split())
    if not SUMMARY_WORDS[0] <= words <= SUMMARY_WORDS[1]:
        raise SoftCheckError(f"el resumen tiene {words} palabras")
    if not TOPICS[0] <= len(out.topics) <= TOPICS[1]:
        raise SoftCheckError(f"tienen que ser dos o tres temas, vinieron {len(out.topics)}")
    numbers = allowed_numbers(facts)
    problem = _text_problem(out.summary, numbers, _evidence_text(events.values()))
    if problem:
        raise SoftCheckError(f"resumen: {problem}")
    for t in out.topics:
        other = _wrong_part_ids(t, events)
        if other:
            raise SoftCheckError(f"«{t.title}» nombra la {_title_part(t.title)} pero incluye eventos de otra "
                                 f"franja: {other}")
        if len(t.narrative.split()) > NARRATIVE_WORDS:
            raise SoftCheckError(f"el párrafo de «{t.title}» es demasiado largo")
        evidence_text = _evidence_text(events[i] for i in t.evidence_ids)
        for text in _texts(t):
            problem = _text_problem(text, numbers, evidence_text)
            if problem:
                raise SoftCheckError(f"«{t.title}»: {problem}")
        for sentence in re.split(r"(?<=[.;])\s+", t.narrative):
            problem = _quote_problem(sentence, events.values(), labels)
            if problem:
                raise SoftCheckError(f"«{t.title}»: {problem}")
        for role, quote in t.voices.items():
            quote = _unquote(quote)
            if quote and not any(quote in e["quote"] for e in events.values() if e["speaker"] == role):
                raise SoftCheckError(f"«{t.title}»: la voz de {role} («{quote}») no es una cita literal de un "
                                     f"evento de esa voz; copiá exacta una `quote` de un evento con speaker={role}")


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
    """Facts → Report verificado. Si después de ATTEMPTS intentos la salida solo falla reglas blandas, usa la última
    así y la limpia verify_local. Lanza llm.LLMError si la IA no respondió o ninguna salida pasó las reglas duras."""
    try:
        out = await llm.call_tool(prompt(), TOOL, user_message(facts), _Output, check=lambda o: check(o, facts),
                                  max_tokens=8000, effort="medium", attempts=ATTEMPTS)
    except llm.LLMError as exc:
        soft = [o for o, err in exc.rejected if isinstance(err, SoftCheckError)]
        if not soft:
            raise
        out = soft[-1]
        log.warning("informe con reglas blandas sin cumplir: se guarda limpio por el verificador")
    draft = to_report(out, facts)
    if verify is not None:                       # primero rules.verifier de Franco, después el local
        draft = verify(draft, facts, facts.get("events", []))
    return verify_local(draft, facts)


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _bad_sentence(sentence: str, numbers: set[str], events: list[dict], labels: dict,
                  evidence_text: str | None = None) -> bool:
    """Una oración se borra si tiene un número que no está literal en facts, o una cita que no está literal en
    los eventos dados, o una cita sin el nombre de quien la dijo. Con `evidence_text`, también si aproxima una
    cifra, habla de explicado/sin explicar o pone una franja que no está en esa evidencia."""
    if any(n not in numbers for n in _NUMBER.findall(sentence)):
        return True
    if evidence_text is not None and _text_problem(sentence, numbers, evidence_text):
        return True
    return _quote_problem(sentence, events, labels) is not None


def verify_local(rep: Report, facts: dict) -> Report:
    """Verificación final en código sobre el texto que se va a guardar (la que hace verdad la frase "Cada cifra se
    verificó… N frases eliminadas" del informe). En el resumen y en cada párrafo borra las oraciones con un número
    que no está literal en facts, una cita que no está literal en un evento de la evidencia (en el resumen, de
    cualquier evento), un hablante que no coincide, una aproximación, "explicado" o una franja que no está en la
    evidencia; saca las voces que no son una cita literal de esa voz, lo observado y la pregunta que no cumplen, la
    evidencia de otra franja que la del título y el tema entero si el título no cumple. Suma lo borrado a
    removed_count. Se encadena después de rules.verifier de Franco cuando exista."""
    numbers = allowed_numbers(facts)
    events = {e["id"]: e for e in facts.get("events", [])}
    labels = facts.get("voices", {})
    by_label = {v: k for k, v in labels.items()}
    removed = 0

    def clean(text: str, evs: list[dict], evidence_text: str) -> str:
        nonlocal removed
        kept = []
        for sentence in _SENTENCE.split(text.strip()):
            if sentence and _bad_sentence(sentence, numbers, evs, labels, evidence_text):
                removed += 1
            elif sentence:
                kept.append(sentence)
        return " ".join(kept)

    private_before = [n for n, t in enumerate(rep.topics, 1) if t.reserved]
    topics = []
    for t in rep.topics:
        wrong = set(_wrong_part_ids(t, events))
        ids = [i for i in t.evidence_ids if i in events and i not in wrong]
        removed += len(t.evidence_ids) - len(ids)
        evs = [events[i] for i in ids]
        evidence_text = _evidence_text(evs)
        if _text_problem(t.title, numbers, evidence_text):
            removed += 1                      # sin título que cierre no hay tema
            continue
        voices = {}
        for who, quote in t.voices.items():
            role = by_label.get(who, who)
            if any(quote in e["quote"] for e in events.values() if e["speaker"] == role):
                voices[who] = quote
            else:
                removed += 1
        observed = [o for o in t.observed if not _text_problem(o, numbers, evidence_text)]
        removed += len(t.observed) - len(observed)
        question = t.question
        if question and _text_problem(question, numbers, evidence_text):
            question, removed = "", removed + 1
        topics.append(t.model_copy(update={"narrative": clean(t.narrative, evs, evidence_text), "voices": voices,
                                           "observed": observed, "question": question, "evidence_ids": ids}))

    summary = rep.summary
    private_after = [n for n, t in enumerate(topics, 1) if t.reserved]
    if private_before and private_before != private_after:     # se cayó un tema: la frase privada se renumera
        new = private_sentence(private_after) if private_after else ""
        summary = summary.replace(private_sentence(private_before), new)
    summary = clean(summary, list(events.values()), _evidence_text(events.values()))
    return rep.model_copy(update={"summary": summary, "topics": topics,
                                  "removed_count": rep.removed_count + removed})


def minimal_report() -> Report:
    """El informe sin IA: ningún texto redactado; la página muestra las cifras que calcula el código."""
    return Report(summary=MINIMAL_SUMMARY, topics=[], removed_count=0)


def is_minimal(rep: Report) -> bool:
    return rep.summary == MINIMAL_SUMMARY and not rep.topics


def _store(patient_id: int, period: str, rep: Report) -> int:
    """`content` lleva además `redaccion`: "ia" o "codigo" (el informe mínimo), para que la web lo rotule."""
    content = {**json.loads(rep.model_dump_json()), "redaccion": "codigo" if is_minimal(rep) else "ia"}
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO reports (patient_id, period, content, removed_by_verifier, created_at) VALUES (?, ?, ?, ?, ?)",
            (patient_id, period, json.dumps(content, ensure_ascii=False), rep.removed_count, db.to_db(clock.now())))
        return cur.lastrowid


async def report(patient_id: int, period: str | None = None) -> Report:
    """Calcula los facts del período (por defecto, las 4 semanas hasta hoy), redacta, verifica y guarda. Si la IA
    no pudo (no respondió o falló una regla dura), guarda el informe mínimo: nunca queda sin informe."""
    now = await asyncio.to_thread(clock.now)
    facts = await asyncio.to_thread(report_facts.build, patient_id, now, period)
    try:
        rep = await generate(facts)
    except Exception as exc:              # solo el tipo: el mensaje puede traer citas con datos de salud
        log.error("informe sin redacción de la IA para el paciente %s (%s): se guarda el mínimo", patient_id,
                  type(exc).__name__)
        rep = minimal_report()
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

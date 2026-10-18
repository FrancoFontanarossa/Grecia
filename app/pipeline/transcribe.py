# pipeline.transcribe(audio_path) -> str · gpt-4o-transcribe por la API de OpenAI (en Railway no hay Whisper local).
# El audio se guarda con la extensión que corresponde a su content-type: OpenAI deduce el formato del nombre.
import asyncio
import logging
import os
import re
import uuid
from pathlib import Path

import openai

from app import _tmp_db as db  # TEMPORAL: DATA_DIR de app/config o app/db de Franco

log = logging.getLogger(__name__)

MODEL_TRANSCRIBE = "gpt-4o-transcribe"
MAX_BYTES = 25 * 1024 * 1024          # límite de la API de transcripción

# Safari (iPhone) graba audio/mp4; Chrome y Android, audio/webm; Firefox, audio/ogg.
EXTENSIONS = {"audio/mp4": ".m4a", "audio/webm": ".webm", "audio/ogg": ".ogg"}
CONTENT_TYPES = {ext: ctype for ctype, ext in EXTENSIONS.items()}

# Guía de estilo y vocabulario para la transcripción (no son instrucciones: solo ayuda a escribir bien los nombres).
PROMPT = ("Relato en español rioplatense sobre la vida diaria de una persona con Parkinson. "
          "Medicamentos: levodopa, carbidopa, pramipexol, apixabán.")


class TranscriptionError(Exception):
    """No se pudo pasar el audio a texto (sin key o la API falló)."""


class NotHeard(TranscriptionError):
    """El audio está vacío o no se entiende: la app muestra "No te escuché bien. ¿Probamos de nuevo?"."""


# Lo que Whisper suele "inventar" sobre silencio o ruido. Con ruido fuerte, además, repite o parafrasea el prompt
# ("la vida de alguien que vive con Parkinson"): eso también es "no te escuché". La lista de fármacos sola la
# cubre only_drug_names(); acá no van, porque "tomo levodopa, carbidopa, pramipexol…" es un relato real.
_SILENCE_HALLUCINATIONS = ("subtitulos realizados", "amara.org", "gracias por ver", "suscribete", "subtitulado por",
                           "relato en espanol", "vida diaria de una persona", "vive con parkinson",
                           "persona con parkinson")


_FILLERS = re.compile(r"^(?:\s*(?:m+|h+m+|e+h*|a+h*|o+h*|u+h*m*)\s*)*$")

# Eco parafraseado del prompt ("Mi vida diaria incluye tomar levodopa, carbidopa, pramipexol y apixabán"): en
# cualquier orden y con palabras de relleno. Se mide qué parte de las palabras con contenido salió del prompt.
# Un relato real puede nombrar fármacos ("se golpeó la cabeza y toma apixabán"), pero casi nunca es casi todo prompt.
_STOPWORDS = {"a", "al", "con", "de", "del", "el", "en", "es", "la", "las", "le", "lo", "los", "me", "mi", "mis",
              "o", "para", "por", "que", "se", "sobre", "su", "sus", "un", "una", "y"}
ECHO_MIN_WORDS, ECHO_MIN_SHARE = 3, 0.6
# Los fármacos del PROMPT: nombrarlos no es eco. Para ser eco hacen falta además ECHO_MIN_NON_DRUG palabras del
# prompt que no son fármacos (relato, espanol, rioplatense, vida, diaria, persona, parkinson, medicamentos).
PROMPT_DRUGS = ("levodopa", "carbidopa", "pramipexol", "apixaban")
ECHO_MIN_NON_DRUG = 2


def _content_words(folded: str) -> list[str]:
    return [w for w in folded.split() if w not in _STOPWORDS]


def echoes_prompt(folded: str) -> bool:
    """True si el texto (ya pasado por _fold) es casi todo palabras del PROMPT: lo inventó el modelo."""
    from app.taxonomy import _fold
    prompt_words = set(_content_words(_fold(PROMPT)))
    words = _content_words(folded)
    shared = [w for w in words if w in prompt_words]
    non_drug = {w for w in shared if w not in PROMPT_DRUGS}
    return (len(non_drug) >= ECHO_MIN_NON_DRUG and len(shared) >= ECHO_MIN_WORDS
            and len(shared) / len(words) >= ECHO_MIN_SHARE)


def only_drug_names(folded: str) -> bool:
    """True si las palabras con contenido son todas nombres de fármacos del PROMPT ("medicamentos" es la única
    extra permitida): "Levodopa, pramipexol, apixabán." es eco. Con cualquier otra palabra ("tomé levodopa") no."""
    words = _content_words(folded)
    return any(w in PROMPT_DRUGS for w in words) and all(w in PROMPT_DRUGS or w == "medicamentos" for w in words)


def is_red(text: str) -> bool:
    """True si el texto dispara (o repregunta) una regla roja. Se evalúa con todos los fármacos del PROMPT, más que
    los de cualquier paciente: acá solo decide no descartar; el rojo de verdad lo evalúa después el pipeline con
    los fármacos del paciente (rules.red.check)."""
    from app.rules import red
    return red.evaluate(text, list(PROMPT_DRUGS)) is not None


def unintelligible(text: str) -> bool:
    """Vacío, solo muletillas ("mmm", "eh") o lo que Whisper inventa sobre silencio (frases típicas o eco del prompt).
    Un rojo nunca es "no te escuché"."""
    from app.taxonomy import _fold
    folded = _fold(text)
    if is_red(text):
        return False
    return (sum(ch.isalnum() for ch in folded) < 3 or bool(_FILLERS.match(folded))
            or any(h in folded for h in _SILENCE_HALLUCINATIONS) or echoes_prompt(folded) or only_drug_names(folded))


class UnsupportedAudio(ValueError):
    """Content-type de audio que no sabemos mandar."""


def extension_for(content_type: str | None) -> str:
    """'audio/mp4;codecs=mp4a.40.2' → '.m4a'. Lanza UnsupportedAudio si no es uno de los conocidos."""
    base = (content_type or "").split(";", 1)[0].strip().lower()
    if base not in EXTENSIONS:
        raise UnsupportedAudio(f"Formato de audio no soportado: {content_type!r}")
    return EXTENSIONS[base]


def audios_dir() -> Path:
    return db.data_dir() / "audios"


def save_audio(data: bytes, content_type: str | None) -> Path:
    """Guarda el audio en DATA_DIR/audios/ con la extensión correcta. Sync: llamar con asyncio.to_thread."""
    ext = extension_for(content_type)
    if not data:
        raise NotHeard("El audio está vacío")
    if len(data) > MAX_BYTES:
        raise UnsupportedAudio("El audio es demasiado largo")
    folder = audios_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{db.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}{ext}"
    path.write_bytes(data)
    return path


_client: openai.AsyncOpenAI | None = None


async def transcribe(audio_path: str | Path) -> str:
    global _client
    path = Path(audio_path)
    if not os.environ.get("OPENAI_API_KEY"):
        raise TranscriptionError("Falta OPENAI_API_KEY")
    if _client is None:
        _client = openai.AsyncOpenAI(timeout=30.0, max_retries=1)
    data = await asyncio.to_thread(path.read_bytes)
    try:
        result = await _client.audio.transcriptions.create(
            model=MODEL_TRANSCRIBE,
            file=(path.name, data, CONTENT_TYPES.get(path.suffix, "application/octet-stream")),
            language="es",
            prompt=PROMPT,
        )
    except openai.OpenAIError as exc:
        raise TranscriptionError(f"Falló la transcripción: {exc}") from exc
    text = (result.text or "").strip()
    if unintelligible(text):
        raise NotHeard(f"No se entendió el audio ({text!r})")
    return text

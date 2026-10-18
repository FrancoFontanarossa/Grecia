# System prompt de los pipelines: knowledge/parkinson.md + el prompt propio, siempre igual byte a byte.
# El cache_control va en el último bloque, así se cachean los dos (CLAUDE.md §7.4). Con PROFILE_ENABLED, el perfil
# del paciente de la llamada en curso (rules.profile.CURRENT) va entre los dos, y knowledge lleva su propio cache.
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_PATH = ROOT / "knowledge" / "parkinson.md"


def strip_comment(text: str) -> str:
    """Saca el comentario <!-- … --> del principio: es para humanos."""
    return text.split("-->", 1)[1].lstrip() if text.startswith("<!--") else text


@cache
def knowledge() -> str:
    return strip_comment(KNOWLEDGE_PATH.read_text(encoding="utf-8"))


def system_blocks(prompt: str, *, profile: bool = True) -> list[dict]:
    from app.rules.profile import current_profile
    text = current_profile() if profile else None
    if not text:
        return [
            {"type": "text", "text": knowledge()},
            {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}},
        ]
    return [
        {"type": "text", "text": knowledge(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": text},
        {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}},
    ]

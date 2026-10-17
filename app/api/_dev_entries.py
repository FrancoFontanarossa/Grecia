# TEMPORAL: borrar cuando exista app/api/entries.py (Guada).
# Imita la FORMA de POST /api/entries, /confirm y /correct (CLAUDE.md §11) para probar las pantallas sin IA.
# Todo lo que devuelve va con simulated=True y la pantalla lo rotula. Si existe el módulo real, no registra nada.
import importlib.util

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api import _store as store

router = APIRouter(prefix="/api", tags=["temporal"])
REAL_ENTRIES = importlib.util.find_spec("app.api.entries") is not None

_HINT_LABEL = {"ahora": "Ahora", "esta_manana": "Esta mañana", "esta_tarde": "Esta tarde", "anoche": "Anoche", "ayer": "Ayer"}


def _fake(entry_id: int, person_id: int, text: str | None, audio: UploadFile | None, hint: str | None) -> dict:
    transcript = (text or "").strip() or ("(audio recibido: sin transcripción en el modo temporal)" if audio else "")
    if not transcript:
        raise HTTPException(422, {"message": "Relato vacío.", "transcript": ""})
    data = {
        "entry_id": entry_id,
        "person_id": person_id,
        "transcript": transcript,
        "understood": [{"plain": f"Contaste: {transcript}", "when": _HINT_LABEL.get(hint or "", "Hoy"), "domain": "otro"}],
        "red": None,
        "alerts": [],
        "simulated": True,
    }
    store.save_entry_snapshot(data)
    return data


if not REAL_ENTRIES:

    @router.post("/entries")
    async def create_entry(person_id: int = Form(...), text: str | None = Form(None), audio: UploadFile | None = File(None),
                           occurred_hint: str | None = Form(None), question_id: int | None = Form(None),
                           quick_reply: str | None = Form(None), reserved_requested: bool = Form(False)):
        if not store.person(person_id):
            raise HTTPException(404, "No encontramos a esa persona.")
        return _fake(store.next_entry_id(), person_id, text or quick_reply, audio, occurred_hint)

    @router.post("/entries/{entry_id}/confirm")
    def confirm(entry_id: int):
        return {"ok": True}

    @router.post("/entries/{entry_id}/correct")
    async def correct(entry_id: int, text: str | None = Form(None), audio: UploadFile | None = File(None)):
        snap = store.entry_snapshot(entry_id) or {}
        return _fake(entry_id, snap.get("person_id", 0), text, audio, None)

    @router.get("/entries/{entry_id}")
    def get_entry(entry_id: int):
        snap = store.entry_snapshot(entry_id)
        if not snap:
            raise HTTPException(404, "No encontramos ese relato.")
        return snap

"""Arnés de desarrollo para probar la push en Chrome de escritorio contra localhost. NO va a producción.
Monta la app real y le suma, solo en este proceso, una página en /dev, su sw.js y una suscripción de prueba
(el /api/push/subscribe de verdad es de Juanpe).

    .venv/bin/uvicorn scripts.dev_push.server:app --port 8000
    → abrir http://localhost:8000/dev/
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import Body                                      # noqa: E402
from fastapi.responses import FileResponse, JSONResponse      # noqa: E402

from app import _tmp_db as db                                 # noqa: E402
from app.main import app                                      # noqa: E402

HERE = Path(__file__).parent


@app.get("/dev/", include_in_schema=False)
def dev_page():
    return FileResponse(HERE / "index.html")


@app.get("/dev/sw.js", include_in_schema=False)
def dev_sw():
    return FileResponse(HERE / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/dev/", "Cache-Control": "no-store"})


@app.get("/dev/vapid", include_in_schema=False)
def dev_vapid():
    key = os.environ.get("VAPID_PUBLIC_KEY")
    if not key:
        return JSONResponse({"error": "Falta VAPID_PUBLIC_KEY en .env (correr scripts/gen_vapid.py)"}, 500)
    return {"public_key": key}


@app.post("/dev/subscribe", include_in_schema=False)
async def dev_subscribe(person_id: int = Body(...), subscription: dict = Body(...)):
    await asyncio.to_thread(db.save_subscription, person_id=person_id, endpoint=subscription["endpoint"],
                            p256dh=subscription["keys"]["p256dh"], auth=subscription["keys"]["auth"])
    return {"ok": True}

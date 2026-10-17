from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api import admin, biometrics, entries
from app.notify import routes as notify_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


app = FastAPI(title="Entrecasa", lifespan=lifespan)
app.include_router(biometrics.router)
app.include_router(admin.router)
app.include_router(entries.router)
app.include_router(notify_routes.router)

@app.get("/health")
def health():
    return {"status": "ok"}

from app.api import screens  # noqa: E402  (Juanpe: API de pantallas + páginas)
app.include_router(screens.router)

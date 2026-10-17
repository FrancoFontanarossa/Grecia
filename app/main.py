from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, scheduler
from app.api import admin, biometrics, entries
from app.notify import routes as notify_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(title="Entrecasa", lifespan=lifespan)
app.middleware("http")(scheduler.kick_after_clock_change)
app.include_router(biometrics.router)
app.include_router(admin.router)
app.include_router(entries.router)
app.include_router(notify_routes.router)

@app.get("/health")
def health():
    return {"status": "ok"}

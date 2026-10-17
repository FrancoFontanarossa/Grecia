from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api import admin, biometrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


app = FastAPI(title="Entrecasa", lifespan=lifespan)
app.include_router(biometrics.router)
app.include_router(admin.router)

@app.get("/health")
def health():
    return {"status": "ok"}

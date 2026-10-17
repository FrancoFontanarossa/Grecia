from fastapi import FastAPI

from app.api import entries
from app.notify import routes as notify_routes

app = FastAPI(title="Entrecasa")
app.include_router(entries.router)
app.include_router(notify_routes.router)

@app.get("/health")
def health():
    return {"status": "ok"}

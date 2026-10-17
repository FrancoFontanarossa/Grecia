from fastapi import FastAPI

from app.api import entries

app = FastAPI(title="Entrecasa")
app.include_router(entries.router)

@app.get("/health")
def health():
    return {"status": "ok"}

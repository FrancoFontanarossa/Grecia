from fastapi import FastAPI

app = FastAPI(title="Entrecasa")

@app.get("/health")
def health():
    return {"status": "ok"}

from app.api import screens  # noqa: E402  (Juanpe: API de pantallas + páginas)
app.include_router(screens.router)

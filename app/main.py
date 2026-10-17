from fastapi import FastAPI

app = FastAPI(title="Entrecasa")

@app.get("/health")
def health():
    return {"status": "ok"}

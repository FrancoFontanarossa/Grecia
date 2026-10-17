"""Corre pipeline.report.generate contra Sonnet real con los facts falsos de la semana de Juan (§3).
    .venv/bin/python scripts/try_report.py [ruta/a/facts.json]
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.pipeline import report  # noqa: E402


async def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scripts" / "fixtures" / "report_facts_semana.json"
    facts = json.loads(path.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    rep = await report.generate(facts)
    print(f"Latencia: {time.perf_counter() - t0:.1f}s · borradas por el verificador: {rep.removed_count}\n")
    print("RESUMEN\n" + rep.summary + "\n")
    for i, t in enumerate(rep.topics, 1):
        print(f"TEMA {i}: {t.title}{'  [para hablar en privado]' if t.reserved else ''}")
        print(f"  {t.narrative}")
        for o in t.observed:
            print(f"  · {o}")
        for who, quote in t.voices.items():
            print(f"  {who}: «{quote}»")
        print(f"  Pregunta sugerida: {t.question}")
        print(f"  Evidencia: {t.evidence_ids}\n")


if __name__ == "__main__":
    asyncio.run(main())

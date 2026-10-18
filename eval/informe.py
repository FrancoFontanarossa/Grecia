"""Solo la parte del informe del eval (CLAUDE.md §13): 5 informes del escenario (cierre del martes 13 al sábado
17) por el mismo camino que producción (pipeline.report.generate), con las reglas que el código rechazó en cada
intento. Escribe eval/results_informe_v2.md (no toca results.md ni results_raw.json de Franco).

    .venv/bin/python eval/informe.py

Usa la IA real (Haiku para extraer los 30 relatos del escenario, Sonnet para el informe). Base temporal: nunca
toca DATA_DIR.
"""
import asyncio
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import clock, config, db  # noqa: E402
from app.config import TZ  # noqa: E402
from eval import run as ev  # noqa: E402

OUT = ROOT / "eval" / "results_informe_v2.md"


async def informes() -> list[dict]:
    from app.pipeline import llm, report_facts
    from app.pipeline import report as report_mod
    relatos = ev.jsonl(ev.EVAL / "sets/relatos.jsonl")
    _, events, errors = await ev._extract_all(relatos)
    ev._load_scenario(events, relatos)
    real_check = report_mod.check
    out = []
    for day in range(13, 18):
        clock.set(dt.datetime(2026, 10, day, 21, tzinfo=TZ).isoformat())
        facts = report_facts.build(1, clock.now())
        rejected: list[str] = []

        def spy(o, f, _rejected=rejected):
            try:
                return real_check(o, f)
            except ValueError as exc:
                kind = "blanda" if isinstance(exc, report_mod.SoftCheckError) else "dura"
                _rejected.append(f"{kind}: {exc}")
                raise
        report_mod.check = spy
        try:
            rep = await report_mod.generate(facts)
            out.append({"day": f"{day}/10", "ok": True, "topics": len(rep.topics), "removed": rep.removed_count,
                        "rejected": rejected})
        except llm.LLMError as exc:
            out.append({"day": f"{day}/10", "ok": False, "topics": 0, "removed": None, "rejected": rejected,
                        "error": str(exc)})
        finally:
            report_mod.check = real_check
    if errors:
        out.append({"note": f"Extracciones que fallaron (cuentan como vacías): {', '.join(errors)}"})
    return out


def render(rows: list[dict], when: str) -> str:
    days = [r for r in rows if "day" in r]
    ok = [r for r in days if r["ok"]]
    lines = ["# Eval del informe (v2)", "",
             f"Corrida: {when} · informe `{config.MODEL_REASON}` · {len(days)} informes del escenario "
             "(cierre de martes 13 a sábado 17) por `pipeline.report.generate`, como en producción.", "",
             f"**Generados: {len(ok)} de {len(days)}** · objetivo: 5 de 5, cada uno con 3 temas y como mucho 1 frase "
             "borrada.", "",
             "| Día | Generado | Temas | Frases borradas por verify_local | Reglas que el código rechazó (por intento) |",
             "|---|---|---|---|---|"]
    for r in days:
        rej = "<br>".join(x.replace("|", "\\|") for x in r["rejected"]) or "—"
        lines.append(f"| {r['day']} | {'sí' if r['ok'] else 'no'} | {r['topics']} | "
                     f"{'—' if r['removed'] is None else r['removed']} | {rej} |")
    notes = [r["note"] for r in rows if "note" in r] + [f"{r['day']}: {r['error']}" for r in days if not r["ok"]]
    if notes:
        lines += ["", "Notas:"] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Falta ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    when = clock.now().strftime("%d/%m/%Y %H:%M")
    with tempfile.TemporaryDirectory(prefix="entrecasa-informe-") as tmp:
        config.DATA_DIR = Path(tmp)
        db.init()
        rows = asyncio.run(informes())
    text = render(rows, when)
    if "--no-escribir" not in sys.argv:
        OUT.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

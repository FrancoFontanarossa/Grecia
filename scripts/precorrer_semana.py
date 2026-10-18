"""Precorre el escenario de la demo (data/escenario/juan.yaml, docs/PULIDO.md §2) por el pipeline real con el reloj.

Los relatos los escribió el equipo (se rotulan source="precorrer"); todo lo demás sale del sistema: extracción,
rojos, avisos, desvíos, preguntas, episodios e informe. Para cada momento mueve el reloj de demo (clock.set), carga
el relato con la misma función que POST /api/entries (process_entry) y corre un tick del scheduler. Además hay
ticks sin relato para que el scheduler vea las ventanas de las tomas: cada hora (:05) en la semana de la demo y tres
por día antes. Al final deja el reloj en `fin` y guarda el informe.

Idempotente: un relato ya precorrido (mismo hablante, hora y texto) no se vuelve a cargar, y el scheduler no repite
preguntas. Las push quedan apagadas mientras corre: las notificaciones se guardan, pero no suenan los teléfonos.

    .venv/bin/python -m scripts.precorrer_semana                       # data/escenario/juan.yaml contra DATA_DIR
    .venv/bin/python -m scripts.precorrer_semana otro_escenario.yaml
Orden del domingo (ROADMAP): seed → precorrer → POST /admin/snapshot → ensayo.
"""
import asyncio
import datetime as dt
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import clock, db, scheduler  # noqa: E402
from app.config import TZ  # noqa: E402

log = logging.getLogger("entrecasa.precorrer")

ESCENARIO = ROOT / "data" / "escenario" / "juan.yaml"
HINTS = {"ahora", "esta_manana", "esta_tarde", "anoche", "ayer"}   # OccurredHint (app/models.py)


@dataclass(frozen=True)
class Relato:
    at: dt.datetime
    person_id: int
    text: str
    hint: str | None = None
    reserved: bool = False
    modality: str = "texto"


@dataclass(frozen=True)
class Escenario:
    patient_id: int
    relatos: list[Relato]
    end: dt.datetime
    ticks: list[dt.datetime]


def _when(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(str(value).replace(" ", "T")).replace(tzinfo=TZ)


def load(path: Path = ESCENARIO) -> Escenario:
    """Lee y valida el YAML: personas conocidas, horas en orden, cuando_paso del contrato."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    people = data["personas"]
    relatos = []
    for i, r in enumerate(data["relatos"], 1):
        if r["quien"] not in people:
            raise ValueError(f"relato {i}: quien={r['quien']!r} no está en personas")
        hint = r.get("cuando_paso")
        if hint is not None and hint not in HINTS:
            raise ValueError(f"relato {i}: cuando_paso={hint!r} no es un OccurredHint")
        relatos.append(Relato(at=_when(r["cuando"]), person_id=people[r["quien"]], text=" ".join(r["texto"].split()),
                              hint=hint, reserved=bool(r.get("reservado", False)), modality=r.get("modalidad", "texto")))
    relatos.sort(key=lambda r: r.at)

    demo = data["ticks"]["semana_demo"]
    demo_from, demo_to = dt.date.fromisoformat(demo["desde"]), dt.date.fromisoformat(demo["hasta"])
    first_h, last_h = demo["horas"]
    ticks, day = [], relatos[0].at.date()
    while day <= demo_to:
        hours = range(first_h, last_h + 1) if day >= demo_from else data["ticks"]["resto"]
        ticks += [dt.datetime.combine(day, dt.time(h, 5), TZ) for h in hours]
        day += dt.timedelta(days=1)
    return Escenario(patient_id=data["paciente"], relatos=relatos, end=_when(data["fin"]), ticks=ticks)


ESC = load()
RELATOS = ESC.relatos
END = ESC.end


def _already_loaded(r: Relato) -> bool:
    with db.connect() as conn:
        return conn.execute(
            "SELECT 1 FROM entries WHERE source = 'precorrer' AND speaker_id = ? AND created_at = ? AND raw_text = ?",
            (r.person_id, db.to_db(r.at), r.text)).fetchone() is not None


def timeline(esc: Escenario = ESC) -> list[tuple[dt.datetime, Relato | None]]:
    """Relatos y ticks, en orden. Un tick (None) va después del relato si caen en el mismo minuto."""
    moments: list[tuple[dt.datetime, Relato | None]] = [(r.at, r) for r in esc.relatos]
    moments += [(t, None) for t in esc.ticks]
    return sorted(moments, key=lambda m: (m[0], m[1] is None))


async def run(esc: Escenario = ESC) -> dict:
    from app.api.entries import process_entry
    from app.notify import inbox as push   # inbox llama a send_push; se apaga ahí
    from app.pipeline import report

    loaded = skipped = 0
    questions: list[int] = []
    real_send, real_regen = push.send_push, report.request_regeneration

    async def silent(subscription, title, body, url):   # se guarda la notificación, no suena el teléfono
        return False
    push.send_push = silent
    report.request_regeneration = lambda patient_id: None   # el informe se genera una sola vez, al final
    try:
        for at, relato in timeline(esc):
            await asyncio.to_thread(clock.set, at.isoformat())
            if relato is not None:
                if await asyncio.to_thread(_already_loaded, relato):
                    skipped += 1
                else:
                    await process_entry(person_id=relato.person_id, text=relato.text, occurred_hint=relato.hint,
                                        reserved_requested=relato.reserved, source="precorrer")
                    loaded += 1
            questions += await scheduler.tick()
        await asyncio.to_thread(clock.set, esc.end.isoformat())
        # El informe final, sincrónico: el script no termina hasta que queda guardado en `reports`.
        try:
            rep = await report.report(esc.patient_id)
            informe = {"ok": True, "temas": len(rep.topics), "borradas": rep.removed_count}
        except Exception as exc:
            log.error("no se pudo generar el informe final (%s)", type(exc).__name__)
            informe = {"ok": False}
    finally:
        push.send_push, report.request_regeneration = real_send, real_regen
    return {"cargados": loaded, "ya_estaban": skipped, "preguntas": questions, "reloj": esc.end.isoformat(),
            "informe": informe}


def summary(patient_id: int) -> list[str]:
    """Qué generó el sistema, por día: para revisar el escenario antes del snapshot (PULIDO §2, paso 4)."""
    with db.connect() as conn:
        qs = conn.execute("SELECT substr(sent_at, 1, 10) AS d, rule_id, to_person_id, question FROM questions "
                          "WHERE patient_id = ? AND question != '' ORDER BY sent_at", (patient_id,)).fetchall()
        alerts = conn.execute("SELECT substr(created_at, 1, 10) AS d, lane, rule_id FROM alerts WHERE patient_id = ? "
                              "ORDER BY created_at", (patient_id,)).fetchall()
        eps = conn.execute("SELECT substr(dose_time, 1, 16) AS t, status FROM episodes WHERE patient_id = ? ORDER BY dose_time",
                           (patient_id,)).fetchall()
        events = conn.execute("SELECT count(*) FROM events WHERE patient_id = ?", (patient_id,)).fetchone()[0]
    lines = [f"Eventos extraídos: {events}"]
    lines += [f"  pregunta {r['d']} {r['rule_id']} → persona {r['to_person_id']}: {r['question']}" for r in qs]
    lines += [f"  aviso {r['d']} {r['lane']} {r['rule_id']}" for r in alerts]
    lines += [f"  episodio {r['t']} {r['status']}" for r in eps]
    return lines


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    esc = load(Path(sys.argv[1])) if len(sys.argv) > 1 else ESC
    db.init()
    by_voice = Counter(r.person_id for r in esc.relatos)
    print(f"Escenario: {len(esc.relatos)} relatos ({dict(by_voice)}) · {len(esc.ticks)} ticks")
    result = asyncio.run(run(esc))
    print(f"Relatos cargados: {result['cargados']} · ya estaban: {result['ya_estaban']}")
    print(f"Preguntas enviadas: {result['preguntas']}")
    print(f"Reloj en: {result['reloj']}")
    print("\n".join(summary(esc.patient_id)))
    if not result["informe"]["ok"]:
        print("ERROR: el informe final no se pudo generar; volver a correr el script.")
        sys.exit(1)
    print(f"Informe guardado: {result['informe']['temas']} temas · {result['informe']['borradas']} frases borradas")


if __name__ == "__main__":
    main()

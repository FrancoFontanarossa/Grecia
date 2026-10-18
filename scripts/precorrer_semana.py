"""Precorre la semana de la demo (lunes 12 a viernes 16/10/2026, CLAUDE.md §3 y §14) por el pipeline real.

Los relatos los escribió el equipo (se rotulan source="precorrer"); todo lo demás sale del sistema: extracción,
rojos, avisos, desvíos, preguntas y episodios. Mueve el reloj de demo a cada momento, carga el relato con la misma
función que POST /api/entries y corre un tick del scheduler. Ticks extra a cada hora (:05) para que el scheduler
vea las ventanas de las tomas. Al final deja el reloj en el viernes 16 a las 23:00.

Idempotente: un relato ya precorrido (mismo hablante, hora y texto) no se vuelve a cargar, y el scheduler no repite
preguntas. Las push quedan apagadas mientras corre: las notificaciones se guardan, pero no suenan los teléfonos.

    .venv/bin/python -m scripts.precorrer_semana            # contra la base de DATA_DIR
Orden del domingo (ROADMAP): seed → precorrer → POST /admin/snapshot → ensayo.
"""
import asyncio
import datetime as dt
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import clock, db, scheduler  # noqa: E402
from app.config import TZ  # noqa: E402

log = logging.getLogger("entrecasa.precorrer")

JUAN, MARTA, LAURA = 1, 2, 3
END = dt.datetime(2026, 10, 16, 23, 0, tzinfo=TZ)
TICK_HOURS = range(8, 23)            # 8:05 a 22:05: el scheduler ve las ventanas de 10, 14, 18 y 22


@dataclass(frozen=True)
class Relato:
    at: dt.datetime
    person_id: int
    text: str
    hint: str | None = None
    reserved: bool = False


def _at(day: int, hhmm: str) -> dt.datetime:
    return dt.datetime.combine(dt.date(2026, 10, day), dt.time.fromisoformat(hhmm), TZ)


RELATOS = [
    Relato(_at(12, "08:40"), MARTA, "Anoche se despertó tres veces, la última a las cuatro, y le costó volver a dormirse.", "anoche"),
    Relato(_at(12, "11:15"), JUAN, "Hoy me levanté bien. Fui caminando hasta la plaza a ver a los nietos."),
    Relato(_at(12, "20:30"), LAURA, "Hablé con papá por teléfono, lo noté contento. Dice que fue a la plaza."),
    Relato(_at(13, "09:30"), JUAN, "A la mañana me tembló un poco la mano con el mate, nada más.", "esta_manana"),
    Relato(_at(13, "21:00"), MARTA, "Esta mañana no se cayó, pero le costó levantarse de la silla del living."),
    Relato(_at(14, "08:20"), MARTA, "No durmió casi nada, se levantó cuatro veces al baño.", "anoche"),
    Relato(_at(14, "10:05"), JUAN, "Duermo bastante bien, me levanto un par de veces al baño nomás, a veces sueño cosas raras."),
    Relato(_at(14, "21:40"), MARTA, "anoche hablaba con alguien que no estaba; debe ser el cansancio", "anoche", reserved=True),
    Relato(_at(15, "12:30"), LAURA, "Mamá me contó que se tambaleó en la vereda volviendo del almacén, pero dice que no es nada."),
    Relato(_at(15, "17:40"), JUAN, "Después de la pastilla de las cuatro me sentí trabado, me costó salir a caminar.", "esta_tarde"),
    Relato(_at(16, "08:10"), MARTA, "Otra noche de levantarse varias veces. Yo también estoy cansada.", "anoche"),
    Relato(_at(16, "13:00"), JUAN, "Estos días ando medio estreñido."),
    Relato(_at(16, "22:10"), MARTA, "Otra vez decía que había gente en el patio. Lo tranquilicé y se durmió."),
    Relato(_at(16, "22:30"), LAURA, "Papá me mandó un audio, estaba bien de ánimo."),
]


def _already_loaded(r: Relato) -> bool:
    with db.connect() as conn:
        return conn.execute(
            "SELECT 1 FROM entries WHERE source = 'precorrer' AND speaker_id = ? AND created_at = ? AND raw_text = ?",
            (r.person_id, db.to_db(r.at), r.text)).fetchone() is not None


def timeline() -> list[tuple[dt.datetime, Relato | None]]:
    """Relatos y ticks horarios, en orden. Un tick (None) va después del relato si caen en el mismo minuto."""
    moments: list[tuple[dt.datetime, Relato | None]] = [(r.at, r) for r in RELATOS]
    for day in range(12, 17):
        moments += [(_at(day, f"{h:02d}:05"), None) for h in TICK_HOURS]
    return sorted(moments, key=lambda m: (m[0], m[1] is None))


async def run() -> dict:
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
        for at, relato in timeline():
            await asyncio.to_thread(clock.set, at.isoformat())
            if relato is not None:
                if await asyncio.to_thread(_already_loaded, relato):
                    skipped += 1
                else:
                    await process_entry(person_id=relato.person_id, text=relato.text, occurred_hint=relato.hint,
                                        reserved_requested=relato.reserved, source="precorrer")
                    loaded += 1
            questions += await scheduler.tick()
        await asyncio.to_thread(clock.set, END.isoformat())
        # El informe final, sincrónico: el script no termina hasta que queda guardado en `reports`.
        try:
            rep = await report.report(JUAN)
            informe = {"ok": True, "temas": len(rep.topics), "borradas": rep.removed_count}
        except Exception as exc:
            log.error("no se pudo generar el informe final (%s)", type(exc).__name__)
            informe = {"ok": False}
    finally:
        push.send_push, report.request_regeneration = real_send, real_regen
    return {"cargados": loaded, "ya_estaban": skipped, "preguntas": questions, "reloj": END.isoformat(),
            "informe": informe}


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    db.init()
    result = asyncio.run(run())
    print(f"Relatos cargados: {result['cargados']} · ya estaban: {result['ya_estaban']}")
    print(f"Preguntas enviadas: {result['preguntas']}")
    print(f"Reloj en: {result['reloj']}")
    if not result["informe"]["ok"]:
        print("ERROR: el informe final no se pudo generar; volver a correr el script.")
        sys.exit(1)
    print(f"Informe guardado: {result['informe']['temas']} temas · {result['informe']['borradas']} frases borradas")


if __name__ == "__main__":
    main()

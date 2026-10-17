"""Seed de la demo (CLAUDE.md §3). Idempotente: se puede correr muchas veces sin duplicar nada.

    python -m data.seed

Solo crea personas, consentimientos, esquema de tomas, tomas del período, el cambio de pramipexol
y la meta de pasos. No crea eventos, preguntas ni informes: esos salen del pipeline real (§0).
Los pasos los carga data/import_health.py.
"""
import json
from datetime import date, datetime, time, timedelta

from app import config, db

JUAN, MARTA, LAURA, PEREIRA, PRUEBA = 1, 2, 3, 4, 5

# patient_id es el id del paciente en people (Juan = 1; el paciente de prueba es su propio paciente).
PEOPLE = [
    (JUAN, JUAN, "paciente", "Juan", "paciente", "llegar a la plaza a ver a sus nietos"),
    (MARTA, JUAN, "cuidador", "Marta", "esposa", None),
    (LAURA, JUAN, "familiar", "Laura", "hija", None),
    (PEREIRA, JUAN, "neurologo", "Dra. Pereira", "neuróloga", None),
    (PRUEBA, PRUEBA, "paciente", "Paciente de prueba", "paciente", None),
]

PERIOD_START = date(2026, 9, 20)       # 4 semanas de historia…
PERIOD_END = date(2026, 10, 17)        # …hasta el sábado de la semana de la demo
LEVODOPA_TIMES = ["08:00", "12:00", "16:00", "20:00"]
PRAMIPEXOL_CHANGED = datetime(2026, 9, 22, tzinfo=config.TZ)
GOAL_STEPS = 4000


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), config.TZ)


def run() -> dict:
    db.init()
    granted = db.to_db(_at(PERIOD_START, "09:00"))
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO people (id, patient_id, role, name, relation, why_walk) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO NOTHING",
            PEOPLE,
        )
        conn.executemany(
            "INSERT INTO consents (patient_id, recipient_id, kind, enabled, granted_at) VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT (patient_id, recipient_id, kind) DO NOTHING",
            [(JUAN, who, kind, granted) for who in (MARTA, LAURA) for kind in ("avisos", "logros", "canal_reservado")],
        )
        conn.executemany(
            "INSERT INTO med_schedule (patient_id, drug, times, changed_at, change_note) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (patient_id, drug) DO NOTHING",
            [
                (JUAN, "levodopa/carbidopa", json.dumps(LEVODOPA_TIMES), None, None),
                (JUAN, "pramipexol", "[]", db.to_db(PRAMIPEXOL_CHANGED), "La Dra. Pereira subió el pramipexol"),
            ],
        )
        doses, day = [], PERIOD_START
        while day <= PERIOD_END:
            doses += [(JUAN, db.to_db(_at(day, t))) for t in LEVODOPA_TIMES]
            day += timedelta(days=1)
        conn.executemany(
            "INSERT INTO doses (patient_id, scheduled_at, source) VALUES (?, ?, 'seed') "
            "ON CONFLICT (patient_id, scheduled_at) DO NOTHING",
            doses,
        )
        if not conn.execute("SELECT 1 FROM goals WHERE patient_id = ? AND metric = 'steps'", (JUAN,)).fetchone():
            conn.execute(
                "INSERT INTO goals (patient_id, metric, target, unit, set_by, active) VALUES (?, 'steps', ?, 'pasos', ?, 1)",
                (JUAN, GOAL_STEPS, PEREIRA),
            )
        counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("people", "consents", "med_schedule", "doses", "goals")}
    return counts


if __name__ == "__main__":
    for table, n in run().items():
        print(f"{table}: {n}")

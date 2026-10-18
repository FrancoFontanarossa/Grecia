"""Seed de la demo (CLAUDE.md §3). Idempotente: se puede correr muchas veces sin duplicar nada.

    python -m data.import_health ruta/a/export.xml --end 2026-10-17   # primero, los pasos
    python -m data.seed

Crea personas, consentimientos, esquema de tomas, tomas del período, el cambio de pramipexol, la meta
de pasos y el historial del golpeteo, y aplica las tres caídas inyectadas sobre los pasos importados
(con la misma lógica que POST /admin/inject_drop). No crea eventos, preguntas ni informes: esos salen
del pipeline real (§0).
"""
import json
from datetime import date, datetime, time, timedelta

from app import config, db
from app.api.admin import NoSyncError, inject_drop

JUAN, MARTA, LAURA, PEREIRA, PRUEBA, FAMILIAR_PRUEBA = 1, 2, 3, 4, 5, 6

# patient_id es el id del paciente en people (Juan = 1; el paciente de prueba es su propio paciente).
PEOPLE = [
    (JUAN, JUAN, "paciente", "Juan", "paciente", "llegar a la plaza a ver a sus nietos"),
    (MARTA, JUAN, "cuidador", "Marta", "esposa", None),
    (LAURA, JUAN, "familiar", "Laura", "hija", None),
    (PEREIRA, JUAN, "neurologo", "Dra. Pereira", "neuróloga", None),
    (PRUEBA, PRUEBA, "paciente", "Paciente de prueba", "paciente", None),
    (FAMILIAR_PRUEBA, PRUEBA, "cuidador", "Familiar de prueba", "familiar", None),
]
CONSENT_KINDS = ("avisos", "logros", "canal_reservado")
CONSENTS = [(JUAN, MARTA), (JUAN, LAURA), (PRUEBA, FAMILIAR_PRUEBA)]   # (paciente, destinatario)

PERIOD_START = date(2026, 9, 20)       # 4 semanas de historia…
PERIOD_END = date(2026, 10, 17)        # …hasta el sábado de la semana de la demo
LEVODOPA_TIMES = ["08:00", "12:00", "16:00", "20:00"]
PRAMIPEXOL_CHANGED = datetime(2026, 10, 3, tzinfo=config.TZ)   # sábado 03/10: la base del escenario queda antes
GOAL_STEPS = 4000

# Historial del golpeteo: 8 sesiones del 1 al 11/10, a las 10:00 (2 h después de la toma de las 8).
TAPPING = [  # día, taps_per_s, interval_cv, left_right_ratio
    (date(2026, 10, 1), 4.5, 0.14, 1.00),
    (date(2026, 10, 2), 4.3, 0.16, 0.97),
    (date(2026, 10, 4), 4.7, 0.12, 1.03),
    (date(2026, 10, 5), 4.4, 0.15, 0.98),
    (date(2026, 10, 7), 4.6, 0.13, 1.02),
    (date(2026, 10, 8), 4.2, 0.18, 0.95),
    (date(2026, 10, 10), 4.8, 0.12, 1.05),
    (date(2026, 10, 11), 4.5, 0.15, 0.99),
]
TAPPING_TIME, TAPPING_MINUTES_SINCE_DOSE = "10:00", 120

# Caídas de pasos de §3: martes 13 (sin explicación), jueves 15 (Juan la explica), viernes 16 (→ A3).
DROPS = [date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 16)]
DROP_DOSE, DROP_PCT = "16:00", 0.7


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), config.TZ)


def _base(conn) -> None:
    granted = db.to_db(_at(PERIOD_START, "09:00"))
    conn.executemany(
        "INSERT INTO people (id, patient_id, role, name, relation, why_walk) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (id) DO NOTHING",
        PEOPLE,
    )
    conn.executemany(
        "INSERT INTO consents (patient_id, recipient_id, kind, enabled, granted_at) VALUES (?, ?, ?, 1, ?) "
        "ON CONFLICT (patient_id, recipient_id, kind) DO NOTHING",
        [(patient, who, kind, granted) for patient, who in CONSENTS for kind in CONSENT_KINDS],
    )
    conn.executemany(
        "INSERT INTO med_schedule (patient_id, drug, times, changed_at, change_note) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (patient_id, drug) DO NOTHING",
        [
            (JUAN, "levodopa/carbidopa", json.dumps(LEVODOPA_TIMES), None, None),
            (JUAN, "pramipexol", "[]", db.to_db(PRAMIPEXOL_CHANGED), "La Dra. Pereira subió el pramipexol"),
        ],
    )
    # Si la fila ya estaba (una base cargada antes), el cambio se mueve a la fecha del escenario.
    conn.execute("UPDATE med_schedule SET changed_at = ? WHERE patient_id = ? AND drug = 'pramipexol'",
                 (db.to_db(PRAMIPEXOL_CHANGED), JUAN))
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
    for day, taps_per_s, interval_cv, left_right_ratio in TAPPING:
        taken_at = db.to_db(_at(day, TAPPING_TIME))
        if conn.execute("SELECT 1 FROM tests WHERE patient_id = ? AND taken_at = ? AND source = 'seed'",
                        (JUAN, taken_at)).fetchone():
            continue
        metrics = {"taps_per_s": taps_per_s, "interval_cv": interval_cv, "left_right_ratio": left_right_ratio}
        conn.execute(
            "INSERT INTO tests (patient_id, type, metrics, raw, taken_at, minutes_since_dose, source) "
            "VALUES (?, 'golpeteo', ?, '[]', ?, ?, 'seed')",
            (JUAN, json.dumps(metrics), taken_at, TAPPING_MINUTES_SINCE_DOSE),
        )


def _drops() -> list[str]:
    """Aplica las caídas sobre los pasos importados. Devuelve los avisos (si no se pudo)."""
    with db.connect() as conn:
        imported = conn.execute(
            "SELECT count(*) FROM biometrics WHERE patient_id = ? AND kind = 'steps' "
            "AND source IN ('importacion', 'inyectado')", (JUAN,)).fetchone()[0]
    if not imported:
        return ["No hay pasos importados: no se inyectaron las caídas. "
                "Correr data/import_health.py y volver a correr el seed."]
    warnings = []
    for day in DROPS:
        try:
            inject_drop(JUAN, _at(day, DROP_DOSE), DROP_PCT)
        except NoSyncError:
            warnings.append(f"Sin pasos sincronizados para el {day:%d/%m} a las {DROP_DOSE}: caída no inyectada.")
    return warnings


def summary() -> dict:
    with db.connect() as conn:
        one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
        return {
            "people": [(r["id"], r["name"], r["role"], r["patient_id"])
                       for r in conn.execute("SELECT id, name, role, patient_id FROM people ORDER BY id")],
            "consents": one("SELECT count(*) FROM consents"),
            "med_schedule": one("SELECT count(*) FROM med_schedule"),
            "doses": one("SELECT count(*) FROM doses"),
            "goals": one("SELECT count(*) FROM goals"),
            "step_samples": one("SELECT count(*) FROM biometrics WHERE patient_id = ? AND kind = 'steps'", JUAN),
            "tapping_sessions": one("SELECT count(*) FROM tests WHERE patient_id = ? AND type = 'golpeteo'", JUAN),
            "injected_drops": one("SELECT count(DISTINCT substr(start, 1, 10)) FROM biometrics "
                                  "WHERE patient_id = ? AND source = 'inyectado'", JUAN),
        }


def run() -> dict:
    db.init()
    with db.connect() as conn:
        _base(conn)
    warnings = _drops()
    return {**summary(), "warnings": warnings}


def print_summary(result: dict) -> None:
    for warning in result["warnings"]:
        print(f"AVISO: {warning}")
    print("Personas:")
    for id_, name, role, patient_id in result["people"]:
        print(f"  {id_:>2}  {name:<20} {role:<10} paciente {patient_id}")
    print(f"Muestras de pasos de Juan: {result['step_samples']}")
    print(f"Sesiones de golpeteo de Juan: {result['tapping_sessions']}")
    print(f"Caídas inyectadas: {result['injected_drops']}")


if __name__ == "__main__":
    print_summary(run())

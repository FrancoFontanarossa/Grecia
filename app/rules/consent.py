# Canal reservado (CLAUDE.md §6.4), primera mención y destinatarios de cada aviso según §6.3 y consents.
# is_reserved y mark_new tienen las mismas firmas que app/_tmp_rules.py de Guada: alcanza con cambiar el import.
from app import db
from app.models import Alert, Event, Person

RESERVED_DOMAINS = {"neuropsiquiatrico", "impulsos", "sexual"}
FAMILY_ROLES = {"cuidador", "familiar"}

# Quién recibe cada aviso (alcance de las 04:15). Ningún aviso notifica: el rojo no tiene destinatarios (solo
# muestra el mensaje fijo a quien escribió, en la respuesta del relato, y queda marcado en el informe) y el ámbar
# va solo al equipo, que lo ve como prioridad en el informe. La familia y el paciente no reciben ninguno.


def is_reserved(event: Event, *, reserved_requested: bool, canal_reservado_active: bool) -> bool:
    """§6.4: solo lo que cuenta la familia, si lo pidió o si el dominio es sensible, y con el consentimiento."""
    return (event.speaker_role in FAMILY_ROLES
            and (reserved_requested or event.domain in RESERVED_DOMAINS)
            and canal_reservado_active)


def is_new(event: Event, already_mentioned: set[str]) -> bool:
    """Primera mención (no negada) del síntoma en la historia del paciente. "otro" nunca es nuevo."""
    return not event.negated and event.symptom != "otro" and event.symptom not in already_mentioned


def mark_new(events: list[Event], already_mentioned: set[str]) -> list[bool]:
    """is_new de cada evento de una entrada: dentro de la misma entrada, solo la primera aparición cuenta."""
    seen = set(already_mentioned)
    flags = []
    for e in events:
        flags.append(is_new(e, seen))
        if not e.negated:
            seen.add(e.symptom)
    return flags


def canal_reservado_active(patient_id: int, speaker_id: int | None = None) -> bool:
    """Consentimiento del canal reservado: el de quien cuenta, o el de cualquiera del paciente. Sin filas se
    asume activo (protege: lo reservado nunca le llega al paciente)."""
    sql = "SELECT MAX(enabled) AS on_ FROM consents WHERE patient_id = ? AND kind = 'canal_reservado'"
    args: tuple = (patient_id,)
    if speaker_id is not None:
        sql, args = sql + " AND recipient_id = ?", (patient_id, speaker_id)
    with db.connect() as conn:
        row = conn.execute(sql, args).fetchone()
    return True if row["on_"] is None else bool(row["on_"])


def patient_can_see(*, reserved: bool, lane: str | None = None) -> bool:
    """El paciente nunca ve contenido reservado. Un rojo sí le llega, con su texto fijo (nombra signos, no el tema)."""
    return lane == "rojo" or not reserved


def _people(patient_id: int) -> list[Person]:
    with db.connect() as conn:
        rows = conn.execute("SELECT id, patient_id, role, name, relation, phone, why_walk FROM people "
                            "WHERE patient_id = ? ORDER BY id", (patient_id,)).fetchall()
    return [Person(**dict(r)) for r in rows]


def _with_consent(patient_id: int, kind: str) -> set[int]:
    with db.connect() as conn:
        return {r["recipient_id"] for r in conn.execute(
            "SELECT recipient_id FROM consents WHERE patient_id = ? AND kind = ? AND enabled = 1", (patient_id, kind))}


def recipients(alert: Alert, *, speaker_id: int | None = None) -> list[Person]:
    """A quién va el aviso. Rojo y verde: a nadie. Ámbar (reservado o no): solo al equipo, en el informe.
    `speaker_id` queda por contrato (§11); ya no cambia el resultado."""
    if alert.lane != "ambar":
        return []
    return [p for p in _people(alert.patient_id) if p.role == "neurologo"]

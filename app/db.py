# SQLite con el esquema de CLAUDE.md §12. Una conexión por operación: `with db.connect() as conn: ...`
# Listas (times[], recipients[], options[], entry_ids[]) y objetos (json) se guardan como texto JSON.
# Las fechas, como ISO 8601 en America/Montevideo (to_db), así se comparan como texto.
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app import config

# NULL en biometric_syncs.scope = pasos (Atajo e importación), como siempre; "pulsera" = la pulsera simulada.
# §7.3 ("sync sin muestras = 0 pasos") solo mira las de pasos.
SYNC_SCOPE_WEARABLE = "pulsera"

BIOMETRICS_COLUMNS = """
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    value REAL NOT NULL,
    start TEXT NOT NULL,
    "end" TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('atajo','importacion','seed','inyectado','simulado','pulsera')),
    UNIQUE (patient_id, kind, start, "end", source)
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('paciente','cuidador','familiar','neurologo')),
    name TEXT NOT NULL,
    relation TEXT NOT NULL,
    phone TEXT,
    why_walk TEXT
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('pregunta','repregunta','logro','ambar','rojo','resumen')),
    lane TEXT CHECK (lane IN ('rojo','ambar','verde')),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    push_sent INTEGER NOT NULL DEFAULT 0,
    read_at TEXT
);
CREATE TABLE IF NOT EXISTS clock_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    offset_seconds REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consents (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('avisos','logros','canal_reservado')),
    enabled INTEGER NOT NULL,
    granted_at TEXT,
    UNIQUE (patient_id, recipient_id, kind)
);
CREATE TABLE IF NOT EXISTS med_schedule (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    drug TEXT NOT NULL,
    times TEXT NOT NULL DEFAULT '[]',
    changed_at TEXT,
    change_note TEXT,
    UNIQUE (patient_id, drug)
);
CREATE TABLE IF NOT EXISTS doses (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    scheduled_at TEXT NOT NULL,
    confirmed_at TEXT,
    source TEXT NOT NULL,
    UNIQUE (patient_id, scheduled_at)
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    speaker_id INTEGER NOT NULL,
    modality TEXT NOT NULL CHECK (modality IN ('texto','audio','toque')),
    question_id INTEGER,
    raw_text TEXT NOT NULL,
    audio_path TEXT,
    occurred_hint TEXT,
    reserved_requested INTEGER NOT NULL DEFAULT 0,
    corrected INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    symptom TEXT NOT NULL,
    severity INTEGER CHECK (severity BETWEEN 0 AND 4),
    negated INTEGER NOT NULL,
    occurred_at TEXT,
    time_vague INTEGER NOT NULL,
    speaker_role TEXT NOT NULL,
    foreign_attribution TEXT,
    quote TEXT NOT NULL,
    plain TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    minutes_since_dose INTEGER,
    is_new INTEGER NOT NULL DEFAULT 0,
    reserved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS biometrics (""" + BIOMETRICS_COLUMNS + """);
CREATE TABLE IF NOT EXISTS biometric_syncs (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    received_at TEXT NOT NULL,
    n_samples INTEGER NOT NULL,
    scope TEXT
);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    dose_time TEXT NOT NULL,
    deviation TEXT,
    explanation TEXT,
    question_id INTEGER,
    entry_ids TEXT NOT NULL DEFAULT '[]',
    test_id INTEGER,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    to_person_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL,
    question TEXT NOT NULL,
    why TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]',
    url TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pendiente','enviada','respondida','descartada')),
    sent_at TEXT,
    answered_entry_id INTEGER
);
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('golpeteo')),
    metrics TEXT NOT NULL,
    raw TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    minutes_since_dose INTEGER,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('rojo','ambar','verde')),
    rule_id TEXT NOT NULL,
    recipients TEXT NOT NULL DEFAULT '[]',
    text TEXT NOT NULL,
    reserved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    acked_at TEXT
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    metric TEXT NOT NULL,
    target REAL NOT NULL,
    unit TEXT NOT NULL,
    set_by INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    paused_reason TEXT
);
CREATE TABLE IF NOT EXISTS goal_days (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    value REAL NOT NULL,
    achieved INTEGER NOT NULL,
    hard_day INTEGER NOT NULL DEFAULT 0,
    notified INTEGER NOT NULL DEFAULT 0,
    UNIQUE (goal_id, date)
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    period TEXT NOT NULL,
    content TEXT NOT NULL,
    removed_by_verifier INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('repeticion','coocurrencia','tras_medicacion','discrepancia_voces','otro')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    suggested_action TEXT NOT NULL CHECK (suggested_action IN ('informe','preguntar')),
    verified INTEGER NOT NULL DEFAULT 0,
    question_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planned_actions (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    plan_date TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('golpeteo','pregunta','seguimiento')),
    at TEXT NOT NULL,
    to_person_id INTEGER,
    reason TEXT NOT NULL,
    why TEXT,
    basis TEXT NOT NULL,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK (status IN ('agendada','ejecutada','descartada')),
    discard_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    plan_date TEXT NOT NULL,
    condition TEXT NOT NULL,
    metric TEXT NOT NULL,
    lag_days INTEGER NOT NULL,
    direction TEXT NOT NULL,
    reason TEXT NOT NULL,
    passed INTEGER NOT NULL,
    mediana_con REAL,
    n_con INTEGER NOT NULL,
    mediana_sin REAL,
    n_sin INTEGER NOT NULL,
    discard_reason TEXT
);
CREATE TABLE IF NOT EXISTS daily_notes (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    text TEXT NOT NULL,
    points TEXT NOT NULL DEFAULT '[]',
    follow_up TEXT NOT NULL DEFAULT '[]',
    removed_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (patient_id, date)
);
CREATE INDEX IF NOT EXISTS ix_people_patient ON people (patient_id);
CREATE INDEX IF NOT EXISTS ix_notifications_person ON notifications (person_id, created_at);
CREATE INDEX IF NOT EXISTS ix_entries_patient ON entries (patient_id, created_at);
CREATE INDEX IF NOT EXISTS ix_events_patient ON events (patient_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_events_entry ON events (entry_id);
CREATE INDEX IF NOT EXISTS ix_biometrics_patient ON biometrics (patient_id, kind, start);
CREATE INDEX IF NOT EXISTS ix_syncs_patient ON biometric_syncs (patient_id, window_start);
CREATE INDEX IF NOT EXISTS ix_questions_person ON questions (to_person_id, status);
CREATE INDEX IF NOT EXISTS ix_alerts_patient ON alerts (patient_id, created_at);
CREATE INDEX IF NOT EXISTS ix_patterns_patient ON patterns (patient_id, day);
"""


def db_path() -> Path:
    return config.DATA_DIR / "entrecasa.db"


def snapshot_path() -> Path:
    return config.DATA_DIR / "snapshot.db"


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Una conexión por operación: commit al salir, rollback si hay error, y se cierra siempre."""
    conn = _open(db_path())
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    """Crea el directorio, activa WAL y crea las tablas que falten. Se puede llamar muchas veces."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / "audios").mkdir(exist_ok=True)
    conn = _open(db_path())
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Pone al día una base creada antes (la del volumen de Railway). Aditivo e idempotente."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'biometrics'").fetchone()[0]
    if "'pulsera'" not in sql:           # SQLite no deja cambiar un CHECK: se recrea la tabla con los mismos datos
        conn.executescript(
            "BEGIN;"
            f"CREATE TABLE biometrics_new ({BIOMETRICS_COLUMNS});"
            'INSERT INTO biometrics_new (id, patient_id, kind, value, start, "end", source)'
            ' SELECT id, patient_id, kind, value, start, "end", source FROM biometrics;'
            "DROP TABLE biometrics;"
            "ALTER TABLE biometrics_new RENAME TO biometrics;"
            "CREATE INDEX IF NOT EXISTS ix_biometrics_patient ON biometrics (patient_id, kind, start);"
            "COMMIT;")
    if "scope" not in {r[1] for r in conn.execute("PRAGMA table_info(biometric_syncs)")}:
        conn.execute("ALTER TABLE biometric_syncs ADD COLUMN scope TEXT")


def _copy(src_path: Path, dst_path: Path) -> None:
    # API de backup de sqlite3: copia consistente aunque la base esté en WAL.
    src, dst = _open(src_path), _open(dst_path)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def snapshot() -> None:
    """Guarda la base entera (incluido el reloj) en DATA_DIR/snapshot.db."""
    _copy(db_path(), snapshot_path())


def restore() -> None:
    """Vuelve la base al último snapshot. FileNotFoundError si no hay ninguno."""
    if not snapshot_path().exists():
        raise FileNotFoundError(snapshot_path())
    _copy(snapshot_path(), db_path())


def to_db(value: datetime) -> str:
    """Fecha aware → texto ISO en America/Montevideo, con segundos (comparable como texto)."""
    if value.tzinfo is None:
        raise ValueError("fecha sin zona horaria")
    return value.astimezone(config.TZ).isoformat(timespec="seconds")


def from_db(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(config.TZ)

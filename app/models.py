# Contratos de CLAUDE.md §11 (y tipos de las tablas de §12). Si hay que cambiar uno, avisar.
# Todos los datetime son aware (AwareDatetime); la zona del producto es app.config.TZ.
import datetime as dt
from typing import Literal

from pydantic import AwareDatetime, BaseModel

Domain = Literal["motor","sueno","neuropsiquiatrico","animo","cognitivo","autonomico",
                 "dolor","deglucion","caidas","impulsos","sexual","otro"]
Speaker = Literal["paciente","cuidador","familiar"]
Role = Literal["paciente","cuidador","familiar","neurologo"]
Lane = Literal["rojo","ambar","verde"]
NotificationKind = Literal["pregunta","repregunta","logro","ambar","rojo","resumen"]


class Event(BaseModel):
    domain: Domain
    symptom: str                            # normalizado contra taxonomy.py
    severity: int | None                    # 0-4, None si no se dice
    negated: bool
    occurred_at: AwareDatetime | None
    time_vague: bool
    speaker_role: Speaker
    foreign_attribution: str | None         # "la edad", "el cansancio"
    quote: str                              # literal del texto
    plain: str                              # frase corta para "Anoté esto", en segunda persona
    confidence: float


class RedResult(BaseModel):
    rule_id: str
    missing_criterion: str | None
    text: str


class BiometricSample(BaseModel):
    patient_id: int
    kind: Literal["steps","walking_speed","walking_asymmetry","double_support","steadiness"]
    value: float
    start: AwareDatetime
    end: AwareDatetime
    source: Literal["atajo","importacion","seed","inyectado"]


class Deviation(BaseModel):
    dose_time: AwareDatetime
    window: str
    observed: int
    median: float
    z: float
    pct_change: float


class Trigger(BaseModel):
    rule_id: str
    patient_id: int
    to_person_id: int
    facts: dict
    why: str                                # why con cifras del código


class Explanation(BaseModel):
    explained: bool
    by: list[str]
    reasoning: str


class QuestionText(BaseModel):
    question: str
    options: list[str]                      # 3 respuestas rápidas


class Question(BaseModel):
    id: int
    person_id: int
    rule_id: str
    question: str
    why: str
    options: list[str]
    url: str
    status: str


class GameResult(BaseModel):
    patient_id: int
    game: Literal["tapping"]
    taken_at: AwareDatetime
    metrics: dict[str, float]               # taps_per_s, interval_cv, left_right_ratio
    vs_history: Literal["parecido","mas_lento","sin_historial"]


class ReportTopic(BaseModel):
    title: str
    narrative: str
    observed: list[str]
    voices: dict[str, str]
    question: str
    evidence_ids: list[int]
    reserved: bool


class Report(BaseModel):
    summary: str
    topics: list[ReportTopic]
    removed_count: int


# Tipos usados en las firmas de §11, con los campos de las tablas de §12.

class TapEvent(BaseModel):
    t_ms: int
    side: Literal["izq","der"]


class Person(BaseModel):                    # tabla people
    id: int
    patient_id: int
    role: Role
    name: str
    relation: str
    phone: str | None = None
    why_walk: str | None = None


class Alert(BaseModel):                     # tabla alerts
    id: int
    patient_id: int
    lane: Lane
    rule_id: str
    recipients: list[int]                   # ids de people
    text: str
    reserved: bool
    created_at: AwareDatetime
    acked_at: AwareDatetime | None = None


class GoalDay(BaseModel):                   # tabla goal_days
    id: int
    goal_id: int
    date: dt.date
    value: float
    achieved: bool
    hard_day: bool
    notified: bool


class Notification(BaseModel):              # tabla notifications
    id: int
    person_id: int
    kind: NotificationKind
    lane: Lane | None = None
    title: str
    body: str
    url: str
    created_at: AwareDatetime
    push_sent: bool
    read_at: AwareDatetime | None = None

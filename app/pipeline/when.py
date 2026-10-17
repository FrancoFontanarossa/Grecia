# Cuándo pasó: el modelo dice lo que el relato dice (time_said) y el código pone la fecha y la hora.
# Prioridad acordada: hora o día dichos en el relato > "¿cuándo pasó?" (occurred_hint) > created_at con time_vague.
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Day = Literal["hoy", "ayer", "anteayer", "dia_semana", "no_dice"]
Weekday = Literal["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
Part = Literal["madrugada", "manana", "mediodia", "tarde", "noche"]

WEEKDAYS: list[str] = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
_WEEKDAY_LABEL = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Hora representativa de cada franja. Un día sin franja ni hora se guarda a las 12:00 (DAY_ONLY), distinto del
# mediodía (12:30), para que describe() diga solo "ayer" y no "ayer al mediodía".
PART_TIME = {"madrugada": dt.time(3, 0), "manana": dt.time(9, 0), "mediodia": dt.time(12, 30),
             "tarde": dt.time(16, 0), "noche": dt.time(22, 0)}
DAY_ONLY = dt.time(12, 0)

# occurred_hint → (días para atrás, franja). "ahora" es la hora de carga, exacta.
HINTS: dict[str, tuple[int, str | None]] = {
    "ahora": (0, None), "esta_manana": (0, "manana"), "esta_tarde": (0, "tarde"),
    "anoche": (1, "noche"), "ayer": (1, None),
}


class TimeSaid(BaseModel):
    day: Day
    weekday: Weekday | None = None
    part: Part | None = None
    clock: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def _days_back(ts: TimeSaid, today: dt.date) -> int | None:
    if ts.day == "hoy":
        return 0
    if ts.day == "ayer":
        return 1
    if ts.day == "anteayer":
        return 2
    if ts.day == "dia_semana" and ts.weekday:
        return (today.weekday() - WEEKDAYS.index(ts.weekday)) % 7
    return None


def resolve(ts: TimeSaid, hint: str | None, created_at: dt.datetime) -> tuple[dt.datetime, bool]:
    """(occurred_at, time_vague). created_at tiene que ser aware; el resultado queda en su misma zona."""
    today = created_at.date()
    back = _days_back(ts, today)
    part = ts.part
    clock = dt.time.fromisoformat(ts.clock) if ts.clock else None

    if back is None and not part and not clock:          # el relato no dice nada: manda el hint
        if hint is None:
            return created_at, True
        hint_back, hint_part = HINTS[hint]
        if hint == "ahora":
            return created_at, False
        back, part = hint_back, hint_part
    elif back is None:                                     # dice la franja o la hora pero no el día
        back = HINTS[hint][0] if hint else 0

    when_time = clock or (PART_TIME[part] if part else DAY_ONLY)
    occurred = dt.datetime.combine(today - dt.timedelta(days=back), when_time, tzinfo=created_at.tzinfo)
    if clock and ts.day == "no_dice" and hint is None and occurred > created_at:
        occurred -= dt.timedelta(days=1)                   # "a las 23" contado a las 9: fue anoche
    if occurred > created_at:                              # nunca en el futuro de la carga
        return created_at, True
    return occurred, clock is None


def describe(occurred_at: dt.datetime, time_vague: bool, now: dt.datetime) -> str:
    """Texto corto para "Anoté esto": "anoche", "hoy 16:30", "ayer a la tarde", "el martes"."""
    occurred_at = occurred_at.astimezone(now.tzinfo)
    days = (now.date() - occurred_at.date()).days
    t = occurred_at.time()

    if not time_vague:
        day = {0: "hoy", 1: "ayer"}.get(days) or _day_word(occurred_at, days)
        return f"{day} {t:%H:%M}"

    part = next((p for p, pt in PART_TIME.items() if pt == t), None)
    if days == 1 and part == "noche":
        return "anoche"
    if days == 0 and part == "madrugada":
        return "esta madrugada"
    day = {0: "hoy", 1: "ayer"}.get(days) or _day_word(occurred_at, days)
    if t == DAY_ONLY or part is None:
        return day
    return f"{day} {_PART_LABEL[part]}"


_PART_LABEL = {"madrugada": "de madrugada", "manana": "a la mañana", "mediodia": "al mediodía",
               "tarde": "a la tarde", "noche": "a la noche"}


def _day_word(occurred_at: dt.datetime, days: int) -> str:
    if days == 2:
        return "anteayer"
    if 2 < days < 7:
        return f"el {_WEEKDAY_LABEL[occurred_at.weekday()]}"
    return f"el {occurred_at:%d/%m}"

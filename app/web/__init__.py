import datetime as dt
import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(WEB_DIR))

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]


def _as_date(value):
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value) if "T" in value else dt.date.fromisoformat(value)
    return value


def miles(value) -> str:
    """4060 → '4.060'."""
    if value is None:
        return "—"
    return f"{int(round(float(value))):,}".replace(",", ".")


def dec1(value) -> str:
    """5.73 → '5,7'."""
    if value is None:
        return "—"
    return f"{float(value):.1f}".replace(".", ",")


def fecha_larga(value) -> str:
    """'Sábado 17 de octubre'."""
    d = _as_date(value)
    return f"{DIAS[d.weekday()].capitalize()} {d.day} de {MESES[d.month - 1]}"


def dia_corto(value) -> str:
    return DIAS_CORTOS[_as_date(value).weekday()]


def dia_largo(value) -> str:
    return DIAS[_as_date(value).weekday()]


def hora(value) -> str:
    d = _as_date(value)
    return d.strftime("%H:%M") if isinstance(d, dt.datetime) else ""


def ddmm(value) -> str:
    return _as_date(value).strftime("%d/%m")


templates.env.filters.update(miles=miles, dec1=dec1, fecha_larga=fecha_larga, dia_corto=dia_corto,
                             dia_largo=dia_largo, hora=hora, ddmm=ddmm)
templates.env.globals.update(
    VAPID_PUBLIC_KEY=os.environ.get("VAPID_PUBLIC_KEY", ""),
    DEMO_MODE=os.environ.get("DEMO_MODE", "1") == "1",
    ASSET_VERSION="1",
)

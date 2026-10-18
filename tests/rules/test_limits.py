import json
from pathlib import Path

import pytest

from app.rules import limits

EVAL = Path(__file__).parents[2] / "eval"


def jsonl(name):
    return [json.loads(line) for line in (EVAL / name).read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("cebo", jsonl("sets/cebos.jsonl"), ids=lambda c: c["id"])
def test_all_cebos_get_the_fixed_text(cebo):
    assert limits.check(cebo["text"]) == "Eso lo decide tu neuróloga. Lo anoto para que lo lleves a la consulta."


@pytest.mark.parametrize("relato", jsonl("sets/relatos.jsonl"), ids=lambda r: r["id"])
def test_no_relato_is_a_limit(relato):
    assert limits.check(relato["text"]) is None


@pytest.mark.parametrize("case", jsonl("sets/rojos.jsonl"), ids=lambda c: c["id"])
def test_reds_and_lookalikes_are_not_limits(case):
    assert limits.check(case["text"]) is None


@pytest.mark.parametrize("text,kind", [
    ("¿Le bajamos la dosis?", "medicacion"),
    ("Le bajamos la dosis como dijo la doctora", None),
    ("¿Tengo que tomar más pastillas?", "medicacion"),
    ("¿Le puedo dar otra pastilla?", "medicacion"),
    ("¿Hay que subirle la levodopa?", "medicacion"),
    ("¿Qué dosis le corresponde?", "dosis"),
    ("¿Cuánto le doy?", "dosis"),
    ("¿Qué tan avanzado está?", "estadio"),
    ("¿Será Parkinson esto que tiene?", "diagnostico"),
    ("¿Tiene cura?", "pronostico"),
    ("¿Es culpa del pramipexol?", "medicacion"),
])
def test_variants(text, kind):
    assert (limits.matches(text)[:1] or [None])[0] == kind


@pytest.mark.parametrize("text", [
    "Le cambiaron la medicación la semana pasada y anda mejor",
    "El cardiólogo dice que es por las pastillas de la presión",
    "Se tomó la pastilla de las 16 a horario",
    "La neuróloga le subió el pramipexol en setiembre",
    "Hoy tomó el café con leche sin derramar nada",
    "Lo que tiene es que no duerme bien",
])
def test_reports_about_medication_are_not_requests(text):
    assert limits.check(text) is None

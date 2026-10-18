from app.api.questions import why_chart

DEV = {"dose_time": "2026-10-17T16:00:00-03:00", "window": "16:00–18:00", "observed": 273, "median": 1200.0,
       "baseline": "combinada"}


def test_la_conclusion_va_primero_y_sin_cifras():
    chart = why_chart(DEV)
    assert chart["headline"] == "Hoy a la tarde caminaste menos que de costumbre"
    assert not any(ch.isdigit() for ch in chart["headline"])
    assert why_chart({**DEV, "dose_time": "2026-10-17T08:00:00-03:00"})["headline"].startswith("Hoy a la mañana")

"""Modo 2: la prueba de hipótesis y la validación del plan (app/rules/plan.py), código puro."""
from datetime import date, datetime, time, timedelta

import pytest

from app import db
from app.config import TZ
from app.models import DailyPlan, Hypothesis, PlannedAction
from app.rules import plan

NOW = datetime(2026, 10, 16, 21, 0, tzinfo=TZ)
FIRST, LAST = plan.window(NOW)
BAD_NIGHTS = {LAST - timedelta(days=k) for k in (1, 4, 8, 11, 15, 20)}       # 6 noches malas en 28 días


def at(d: date, h: int, m: int = 0) -> str:
    return db.to_db(datetime.combine(d, time(h, m), TZ))


def insert_bio(conn, kind, value, start, end, source):
    conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                 (kind, value, start, end, source))


@pytest.fixture
def datos(tmp_data_dir):
    """28 días: los días después de una noche mala (7 despertares) camina la mitad; el resto, normal."""
    with db.connect() as conn:
        for i in range(28):
            d = FIRST + timedelta(days=i)
            bad = d in BAD_NIGHTS
            insert_bio(conn, "sleep_awakenings", 7 if bad else 2, at(d - timedelta(days=1), 23), at(d, 7), "simulado")
            for h in range(8, 20):
                insert_bio(conn, "steps", 170 if bad else 340, at(d, h), at(d, h, 59), "importacion")
    return tmp_data_dir


def h(condition="noche_mala", metric="pasos_dia", lag=0, direction="menos"):
    return Hypothesis(condition=condition, metric=metric, lag_days=lag, direction=direction, reason="x")


# ---------------------------------------------------------------- hipótesis

def test_hipotesis_verdadera_pasa(datos):
    r = plan.test_hypothesis(h(), 1, (FIRST, LAST))
    assert r.passed and r.n_con == 6 and r.n_sin == 22
    assert r.mediana_con == 12 * 170 and r.mediana_sin == 12 * 340
    assert plan.result_text(r) == ("Los días después de una noche mala: mediana 2.040 pasos en el día (n=6); "
                                   "el resto: 4.080 (n=22).")


def test_con_pocos_dias_se_descarta(datos):
    with db.connect() as conn:
        conn.execute("UPDATE biometrics SET value = 2 WHERE kind = 'sleep_awakenings' AND value = 7 AND start < ?",
                     (at(LAST - timedelta(days=5), 0),))
    r = plan.test_hypothesis(h(), 1, (FIRST, LAST))
    assert not r.passed and r.discard_reason == "solo 2 días con la condición"


def test_con_diferencia_chica_se_descarta(datos):
    r = plan.test_hypothesis(h(condition="fin_de_semana", direction="menos"), 1, (FIRST, LAST))
    assert not r.passed and r.discard_reason.startswith("diferencia ")


def test_en_la_direccion_contraria_se_descarta(datos):
    r = plan.test_hypothesis(h(direction="mas"), 1, (FIRST, LAST))
    assert not r.passed and r.discard_reason.startswith("dirección contraria")


def test_fuera_del_vocabulario_se_descarta(datos):
    r = plan.test_hypothesis(h(condition="esta_off"), 1, (FIRST, LAST))
    assert not r.passed and "vocabulario" in r.discard_reason


def test_con_lag_mira_el_dia_siguiente(datos):
    """La noche mala del día d no cambia los pasos de d+1 en estos datos: con lag 1 la diferencia no aparece."""
    r = plan.test_hypothesis(h(lag=1), 1, (FIRST, LAST))
    assert not r.passed


# ---------------------------------------------------------------- acciones

def digest():
    return {"patient_id": 1, "plan_date": (LAST + timedelta(days=1)).isoformat(),
            "ventana": {"desde": FIRST.isoformat(), "hasta": LAST.isoformat()}}


def action(**kw):
    base = dict(kind="golpeteo", at="16:30", to_role="paciente", reason="Medir cómo estás a la tarde",
                basis="hipotesis:0", evidence_ids=[f"dia:{(LAST - timedelta(days=1)).isoformat()}"])
    return PlannedAction(**{**base, **kw})


def run(*actions, hypotheses=None):
    p = DailyPlan(hypotheses=hypotheses or [h()], actions=list(actions))
    return plan.validate(p, digest(), NOW)


def test_accion_valida_se_agenda_con_el_por_que_del_codigo(datos):
    ok, ko = run(action())
    assert ko == [] and len(ok) == 1
    assert ok[0]["to_person_id"] == 1 and ok[0]["at"] == "16:30"
    assert "mediana 2.040 pasos" in ok[0]["why"] and "no una causa" in ok[0]["why"]


def test_sin_base_valida_se_descarta(datos):
    ok, ko = run(action(basis="hipotesis:3"), action(basis="corazonada"))
    assert ok == [] and [k["discard_reason"] for k in ko] == ["sin base válida (ni desvío del código ni hipótesis)"] * 2


def test_hipotesis_que_no_paso_no_sirve_de_base(datos):
    ok, ko = run(action(), hypotheses=[h(direction="mas")])
    assert ok == [] and ko[0]["discard_reason"].startswith("la hipótesis no pasó la prueba")


def test_fuera_de_horario_se_descarta(datos):
    ok, ko = run(action(at="23:30"), action(at="07:15", kind="pregunta"))
    assert ok == [] and all(k["discard_reason"].startswith("fuera de horario") for k in ko)


def test_excede_el_limite_se_descarta(datos):
    ok, ko = run(action(at="10:00"), action(at="17:00"))
    assert len(ok) == 1 and ko[0]["discard_reason"].startswith("excede el límite diario")


def test_el_limite_cuenta_lo_ya_agendado_para_ese_dia(datos):
    with db.connect() as conn:
        conn.execute("INSERT INTO planned_actions (patient_id, plan_date, kind, at, to_person_id, reason, basis, status, "
                     "created_at) VALUES (1, ?, 'pregunta', '10:00', 1, 'x', 'desvio:1', 'agendada', ?)",
                     (digest()["plan_date"], at(LAST, 21)))
    ok, ko = run(action(kind="pregunta"))
    assert ok == [] and ko[0]["discard_reason"].startswith("excede el límite diario")


def test_reservado_hacia_juan_se_descarta(datos):
    with db.connect() as conn:
        eid = conn.execute("INSERT INTO entries (patient_id, speaker_id, modality, raw_text, created_at, source) "
                           "VALUES (1, 2, 'texto', 'x', ?, 'app')", (at(LAST, 9),)).lastrowid
        ev = conn.execute("INSERT INTO events (entry_id, patient_id, domain, symptom, negated, time_vague, speaker_role, "
                          "quote, plain, confidence, reserved) VALUES (?, 1, 'neuropsiquiatrico', 'alucinaciones', 0, 0, "
                          "'cuidador', 'q', 'p', 0.9, 1)", (eid,)).lastrowid
    ok, ko = run(action(evidence_ids=[f"relato:{ev}"]))
    assert ok == [] and ko[0]["discard_reason"] == "tiene algo reservado y va al paciente"
    ok, ko = run(action(evidence_ids=[f"relato:{ev}"], to_role="cuidador", kind="pregunta"))
    assert len(ok) == 1 and ok[0]["to_person_id"] == 2          # a quien lo contó sí


def test_evidencia_inexistente_o_fuera_de_la_ventana_se_descarta(datos):
    ok, ko = run(action(evidence_ids=["relato:999"]), action(evidence_ids=["dia:2026-01-01"], at="11:00"))
    assert ok == [] and all(k["discard_reason"].startswith("evidencia que no existe") for k in ko)
    ok, ko = run(action(evidence_ids=[]))
    assert ko[0]["discard_reason"] == "sin evidencia"


def test_desvio_del_codigo_es_base_valida(datos):
    with db.connect() as conn:
        ep = conn.execute("INSERT INTO episodes (patient_id, dose_time, deviation, explanation, status) "
                          "VALUES (1, ?, ?, '{}', 'preguntado')",
                          (at(LAST, 16), '{"observed": 420, "median": 1300}')).lastrowid
    ok, ko = run(action(basis=f"desvio:{ep}", evidence_ids=[f"episodio:{ep}"]))
    assert ko == [] and ok[0]["why"] == f"El {LAST:%d/%m}, después de la toma de las 16: 420 pasos; lo habitual ≈ 1.300."


def test_la_accion_nada_no_se_agenda_ni_se_descarta(datos):
    assert run(action(kind="nada")) == ([], [])

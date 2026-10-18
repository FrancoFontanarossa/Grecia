"""Informe v2 (docs/PULIDO.md §3): cobertura, "Desde el cambio" y "Lo que no sabemos", calculados por código."""
import datetime as dt
import json

import pytest

from app import db
from app.api import _store as store
from app.api import report as rep
from app.config import TZ

NOW = dt.datetime(2026, 10, 17, 19, 0, tzinfo=TZ)
START, END = dt.date(2026, 9, 20), dt.date(2026, 10, 17)


def at(day: dt.date, hh: int, mm: int = 0) -> str:
    return db.to_db(dt.datetime.combine(day, dt.time(hh, mm), TZ))


def day(n: int) -> dt.date:
    return START + dt.timedelta(days=n)


@pytest.fixture
def base(tmp_data_dir):
    """28 días: pasos cada hora de 8 a 20 salvo los días 3 y 9 (sin sincronizar); 16-18 h más bajo después del cambio."""
    with db.connect() as conn:
        conn.execute("INSERT INTO med_schedule (patient_id, drug, times, changed_at, change_note) VALUES (1, 'pramipexol', '[]', ?, ?)",
                     (at(day(10), 9), "La Dra. Pereira subió el pramipexol"))
        conn.execute("INSERT INTO med_schedule (patient_id, drug, times) VALUES (1, 'levodopa/carbidopa', ?)",
                     (json.dumps(["08:00", "12:00", "16:00", "20:00"]),))
        for i in range(28):
            d = day(i)
            if i in (3, 9):
                continue
            conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) "
                         "VALUES (1, ?, ?, ?, 13)", (at(d, 0), db.to_db(dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), TZ)),
                                                     at(d, 23)))
            for h in range(8, 21):
                v = 300.0
                if h in (16, 17):
                    v = 600.0 if i < 10 else 400.0
                conn.execute("INSERT INTO biometrics (patient_id, kind, value, start, \"end\", source) VALUES (1, 'steps', ?, ?, ?, 'importacion')",
                             (v, at(d, h), at(d, h, 59)))
        for i, v in [(1, 4.6), (2, 4.4), (4, 4.5), (12, 4.0), (15, 3.9), (20, 4.1)]:
            conn.execute("INSERT INTO tests (patient_id, type, metrics, raw, taken_at, source) VALUES (1, 'golpeteo', ?, '[]', ?, 'seed')",
                         (json.dumps({"taps_per_s": v}), at(day(i), 10)))
    return tmp_data_dir


def add_entry(speaker: int, role: str, created: str, events: list[dict]) -> list[int]:
    with db.connect() as conn:
        eid = conn.execute("INSERT INTO entries (patient_id, speaker_id, modality, raw_text, reserved_requested, corrected, "
                           "created_at, source) VALUES (1, ?, 'texto', 'x', 0, 0, ?, 'app')", (speaker, created)).lastrowid
        ids = []
        for e in events:
            ids.append(conn.execute(
                "INSERT INTO events (entry_id, patient_id, domain, symptom, negated, occurred_at, time_vague, speaker_role, "
                "quote, plain, confidence, is_new, reserved) VALUES (?, 1, ?, ?, ?, ?, 1, ?, 'q', 'p', 0.9, 0, ?)",
                (eid, e["domain"], e["symptom"], e.get("negated", 0), e.get("at", created), role, e.get("reserved", 0))).lastrowid)
    return ids


# ---------------------------------------------------------------- cobertura

def test_cobertura_cuenta_dias_sincronizados_relatos_por_voz_y_golpeteo(base):
    add_entry(1, "paciente", at(day(20), 10), [])
    add_entry(1, "paciente", at(day(21), 10), [])
    add_entry(2, "cuidador", at(day(22), 22), [])
    c = rep.coverage(1, START, END, NOW)
    assert c["pasos"] == {"dias_con_datos": 26, "dias_total": 28, "mediciones_por_fuente": {"importacion": 26 * 13}}
    assert [(v["nombre"], v["n"]) for v in c["relatos"]["por_voz"]] == [("Juan", 2), ("Marta", 1)]
    assert c["relatos"]["total"] == 3 and c["golpeteo"]["sesiones"] == 6
    assert c["texto"] == "Pasos: 26 de 28 días sincronizados · relatos: Juan 2, Marta 1 · golpeteo: 6 sesiones"


def test_sync_sin_muestras_cuenta_como_dia_con_datos(base):
    """Con biometric_syncs y sin muestras son 0 pasos, no "sin datos" (CLAUDE.md §7.3)."""
    with db.connect() as conn:
        d = day(3)
        conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples) VALUES (1, ?, ?, ?, 0)",
                     (at(d, 0), at(day(4), 0), at(d, 23)))
    assert rep.coverage(1, START, END, NOW)["pasos"]["dias_con_datos"] == 27


# ---------------------------------------------------------------- desde el cambio

def test_desde_el_cambio_compara_medianas_y_tasas(base):
    add_entry(2, "cuidador", at(day(5), 23), [{"domain": "sueno", "symptom": "despertares_nocturnos"}])
    add_entry(2, "cuidador", at(day(15), 23), [{"domain": "sueno", "symptom": "despertares_nocturnos"}])
    add_entry(2, "cuidador", at(day(16), 23), [{"domain": "sueno", "symptom": "insomnio"},
                                               {"domain": "neuropsiquiatrico", "symptom": "alucinaciones"}])
    add_entry(1, "paciente", at(day(17), 9), [{"domain": "sueno", "symptom": "despertares_nocturnos", "negated": 1}])
    s = rep.since_change(1, NOW)
    assert s["medicamento"] == "pramipexol" and s["fecha"] == "2026-09-30" and s["hace_dias"] == 17
    assert s["antes"] == {"desde": "2026-09-20", "hasta": "2026-09-29", "dias": 10}
    assert s["despues"]["dias"] == 18
    filas = {f["clave"]: f for f in s["filas"]}
    # 13 horas x 300 + 2 horas de 16-18: antes 600 c/u, después 400 c/u. Hoy no cuenta (día a medias).
    assert filas["pasos_dia"]["antes"] == 11 * 300 + 1200 and filas["pasos_dia"]["despues"] == 11 * 300 + 800
    assert filas["pasos_dia"]["n_antes"] == 8 and filas["pasos_dia"]["n_despues"] == 17      # antes sin los días 3 y 9; después sin hoy
    assert filas["pasos_16_18"]["antes"] == 1200 and filas["pasos_16_18"]["despues"] == 800
    assert filas["pasos_16_18"]["cambio_pct"] == -33.3 and filas["pasos_16_18"]["n_despues"] == 18  # hoy ya cerró (19 h)
    assert filas["golpeteo"]["antes"] == 4.5 and filas["golpeteo"]["despues"] == 4.0 and filas["golpeteo"]["suficiente"]
    # Noches: 1 antes en 10 días; 2 después en 18 días (la negada no cuenta).
    assert filas["noches_despertares"]["n_antes"] == 1 and filas["noches_despertares"]["n_despues"] == 2
    assert filas["noches_despertares"]["antes"] == 0.7 and filas["noches_despertares"]["despues"] == 0.8
    assert filas["relatos_neuropsiquiatricos"]["n_antes"] == 0 and filas["relatos_neuropsiquiatricos"]["n_despues"] == 1


def test_desde_el_cambio_marca_pocos_datos(base):
    with db.connect() as conn:
        conn.execute("UPDATE med_schedule SET changed_at = ? WHERE drug = 'pramipexol'", (at(day(2), 9),))
    filas = {f["clave"]: f for f in rep.since_change(1, NOW)["filas"]}
    assert filas["pasos_dia"]["n_antes"] == 2 and filas["pasos_dia"]["suficiente"] is False
    assert filas["golpeteo"]["n_antes"] == 1 and filas["golpeteo"]["suficiente"] is False


def test_sin_cambio_de_medicacion_es_none(tmp_data_dir):
    assert rep.since_change(1, NOW) is None


# ---------------------------------------------------------------- lo que no sabemos

def test_lo_que_no_sabemos(base):
    with db.connect() as conn:
        conn.execute("INSERT INTO questions (patient_id, to_person_id, rule_id, question, why, options, url, status, sent_at) "
                     "VALUES (1, 1, 'P-DESVIO', '¿Pasó algo?', 'x', '[]', '/casa/pregunta/1', 'enviada', ?)", (at(day(23), 18, 5),))
        conn.execute("INSERT INTO questions (patient_id, to_person_id, rule_id, question, why, options, url, status, sent_at) "
                     "VALUES (1, 1, 'P-DESVIO', 'Respondida', 'x', '[]', '/casa/pregunta/2', 'respondida', ?)", (at(day(25), 18, 5),))
    alu = add_entry(2, "cuidador", at(day(24), 22), [{"domain": "neuropsiquiatrico", "symptom": "alucinaciones", "reserved": 1}])
    alu += add_entry(2, "cuidador", at(day(26), 22), [{"domain": "neuropsiquiatrico", "symptom": "alucinaciones", "reserved": 1}])
    add_entry(3, "familiar", at(day(25), 20), [{"domain": "motor", "symptom": "lentitud"}])
    add_entry(2, "cuidador", at(day(25), 9), [{"domain": "motor", "symptom": "rigidez"}])
    add_entry(1, "paciente", at(day(25), 10), [{"domain": "motor", "symptom": "rigidez"}])   # Juan lo confirma
    add_entry(3, "familiar", at(day(26), 20), [{"domain": "dolor", "symptom": "dolor", "negated": 1}])
    u = rep.unknowns(1, START, END, NOW)
    assert u["dias_sin_pasos"] == ["2026-09-23", "2026-09-29"]
    assert [q["pregunta"] for q in u["preguntas_sin_respuesta"]] == ["¿Pasó algo?"]
    fam = {f["sintoma"]: f for f in u["solo_la_familia"]}
    assert set(fam) == {"alucinaciones", "lentitud"}          # rigidez la confirmó Juan; la negada no cuenta
    assert fam["alucinaciones"]["veces"] == 2 and fam["alucinaciones"]["quien"] == ["Marta"]
    assert fam["alucinaciones"]["reservado"] is True and fam["alucinaciones"]["evidence_ids"] == alu
    assert fam["alucinaciones"]["dominio_label"] == "Alucinaciones y confusión"
    assert u["solo_la_familia"][0]["sintoma"] == "alucinaciones"   # lo reservado primero
    assert u["textos"] == [
        "Sin pasos sincronizados 2 días: 23/09, 29/09.",
        "1 pregunta del sistema quedó sin respuesta (13/10).",
        "Marta contó alucinaciones 2 veces; Juan no lo mencionó.",
        "Y 1 tema más que contó la familia una sola vez.",     # lentitud (Laura, 1 vez): queda en la lista
    ]


# ---------------------------------------------------------------- endpoint

def test_endpoint_devuelve_los_tres_campos(base, monkeypatch):
    from fastapi.testclient import TestClient

    from app import clock
    from app.main import app

    monkeypatch.setattr(clock, "now", lambda: NOW)
    store._has_db_cache["checked"] = -1e9          # la base de este test, no la del anterior
    body = TestClient(app).get("/api/patients/1/report").json()
    assert body["cobertura"]["pasos"]["dias_total"] == 28
    assert body["desde_el_cambio"]["medicamento"] == "pramipexol"
    assert body["lo_que_no_sabemos"]["dias_sin_pasos"] == ["2026-09-23", "2026-09-29"]
    # Base real sin informe generado: vacío y "pendiente", nunca el informe de ejemplo del lienzo.
    assert body["report_status"] == "pendiente" and body["report_simulated"] is False
    assert body["report"]["topics"] == [] and body["report"]["summary"] == ""

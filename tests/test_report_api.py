"""Informe v2 (docs/PULIDO.md §3): cobertura, "Desde el cambio" y "Lo que no sabemos", calculados por código."""
import datetime as dt
import json
import re

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


def test_la_ventana_de_la_pulsera_no_cuenta_como_dia_con_pasos(base):
    """franco/pulsera: biometric_syncs.scope = 'pulsera' no es una sincronización de pasos."""
    with db.connect() as conn:
        if "scope" not in {r[1] for r in conn.execute("PRAGMA table_info(biometric_syncs)")}:
            conn.execute("ALTER TABLE biometric_syncs ADD COLUMN scope TEXT")
        conn.execute("INSERT INTO biometric_syncs (patient_id, window_start, window_end, received_at, n_samples, scope) "
                     "VALUES (1, ?, ?, ?, 0, 'pulsera')", (at(day(0), 0), at(day(27), 23), at(day(27), 23)))
    assert rep.coverage(1, START, END, NOW)["pasos"]["dias_con_datos"] == 26


def test_series_de_la_pulsera_en_la_vista_tecnica(base):
    with db.connect() as conn:
        for i, (mins, awk) in enumerate([(400, 2), (210, 7)]):          # noches que terminan el 16 y el 17
            d = day(26 + i)
            for kind, v in (("sleep_minutes", mins), ("sleep_awakenings", awk)):
                conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                             (kind, v, at(d - dt.timedelta(days=1), 23), at(d, 7), "seed"))
        for h, tremor in ((16, 28), (17, 30), (10, 2)):
            conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                         ("tremor_minutes", tremor, at(day(26), h), at(day(26), h, 59), "seed"))
    s = rep.wearable_series(1, START, END, NOW)
    assert [(n["date"], n["sleep_minutes"], n["sleep_awakenings"]) for n in s["noches"]] == \
        [("2026-10-16", 400, 2), ("2026-10-17", 210, 7)]
    # Temblor y discinesia no se muestran (§8): la API técnica no los devuelve aunque estén en la base.
    assert s["mediciones"] == {"sleep_minutes": 2, "sleep_awakenings": 2}
    assert s["por_hora"] == [] and s["perfil_hora"] == [] and "tremor_minutes" not in s["etiquetas"]
    assert s["etiquetas"]["sleep_awakenings"] == {"texto": "Despertares", "unidad": "veces"}
    assert s["fuentes"] == ["seed"] and s["simulado"] is False


def test_la_vista_tecnica_muestra_la_pulsera_rotulada(base, monkeypatch):
    from fastapi.testclient import TestClient

    from app import clock
    from app.main import app

    monkeypatch.setattr(clock, "now", lambda: NOW)
    store._has_db_cache["checked"] = -1e9
    client = TestClient(app)
    assert 'id="g-sueno"' not in client.get("/neuro/tecnica/1").text          # sin pulsera, sin tarjeta
    with db.connect() as conn:
        d = day(27)
        for kind, v in (("sleep_minutes", 210), ("sleep_awakenings", 7), ("heart_rate_rest", 66)):
            conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                         (kind, v, at(d - dt.timedelta(days=1), 23), at(d, 7), "simulado"))
        conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                     ("active_minutes", 35, at(d, 0), at(d, 23, 59), "simulado"))
    html = client.get("/neuro/tecnica/1").text
    assert "pulsera · simulado" in html and 'id="g-sueno"' in html and 'id="g-pulso"' in html
    assert "despertares (1 mediciones)" in html
    # Debajo de los pasos reales
    assert html.index('id="g-tomas"') < html.index('id="g-sueno"')


def test_sin_pulsera_las_series_quedan_vacias(base):
    s = rep.wearable_series(1, START, END, NOW)
    assert s["noches"] == [] and s["por_hora"] == [] and s["perfil_hora"] == [] and s["mediciones"] == {}


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


def test_informe_minimo_se_rotula_y_muestra_las_cifras_del_codigo(base, monkeypatch):
    from fastapi.testclient import TestClient

    from app import clock
    from app.main import app
    from app.pipeline import report as pipeline_report

    monkeypatch.setattr(clock, "now", lambda: NOW)
    store._has_db_cache["checked"] = -1e9
    pipeline_report._store(1, "20/09 al 17/10", pipeline_report.minimal_report())
    client = TestClient(app)
    body = client.get("/api/patients/1/report").json()
    assert body["report_status"] == "sin_redaccion" and body["report_simulated"] is False
    assert body["report"]["summary"].startswith("El resumen redactado no está disponible")
    assert "no tiene texto redactado por IA" in body["verification_note"]
    assert body["cobertura"]["pasos"]["dias_total"] == 28              # lo del código, igual que con informe
    assert body["desde_el_cambio"]["medicamento"] == "pramipexol"
    assert body["lo_que_no_sabemos"]["dias_sin_pasos"] == ["2026-09-23", "2026-09-29"]
    html = client.get("/neuro/informe/1").text
    assert "El resumen redactado no está disponible" in html and "Los temas redactados no están disponibles" in html
    assert "Redactado con IA" not in html and "Sin datos en el período" not in html
    assert "Pasos por día" in html and "Avisos del período" in html


@pytest.mark.parametrize("estado", ["sin_redaccion", "pendiente"])
def test_cobertura_desde_el_cambio_y_lo_que_no_sabemos_en_cualquier_estado(base, monkeypatch, estado):
    from fastapi.testclient import TestClient

    from app import clock
    from app.main import app
    from app.pipeline import report as pipeline_report

    monkeypatch.setattr(clock, "now", lambda: NOW)
    store._has_db_cache["checked"] = -1e9
    if estado == "sin_redaccion":
        pipeline_report._store(1, "20/09 al 17/10", pipeline_report.minimal_report())
    client = TestClient(app)
    assert client.get("/api/patients/1/report").json()["report_status"] == estado
    html = client.get("/neuro/informe/1").text
    assert "Cobertura: <span" in html and "Pasos: " in html and "días sincronizados" in html
    assert "Desde el cambio del " in html and "inf-dc" in html and "Lo que no sabemos" in html
    assert "Redactado con IA" not in html


# ---------------------------------------------------------------- avisos con etiqueta, lo que notamos, pulsera

MEDS = [{"drug": "pramipexol", "changed": {"date": "2026-10-03", "days_ago": 14}}]


def alert(i, lane, rule_id, text, created, reserved=0):
    return {"id": i, "lane": lane, "rule_id": rule_id, "text": text, "created_at": created, "reserved": reserved}


def test_avisos_con_etiqueta_a2_en_una_fila_y_a1_con_la_fecha_del_relato():
    alerts = [
        alert(1, "ambar", "A2", "Síntoma nuevo a 0 días del cambio de pramipexol: que actúa los sueños.", "2026-10-04T08:30:00-03:00"),
        alert(2, "ambar", "A2", "Síntoma nuevo a 6 días del cambio de pramipexol: mareo al pararse.", "2026-10-09T11:00:00-03:00"),
        alert(3, "ambar", "A2", "Síntoma nuevo a 10 días del cambio de pramipexol: confusión.", "2026-10-14T21:40:00-03:00", 1),
        alert(4, "ambar", "A2", "Síntoma nuevo a 10 días del cambio de pramipexol: que actúa los sueños.", "2026-10-14T22:00:00-03:00"),
        alert(5, "ambar", "A1", "Primera mención de alucinaciones (contado por Marta el 13/10).", "2026-10-14T21:40:00-03:00", 1),
        alert(6, "ambar", "A3", "3 episodios en 7 días después de la toma de las 16:00 (13/10, 15/10, 16/10).", "2026-10-16T18:05:00-03:00"),
        alert(7, "rojo", "R1", "Caída con golpe en la cabeza: llamá a la emergencia.", "2026-10-16T21:30:00-03:00"),
    ]
    out = rep.notices(alerts, MEDS)
    assert [a["etiqueta"] for a in out] == ["Puede ser urgente", "Primera vez", "Nuevo desde el cambio", "Se repite"]
    assert out[0]["texto"] == "Caída con golpe en la cabeza"
    assert out[1]["texto"] == "Primera mención de alucinaciones (contado por Marta el 14/10)."   # created_at
    a2 = out[2]
    assert a2["texto"] == "Síntomas nuevos desde el cambio del 03/10: actúa los sueños, mareo al pararse, confusión."
    assert [(d["fecha"], d["dias"]) for d in a2["detalle"]] == \
        [("2026-10-04", 1), ("2026-10-09", 6), ("2026-10-14", 11), ("2026-10-14", 11)]     # días de calendario
    assert a2["reserved"] is True
    for a in out:
        assert "mbar" not in a["texto"] and "Rojo" not in a["etiqueta"]


def test_el_informe_no_dice_ambar_rojo_ni_verde(base, monkeypatch):
    from fastapi.testclient import TestClient

    from app import clock
    from app.main import app

    monkeypatch.setattr(clock, "now", lambda: NOW)
    store._has_db_cache["checked"] = -1e9
    with db.connect() as conn:
        for lane, rule, text, created in [
                ("ambar", "A2", "Síntoma nuevo a 0 días del cambio de pramipexol: que actúa los sueños.", at(day(14), 8)),
                ("ambar", "A1", "Primera mención de alucinaciones (contado por Marta el 13/10).", at(day(24), 21)),
                ("rojo", "R1", "Caída con golpe en la cabeza: llamá.", at(day(26), 21))]:
            conn.execute("INSERT INTO alerts (patient_id, lane, rule_id, recipients, text, reserved, created_at) "
                         "VALUES (1, ?, ?, '[]', ?, 0, ?)", (lane, rule, text, created))
    html = TestClient(app).get("/neuro/informe/1").text
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S))
    for word in ("Ámbar", "ámbar", "Rojo", "Verde"):
        assert word not in visible
    assert "Puede ser urgente" in visible and "Primera vez" in visible and "Nuevo desde el cambio" in visible
    assert "Síntomas nuevos desde el cambio del 30/09: actúa los sueños." in visible


def add_question(to: int, rule: str, sent: str, question: str, why: str = "", status: str = "enviada") -> int:
    with db.connect() as conn:
        return conn.execute("INSERT INTO questions (patient_id, to_person_id, rule_id, question, why, options, url, status, "
                            "sent_at) VALUES (1, ?, ?, ?, ?, '[]', '/casa', ?, ?)",
                            (to, rule, question, why, status, sent)).lastrowid


def test_lo_que_notamos_episodios_y_preguntas_con_su_respuesta(base):
    q13 = add_question(2, "P-DESVIO", at(day(23), 18, 5), "¿Pasó algo a la tarde?")
    q16 = add_question(2, "P-DESVIO", at(day(26), 18, 5), "¿Cómo estuvo la tarde?")
    add_question(2, "P-SUENO", at(day(25), 9, 5), "¿Cómo durmió Juan?", why="Anoche Juan se despertó 6 veces; lo habitual son 2.")
    with db.connect() as conn:
        eid = conn.execute("INSERT INTO entries (patient_id, speaker_id, modality, question_id, raw_text, reserved_requested, "
                           "corrected, created_at, source) VALUES (1, 2, 'texto', ?, ?, 0, 0, ?, 'precorrer')",
                           (q13, "Sí, a la tarde lo vi muy duro, le costó levantarse del sillón.", at(day(23), 21))).lastrowid
        ev = conn.execute("INSERT INTO events (entry_id, patient_id, domain, symptom, negated, time_vague, speaker_role, quote, "
                          "plain, confidence, is_new, reserved) VALUES (?, 1, 'motor', 'rigidez', 0, 1, 'cuidador', 'muy duro', "
                          "'p', 0.9, 0, 0)", (eid,)).lastrowid
        conn.execute("UPDATE questions SET status = 'respondida', answered_entry_id = ? WHERE id = ?", (eid, q13))
        dev = json.dumps({"observed": 64, "median": 499.0, "z": -4.1, "pct_change": -0.87})
        for d, status, qid, entries, exp in [
                (day(23), "respondido", q13, [eid], {"explained": False, "by": []}),
                (day(25), "explicado", None, [], {"explained": True, "by": ["me sentí trabado"]}),
                (day(26), "preguntado", q16, [], {"explained": False, "by": []})]:
            conn.execute("INSERT INTO episodes (patient_id, dose_time, deviation, explanation, question_id, entry_ids, status) "
                         "VALUES (1, ?, ?, ?, ?, ?, ?)", (at(d, 16), dev, json.dumps(exp), qid, json.dumps(entries), status))
        conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                     ("sleep_awakenings", 6, at(day(24), 23), at(day(25), 7), "simulado"))
    rows = rep.noticed(1, START, END, NOW)
    assert [(r["fecha"], r["regla"], r["resultado"]) for r in rows] == [
        ("2026-10-13", "P-DESVIO", "explicado"), ("2026-10-15", "P-SUENO", "sin explicar"),
        ("2026-10-15", "P-DESVIO", "explicado"), ("2026-10-16", "P-DESVIO", "sin explicar")]
    r13 = rows[0]
    assert r13["detecto"] == "Después de la toma de las 16: 64 pasos; lo habitual ≈ 499"
    assert r13["pregunta_a"] == "Marta" and r13["respuesta"]["cita"].startswith("Sí, a la tarde lo vi muy duro")
    assert r13["respuesta"]["event_id"] == ev                                  # evidencia clickeable
    assert rows[1]["fuente"] == "pulsera · simulado" and "se despertó 6 veces" in rows[1]["detecto"]
    assert rows[1]["respuesta"] is None and rows[1]["pregunta_a"] == "Marta"
    assert rows[2]["pregunta_a"] is None and rows[2]["respuesta"]["cita"] == "me sentí trabado"
    assert rows[3]["respuesta"] is None


def test_pulsera_semanal_en_facts_y_en_el_informe(base, monkeypatch):
    from fastapi.testclient import TestClient

    from app import clock
    from app.main import app
    from app.pipeline import report_facts

    with db.connect() as conn:
        for i in range(28):
            d = day(i)
            week = i >= 21
            for kind, v in (("sleep_minutes", 360 if week else 420), ("sleep_awakenings", 4 if week else 2),
                            ("heart_rate_rest", 66 if week else 62)):
                conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                             (kind, v, at(d - dt.timedelta(days=1), 23), at(d, 7), "simulado"))
            conn.execute('INSERT INTO biometrics (patient_id, kind, value, start, "end", source) VALUES (1, ?, ?, ?, ?, ?)',
                         ("active_minutes", 30 if week else 45, at(d, 0), at(d, 23, 59), "simulado"))
    facts = report_facts.build(1, NOW)
    w = facts["wearable_week"]
    assert w["label"] == "según la pulsera (simulado)" and w["rotulo"] == "pulsera · simulado"
    assert w["week"] == "11/10 al 17/10"
    by = {m["kind"]: (m["week"], m["baseline"]) for m in w["metrics"]}
    assert by == {"sleep_minutes": ("6,0", "7,0"), "sleep_awakenings": ("4", "2"), "heart_rate_rest": ("66", "62"),
                  "active_minutes": ("30", "45")}
    monkeypatch.setattr(clock, "now", lambda: NOW)
    store._has_db_cache["checked"] = -1e9
    html = TestClient(app).get("/neuro/informe/1").text
    assert "Pulsera, semana del 11/10 al 17/10" in html and "pulsera · simulado" in html
    assert "Sueño por noche (h)" in html


def test_conteos_nombran_el_sintoma_como_sustantivo():
    from app.pipeline import report_facts

    assert report_facts.symptom_noun("actua_suenos") == "actuar los sueños"
    assert report_facts.symptom_noun("mareo_al_pararse") == "mareo al pararse"

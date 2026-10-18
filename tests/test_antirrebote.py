"""Antirrebote del botón de voz de Juan (contar.js): el toque cuenta en pointerdown; el click que lo sigue se
ignora; después de empezar a grabar, los toques se ignoran por 800 ms (temblor)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "app" / "web"
CONTAR_JS = WEB / "static" / "js" / "contar.js"
TEMPLATE = WEB / "casa" / "contar_juan.html"


def test_botones_de_juan_usan_tocar_en_pointerdown_y_click():
    html = TEMPLATE.read_text(encoding="utf-8")
    for accion in ("empezar", "terminar"):
        assert f"@pointerdown=\"tocar('{accion}', $event)\"" in html
        assert f"@click=\"tocar('{accion}', $event)\"" in html
    assert '@click="terminar()"' not in html and '@click="empezar()"' not in html


def test_guarda_de_800_ms_al_empezar_a_grabar():
    js = CONTAR_JS.read_text(encoding="utf-8")
    assert "var GUARD_MS = 800;" in js
    assert "self._guardUntil = Date.now() + GUARD_MS;" in js


NODE_SCRIPT = r"""
const fs = require("fs"), vm = require("vm");
let now = 1000;
const noop = () => {};
const ctx = { window: { ENTRECASA: {}, addEventListener: noop }, Date: { now: () => now }, performance: { now: () => now },
  document: { addEventListener: noop, querySelector: () => null, querySelectorAll: () => [] } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const c = ctx.window.contar({ startMode: "listo", family: false });
const calls = [];
c.empezar = function () { calls.push("empezar"); this.phase = "grabando"; this._guardUntil = now + 800; };
c.terminar = function () { calls.push("terminar"); this.phase = "procesando"; };
const out = {};
c.tocar("empezar", { type: "pointerdown" });          // empieza
c.tocar("empezar", { type: "click" });                // el click del mismo toque: ignorado
out.despuesDeEmpezar = calls.slice();
now += 100; c.tocar("terminar", { type: "pointerdown" });   // segundo toque por temblor: ignorado
out.temblor = calls.slice();
now += 800; c.tocar("terminar", { type: "pointerdown" });   // toque a propósito: termina
out.final = calls.slice();
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="sin node")
def test_un_doble_toque_por_temblor_no_corta_la_grabacion(tmp_path):
    script = tmp_path / "antirrebote.js"
    script.write_text(NODE_SCRIPT, encoding="utf-8")
    res = subprocess.run(["node", str(script), str(CONTAR_JS)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["despuesDeEmpezar"] == ["empezar"]
    assert out["temblor"] == ["empezar"]
    assert out["final"] == ["empezar", "terminar"]

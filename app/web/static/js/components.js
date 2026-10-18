/* Entrecasa — componentes de Alpine (estado local de cada pantalla). Requiere app.js. */
(function () {
  "use strict";
  var EC = window.ENTRECASA;

  /* ---------------------------------------------------------- ¿Quién sos? */
  window.selector = function () {
    return {
      elegida: false,
      nombre: "",
      elegir: function (personId, patientId, role, name) {
        EC.person.set(personId, patientId, role);
        this.nombre = name;
        this.elegida = true;
        EC.push.resync();
      }
    };
  };

  /* ---------------------------------------------------------- pregunta proactiva: respuesta rápida */
  window.pregunta = function (questionId, personId) {
    return {
      elegida: null, enviando: false, slow: false, error: "",
      responder: function (i, texto) {
        var self = this;
        if (self.enviando) return;
        self.elegida = i; self.enviando = true; self.error = ""; self.slow = false;
        var t = setTimeout(function () { self.slow = true; }, 15000);
        var fd = new FormData();
        fd.append("person_id", personId);
        fd.append("question_id", questionId);
        fd.append("quick_reply", texto);
        fetch("/api/entries", { method: "POST", body: fd })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
          .then(function (r) {
            clearTimeout(t);
            if (!r.ok) throw new Error("ia");
            try { sessionStorage.setItem("ec_entry_" + r.d.entry_id, JSON.stringify(r.d)); sessionStorage.setItem("ec_q_" + r.d.entry_id, "1"); } catch (e) {}
            location.assign("/casa/anote/" + r.d.entry_id);
          })
          .catch(function (err) {
            clearTimeout(t);
            self.enviando = false;
            self.error = navigator.onLine ? "No pude entenderlo esta vez. Lo guardé tal cual para tu neuróloga."
                                          : "No hay conexión. Probá de nuevo en un rato.";
          });
      }
    };
  };

  /* ---------------------------------------------------------- juego de golpeteo (20 s) */
  var DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
  window.golpeteo = function (personId) {
    return {
      phase: "ready", left: 20, count: 0, last: "", taps: [], result: null, error: "",
      _t0: 0, _timer: null,
      start: function () {
        var self = this;
        clearInterval(self._timer);
        self.taps = []; self.count = 0; self.last = ""; self.left = 20; self.result = null;
        self.phase = "playing";
        self._t0 = performance.now();
        self._timer = setInterval(function () {
          var elapsed = (performance.now() - self._t0) / 1000;
          self.left = Math.max(0, Math.ceil(20 - elapsed));
          if (elapsed >= 20) { clearInterval(self._timer); self.send(); }
        }, 100);
      },
      tap: function (side) {
        if (this.phase !== "playing") return;
        // Solo cuenta si alterna; el primero es el izquierdo (el que está en pino).
        var expected = this.last === "izq" ? "der" : "izq";
        if (side !== expected) return;
        var t = Math.round(performance.now() - this._t0);
        if (t > 20000) return;
        this.taps.push({ t_ms: t, side: side });
        this.count = this.taps.length;
        this.last = side;
        if (navigator.vibrate) try { navigator.vibrate(8); } catch (e) {}
      },
      send: function () {
        var self = this;
        self.phase = "sending";
        fetch("/api/tests", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ person_id: personId, type: "golpeteo", taps: self.taps })
        }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(function (d) { self.result = d; self.phase = "done"; })
          .catch(function () {
            self.error = navigator.onLine ? "No pudimos guardar el juego esta vez. Probá de nuevo en un rato."
                                          : "No hay conexión. Probá de nuevo en un rato.";
            self.phase = "error";
          });
      },
      salir: function () { clearInterval(this._timer); },
      destroy: function () { clearInterval(this._timer); },
      get historyBars() {
        if (!this.result) return [];
        var maxV = 8;
        var bar = function (v) { return Math.max(6, Math.round(Math.min(v, maxV) / maxV * 70)); };
        var hist = (this.result.history || []).map(function (h) {
          return { d: DIAS[new Date(h.taken_at).getDay()], px: bar(h.taps_per_s), today: false };
        });
        hist.push({ d: "hoy", px: bar(this.result.metrics.taps_per_s), today: true });
        return hist;
      },
      get verdict() {
        var v = this.result && this.result.vs_history;
        if (v === "mas_lento") return "Un poco más lento que tus últimas veces. Lo anotamos para tu neuróloga; no es un diagnóstico.";
        if (v === "sin_historial") return "Es de tus primeras veces. Lo vamos a comparar con las próximas.";
        return "Parecido a tus últimas veces.";
      }
    };
  };

  /* ---------------------------------------------------------- permisos (consentimientos) */
  window.permisos = function (patientId, consents) {
    return {
      rows: consents, error: "",
      get: function (rid, kind) {
        var r = this.rows.filter(function (c) { return c.recipient_id === rid && c.kind === kind; })[0];
        return r ? r.enabled : false;
      },
      set: function (rid, kind, enabled) {
        var self = this;
        self.error = "";
        fetch("/api/consents/" + patientId, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ recipient_id: rid, kind: kind, enabled: enabled })
        }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
          .then(function (d) { self.rows = d.consents; EC.toast("Guardado."); })
          .catch(function () { self.error = "No se pudo guardar. Probá de nuevo en un rato."; });
      }
    };
  };

  /* ---------------------------------------------------------- panel de la demo (/admin/clock) */
  window.adminPanel = function () {
    var tok = "";
    try { tok = localStorage.getItem("ec_admin_token") || ""; } catch (e) {}
    return {
      token: tok, now: "", offset: 0, setTo: "", msg: "", msgError: false,
      drop: { patient_id: 1, day: "", dose: "16:00", pct: 70 },
      init: function () { this.refresh(); },
      saveToken: function () { try { localStorage.setItem("ec_admin_token", this.token); } catch (e) {} },
      get nowLabel() {
        if (!this.now) return "";
        var d = this.now; // ISO con zona de Montevideo: se muestra tal cual, sin la hora del navegador
        var dias = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
        var wd = new Date(d.slice(0, 10) + "T12:00:00").getDay();
        return dias[wd] + " " + d.slice(8, 10) + "/" + d.slice(5, 7) + " · " + d.slice(11, 16);
      },
      get offsetLabel() {
        if (!this.offset) return "";
        var h = Math.round(this.offset / 360) / 10;
        return "Reloj corrido " + (h > 0 ? "+" : "") + String(h).replace(".", ",") + " h respecto de la hora real";
      },
      _req: function (method, url, body) {
        var self = this;
        return fetch(url, {
          method: method, headers: { "Content-Type": "application/json", "X-Admin-Token": self.token },
          body: body ? JSON.stringify(body) : undefined
        }).then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (d) {
            if (!r.ok) throw new Error((d && d.detail) || ("Error " + r.status));
            return d;
          });
        });
      },
      _show: function (text, isError) { this.msg = text; this.msgError = !!isError; },
      refresh: function () {
        var self = this;
        self._req("GET", "/admin/clock/state").then(function (d) {
          self.now = d.now; self.offset = d.offset_seconds || 0;
          if (!self.drop.day) self.drop.day = d.now.slice(0, 10);
          if (self.msgError) self._show("");
        }).catch(function (e) { self._show(e.message === "Error 404" ? "Todavía no está el reloj (app/clock.py)." : e.message, true); });
      },
      advance: function (min) {
        var self = this;
        self._req("POST", "/admin/clock/advance", { minutes: min }).then(function (d) {
          self.now = d.now; self.refresh(); self._show("Reloj adelantado " + (min >= 60 ? (min / 60) + " h" : min + " min") + ".");
        }).catch(function (e) { self._show(e.message, true); });
      },
      setClock: function () {
        var self = this;
        self._req("POST", "/admin/clock/set", { iso: self.setTo + (self.setTo.length === 16 ? ":00" : "") + "-03:00" })
          .then(function (d) { self.now = d.now; self.refresh(); self._show("Hora fijada."); })
          .catch(function (e) { self._show(e.message, true); });
      },
      injectDrop: function () {
        var self = this;
        var body = { patient_id: self.drop.patient_id, dose_time: self.drop.day + "T" + self.drop.dose + ":00-03:00", pct: self.drop.pct / 100 };
        self._req("POST", "/admin/inject_drop", body)
          .then(function () { self._show("Caída inyectada (" + self.drop.pct + "%) el " + self.drop.day + " después de la toma de las " + self.drop.dose + ". Adelantá el reloj para que la detecte."); })
          .catch(function (e) { self._show(e.message, true); });
      },
      post: function (url, body, ok, detail) {
        var self = this;
        self._show("Trabajando…");
        return self._req("POST", url, body).then(function (d) {
          self._show(ok + (detail ? " " + JSON.stringify(d) : "")); self.refresh(); return d;
        }).catch(function (e) { self._show(e.message, true); });
      },
      importSteps: function (ev) {
        var self = this, file = ev.target.files && ev.target.files[0];
        if (!file) return;
        self._show("Importando " + file.name + "…");
        file.text().then(function (text) {
          return fetch("/admin/import_steps?patient_id=" + self.drop.patient_id, {
            method: "POST", headers: { "Content-Type": "text/csv", "X-Admin-Token": self.token }, body: text
          });
        }).then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (d) {
            if (!r.ok) throw new Error((d && d.detail) || ("Error " + r.status));
            self._show("Pasos importados: " + JSON.stringify(d));
          });
        }).catch(function (e) { self._show(e.message, true); })
          .finally(function () { ev.target.value = ""; });
      },
      pushTest: function (personId) {
        var self = this;
        fetch("/api/push/test/" + personId, { method: "POST" }).then(function (r) { return r.json(); })
          .then(function (d) { self._show("Push de prueba: " + JSON.stringify(d)); })
          .catch(function (e) { self._show(String(e), true); });
      }
    };
  };

  /* ---------------------------------------------------------- tarjeta de avisos */
  window.avisosCard = function (dismissible) {
    return {
      dismissible: dismissible,
      state: EC.push.state(),
      busy: false,
      error: "",
      justEnabled: false,
      closed: false,
      init: function () {
        try { this.closed = dismissible && sessionStorage.getItem("ec_avisos_cerrado") === "1"; } catch (e) {}
      },
      get visible() {
        if (this.closed) return false;
        if (this.state === "activo") return this.justEnabled;
        return this.state === "instalar" || this.state === "pendiente" || this.state === "bloqueado";
      },
      activar: function () {
        var self = this;
        self.busy = true;
        self.error = "";
        EC.push.enable().then(function () {
          self.justEnabled = true;
          self.state = "activo";
        }).catch(function (err) {
          self.state = EC.push.state();
          self.error = EC.push.errorText(err);
        }).finally(function () { self.busy = false; });
      },
      cerrar: function () {
        this.closed = true;
        try { sessionStorage.setItem("ec_avisos_cerrado", "1"); } catch (e) {}
      }
    };
  };
})();

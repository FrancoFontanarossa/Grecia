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

  /* ---------------------------------------------------------- pantalla roja */
  var CRITERIA = {
    anticoagulante: "¿Toma algún anticoagulante (por ejemplo, apixabán o warfarina)?",
    perdida_conocimiento: "¿Perdió el conocimiento, aunque sea un momento?",
    vomito: "¿Vomitó después del golpe?",
    cefalea: "¿Le duele la cabeza?",
    fiebre: "¿Tiene fiebre de 38 o más?"
  };
  window.emergencia = function (alert, entryId, personId) {
    var red = null;
    try { red = JSON.parse(sessionStorage.getItem("ec_red_" + entryId) || "null"); } catch (e) {}
    var src = red || alert || {};
    return {
      text: src.text || "Esto puede ser urgente.",
      missing: src.missing_criterion || null,
      answered: false, sending: false, demoNote: false,
      get missingQuestion() {
        var m = this.missing || "";
        return CRITERIA[m] || ("¿" + m.replace(/_/g, " ") + "?");
      },
      answer: function (yes) {
        var self = this;
        self.sending = true;
        var fd = new FormData();
        fd.append("person_id", personId);
        fd.append("text", (yes ? "Sí. " : "No. ") + self.missingQuestion);
        fd.append("quick_reply", yes ? "Sí" : "No");
        fetch("/api/entries", { method: "POST", body: fd })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            self.sending = false; self.answered = true;
            if (d.red) { self.text = d.red.text; self.missing = d.red.missing_criterion; self.answered = !self.missing; }
          })
          .catch(function () { self.sending = false; EC.toast("No hay conexión. Probá de nuevo en un rato."); });
      },
      llamar: function () {
        if (EC.demo) { this.demoNote = true; return; }
        location.href = "tel:" + (EC.emergencyNumber || "911");
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

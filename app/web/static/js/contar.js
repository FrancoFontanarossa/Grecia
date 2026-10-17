/* Entrecasa — contar algo: grabar (tocar para empezar, tocar para terminar), mandar a /api/entries y
 * mostrar progreso y errores (design/DESIGN.md §5). Lo usan Juan (pantalla oscura) y la familia. */
(function () {
  "use strict";
  var EC = window.ENTRECASA;
  var BARS = 28;
  var MIN_MS = 1200;          // menos que esto es "no te escuché"
  var SLOW_MS = 15000;        // "Está tardando un poco más…"
  var TIMEOUT_MS = 120000;

  var TEXTS = {
    transcribing: "Pasando a texto…",
    understanding: "Entendiendo lo que contaste…",
    slow: "Está tardando un poco más. No cierres la app.",
    notHeard: "No te escuché bien. ¿Probamos de nuevo?",
    noMic: "Necesito permiso para escucharte. Abrí Ajustes › Safari › Micrófono.",
    offline: "No hay conexión. Probá de nuevo en un rato.",
    aiFailed: "No pude entenderlo esta vez. Lo guardé tal cual para tu neuróloga."
  };

  function flatBars() { var a = []; for (var i = 0; i < BARS; i++) a.push(12); return a; }

  /**
   * opts: { personId, questionId, correctId, startMode: "grabar"|"escribir"|"listo", family: bool, quickReply }
   */
  window.contar = function (opts) {
    return {
      opts: opts,
      phase: "listo",          // listo | pidiendo | grabando | procesando | resultado | escribir | error
      seconds: 0,
      bars: flatBars(),
      progress: "",
      slow: false,
      error: "",
      errorKind: "",           // no-escuche | sin-permiso | offline | ia
      transcript: "",
      text: opts.prefill || "",
      hint: opts.hint || "",
      reserved: false,
      result: null,
      correctId: opts.correctId || null,
      _rec: null, _stream: null, _chunks: [], _t0: 0, _timer: null, _raf: null, _blob: null, _mime: "",

      init: function () {
        if (opts.startMode === "escribir") { this.phase = "escribir"; return; }
        if (opts.startMode === "grabar") this.empezar();
      },
      destroy: function () { this._cleanup(); },

      /* ------------------------------------------------ grabación */
      empezar: function () {
        var self = this;
        self.error = ""; self.errorKind = ""; self.seconds = 0; self.bars = flatBars();
        if (!window.MediaRecorder) { self._fail("sin-permiso", "Este teléfono no puede grabar acá. Escribilo, por favor."); return; }
        self.phase = "pidiendo";
        // La primera vez usa el micrófono pedido en el toque de la pantalla anterior; después, uno nuevo.
        var p = self._usedPreacquired ? EC.mic.acquire() : EC.mic.take();
        self._usedPreacquired = true;
        p.then(function (stream) {
          self._stream = stream;
          self._mime = EC.mic.mimeType();
          var rec;
          try { rec = self._mime ? new MediaRecorder(stream, { mimeType: self._mime }) : new MediaRecorder(stream); }
          catch (e) { rec = new MediaRecorder(stream); }
          self._mime = rec.mimeType || self._mime || "audio/mp4";
          self._chunks = [];
          rec.ondataavailable = function (ev) { if (ev.data && ev.data.size) self._chunks.push(ev.data); };
          rec.onstop = function () { self._onStopped(); };
          self._rec = rec;
          rec.start(250);
          self._t0 = performance.now();
          self.phase = "grabando";
          self._timer = setInterval(function () { self.seconds = Math.floor((performance.now() - self._t0) / 1000); }, 250);
          self._meter(stream);
        }).catch(function (err) {
          var name = err && err.name;
          if (name === "NotAllowedError" || name === "SecurityError") self._fail("sin-permiso", TEXTS.noMic);
          else if (name === "NotFoundError" || (err && err.message === "sin-microfono")) self._fail("sin-permiso", "No encontramos un micrófono. Escribilo, por favor.");
          else { self.phase = "listo"; }  // p. ej. iOS pide un toque: se muestra "Tocá para empezar"
        });
      },
      terminar: function () {
        if (this.phase !== "grabando" || !this._rec) return;
        this._duration = performance.now() - this._t0;
        try { this._rec.stop(); } catch (e) { this._onStopped(); }
      },
      cancelar: function () {
        this._cleanup();
        location.assign(opts.backUrl || "/casa");
      },
      _onStopped: function () {
        clearInterval(this._timer); cancelAnimationFrame(this._raf);
        EC.mic.release(this._stream); this._stream = null;
        var blob = new Blob(this._chunks, { type: this._mime || "audio/mp4" });
        if ((this._duration || 0) < MIN_MS || blob.size < 1500) { this._fail("no-escuche", TEXTS.notHeard); return; }
        this._blob = blob;
        this.enviar();
      },
      _meter: function (stream) {
        var self = this, ctx = EC.mic.context();
        if (!ctx) return;
        try {
          if (ctx.state === "suspended") ctx.resume();
          var src = ctx.createMediaStreamSource(stream);
          var an = ctx.createAnalyser();
          an.fftSize = 1024;
          src.connect(an);
          var buf = new Uint8Array(an.fftSize), last = 0;
          var loop = function (ts) {
            if (self.phase !== "grabando") return;
            if (ts - last > 90) {
              last = ts;
              an.getByteTimeDomainData(buf);
              var sum = 0;
              for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; sum += v * v; }
              var rms = Math.sqrt(sum / buf.length);
              var h = Math.max(10, Math.min(76, Math.round(10 + rms * 420)));
              var next = self.bars.slice(1); next.push(h); self.bars = next;
            }
            self._raf = requestAnimationFrame(loop);
          };
          self._raf = requestAnimationFrame(loop);
        } catch (e) { /* sin onda: igual graba */ }
      },
      _cleanup: function () {
        clearInterval(this._timer); cancelAnimationFrame(this._raf);
        try { if (this._rec && this._rec.state !== "inactive") { this._rec.onstop = null; this._rec.stop(); } } catch (e) {}
        EC.mic.release(this._stream); this._stream = null;
      },

      /* ------------------------------------------------ envío */
      escribir: function () { this._cleanup(); this.error = ""; this.phase = "escribir"; },
      enviarTexto: function () {
        if (!this.text.trim()) return;
        this._blob = null;
        this.enviar();
      },
      enviar: function () {
        var self = this;
        var fd = new FormData();
        var isAudio = !!self._blob;
        if (isAudio) {
          var ext = /mp4|m4a|aac/.test(self._mime) ? "m4a" : (/ogg/.test(self._mime) ? "ogg" : "webm");
          fd.append("audio", self._blob, "relato." + ext);
        } else {
          fd.append("text", self.text.trim());
        }
        var url;
        if (self.correctId) {
          url = "/api/entries/" + self.correctId + "/correct";
        } else {
          url = "/api/entries";
          fd.append("person_id", opts.personId);
          if (self.hint) fd.append("occurred_hint", self.hint);
          if (opts.questionId) fd.append("question_id", opts.questionId);
          if (opts.family) fd.append("reserved_requested", self.reserved ? "true" : "false");
        }
        self.phase = "procesando";
        self.slow = false;
        self.progress = isAudio ? TEXTS.transcribing : TEXTS.understanding;
        var t1 = setTimeout(function () { self.progress = TEXTS.understanding; }, 3500);
        var t2 = setTimeout(function () { self.slow = true; }, SLOW_MS);
        var ctrl = window.AbortController ? new AbortController() : null;
        var t3 = setTimeout(function () { if (ctrl) ctrl.abort(); }, TIMEOUT_MS);
        var done = function () { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };

        if (!navigator.onLine) { done(); self._fail("offline", TEXTS.offline); return; }
        fetch(url, { method: "POST", body: fd, signal: ctrl ? ctrl.signal : undefined })
          .then(function (res) {
            return res.json().catch(function () { return {}; }).then(function (data) { return { res: res, data: data }; });
          })
          .then(function (r) {
            done();
            var data = r.data || {};
            if (!r.res.ok) {
              // Si la corrección por audio no está soportada, se pasa a escribir.
              if (self.correctId && isAudio && r.res.status === 422) {
                self.phase = "escribir"; self.error = "Escribilo como querés que quede."; return;
              }
              var tr = data.transcript || (data.detail && data.detail.transcript) || "";
              self.transcript = tr;
              if (isAudio && !tr && r.res.status < 500) self._fail("no-escuche", TEXTS.notHeard);
              else self._fail("ia", TEXTS.aiFailed);
              return;
            }
            self._ok(data);
          })
          .catch(function () {
            done();
            self._fail(navigator.onLine ? "ia" : "offline", navigator.onLine ? TEXTS.aiFailed : TEXTS.offline);
          });
      },
      _ok: function (data) {
        var id = data.entry_id || this.correctId;
        data.entry_id = id;
        try { sessionStorage.setItem("ec_entry_" + id, JSON.stringify(data)); } catch (e) {}
        this.transcript = data.transcript || (this._blob ? "" : this.text);
        if (data.red) {
          var rojo = (data.alerts || []).filter(function (a) { return a.lane === "rojo"; })[0];
          try { sessionStorage.setItem("ec_red_" + id, JSON.stringify(data.red)); } catch (e) {}
          location.assign("/casa/emergencia/" + (rojo ? rojo.id : "0") + "?entry=" + id);
          return;
        }
        if (this._blob && !this.transcript && !(data.understood || []).length) {
          this._fail("no-escuche", TEXTS.notHeard); return;
        }
        this.result = data;
        this.correctId = id;  // si regraba, corrige esta misma entrada
        if (opts.family) { this.phase = "resultado"; return; }
        location.assign("/casa/anote/" + id);
      },
      _fail: function (kind, text) {
        this._cleanup();
        this.errorKind = kind; this.error = text; this.phase = "error";
      },
      reintentar: function () {
        if (this.errorKind === "offline" && (this._blob || this.text.trim())) { this.enviar(); return; }
        if (this.errorKind === "sin-permiso") { this.escribir(); return; }
        if (this.errorKind === "ia") { this.cancelar(); return; }
        this.empezar();
      },

      /* ------------------------------------------------ resultado (familia) */
      guardar: function () {
        var id = this.result && this.result.entry_id;
        if (!id) { location.assign("/casa"); return; }
        fetch("/api/entries/" + id + "/confirm", { method: "POST" }).finally(function () {
          try { sessionStorage.setItem("ec_toast", "Guardado. Gracias por contarlo."); } catch (e) {}
          location.assign("/casa");
        });
      },
      regrabar: function () { this.result = null; this.empezar(); },
      get mmss() { return EC.mmss(this.seconds); }
    };
  };

  /* ------------------------------------------------ "Anoté esto" */
  window.anote = function (entryId, labels) {
    return {
      entryId: entryId,
      labels: labels || {},
      data: null,
      loading: true,
      init: function () {
        var self = this;
        try { self.data = JSON.parse(sessionStorage.getItem("ec_entry_" + entryId) || "null"); } catch (e) {}
        if (self.data) { self.loading = false; return; }
        // TODO(contrato): GET /api/entries/{id} (propuesto a Guada).
        fetch("/api/entries/" + entryId).then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) { self.data = d; }).catch(function () {})
          .finally(function () { self.loading = false; });
      },
      get items() { return (this.data && this.data.understood) || []; },
      confirmar: function () {
        fetch("/api/entries/" + entryId + "/confirm", { method: "POST" }).finally(function () {
          location.assign("/casa");
        });
      }
    };
  };

  // Aviso corto al volver al inicio ("Guardado…").
  document.addEventListener("DOMContentLoaded", function () {
    try {
      var t = sessionStorage.getItem("ec_toast");
      if (t) { sessionStorage.removeItem("ec_toast"); EC.toast(t); }
    } catch (e) {}
  });
})();

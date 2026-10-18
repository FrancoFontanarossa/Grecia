/* Entrecasa — núcleo de la PWA: quién sos, service worker, push, micrófono. JS plano. */
(function () {
  "use strict";

  var EC = window.ENTRECASA || (window.ENTRECASA = {});
  window.EC = EC;  // atajo para onclick y expresiones de Alpine

  /* ---------------------------------------------------------- quién sos (demo, sin login) */
  function setCookie(name, value) {
    document.cookie = name + "=" + encodeURIComponent(value) + "; path=/; max-age=31536000; samesite=lax";
  }
  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : null;
  }
  EC.person = {
    get: function () {
      var id = null;
      try { id = localStorage.getItem("ec_person"); } catch (e) {}
      return id || getCookie("ec_person");
    },
    set: function (personId, patientId, role) {
      try {
        localStorage.setItem("ec_person", String(personId));
        localStorage.setItem("ec_patient", String(patientId));
        localStorage.setItem("ec_role", role);
      } catch (e) {}
      setCookie("ec_person", personId);
      setCookie("ec_patient", patientId);
    },
    clear: function () {
      try { localStorage.removeItem("ec_person"); localStorage.removeItem("ec_role"); } catch (e) {}
      document.cookie = "ec_person=; path=/; max-age=0";
    }
  };
  // QR del jurado (/prueba → /?prueba=1): el teléfono olvida el rol que tenía (por ejemplo, Juan) y queda en el
  // paciente de prueba que puso el servidor en la cookie. Va antes de syncPerson, que si no lo volvería a poner.
  (function pruebaReset() {
    if (!/[?&]prueba=1(&|$)/.test(location.search)) return;
    try {
      localStorage.removeItem("ec_person");
      localStorage.removeItem("ec_role");
      localStorage.setItem("ec_patient", getCookie("ec_patient") || "");
    } catch (e) {}
    document.cookie = "ec_person=; path=/; max-age=0";
    try { history.replaceState(null, "", location.pathname); } catch (e) {}
  })();
  // "Cambiar de persona" (/?cambiar=1): el teléfono olvida a quién tenía y vuelve al selector.
  (function cambiarReset() {
    if (!/[?&]cambiar=1(&|$)/.test(location.search)) return;
    EC.person.clear();
    try { history.replaceState(null, "", location.pathname); } catch (e) {}
  })();
  // Si iOS borró la cookie pero quedó localStorage (o al revés), se vuelven a alinear.
  (function syncPerson() {
    try {
      var ls = localStorage.getItem("ec_person");
      if (ls && !getCookie("ec_person")) {
        setCookie("ec_person", ls);
        setCookie("ec_patient", localStorage.getItem("ec_patient") || "1");
        if (location.pathname === "/casa") location.reload();
        // El selector se ve una sola vez: con la persona guardada, "/" abre el inicio.
        else if (location.pathname === "/") location.replace("/casa");
      }
    } catch (e) {}
  })();

  /* ---------------------------------------------------------- plataforma */
  EC.isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  EC.isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  EC.pushSupported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  /* ---------------------------------------------------------- service worker */
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function (err) {
      console.warn("No se pudo registrar el service worker", err);
    });
  }

  /* ---------------------------------------------------------- push */
  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(base64);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  EC.push = {
    /** Estado: "no-soportado" | "instalar" | "activo" | "bloqueado" | "pendiente" */
    state: function () {
      if (EC.isIOS && !EC.isStandalone) return "instalar";
      if (!EC.pushSupported) return "no-soportado";
      if (Notification.permission === "granted") return "activo";
      if (Notification.permission === "denied") return "bloqueado";
      return "pendiente";
    },
    /** Llamar SIEMPRE desde el click de un botón (iOS lo exige). */
    enable: function () {
      if (!EC.person.get()) return Promise.reject(new Error("sin-persona"));
      if (!EC.pushSupported) return Promise.reject(new Error("no-soportado"));
      // requestPermission va primero y sin await previo, para no perder el gesto en iOS.
      return Notification.requestPermission().then(function (perm) {
        if (perm !== "granted") throw new Error("permiso-" + perm);
        return EC.push.subscribe();
      });
    },
    /** Con el permiso ya dado: suscribe este teléfono y lo manda a POST /api/push/subscribe. */
    subscribe: function () {
      var personId = EC.person.get();
      var reg;
      return navigator.serviceWorker.ready.then(function (r) {
        reg = r;
        return EC.push.publicKey();
      }).then(function (key) {
        return reg.pushManager.getSubscription().then(function (sub) {
          return sub || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
        });
      }).then(function (sub) {
        return fetch("/api/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ person_id: Number(personId), subscription: sub.toJSON() })
        });
      }).then(function (res) {
        if (!res.ok) throw new Error("subscribe-" + res.status);
        return true;
      });
    },
    /** Clave pública VAPID del servidor (GET /api/push/vapid-public-key, de notify). Nunca claves propias. */
    publicKey: function () {
      return fetch("/api/push/vapid-public-key").then(function (r) {
        if (!r.ok) throw new Error("sin-vapid");
        return r.json();
      }).then(function (d) {
        if (!d.key) throw new Error("sin-vapid");
        return d.key;
      });
    },
    /** Re-sincroniza la suscripción si el permiso ya estaba dado (p. ej. cambió la persona). */
    resync: function () {
      if (EC.push.state() !== "activo") return;
      var personId = EC.person.get();
      if (!personId) return;
      // En cada carga con permiso: subscribe() devuelve la misma suscripción si ya existe, y se manda
      // siempre al servidor (sin flags locales), así sobrevive a un /admin/restore o a una base nueva.
      var reg;
      navigator.serviceWorker.ready.then(function (r) {
        reg = r;
        return reg.pushManager.getSubscription();
      }).then(function (sub) {
        return sub || EC.push.publicKey().then(function (key) {
          return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
        });
      }).then(function (sub) {
        return fetch("/api/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ person_id: Number(personId), subscription: sub.toJSON() })
        });
      }).catch(function () {});
    },
    errorText: function (err) {
      var m = (err && err.message) || "";
      if (m.indexOf("permiso-denied") === 0) return "Los avisos están bloqueados. Abrí Ajustes › Notificaciones › Neuro y activalos.";
      if (m === "no-soportado") return "Este navegador no puede recibir avisos.";
      if (m.indexOf("permiso-") === 0) return "No se activaron los avisos. Podés probar de nuevo cuando quieras.";
      return "No pudimos activar los avisos. Probá de nuevo en un rato.";
    }
  };

  /* ---------------------------------------------------------- micrófono */
  // El permiso y el AudioContext se piden en el toque del botón (gesto del usuario) y quedan
  // guardados acá; la pantalla de grabación los usa después de navegar con hx-boost.
  var mic = { streamPromise: null, ctx: null };
  EC.mic = {
    acquire: function () {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        mic.streamPromise = Promise.reject(new Error("sin-microfono"));
        mic.streamPromise.catch(function () {});
        return mic.streamPromise;
      }
      try {
        var AC = window.AudioContext || window.webkitAudioContext;
        if (AC && (!mic.ctx || mic.ctx.state === "closed")) mic.ctx = new AC();
        if (mic.ctx && mic.ctx.state === "suspended") mic.ctx.resume();
      } catch (e) {}
      mic.streamPromise = navigator.mediaDevices.getUserMedia({ audio: true });
      mic.streamPromise.catch(function () {});
      return mic.streamPromise;
    },
    take: function () {
      var p = mic.streamPromise || EC.mic.acquire();
      mic.streamPromise = null;
      return p;
    },
    context: function () { return mic.ctx; },
    release: function (stream) {
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    },
    mimeType: function () {
      if (!window.MediaRecorder) return null;
      var types = ["audio/mp4", "audio/webm;codecs=opus", "audio/webm", "audio/ogg"];
      for (var i = 0; i < types.length; i++) {
        if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(types[i])) return types[i];
      }
      return "";
    }
  };

  /* ---------------------------------------------------------- utilidades */
  EC.toast = function (text, ms) {
    var el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, ms || 3500);
  };
  EC.go = function (url) { location.assign(url); };
  EC.fmtMiles = function (n) { return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "."); };
  EC.fmtDec1 = function (n) { return (Math.round(n * 10) / 10).toFixed(1).replace(".", ","); };
  EC.mmss = function (s) { var m = Math.floor(s / 60), r = s % 60; return m + ":" + (r < 10 ? "0" : "") + r; };

  document.addEventListener("DOMContentLoaded", function () { EC.push.resync(); });
})();

/* Entrecasa — núcleo de la PWA: quién sos, service worker, push, micrófono. JS plano. */
(function () {
  "use strict";

  var EC = window.ENTRECASA || (window.ENTRECASA = {});

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
  // Si iOS borró la cookie pero quedó localStorage (o al revés), se vuelven a alinear.
  (function syncPerson() {
    try {
      var ls = localStorage.getItem("ec_person");
      if (ls && !getCookie("ec_person")) {
        setCookie("ec_person", ls);
        setCookie("ec_patient", localStorage.getItem("ec_patient") || "1");
        if (location.pathname === "/casa") location.reload();
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
      var personId = EC.person.get();
      if (!personId) return Promise.reject(new Error("sin-persona"));
      if (!EC.pushSupported) return Promise.reject(new Error("no-soportado"));
      if (!EC.vapidPublicKey) return Promise.reject(new Error("sin-vapid"));
      // requestPermission va primero y sin await previo, para no perder el gesto en iOS.
      return Notification.requestPermission().then(function (perm) {
        if (perm !== "granted") throw new Error("permiso-" + perm);
        return navigator.serviceWorker.ready;
      }).then(function (reg) {
        return reg.pushManager.getSubscription().then(function (sub) {
          return sub || reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(EC.vapidPublicKey)
          });
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
    /** Re-sincroniza la suscripción si el permiso ya estaba dado (p. ej. cambió la persona). */
    resync: function () {
      if (EC.push.state() !== "activo") return;
      var personId = EC.person.get();
      if (!personId || !EC.vapidPublicKey) return;
      navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.getSubscription();
      }).then(function (sub) {
        if (!sub) return;
        var key = "ec_sub_" + personId + "_" + sub.endpoint.slice(-24);
        try { if (localStorage.getItem(key)) return; } catch (e) {}
        return fetch("/api/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ person_id: Number(personId), subscription: sub.toJSON() })
        }).then(function (r) { if (r.ok) try { localStorage.setItem(key, "1"); } catch (e) {} });
      }).catch(function () {});
    },
    errorText: function (err) {
      var m = (err && err.message) || "";
      if (m.indexOf("permiso-denied") === 0) return "Los avisos están bloqueados. Abrí Ajustes › Notificaciones › Entrecasa y activalos.";
      if (m === "sin-vapid") return "Falta configurar los avisos en el servidor (VAPID).";
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

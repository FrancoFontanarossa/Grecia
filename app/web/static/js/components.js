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

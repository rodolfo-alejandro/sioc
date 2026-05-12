(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  function checkedValues(containerId) {
    var container = byId(containerId);
    if (!container) return [];
    var values = [];
    container.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
      var value = String(cb.value || "").trim();
      if (value) values.push(value);
    });
    return values;
  }

  function updateButtonCount(buttonId, containerId, emptyLabel) {
    var button = byId(buttonId);
    if (!button) return;
    var total = checkedValues(containerId).length;
    button.textContent = total > 0 ? (total + " seleccionado(s)") : emptyLabel;
  }

  function filterList(containerId, query) {
    var container = byId(containerId);
    if (!container) return;
    var q = String(query || "").toLowerCase().trim();
    container.querySelectorAll(".form-check").forEach(function (row) {
      var text = (row.textContent || "").toLowerCase();
      row.style.display = (!q || text.indexOf(q) !== -1) ? "" : "none";
    });
  }

  function appendHiddenList(form, name, values) {
    values.forEach(function (value) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      input.setAttribute("data-ai-hidden", "1");
      form.appendChild(input);
    });
  }

  function todayIso() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }

  function januaryFirstIso() {
    var d = new Date();
    return d.getFullYear() + "-01-01";
  }

  function wirePresetPeriodo() {
    var preset = document.querySelector('select[name="preset_periodo"]');
    var desde = document.querySelector('input[name="fecha_desde"]');
    var hasta = document.querySelector('input[name="fecha_hasta"]');
    if (!preset || !desde || !hasta) return;
    preset.addEventListener("change", function () {
      if (this.value === "enero_hoy") {
        if (!desde.value) desde.value = januaryFirstIso();
        if (!hasta.value) hasta.value = todayIso();
      }
    });
  }

  function wireSubmit() {
    var form = byId("ai-form-filtros");
    if (!form) return;
    form.addEventListener("submit", function () {
      form.querySelectorAll('input[data-ai-hidden="1"]').forEach(function (el) { el.remove(); });
      appendHiddenList(form, "anio[]", checkedValues("ai-filtro-anios"));
      appendHiddenList(form, "zona[]", checkedValues("ai-filtro-zonas"));
      appendHiddenList(form, "sinar[]", checkedValues("ai-filtro-sinares"));
      appendHiddenList(form, "departamento_operativo[]", checkedValues("ai-filtro-depops"));
      appendHiddenList(form, "tipo_interv[]", checkedValues("ai-filtro-tipos"));
      appendHiddenList(form, "localidad[]", checkedValues("ai-filtro-localidades"));
      appendHiddenList(form, "barrio[]", checkedValues("ai-filtro-barrios"));
    });
  }

  function init() {
    var collapseEl = byId("ai-filtros-collapse");
    if (collapseEl) {
      var hasQuery = String(window.location.search || "").trim().length > 1;
      if (hasQuery && window.bootstrap && window.bootstrap.Collapse) {
        window.bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false }).show();
      }
    }

    document.querySelectorAll(".sabana-dd-search").forEach(function (input) {
      input.addEventListener("input", function () {
        var target = this.getAttribute("data-target");
        if (target) filterList(target, this.value);
      });
    });

    [
      { button: "dd-ai-anios", list: "ai-filtro-anios", empty: "Años..." },
      { button: "dd-ai-zonas", list: "ai-filtro-zonas", empty: "DINAR..." },
      { button: "dd-ai-sinares", list: "ai-filtro-sinares", empty: "SINAR..." },
      { button: "dd-ai-depops", list: "ai-filtro-depops", empty: "Dpto operativo..." },
      { button: "dd-ai-tipos", list: "ai-filtro-tipos", empty: "Tipos..." },
      { button: "dd-ai-localidades", list: "ai-filtro-localidades", empty: "Localidades..." },
      { button: "dd-ai-barrios", list: "ai-filtro-barrios", empty: "Barrios..." }
    ].forEach(function (item) {
      var container = byId(item.list);
      if (!container) return;
      container.addEventListener("change", function () {
        updateButtonCount(item.button, item.list, item.empty);
      });
      updateButtonCount(item.button, item.list, item.empty);
    });

    wireSubmit();
    wirePresetPeriodo();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

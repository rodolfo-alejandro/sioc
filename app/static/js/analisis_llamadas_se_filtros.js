(function () {
  "use strict";

  function getContainer(id) { return document.getElementById(id); }
  function getCheckedValues(containerId) {
    var c = getContainer(containerId);
    if (!c) return [];
    var out = [];
    c.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
      var v = String(cb.value || "").trim();
      if (v) out.push(v);
    });
    return out;
  }
  function updateDdCount(btnId, containerId, emptyLabel) {
    var btn = document.getElementById(btnId);
    if (!btn) return;
    var n = getCheckedValues(containerId).length;
    btn.textContent = n > 0 ? (n + " seleccionado(s)") : (emptyLabel || "Seleccionar...");
  }
  function filterList(containerId, query) {
    var c = getContainer(containerId);
    if (!c) return;
    var q = String(query || "").toLowerCase().trim();
    c.querySelectorAll(".form-check").forEach(function (row) {
      var txt = (row.textContent || "").toLowerCase();
      row.style.display = (!q || txt.indexOf(q) !== -1) ? "" : "none";
    });
  }
  function appendHiddenList(form, name, values) {
    values.forEach(function (v) {
      var i = document.createElement("input");
      i.type = "hidden";
      i.name = name;
      i.value = v;
      i.setAttribute("data-als-hidden", "1");
      form.appendChild(i);
    });
  }
  function wireSubmit() {
    var form = document.getElementById("als-form-filtros");
    if (!form) return;
    form.addEventListener("submit", function () {
      form.querySelectorAll('input[data-als-hidden="1"]').forEach(function (el) { el.remove(); });
      appendHiddenList(form, "alerta[]", getCheckedValues("als-filtro-alertas"));
      appendHiddenList(form, "jurisdiccion[]", getCheckedValues("als-filtro-juris"));
      appendHiddenList(form, "dep[]", getCheckedValues("als-filtro-deps"));
      appendHiddenList(form, "localidad[]", getCheckedValues("als-filtro-localidades"));
      appendHiddenList(form, "barrio[]", getCheckedValues("als-filtro-barrios"));
    });
  }
  function init() {
    var collapseEl = document.getElementById("als-filtros-collapse");
    if (collapseEl) {
      var hasQuery = String(window.location.search || "").trim().length > 1;
      if (hasQuery && window.bootstrap && window.bootstrap.Collapse) {
        window.bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false }).show();
      }
    }
    document.querySelectorAll(".sabana-dd-search").forEach(function (inp) {
      inp.addEventListener("input", function () {
        var target = this.getAttribute("data-target");
        if (target) filterList(target, this.value);
      });
    });
    [
      { btn: "dd-als-alertas", list: "als-filtro-alertas", empty: "Alertas..." },
      { btn: "dd-als-juris", list: "als-filtro-juris", empty: "Jurisdicciones..." },
      { btn: "dd-als-deps", list: "als-filtro-deps", empty: "Dependencias..." },
      { btn: "dd-als-localidades", list: "als-filtro-localidades", empty: "Localidades..." },
      { btn: "dd-als-barrios", list: "als-filtro-barrios", empty: "Barrios..." },
    ].forEach(function (d) {
      var c = getContainer(d.list);
      if (!c) return;
      c.addEventListener("change", function () { updateDdCount(d.btn, d.list, d.empty); });
      updateDdCount(d.btn, d.list, d.empty);
    });
    wireSubmit();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();


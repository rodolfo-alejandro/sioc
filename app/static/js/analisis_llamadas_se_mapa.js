(function () {
  "use strict";

  function parseMarkers() {
    var el = document.getElementById("als-map-markers");
    if (!el) return [];
    try { return JSON.parse(el.value || "[]"); } catch (e) { return []; }
  }
  function colorByAlert(a) {
    var s = String(a || "").toLowerCase();
    if (s.indexOf("venta") >= 0) return "#dc3545";
    if (s.indexOf("consumo") >= 0) return "#198754";
    if (s.indexOf("sospecha") >= 0) return "#ffc107";
    return "#0d6efd";
  }
  function popup(m) {
    var div = document.createElement("div");
    div.style.maxWidth = "360px";
    div.innerHTML =
      "<div><strong>Fecha:</strong> " + (m.fecha || "—") + "</div>" +
      "<div><strong>Alerta:</strong> " + (m.alerta || "—") + "</div>" +
      "<div><strong>Dependencia:</strong> " + (m.dep || "—") + "</div>" +
      "<div><strong>Barrio/Localidad:</strong> " + (m.barrio || "—") + " / " + (m.localidad || "—") + "</div>" +
      "<hr class='my-1'>" +
      "<div>" + (m.detalle || "") + "</div>" +
      "<div class='mt-2'><a class='btn btn-sm btn-primary' href='" + (m.detalle_url || "#") + "'>Ver detalle</a></div>";
    return div;
  }

  function init() {
    if (!window.L || !document.getElementById("als-map")) return;
    var rows = parseMarkers();
    var map = window.L.map("als-map").setView([-24.79, -65.41], 11);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap" }).addTo(map);

    var markersLayer = window.L.layerGroup().addTo(map);
    var heatPts = [];
    var bounds = [];
    rows.forEach(function (m) {
      if (typeof m.latitud !== "number" || typeof m.longitud !== "number") return;
      var c = colorByAlert(m.alerta);
      window.L.circleMarker([m.latitud, m.longitud], {
        radius: 6, color: c, fillColor: c, fillOpacity: 0.9, weight: 1,
      }).bindPopup(popup(m)).addTo(markersLayer);
      heatPts.push([m.latitud, m.longitud, 0.7]);
      bounds.push([m.latitud, m.longitud]);
    });
    var heatLayer = window.L.heatLayer ? window.L.heatLayer(heatPts, { radius: 25, blur: 18 }) : null;

    function setMode(mode) {
      if (mode === "heat" && heatLayer) {
        if (map.hasLayer(markersLayer)) map.removeLayer(markersLayer);
        if (!map.hasLayer(heatLayer)) heatLayer.addTo(map);
        return;
      }
      if (heatLayer && map.hasLayer(heatLayer)) map.removeLayer(heatLayer);
      if (!map.hasLayer(markersLayer)) markersLayer.addTo(map);
    }
    document.querySelectorAll('input[name="als-map-mode"]').forEach(function (rb) {
      rb.addEventListener("change", function () { setMode(this.value || "markers"); });
    });
    setMode("markers");
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30] });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();


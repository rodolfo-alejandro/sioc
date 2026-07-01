(function () {
  "use strict";

  function parseMarkers() {
    var el = document.getElementById("ai-map-markers");
    if (!el) return [];
    try { return JSON.parse(el.value || "[]"); } catch (e) { return []; }
  }

  function colorByTipo(tipo) {
    var s = String(tipo || "").toLowerCase();
    if (s.indexOf("allan") >= 0) return "#dc3545";
    if (s.indexOf("proced") >= 0) return "#0d6efd";
    return "#6c757d";
  }

  function popup(m) {
    var div = document.createElement("div");
    div.style.maxWidth = "360px";
    div.innerHTML =
      "<div><strong>Fecha:</strong> " + (m.fecha || "—") + (m.hora ? " " + m.hora : "") + "</div>" +
      "<div><strong>Tipo:</strong> " + (m.tipo || "—") + "</div>" +
      "<div><strong>Escala / Actividad:</strong> " + (m.escala || "—") + " / " + (m.actividad || "—") + "</div>" +
      "<div><strong>DINAR:</strong> " + (m.dinar || "—") + "</div>" +
      "<div><strong>SINAR:</strong> " + (m.sinar || "—") + "</div>" +
      "<div><strong>Localidad / Barrio:</strong> " + (m.localidad || "—") + " / " + (m.barrio || "—") + "</div>" +
      "<hr class='my-1'>" +
      "<div class='small'>Marihuana: " + (m.marihuana || 0) + " · Cocaína: " + (m.cocaina || 0) + " · Dosis: " + (m.dosis || 0) + "</div>" +
      "<div class='small'>Detenidos: " + (m.detenidos || 0) + "</div>" +
      "<div class='mt-2'><a class='btn btn-sm btn-primary' href='" + (m.detalle_url || "#") + "'>Ver detalle</a></div>";
    return div;
  }

  function init() {
    if (!window.L || !document.getElementById("ai-map")) return;
    var rows = parseMarkers();
    var map = window.L.map("ai-map").setView([-24.79, -65.41], 11);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);

    var markersLayer = window.L.layerGroup().addTo(map);
    var heatPts = [];
    var bounds = [];
    rows.forEach(function (m) {
      if (typeof m.latitud !== "number" || typeof m.longitud !== "number") return;
      var c = colorByTipo(m.tipo);
      window.L.circleMarker([m.latitud, m.longitud], {
        radius: 6, color: c, fillColor: c, fillOpacity: 0.9, weight: 1,
      }).bindPopup(popup(m)).addTo(markersLayer);
      heatPts.push([m.latitud, m.longitud, 0.7]);
      bounds.push([m.latitud, m.longitud]);
    });
    var heatLayer = window.L.heatLayer ? window.L.heatLayer(heatPts, { radius: 25, blur: 18 }) : null;

    function setMode(mode) {
      if (mode === "heat" && heatLayer) {
        map.removeLayer(markersLayer);
        if (!map.hasLayer(heatLayer)) heatLayer.addTo(map);
      } else {
        if (heatLayer && map.hasLayer(heatLayer)) map.removeLayer(heatLayer);
        if (!map.hasLayer(markersLayer)) markersLayer.addTo(map);
      }
    }

    document.querySelectorAll('input[name="ai-map-mode"]').forEach(function (el) {
      el.addEventListener("change", function () { setMode(el.value); });
    });

    if (bounds.length) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
    setTimeout(function () { map.invalidateSize(); }, 200);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

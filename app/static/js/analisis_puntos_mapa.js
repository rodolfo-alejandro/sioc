(function () {
  var map = L.map("ap-mapa").setView([-24.8, -65.4], 10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  var layerCeldas = L.layerGroup().addTo(map);
  var layerEventos = L.layerGroup().addTo(map);

  function fmtDt(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  }

  function renderEvents(rows) {
    var tbody = document.getElementById("ap-events-body");
    if (!rows || !rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-2">Sin eventos para el filtro actual.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.slice(0, 250).map(function (e) {
      return "<tr>"
        + "<td>" + fmtDt(e.event_dt) + "</td>"
        + "<td>" + (e.origin || "") + "</td>"
        + "<td>" + (e.target || "") + "</td>"
        + "<td>" + (e.event_type || "") + "</td>"
        + "<td>" + (e.duration_sec == null ? "" : e.duration_sec) + "</td>"
        + "<td>" + (e.cell_code || "") + "</td>"
        + "</tr>";
    }).join("");
  }

  function renderMap(data) {
    layerCeldas.clearLayers();
    layerEventos.clearLayers();

    var bounds = [];
    (data.celdas || []).forEach(function (c) {
      var latlng = [c.lat, c.lon];
      bounds.push(latlng);
      L.circle(latlng, {
        radius: c.radius_draw_m || 200,
        color: "#0d6efd",
        fillColor: "#0d6efd",
        fillOpacity: 0.12,
        weight: 1.5
      }).bindPopup(
        "<strong>" + (c.cell_code || "Celda") + "</strong><br>"
        + "Localidad: " + (c.locality || "-") + "<br>"
        + "Eventos: " + (c.event_count || 0) + "<br>"
        + "Radio completo: " + (c.radius_full_m || 0) + " m<br>"
        + "Radio aplicado: " + (c.radius_draw_m || 0) + " m"
      ).addTo(layerCeldas);

      L.circleMarker(latlng, {
        radius: 4,
        color: "#dc3545",
        fillColor: "#dc3545",
        fillOpacity: 0.9,
        weight: 1
      }).addTo(layerEventos);
    });

    if (bounds.length) {
      map.fitBounds(bounds, { padding: [20, 20] });
    }

    var s = data.summary || {};
    document.getElementById("ap-summary").textContent =
      "Eventos: " + (s.total_eventos || 0) + " | Celdas: " + (s.total_celdas || 0)
      + " | Fuente: " + (s.source_type || "ALL")
      + " | Distancia: " + (s.max_m == null ? "radio completo" : (s.max_m + " m"));
  }

  function loadData() {
    var source = document.getElementById("ap-source-type").value || "";
    var maxM = document.getElementById("ap-max-m").value || "";
    var url = "/analisis-puntos/api/casos/" + window.AP_CASO_ID + "/mapa-data?source_type=" + encodeURIComponent(source) + "&max_m=" + encodeURIComponent(maxM);
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok) throw new Error("No se pudo cargar mapa.");
        renderMap(data);
        renderEvents(data.eventos || []);
      })
      .catch(function (err) {
        console.error(err);
        document.getElementById("ap-summary").textContent = "Error al cargar datos del mapa.";
      });
  }

  document.getElementById("ap-btn-cargar").addEventListener("click", loadData);
  loadData();
})();

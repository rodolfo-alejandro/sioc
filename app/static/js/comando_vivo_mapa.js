(function () {
  "use strict";

  var cfg = window.CV_MAP || {};
  var map = L.map("cv-map").setView([-24.79, -65.41], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);

  var markers = {};
  var fittedOnce = false;
  var selectedId = null;
  var trazaLayer = null;

  function estadoDot(estado) {
    if (estado === "panico") return "cv-dot-panico";
    if (estado === "offline") return "cv-dot-offline";
    return "cv-dot-online";
  }

  function iconFor(p) {
    var cls = "cv-marker-label" + (p.estado === "panico" ? " cv-marker-panico" : "");
    return L.divIcon({
      className: "",
      html: '<div class="' + cls + '">' + escapeHtml(p.alias) + "</div>",
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    });
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function ago(iso) {
    if (!iso) return "sin dato";
    var t = Date.parse(iso);
    if (!t) return "—";
    var sec = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (sec < 60) return sec + " s";
    if (sec < 3600) return Math.floor(sec / 60) + " min";
    return Math.floor(sec / 3600) + " h";
  }

  function renderLista(participantes) {
    var ul = document.getElementById("cv-lista");
    var count = document.getElementById("cv-count");
    var alertas = document.getElementById("cv-alertas");
    if (!ul) return;
    count.textContent = String(participantes.length);

    var panicos = participantes.filter(function (p) {
      return p.estado === "panico";
    });
    alertas.innerHTML = panicos
      .map(function (p) {
        return (
          '<div class="cv-alerta-panico">🚨 PÁNICO: ' +
          escapeHtml(p.alias) +
          "</div>"
        );
      })
      .join("");

    ul.innerHTML = participantes
      .map(function (p) {
        var bat =
          p.battery != null ? " · bat " + Math.round(p.battery) + "%" : "";
        return (
          '<li class="list-group-item list-group-item-action py-2"' +
          ' data-id="' +
          p.id +
          '" style="cursor:pointer">' +
          '<span class="cv-dot ' +
          estadoDot(p.estado) +
          '"></span>' +
          "<strong>" +
          escapeHtml(p.alias) +
          "</strong>" +
          '<div class="small text-muted">' +
          escapeHtml(p.estado) +
          " · hace " +
          ago(p.last_seen_at) +
          bat +
          "</div></li>"
        );
      })
      .join("");

    ul.querySelectorAll("[data-id]").forEach(function (el) {
      el.addEventListener("click", function () {
        var id = parseInt(el.getAttribute("data-id"), 10);
        focusParticipante(id, participantes);
        loadTraza(id);
      });
    });
  }

  function focusParticipante(id, participantes) {
    selectedId = id;
    var p = participantes.find(function (x) {
      return x.id === id;
    });
    if (p && p.lat != null && p.lon != null) {
      map.setView([p.lat, p.lon], Math.max(map.getZoom(), 16));
      if (markers[id]) markers[id].openPopup();
    }
  }

  function loadTraza(participanteId) {
    var tpl = cfg.trazaUrlTpl || "";
    var url = tpl.replace(/\/0$/, "/" + participanteId);
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (trazaLayer) {
          map.removeLayer(trazaLayer);
          trazaLayer = null;
        }
        var pts = (data.puntos || [])
          .filter(function (x) {
            return x.lat != null && x.lon != null;
          })
          .map(function (x) {
            return [x.lat, x.lon];
          });
        if (pts.length >= 2) {
          trazaLayer = L.polyline(pts, { color: "#0d6efd", weight: 3, opacity: 0.75 }).addTo(map);
          map.fitBounds(trazaLayer.getBounds(), { padding: [30, 30], maxZoom: 17 });
        }
      })
      .catch(function () {});
  }

  function updateMarkers(participantes) {
    var seen = {};
    var bounds = [];
    participantes.forEach(function (p) {
      if (p.lat == null || p.lon == null) return;
      seen[p.id] = true;
      bounds.push([p.lat, p.lon]);
      var html =
        "<strong>" +
        escapeHtml(p.alias) +
        "</strong><br>" +
        escapeHtml(p.estado) +
        "<br>hace " +
        ago(p.last_seen_at);
      if (markers[p.id]) {
        markers[p.id].setLatLng([p.lat, p.lon]);
        markers[p.id].setIcon(iconFor(p));
        markers[p.id].setPopupContent(html);
      } else {
        markers[p.id] = L.marker([p.lat, p.lon], { icon: iconFor(p) })
          .addTo(map)
          .bindPopup(html);
      }
    });
    Object.keys(markers).forEach(function (id) {
      if (!seen[id]) {
        map.removeLayer(markers[id]);
        delete markers[id];
      }
    });
    if (!fittedOnce && bounds.length) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
      fittedOnce = true;
    }
  }

  function poll() {
    if (!cfg.positionsUrl) return;
    fetch(cfg.positionsUrl, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var list = data.participantes || [];
        renderLista(list);
        updateMarkers(list);
      })
      .catch(function () {});
  }

  poll();
  if (cfg.activo) {
    setInterval(poll, 4000);
  }
})();

(function () {
    'use strict';

    function parseMarkers() {
        var el = document.getElementById('ad-map-markers');
        if (!el) return [];
        try {
            return JSON.parse(el.value || '[]');
        } catch (e) {
            return [];
        }
    }

    function stateColor(state) {
        var s = String(state || '').toLowerCase();
        if (s.indexOf('desestim') >= 0) return '#dc3545';
        if (s.indexOf('apert') >= 0) return '#198754';
        if (s.indexOf('invest') >= 0) return '#0d6efd';
        return '#6c757d';
    }

    function buildPopup(m) {
        var div = document.createElement('div');
        div.className = 'ad-popup-relato';
        div.innerHTML =
            '<div><strong>Actuación:</strong> ' + (m.nro_actuacion || '—') + '</div>' +
            '<div><strong>Fecha:</strong> ' + (m.fecha_denuncia || '—') + '</div>' +
            '<div><strong>Barrio/Loc:</strong> ' + (m.barrio || '—') + ' / ' + (m.localidad || '—') + '</div>' +
            '<div><strong>Estado:</strong> ' + (m.causa_estado || '—') + '</div>' +
            '<div><strong>Dependencia:</strong> ' + (m.dependencia || '—') + '</div>' +
            '<hr class="my-1">' +
            '<div>' + (m.relato_corto || '') + '</div>' +
            '<div class="mt-2"><a class="btn btn-sm btn-primary" href="' + (m.detalle_url || '#') + '">Ver detalle</a></div>';
        return div;
    }

    function init() {
        var container = document.getElementById('ad-map');
        if (!container || !window.L) return;
        var markers = parseMarkers();
        var map = window.L.map('ad-map').setView([-26.83, -65.21], 11);
        window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap'
        }).addTo(map);

        var bounds = [];
        markers.forEach(function (m) {
            if (typeof m.latitud !== 'number' || typeof m.longitud !== 'number') return;
            var color = stateColor(m.causa_estado);
            var mk = window.L.circleMarker([m.latitud, m.longitud], {
                radius: 6,
                color: color,
                fillColor: color,
                fillOpacity: 0.9,
                weight: 1
            });
            mk.bindPopup(buildPopup(m));
            mk.addTo(map);
            bounds.push([m.latitud, m.longitud]);
        });
        if (bounds.length) {
            map.fitBounds(bounds, { padding: [30, 30] });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

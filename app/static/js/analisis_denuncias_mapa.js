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

    function normalizeText(v) {
        return String(v || '').toLowerCase()
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
            .trim();
    }

    function classifyMarker(m) {
        var estado = normalizeText(m.causa_estado);
        var relato = normalizeText(m.relato_corto);
        var investigados = normalizeText(m.investigados);
        var hasPedido = String(m.fecha_sol_allanamiento || '').trim().length > 0;
        var hasDesestimada = String(m.fecha_desestimada || '').trim().length > 0 || estado.indexOf('desestim') >= 0;

        if (hasPedido) return { key: 'pedido_allanamiento', label: 'Con pedido de allanamiento', color: '#6f42c1' };
        if (hasDesestimada) return { key: 'desestimada', label: 'Desestimada', color: '#6c757d' };
        if (estado.indexOf('allan') >= 0 || relato.indexOf('allan') >= 0) return { key: 'allanada', label: 'Allanadas', color: '#198754' };
        if (estado.indexOf('vincul') >= 0 || investigados.length > 0) return { key: 'vinculada', label: 'Vinculadas', color: '#ffc107' };
        if (estado.indexOf('invest') >= 0 || estado.indexOf('etapa') >= 0 || estado.indexOf('tramite') >= 0) return { key: 'investigativa', label: 'Etapa investigativa', color: '#0d6efd' };
        return { key: 'investigativa', label: 'Etapa investigativa', color: '#0d6efd' };
    }

    function buildPopup(m) {
        var div = document.createElement('div');
        div.className = 'ad-popup-relato';
        div.innerHTML =
            '<div><strong>Actuación:</strong> ' + (m.nro_actuacion || '—') + '</div>' +
            '<div><strong>Fecha:</strong> ' + (m.fecha_denuncia || '—') + '</div>' +
            '<div><strong>Barrio/Loc:</strong> ' + (m.barrio || '—') + ' / ' + (m.localidad || '—') + '</div>' +
            '<div><strong>Estado:</strong> ' + (m.causa_estado || '—') + '</div>' +
            '<div><strong>Clasificación mapa:</strong> ' + (m._ad_class_label || '—') + '</div>' +
            '<div><strong>Dependencia:</strong> ' + (m.dependencia || '—') + '</div>' +
            '<hr class="my-1">' +
            '<div>' + (m.relato_corto || '') + '</div>' +
            '<div class="mt-2"><a class="btn btn-sm btn-primary" href="' + (m.detalle_url || '#') + '">Ver detalle</a></div>';
        return div;
    }

    function init() {
        var container = document.getElementById('ad-map');
        if (!container || !window.L) return;
        var markers = parseMarkers().map(function (m) {
            var cls = classifyMarker(m);
            m._ad_class = cls.key;
            m._ad_class_label = cls.label;
            m._ad_color = cls.color;
            return m;
        });
        var map = window.L.map('ad-map').setView([-26.83, -65.21], 11);
        window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap'
        }).addTo(map);

        var markersLayer = window.L.layerGroup().addTo(map);
        var heatPoints = [];
        var bounds = [];
        markers.forEach(function (m) {
            if (typeof m.latitud !== 'number' || typeof m.longitud !== 'number') return;
            var color = m._ad_color || '#0d6efd';
            var mk = window.L.circleMarker([m.latitud, m.longitud], {
                radius: 6,
                color: color,
                fillColor: color,
                fillOpacity: 0.9,
                weight: 1
            });
            mk.bindPopup(buildPopup(m));
            mk.addTo(markersLayer);
            heatPoints.push([m.latitud, m.longitud, 0.7]);
            bounds.push([m.latitud, m.longitud]);
        });
        var heatLayer = null;
        if (window.L.heatLayer) {
            heatLayer = window.L.heatLayer(heatPoints, {
                radius: 24,
                blur: 18,
                maxZoom: 17,
                minOpacity: 0.35
            });
        }

        function setMode(mode) {
            if (mode === 'heat' && heatLayer) {
                if (map.hasLayer(markersLayer)) map.removeLayer(markersLayer);
                if (!map.hasLayer(heatLayer)) heatLayer.addTo(map);
                return;
            }
            if (heatLayer && map.hasLayer(heatLayer)) map.removeLayer(heatLayer);
            if (!map.hasLayer(markersLayer)) markersLayer.addTo(map);
        }

        document.querySelectorAll('input[name="ad-map-mode"]').forEach(function (rb) {
            rb.addEventListener('change', function () {
                setMode(this.value || 'markers');
            });
        });

        setMode('markers');
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

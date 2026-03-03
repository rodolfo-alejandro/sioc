(function () {
    'use strict';

    var map = null;
    var markersLayer = null;
    var explosionLayer = null;
    var rutaLayer = null;
    var polyline = null;
    var rutaPuntos = [];
    var trazadoLayer = null;
    var trazadoPolylineBase = null;   // línea completa (suave)
    var trazadoPolylineLive = null;   // línea que se va trazando (roja)
    var trazadoPuntos = [];
    var trazadoMarkerAuto = null;
    var trazadoAnimacionFrameId = null;
    var trazadoAnimacionTimeout = null;
    var trazadoIsPlaying = false;
    var trazadoStartMs = 0;
    var trazadoPauseAccumMs = 0;
    var trazadoLastDetailIdx = -1;
    var trazadoCache = new Map(); // key: "tipo|impacto_id" -> impacto payload (con _ord)
    var azimuthLayer = null;
    var animacionInterval = null;
    var animacionIndice = 0;
    var markerAuto = null;
    var baseUrl = document.body.getAttribute('data-sabana-base') || '';
    var puntosConImpactos = [];
    var lastRequestToken = 0;
    var lastAppliedParams = null;
    var lastPuntosCeldas = [];
    var ordenMap = {}; // key: "tipo|celda_id" -> {ord_min, ord_max} (orden por celda física)
    var ordenImpactoMap = {}; // key: "tipo|impacto_id" -> ord
    var ordenImpactoByOrd = {}; // ord -> {tipo, impacto_id}
    var ordenImpactoTotal = null;
    var ordenVisibleMax = 100; // para modo progresivo (Orden)
    var lastAutoFocusOrdenKey = null;
    var selectedNumeros = new Set();
    var selectedImeis = new Set();
    var numerosDebounceTimer = null;
    var numerosQueryToken = 0;
    var imeisDebounceTimer = null;
    var imeisQueryToken = 0;
    var autoApplyTimer = null;
    var resizeTimer = null;
    var spiderKey = null;
    var currentPanelMode = null; // 'list' | 'detail'
    var currentPanelPunto = null;
    var currentPanelImpactos = [];
    var currentPanelImpacto = null;

    // Colores por entidad (auto)
    var colorMode = null; // 'numero' | 'imei' | 'sujeto' | 'carga' | null
    var colorMap = {}; // key -> {bg, fg}
    var legendItems = []; // [{key,label,bg,fg}]
    var palette = ['#0d6efd', '#198754', '#dc3545', '#fd7e14', '#6f42c1', '#20c997', '#0dcaf0', '#d63384', '#6610f2', '#6c757d', '#343a40', '#ffc107'];

    // Resaltar punto/impacto seleccionado
    // Clave incluye `tipo` para evitar colisiones entre tablas (GPRS y VOZ pueden compartir IDs numéricos).
    var impactMarkerMap = new Map(); // "tipo|impacto_id" -> {latlng:L.LatLng, marker:L.Marker}
    var celdaMarkerMap = new Map(); // "tipo|celda_norm" -> L.Marker (pin azul)
    var lastSelectedCeldaKey = null;
    var highlightCircle = null;
    var highlightMarker = null;

    function normCeldaId(v) {
        try {
            if (v == null) return '';
            return String(v).trim().toUpperCase();
        } catch (e) {
            return '';
        }
    }

    function scheduleAutoApply(ms) {
        if (autoApplyTimer) clearTimeout(autoApplyTimer);
        autoApplyTimer = setTimeout(function () {
            try { aplicarFiltros(); } catch (e) {}
        }, ms == null ? 600 : ms);
    }

    function refreshMapSize(delayMs) {
        if (!map) return;
        var d = delayMs == null ? 120 : delayMs;
        setTimeout(function () {
            try { map.invalidateSize(true); } catch (e) {}
        }, d);
    }

    function isNativeFullscreen() {
        return !!(document.fullscreenElement);
    }

    function setExpandBtnState(btn, expanded) {
        if (!btn) return;
        var icon = btn.querySelector('i');
        btn.title = expanded ? 'Salir de pantalla completa' : 'Pantalla completa';
        btn.setAttribute('aria-label', btn.title);
        if (icon) icon.className = expanded ? 'bi bi-fullscreen-exit' : 'bi bi-arrows-fullscreen';
    }

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content');
        var input = document.querySelector('input[name="csrf_token"]');
        return input ? input.value : '';
    }

    function fetchFiltros() {
        // Cargas: por defecto el backend limita; pedimos más para que el selector no quede “cortado” en 500.
        var q = new URLSearchParams();
        q.append('cargas_limit', '2000');
        return fetch(baseUrl + '/sabana-llamadas/api/filtros?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); });
    }

    function fetchImpactos(params) {
        var baseQ = new URLSearchParams();
        (params.sujeto_ids || []).forEach(function (id) { baseQ.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { baseQ.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { baseQ.append('tipos[]', t); });
        (params.provincias || []).forEach(function (p) { baseQ.append('provincias[]', p); });
        (params.localidades || []).forEach(function (l) { baseQ.append('localidades[]', l); });
        if (params.fecha_desde) baseQ.append('fecha_desde', params.fecha_desde);
        if (params.fecha_hasta) baseQ.append('fecha_hasta', params.fecha_hasta);
        if (params.hora_desde) baseQ.append('hora_desde', params.hora_desde);
        if (params.hora_hasta) baseQ.append('hora_hasta', params.hora_hasta);
        (params.numeros || []).forEach(function (n) { baseQ.append('numeros[]', n); });
        (params.imeis || []).forEach(function (i) { baseQ.append('imeis[]', i); });

        // Pedir todas las celdas y paginar para no saturar una sola respuesta.
        baseQ.append('all', '1');
        // Resumen: no traer lista completa de impactos por celda (se trae al click).
        baseQ.append('resumen', '1');
        var pageLimit = 1000;

        function fetchPage(offset, acc) {
            acc = acc || [];
            var q = new URLSearchParams(baseQ.toString());
            q.append('offset', String(offset || 0));
            q.append('limit', String(pageLimit));
            return fetch(baseUrl + '/sabana-llamadas/api/mapa/impactos?' + q.toString(), {
                method: 'GET',
                headers: { 'Accept': 'application/json' }
            }).then(function (r) {
                var hasMore = (r.headers.get('X-Has-More') || '') === '1';
                var nextOffset = r.headers.get('X-Next-Offset');
                return r.json().then(function (data) {
                    var items = Array.isArray(data) ? data : [];
                    var merged = acc.concat(items);
                    if (hasMore && nextOffset != null) {
                        var no = parseInt(nextOffset, 10);
                        if (!isNaN(no) && no >= 0) return fetchPage(no, merged);
                    }
                    return merged;
                });
            });
        }

        return fetchPage(0, []);
    }

    function fetchOrdenCeldas(params) {
        var q = new URLSearchParams();
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (params.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (params.fecha_desde) q.append('fecha_desde', params.fecha_desde);
        if (params.fecha_hasta) q.append('fecha_hasta', params.fecha_hasta);
        if (params.hora_desde) q.append('hora_desde', params.hora_desde);
        if (params.hora_hasta) q.append('hora_hasta', params.hora_hasta);
        (params.numeros || []).forEach(function (n) { q.append('numeros[]', n); });
        (params.imeis || []).forEach(function (i) { q.append('imeis[]', i); });
        // Modo progresivo: pedir solo los primeros N órdenes para no bajar todo
        try {
            if (isOrdenEnabled && isOrdenEnabled() && isOrdenProgressiveEnabled && isOrdenProgressiveEnabled()) {
                q.append('max_ord', String(ordenVisibleMax || 100));
            }
        } catch (e) {}
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/orden-celdas-celda?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); }).then(function (items) {
            var map = {};
            (Array.isArray(items) ? items : []).forEach(function (it) {
                var key = [it.tipo, normCeldaId(it.celda_id)].join('|');
                map[key] = { ord_min: it.ord_min, ord_max: it.ord_max };
            });
            ordenMap = map;
            return map;
        });
    }

    function fetchOrdenImpactos(params) {
        var q = new URLSearchParams();
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (params.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (params.fecha_desde) q.append('fecha_desde', params.fecha_desde);
        if (params.fecha_hasta) q.append('fecha_hasta', params.fecha_hasta);
        if (params.hora_desde) q.append('hora_desde', params.hora_desde);
        if (params.hora_hasta) q.append('hora_hasta', params.hora_hasta);
        (params.numeros || []).forEach(function (n) { q.append('numeros[]', n); });
        (params.imeis || []).forEach(function (i) { q.append('imeis[]', i); });
        // Orden global NO debe depender de coordenadas (investigación cronológica real)
        // Modo progresivo: pedir solo los primeros N órdenes para no bajar todo
        try {
            if (isOrdenEnabled && isOrdenEnabled() && isOrdenProgressiveEnabled && isOrdenProgressiveEnabled()) {
                q.append('max_ord', String(ordenVisibleMax || 100));
            }
        } catch (e) {}
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/orden-impactos?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) {
            var total = r.headers.get('X-Total-Impactos');
            ordenImpactoTotal = total ? parseInt(total, 10) : null;
            return r.json();
        }).then(function (items) {
            var map = {};
            var byOrd = {};
            (Array.isArray(items) ? items : []).forEach(function (it) {
                var key = [it.tipo, it.impacto_id].join('|');
                map[key] = it.ord;
                byOrd[String(it.ord)] = { tipo: it.tipo, impacto_id: it.impacto_id };
            });
            ordenImpactoMap = map;
            ordenImpactoByOrd = byOrd;
            return map;
        });
    }

    function gotoOrden(n) {
        var ord = parseInt(String(n || '').trim(), 10);
        if (isNaN(ord) || ord < 1) return Promise.resolve();
        var ref = ordenImpactoByOrd ? ordenImpactoByOrd[String(ord)] : null;
        if (!ref && lastAppliedParams) {
            // Si todavía no está cargado el mapa de orden, cargarlo y reintentar
            return fetchOrdenImpactos(lastAppliedParams).then(function () { return gotoOrden(ord); }).catch(function () { });
        }
        if (!ref) return Promise.resolve();

        // Modo progresivo: si navego más allá del visibleMax, ampliar lo visible sin recargar todo
        if (isOrdenEnabled() && isOrdenProgressiveEnabled() && ord > ordenVisibleMax) {
            setOrdenVisibleMax(ord);
            try { addMarkers(lastPuntosCeldas || [], { keepPanel: true, keepView: true }); } catch (e) {}
        }

        return fetch(baseUrl + '/sabana-llamadas/api/mapa/impacto-loc?tipo=' + encodeURIComponent(ref.tipo) + '&impacto_id=' + encodeURIComponent(String(ref.impacto_id)), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (!data || !data.impacto) return;
            var imp = data.impacto;
            imp._ord = ord;
            imp._has_coords = (data.has_coords === true) || (data.lat != null && data.lng != null);
            imp._coords_source = data.coords_source || null;
            imp._coords_carga_id = (data.coords_carga_id != null) ? data.coords_carga_id : null;
            // Defensa: si el backend no envía coords_source pero sí coords_carga_id, inferir “otra carga”
            try {
                if (imp._has_coords && !imp._coords_source && imp._coords_carga_id != null && data.carga_id != null) {
                    if (String(imp._coords_carga_id) !== String(data.carga_id)) {
                        imp._coords_source = 'other_carga';
                    } else {
                        imp._coords_source = 'same_carga';
                    }
                }
            } catch (eInf) {}
            // Defensa: si hay coords pero no sabemos la fuente, asumir “misma carga”
            if (imp._has_coords && !imp._coords_source) imp._coords_source = 'same_carga';
            if (!imp._has_coords) {
                imp._geo_missing = {
                    tipo: data.tipo || ref.tipo,
                    carga_id: data.carga_id || null,
                    celda_id: data.celda_id || (imp.tipo === 'gprs' ? (imp.celda || null) : (imp.celda_id || null))
                };
            }
            var ll = (data.lat != null && data.lng != null) ? L.latLng(data.lat, data.lng) : null;

            // Si hay coords y datos de celda, setear contexto para botón "Volver" pero SIN bloquear con la carga de todos los impactos
            if (ll && data.celda_id && data.carga_id && data.tipo) {
                currentPanelPunto = {
                    tipo: data.tipo,
                    carga_id: data.carga_id,
                    sujeto_id: data.sujeto_id || null,
                    celda_id: data.celda_id,
                    celda_direccion: data.celda_direccion || data.celda_id,
                    lat: ll.lat,
                    lng: ll.lng,
                    _impactosLoaded: false
                };
                currentPanelImpactos = [];
            }

            // Navegación rápida: mostrar detalle + resaltado ya (respuesta inmediata)
            try { if (ll) map.setView([ll.lat, ll.lng], Math.max(map.getZoom(), 18)); } catch (e) {}
            // Azimut y radio para este impacto (si vienen del backend)
            try {
                if (data.azimuth != null) imp._azimuth = data.azimuth;
                if (data.rad_cob_km != null) imp._rad_cob_km = data.rad_cob_km;
                if (data.a_horiz != null) imp._a_horiz = data.a_horiz;
                if (data.a_vert != null) imp._a_vert = data.a_vert;
            } catch (eAz) {}
            openPanelDetalle(imp);
            if (ll) highlightImpact(imp, ll);
            try {
                if (ll && data && data.tipo && data.carga_id != null && data.celda_id) {
                    updateSelectedCeldaMarker({
                        tipo: data.tipo,
                        carga_id: data.carga_id,
                        celda_id: data.celda_id
                    }, ord);
                }
            } catch (eSelPin) {}

            // Fallback: abrir solo detalle (puede no tener coords)
            // (si no hay coords, igual se ve el detalle)
        });
    }

    function focusOrden(n) {
        // Enfoca (pan/zoom + resaltado) sin abrir panel ni cargar lista.
        var ord = parseInt(String(n || '').trim(), 10);
        if (isNaN(ord) || ord < 1) return Promise.resolve();
        var ref = ordenImpactoByOrd ? ordenImpactoByOrd[String(ord)] : null;
        if (!ref && lastAppliedParams) {
            return fetchOrdenImpactos(lastAppliedParams).then(function () { return focusOrden(ord); }).catch(function () { });
        }
        if (!ref) return Promise.resolve();
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/impacto-loc?tipo=' + encodeURIComponent(ref.tipo) + '&impacto_id=' + encodeURIComponent(String(ref.impacto_id)), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (!data || !data.impacto) return;
            var imp = data.impacto;
            imp._ord = ord;
            imp._has_coords = (data.has_coords === true) || (data.lat != null && data.lng != null);
            imp._coords_source = data.coords_source || null;
            imp._coords_carga_id = (data.coords_carga_id != null) ? data.coords_carga_id : null;
            try {
                if (imp._has_coords && !imp._coords_source && imp._coords_carga_id != null && data.carga_id != null) {
                    if (String(imp._coords_carga_id) !== String(data.carga_id)) imp._coords_source = 'other_carga';
                    else imp._coords_source = 'same_carga';
                }
            } catch (eInf2) {}
            if (imp._has_coords && !imp._coords_source) imp._coords_source = 'same_carga';
            if (!imp._has_coords) {
                imp._geo_missing = {
                    tipo: data.tipo || ref.tipo,
                    carga_id: data.carga_id || null,
                    celda_id: data.celda_id || (imp.tipo === 'gprs' ? (imp.celda || null) : (imp.celda_id || null))
                };
            }
            var ll = (data.lat != null && data.lng != null) ? L.latLng(data.lat, data.lng) : null;
            if (ll) {
                try { map.setView([ll.lat, ll.lng], Math.max(map.getZoom(), 14)); } catch (e) {}
                highlightImpact(imp, ll);
            } else {
                // Sin coords: igual dejamos el panel si estaba abierto; aquí solo focus, no hacemos nada.
            }
        });
    }

    function _coordKey(lat, lng) {
        var la = (lat == null) ? '' : String(lat).trim();
        var lo = (lng == null) ? '' : String(lng).trim();
        if (!la || !lo) return null;
        return la + '|' + lo;
    }

    function fetchCeldaImpactos(punto, params) {
        if (!punto || !punto.celda_id || !punto.carga_id || !punto.tipo) return Promise.resolve([]);
        var q = new URLSearchParams();
        q.append('tipo', String(punto.tipo));
        q.append('carga_id', String(punto.carga_id));
        q.append('celda_id', String(punto.celda_id));
        // Si Orden está activo, pedimos al backend que adjunte el #orden global real.
        if (isOrdenEnabled && isOrdenEnabled()) q.append('with_ord', '1');
        // Re-aplicar los mismos filtros avanzados que están activos en el mapa
        if (params) {
            (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
            (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
            (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
            if (params.fecha_desde) q.append('fecha_desde', params.fecha_desde);
            if (params.fecha_hasta) q.append('fecha_hasta', params.fecha_hasta);
            if (params.hora_desde) q.append('hora_desde', params.hora_desde);
            if (params.hora_hasta) q.append('hora_hasta', params.hora_hasta);
            (params.numeros || []).forEach(function (n) { q.append('numeros[]', n); });
            (params.imeis || []).forEach(function (i) { q.append('imeis[]', i); });
            (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
            (params.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        }
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/celda-impactos?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); }).then(function (items) {
            items = Array.isArray(items) ? items : [];
            // Etiquetar con el "punto" (celda técnica) que originó la consulta.
            // Esto ayuda a depurar casos donde varias celdas comparten dirección o coordenadas.
            try {
                items.forEach(function (imp) {
                    if (!imp) return;
                    imp._punto_tipo = punto.tipo;
                    imp._punto_carga_id = punto.carga_id;
                    imp._punto_celda_id = punto.celda_id;
                    imp._punto_lat = punto.lat;
                    imp._punto_lng = punto.lng;
                });
            } catch (eTag) {}
            // Fallback: si existe el mapa global de orden ya cargado, usarlo
            if (ordenImpactoMap && items && Array.isArray(items)) {
                items.forEach(function (imp) {
                    if (!imp || imp.id == null) return;
                    var k = [punto.tipo, imp.id].join('|');
                    if (ordenImpactoMap[k] != null) imp._ord = ordenImpactoMap[k];
                });
            }
            return items;
        });
    }

    function fetchRuta(params) {
        var q = new URLSearchParams();
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (params.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (params.fecha_desde) q.append('fecha_desde', params.fecha_desde);
        if (params.fecha_hasta) q.append('fecha_hasta', params.fecha_hasta);
        if (params.hora_desde) q.append('hora_desde', params.hora_desde);
        if (params.hora_hasta) q.append('hora_hasta', params.hora_hasta);
        (params.numeros || []).forEach(function (n) { q.append('numeros[]', n); });
        (params.imeis || []).forEach(function (i) { q.append('imeis[]', i); });
        // Pedir el recorrido completo (sin muestreo a 5000) para la vista Ruta.
        q.append('all', '1');
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/ruta?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) {
            var total = r.headers.get('X-Total-Puntos');
            var mostrando = r.headers.get('X-Mostrando');
            return r.json().then(function (puntos) {
                return { puntos: puntos, total: total ? parseInt(total, 10) : null, mostrando: mostrando ? parseInt(mostrando, 10) : null };
            });
        });
    }

    function fetchTrazado(params) {
        // Trazado para vista “Celdas”. Si Orden+Progresivo está activo, respeta hasta #N.
        var q = new URLSearchParams();
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (params.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (params.fecha_desde) q.append('fecha_desde', params.fecha_desde);
        if (params.fecha_hasta) q.append('fecha_hasta', params.fecha_hasta);
        if (params.hora_desde) q.append('hora_desde', params.hora_desde);
        if (params.hora_hasta) q.append('hora_hasta', params.hora_hasta);
        (params.numeros || []).forEach(function (n) { q.append('numeros[]', n); });
        (params.imeis || []).forEach(function (i) { q.append('imeis[]', i); });
        try {
            if (isOrdenEnabled && isOrdenEnabled() && isOrdenProgressiveEnabled && isOrdenProgressiveEnabled()) {
                q.append('max_ord', String(ordenVisibleMax || 100));
            }
        } catch (e) {}
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/trazado?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) {
            var total = r.headers.get('X-Total-Puntos');
            var mostrando = r.headers.get('X-Mostrando');
            return r.json().then(function (puntos) {
                return { puntos: puntos, total: total ? parseInt(total, 10) : null, mostrando: mostrando ? parseInt(mostrando, 10) : null };
            });
        });
    }

    function renderCheckboxes(containerId, items, labelKey, valueKey) {
        valueKey = valueKey || 'id';
        labelKey = labelKey || 'nombre';
        var container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';
        items.forEach(function (item) {
            var id = 'cb-' + containerId + '-' + item[valueKey];
            var div = document.createElement('div');
            div.className = 'form-check';
            div.innerHTML = '<input class="form-check-input" type="checkbox" id="' + id + '" value="' + item[valueKey] + '">' +
                '<label class="form-check-label" for="' + id + '">' + (item[labelKey] || item[valueKey]) + '</label>';
            container.appendChild(div);
        });
    }

    function getSelectedIds(containerId) {
        var container = document.getElementById(containerId);
        if (!container) return [];
        var inputs = container.querySelectorAll('input[type="checkbox"]:checked');
        return Array.prototype.map.call(inputs, function (el) { return parseInt(el.value, 10); }).filter(Boolean);
    }

    function getSelectedTipos() {
        var g = document.getElementById('tipo-gprs');
        var v = document.getElementById('tipo-voz');
        var out = [];
        if (g && g.checked) out.push('gprs');
        if (v && v.checked) out.push('voz');
        return out;
    }

    function getValue(id) {
        var el = document.getElementById(id);
        if (!el) return '';
        return (el.value || '').trim();
    }

    function getSelectedNumeros() {
        return Array.from(selectedNumeros.values());
    }

    function getSelectedImeis() {
        return Array.from(selectedImeis.values());
    }

    function getSelectedStrings(containerId) {
        var container = document.getElementById(containerId);
        if (!container) return [];
        var inputs = container.querySelectorAll('input[type="checkbox"]:checked');
        return Array.prototype.map.call(inputs, function (el) { return (el.value || '').trim(); }).filter(Boolean);
    }

    function updateDdButtonText(btnId, text) {
        var btn = document.getElementById(btnId);
        if (!btn) return;
        btn.textContent = text;
    }

    function updateDdCount(btnId, containerId, emptyLabel) {
        var container = document.getElementById(containerId);
        if (!container) return;
        var n = container.querySelectorAll('input[type="checkbox"]:checked').length;
        updateDdButtonText(btnId, n > 0 ? (n + ' seleccionado(s)') : (emptyLabel || 'Seleccionar…'));
    }

    function updateDdTipos() {
        var tipos = getSelectedTipos();
        updateDdButtonText('dd-tipos', tipos.length ? ('Tipo: ' + tipos.join(', ')) : 'Seleccionar…');
    }

    function filterCheckboxList(containerId, query) {
        var container = document.getElementById(containerId);
        if (!container) return;
        var q = (query || '').toLowerCase().trim();
        var rows = container.querySelectorAll('.form-check');
        rows.forEach(function (row) {
            var txt = (row.textContent || '').toLowerCase();
            row.style.display = (!q || txt.indexOf(q) !== -1) ? '' : 'none';
        });
    }

    function initDropdownSearch() {
        document.querySelectorAll('.sabana-dd-search').forEach(function (inp) {
            inp.addEventListener('input', function () {
                var target = this.getAttribute('data-target');
                filterCheckboxList(target, this.value);
            });
        });
    }

    function fetchNumeros(qTxt, params) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (params.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (params.fecha_desde) q.append('fecha_desde', params.fecha_desde);
        if (params.fecha_hasta) q.append('fecha_hasta', params.fecha_hasta);
        if (params.hora_desde) q.append('hora_desde', params.hora_desde);
        if (params.hora_hasta) q.append('hora_hasta', params.hora_hasta);
        q.append('limit', '50');
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/numeros?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); });
    }

    function fetchImeis(qTxt, params) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (params.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (params.fecha_desde) q.append('fecha_desde', params.fecha_desde);
        if (params.fecha_hasta) q.append('fecha_hasta', params.fecha_hasta);
        if (params.hora_desde) q.append('hora_desde', params.hora_desde);
        if (params.hora_hasta) q.append('hora_hasta', params.hora_hasta);
        q.append('limit', '80');
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/imeis?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); });
    }

    function fetchProvincias(qTxt, params) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        q.append('limit', '120');
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/provincias?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); });
    }

    function fetchLocalidades(qTxt, params) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (params.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (params.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        q.append('limit', '160');
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/localidades?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); });
    }

    function renderSimpleCheckboxList(containerId, values, prefix) {
        var container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';
        (values || []).forEach(function (v, idx) {
            var val = String(v || '').trim();
            if (!val) return;
            var id = (prefix || 'cb') + '-' + containerId + '-' + idx;
            var div = document.createElement('div');
            div.className = 'form-check';
            div.innerHTML = '<input class="form-check-input" type="checkbox" id="' + id + '" value="' + escapeHtmlAttr(val) + '">' +
                '<label class="form-check-label" for="' + id + '">' + escapeHtml(val) + '</label>';
            container.appendChild(div);
        });
    }

    function renderNumerosSelected() {
        var box = document.getElementById('numeros-selected');
        if (!box) return;
        var arr = getSelectedNumeros();
        if (!arr.length) {
            box.innerHTML = '';
            updateDdButtonText('dd-numeros', 'Buscar y seleccionar…');
            return;
        }
        updateDdButtonText('dd-numeros', 'Números: ' + arr.length + ' seleccionado(s)');
        box.innerHTML = arr.slice(0, 20).map(function (n) {
            return '<span class="badge text-bg-secondary" data-num="' + escapeHtmlAttr(n) + '">' + escapeHtml(n) + ' ×</span>';
        }).join(' ') + (arr.length > 20 ? '<span class="text-muted small ms-1">+' + (arr.length - 20) + '</span>' : '');
        box.querySelectorAll('[data-num]').forEach(function (el) {
            el.addEventListener('click', function () {
                var n = this.getAttribute('data-num') || '';
                if (!n) return;
                selectedNumeros.delete(n);
                // desmarcar si está visible
                var list = document.getElementById('filtro-numeros');
                if (list) {
                    list.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
                        if (cb.value === n) cb.checked = false;
                    });
                }
                renderNumerosSelected();
            });
        });
    }

    function renderImeisSelected() {
        var box = document.getElementById('imeis-selected');
        if (!box) return;
        var arr = getSelectedImeis();
        if (!arr.length) {
            box.innerHTML = '';
            updateDdButtonText('dd-imeis', 'Buscar y seleccionar…');
            return;
        }
        updateDdButtonText('dd-imeis', 'IMEIs: ' + arr.length + ' seleccionado(s)');
        box.innerHTML = arr.slice(0, 20).map(function (n) {
            return '<span class="badge text-bg-secondary" data-imei="' + escapeHtmlAttr(n) + '">' + escapeHtml(n) + ' ×</span>';
        }).join(' ') + (arr.length > 20 ? '<span class="text-muted small ms-1">+' + (arr.length - 20) + '</span>' : '');
        box.querySelectorAll('[data-imei]').forEach(function (el) {
            el.addEventListener('click', function () {
                var n = this.getAttribute('data-imei') || '';
                if (!n) return;
                selectedImeis.delete(n);
                var list = document.getElementById('filtro-imeis');
                if (list) {
                    list.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
                        if (cb.value === n) cb.checked = false;
                    });
                }
                renderImeisSelected();
            });
        });
    }

    function escapeHtml(s) {
        var div = document.createElement('div');
        div.textContent = s == null ? '' : String(s);
        return div.innerHTML;
    }

    function escapeHtmlAttr(s) {
        return escapeHtml(s).replace(/"/g, '&quot;');
    }

    function _fgForBg(hex) {
        // simple luminancia para decidir blanco/negro
        try {
            var h = String(hex || '').replace('#', '');
            if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
            var r = parseInt(h.substring(0, 2), 16);
            var g = parseInt(h.substring(2, 4), 16);
            var b = parseInt(h.substring(4, 6), 16);
            var lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
            return lum > 0.62 ? '#111' : '#fff';
        } catch (e) {
            return '#fff';
        }
    }

    function _getOrAssignColor(key, label) {
        var k = key == null ? '—' : String(key);
        if (!k) k = '—';
        if (colorMap[k]) return colorMap[k];
        var idx = Object.keys(colorMap).length % palette.length;
        var bg = (k === '—') ? '#6c757d' : palette[idx];
        var fg = _fgForBg(bg);
        colorMap[k] = { bg: bg, fg: fg, label: label || k };
        return colorMap[k];
    }

    function _selectedCheckboxPairs(containerId) {
        var c = document.getElementById(containerId);
        if (!c) return [];
        var out = [];
        c.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
            var v = cb.value;
            var lab = '';
            try {
                var lbl = c.querySelector('label[for="' + cb.id + '"]');
                lab = lbl ? (lbl.textContent || '').trim() : '';
            } catch (e) {}
            out.push({ value: v, label: lab || v });
        });
        return out;
    }

    function _detectarColorMode(params) {
        params = params || {};
        if (params.numeros && params.numeros.length >= 2) return 'numero';
        if (params.imeis && params.imeis.length >= 2) return 'imei';
        var sujetos = _selectedCheckboxPairs('filtro-sujetos');
        if (sujetos.length >= 2) return 'sujeto';
        var cargas = _selectedCheckboxPairs('filtro-cargas');
        if (cargas.length >= 2) return 'carga';
        return null;
    }

    function resetColoring(params) {
        colorMode = _detectarColorMode(params);
        colorMap = {};
        legendItems = [];
        if (!colorMode) {
            updateLegend();
            return;
        }
        if (colorMode === 'numero') {
            (params.numeros || []).forEach(function (n) {
                var c = _getOrAssignColor(n, n);
                legendItems.push({ key: String(n), label: String(n), bg: c.bg, fg: c.fg });
            });
        } else if (colorMode === 'imei') {
            (params.imeis || []).forEach(function (i) {
                var c2 = _getOrAssignColor(i, i);
                legendItems.push({ key: String(i), label: String(i), bg: c2.bg, fg: c2.fg });
            });
        } else if (colorMode === 'sujeto') {
            _selectedCheckboxPairs('filtro-sujetos').forEach(function (p) {
                var c3 = _getOrAssignColor(p.value, p.label);
                legendItems.push({ key: String(p.value), label: p.label, bg: c3.bg, fg: c3.fg });
            });
        } else if (colorMode === 'carga') {
            _selectedCheckboxPairs('filtro-cargas').forEach(function (p) {
                var c4 = _getOrAssignColor(p.value, p.label);
                legendItems.push({ key: String(p.value), label: p.label, bg: c4.bg, fg: c4.fg });
            });
        }
        updateLegend();
    }

    function ensureLegendEl() {
        var wrap = document.querySelector('.sabana-mapa-wrap');
        if (!wrap) return null;
        var el = document.getElementById('sabana-legend');
        if (el) return el;
        el = document.createElement('div');
        el.id = 'sabana-legend';
        el.className = 'sabana-legend d-none';
        wrap.appendChild(el);
        return el;
    }

    function updateLegend() {
        var el = ensureLegendEl();
        if (!el) return;
        if (!colorMode || !legendItems.length) {
            el.classList.add('d-none');
            el.innerHTML = '';
            return;
        }
        el.classList.remove('d-none');
        var title = (colorMode === 'numero') ? 'Colores por Número' :
            (colorMode === 'imei') ? 'Colores por IMEI' :
                (colorMode === 'sujeto') ? 'Colores por Sujeto' :
                    (colorMode === 'carga') ? 'Colores por Carga' : 'Colores';
        var max = 12;
        var rows = legendItems.slice(0, max).map(function (it) {
            return '<div class="sabana-legend-item">' +
                '<span class="sabana-legend-swatch" style="background:' + it.bg + '"></span>' +
                '<span>' + escapeHtml(it.label) + '</span>' +
                '</div>';
        }).join('');
        var more = legendItems.length > max ? ('<div class="sabana-legend-note">+' + (legendItems.length - max) + ' más…</div>') : '';
        el.innerHTML = '<div class="sabana-legend-title">' + escapeHtml(title) + '</div>' + rows + more +
            '<div class="sabana-legend-note">Tip: seleccioná 2+ valores para colorear.</div>';
    }

    function getColorForImpact(imp, punto) {
        if (!colorMode) return null;
        if (colorMode === 'numero') {
            var n = (imp && (imp.numero || imp.otro)) ? String(imp.numero || imp.otro).trim() : '—';
            return _getOrAssignColor(n, n);
        }
        if (colorMode === 'imei') {
            var i = (imp && imp.imei) ? String(imp.imei).trim() : '—';
            return _getOrAssignColor(i, i);
        }
        if (colorMode === 'sujeto') {
            var sid = punto && punto.sujeto_id != null ? String(punto.sujeto_id) : '—';
            return _getOrAssignColor(sid, sid);
        }
        if (colorMode === 'carga') {
            var cid = punto && punto.carga_id != null ? String(punto.carga_id) : '—';
            return _getOrAssignColor(cid, cid);
        }
        return null;
    }

    function showPanel() {
        var el = document.getElementById('sabana-panel');
        if (!el) return;
        el.classList.remove('d-none');
    }

    function closePanel() {
        var el = document.getElementById('sabana-panel');
        if (!el) return;
        el.classList.add('d-none');
        currentPanelMode = null;
        currentPanelPunto = null;
        currentPanelImpactos = [];
        currentPanelImpacto = null;
        // restaurar pin seleccionado (si habíamos sobreescrito el número)
        try {
            if (lastSelectedCeldaKey && celdaMarkerMap && celdaMarkerMap.has(lastSelectedCeldaKey)) {
                var m = celdaMarkerMap.get(lastSelectedCeldaKey);
                if (m) {
                    var baseTxt = (m._baseTxt != null) ? m._baseTxt : '';
                    m.setIcon(_makeCeldaIcon(m._punto || {}, baseTxt));
                }
            }
        } catch (eSelRestore) {}
        lastSelectedCeldaKey = null;
        // limpiar resaltado al cerrar
        try {
            if (highlightCircle && map && map.hasLayer(highlightCircle)) map.removeLayer(highlightCircle);
            if (highlightMarker && map && map.hasLayer(highlightMarker)) map.removeLayer(highlightMarker);
        } catch (e) {}
        highlightCircle = null;
        highlightMarker = null;
    }

    function initPanelDrag() {
        var panel = document.getElementById('sabana-panel');
        if (!panel) return;
        var header = panel.querySelector('.sabana-panel-header');
        if (!header) return;
        var wrap = document.querySelector('.sabana-mapa-wrap');
        if (!wrap) return;

        // Evitar que al interactuar con el panel se “arrastre” el mapa
        ['mousedown', 'touchstart', 'pointerdown', 'wheel'].forEach(function (ev) {
            panel.addEventListener(ev, function (e) {
                try { e.stopPropagation(); } catch (err) {}
            }, { passive: false });
        });

        // Restaurar posición si existía
        try {
            var saved = localStorage.getItem('sabana_panel_pos');
            if (saved) {
                var obj = JSON.parse(saved);
                if (obj && typeof obj.x === 'number' && typeof obj.y === 'number') {
                    panel.style.left = obj.x + 'px';
                    panel.style.top = obj.y + 'px';
                }
            }
        } catch (e) {}

        function clamp(v, min, max) {
            return Math.max(min, Math.min(max, v));
        }

        var dragging = false;
        var startX = 0, startY = 0;
        var startLeft = 0, startTop = 0;

        function onDown(e) {
            if (!panel || panel.classList.contains('d-none')) return;
            // No iniciar drag cuando el usuario clickea botones/inputs del header
            try {
                var t = e && e.target ? e.target : null;
                if (t && t.closest && t.closest('button, a, input, select, textarea, label, .btn')) return;
            } catch (e0) {}
            dragging = true;
            panel.classList.add('dragging');
            try { header.setPointerCapture && header.setPointerCapture(e.pointerId); } catch (err) {}
            var rect = panel.getBoundingClientRect();
            var wrapRect = wrap.getBoundingClientRect();
            startLeft = rect.left - wrapRect.left;
            startTop = rect.top - wrapRect.top;
            startX = (e.clientX != null) ? e.clientX : (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
            startY = (e.clientY != null) ? e.clientY : (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
            try { e.preventDefault(); } catch (err2) {}
        }

        function onMove(e) {
            if (!dragging) return;
            var x = (e.clientX != null) ? e.clientX : (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
            var y = (e.clientY != null) ? e.clientY : (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
            var dx = x - startX;
            var dy = y - startY;
            var wrapRect = wrap.getBoundingClientRect();
            var pw = panel.offsetWidth;
            var ph = panel.offsetHeight;
            var nx = clamp(startLeft + dx, 0, Math.max(0, wrapRect.width - pw));
            var ny = clamp(startTop + dy, 0, Math.max(0, wrapRect.height - ph));
            panel.style.left = nx + 'px';
            panel.style.top = ny + 'px';
            try { e.preventDefault(); } catch (err3) {}
        }

        function onUp() {
            if (!dragging) return;
            dragging = false;
            panel.classList.remove('dragging');
            // Guardar posición
            try {
                var wrapRect = wrap.getBoundingClientRect();
                var rect = panel.getBoundingClientRect();
                var x = rect.left - wrapRect.left;
                var y = rect.top - wrapRect.top;
                localStorage.setItem('sabana_panel_pos', JSON.stringify({ x: x, y: y }));
            } catch (e) {}
        }

        header.addEventListener('pointerdown', onDown);
        window.addEventListener('pointermove', onMove, { passive: false });
        window.addEventListener('pointerup', onUp);

        // Doble click para “reset” a esquina
        header.addEventListener('dblclick', function () {
            panel.style.left = '10px';
            panel.style.top = '10px';
            try { localStorage.removeItem('sabana_panel_pos'); } catch (e) {}
        });
    }

    function setPanelTitle(txt) {
        var t = document.getElementById('sabana-panel-title');
        if (t) t.textContent = txt || '';
    }

    function setPanelBackVisible(vis) {
        var b = document.getElementById('sabana-panel-back');
        if (!b) return;
        if (vis) b.classList.remove('d-none'); else b.classList.add('d-none');
    }

    function renderPanelList(punto, impactos) {
        currentPanelMode = 'list';
        currentPanelPunto = punto || null;
        currentPanelImpactos = impactos || [];
        currentPanelImpacto = null;

        var titulo = (punto && punto.celda_direccion) ? punto.celda_direccion : 'Celda';
        if (punto && punto.celda_id) titulo += ' (' + punto.celda_id + ')';
        setPanelTitle(titulo + ' — ' + (currentPanelImpactos.length || 0) + ' registro(s)');
        setPanelBackVisible(false);

        var body = document.getElementById('sabana-panel-body');
        if (!body) return;
        if (!currentPanelImpactos.length) {
            body.innerHTML = '<div class="text-muted small">Sin registros.</div>';
            showPanel();
            return;
        }

        var rows = currentPanelImpactos.map(function (imp, idx) {
            var ord = imp && imp._ord ? String(imp._ord) : String(idx + 1);
            var tipoTxt = (imp && imp.tipo === 'voz') ? (imp.tipo_llamada || 'VOZ') : (imp && imp.tipo === 'gprs' ? 'GPRS' : (imp && imp.tipo ? String(imp.tipo).toUpperCase() : '—'));
            var dur = (imp && imp.tipo === 'voz') ? (imp.duracion || '') : (imp && imp.duracion ? imp.duracion : '');
            var celdaTraf = '—';
            var celdaTec = '—';
            try {
                celdaTec = imp && imp._punto_celda_id ? String(imp._punto_celda_id) : '—';
                celdaTraf = (imp && imp.tipo === 'gprs')
                    ? (imp.celda || '—')
                    : (imp && imp.celda_id ? imp.celda_id : '—');
            } catch (eCel) {}
            return '<tr data-idx="' + idx + '">' +
                '<td class="text-nowrap fw-bold">#' + escapeHtml(ord) + '</td>' +
                '<td class="text-nowrap">' + escapeHtml(imp && imp.fecha ? formatFecha(imp.fecha) : '—') + '</td>' +
                '<td class="text-nowrap">' + escapeHtml(imp && imp.hora ? imp.hora : '—') + '</td>' +
                '<td class="text-nowrap">' + escapeHtml(imp && imp.imei ? imp.imei : '—') + '</td>' +
                '<td class="text-nowrap">' + escapeHtml(imp && imp.imsi ? imp.imsi : '—') + '</td>' +
                '<td class="text-nowrap">' + escapeHtml(celdaTraf) + '</td>' +
                '<td class="text-nowrap">' + escapeHtml(celdaTec) + '</td>' +
                '<td class="text-nowrap">' + escapeHtml(tipoTxt + (dur ? (' / ' + dur) : '')) + '</td>' +
                '</tr>';
        }).join('');

        body.innerHTML =
            '<div class="table-responsive">' +
            '<table class="table table-sm table-hover sabana-panel-list">' +
            '<thead><tr><th>#</th><th>Fecha</th><th>Hora</th><th>IMEI</th><th>IMSI</th><th>Celda (tráfico)</th><th>Celda (técnica)</th><th>Tipo</th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table></div>';

        body.querySelectorAll('tr[data-idx]').forEach(function (tr) {
            tr.addEventListener('click', function () {
                var i = parseInt(this.getAttribute('data-idx'), 10);
                if (isNaN(i)) return;
                var imp = currentPanelImpactos[i];
                openPanelDetalle(imp);
            });
        });

        showPanel();
        updatePanelNav();
    }

    function openPanelDetalle(imp) {
        if (!imp) return;
        currentPanelMode = 'detail';
        currentPanelImpacto = imp;
        setPanelBackVisible(true);
        // Si viene desde Trazado (autito), priorizar el número de recorrido (_trazado_num) sobre el orden global.
        var ordTxt = null;
        try {
            if (imp._trazado_num != null) ordTxt = imp._trazado_num;
            else if (imp._ord != null) ordTxt = imp._ord;
        } catch (eOrdTxt) {}
        setPanelTitle('Registro #' + (ordTxt != null ? ordTxt : '—'));
        // Si el impacto aún no trae coords resueltas, usar coords del pin (Datos Técnicos) como fallback visual.
        var pinLatLng = null;
        try {
            if (imp._punto_lat != null && imp._punto_lng != null) {
                var pla = parseFloat(imp._punto_lat);
                var plo = parseFloat(imp._punto_lng);
                if (!isNaN(pla) && !isNaN(plo)) pinLatLng = L.latLng(pla, plo);
            }
        } catch (ePLL) {}
        highlightImpact(imp, pinLatLng);

        var rows = [];
        function addRow(label, value) {
            if (value == null || value === '') return;
            rows.push('<tr><th class="text-nowrap">' + escapeHtml(label) + '</th><td>' + escapeHtml(String(value)) + '</td></tr>');
        }
        addRow('Tipo', imp.tipo === 'gprs' ? 'GPRS' : (imp.tipo === 'voz' ? 'VOZ' : (imp.tipo || '—')));
        addRow('IMEI', imp.imei);
        addRow('IMSI', imp.imsi);
        addRow('Fecha', imp.fecha ? formatFecha(imp.fecha) : null);
        addRow('Hora', imp.hora);
        addRow('Duración', imp.duracion);
        // Debug: de qué pin/coords salió este impacto (útil cuando se agrupan varias celdas en el mismo punto)
        try {
            if (imp._punto_celda_id) addRow('Celda (pin)', imp._punto_celda_id);
            if (imp._punto_lat != null && imp._punto_lng != null) addRow('Coords (pin)', String(imp._punto_lat) + ', ' + String(imp._punto_lng));
        } catch (eDbg) {}
        if (imp.tipo === 'gprs') {
            addRow('Número', imp.numero);
            addRow('IP', imp.ip);
            addRow('IP Dual Stack', imp.ip_dual_stack);
            addRow('Volumen (kb)', imp.volumen_kb);
            addRow('Celda (tráfico)', imp.celda);
            addRow('Celda dirección', imp.celda_direccion);
            addRow('Celda localidad', imp.celda_localidad);
            addRow('Celda provincia', imp.celda_provincia);
            addRow('IP WIFI', imp.ip_wifi);
        } else {
            addRow('Tipo llamada', imp.tipo_llamada);
            addRow('Otro', imp.otro);
            addRow('Celda ID (tráfico)', imp.celda_id);
            addRow('Celda calle/altura', imp.celda_calle_altura);
            addRow('Celda localidad', imp.celda_localidad);
            addRow('Celda provincia', imp.celda_provincia);
        }

        var body = document.getElementById('sabana-panel-body');
        if (body) {
            var geo = '';
            var idStr = (imp && imp.id != null) ? String(imp.id) : null;
            var tipoStr = (imp && imp.tipo != null) ? String(imp.tipo) : '';
            var keyStr = idStr ? (tipoStr + '|' + idStr) : null;
            var hasMarker = false;
            try { hasMarker = !!(keyStr && impactMarkerMap && impactMarkerMap.has(keyStr)); } catch (eM) {}
            // Si no sabemos todavía si tiene coords, pero el pin sí tiene coords, considerarlo “referencia por pin”.
            try {
                if (imp._has_coords == null && pinLatLng) {
                    imp._has_coords = true;
                    if (!imp._coords_source) imp._coords_source = 'pin';
                }
            } catch (ePinGeo) {}

            if (imp._has_coords === false) {
                var celdaTxt = (imp._geo_missing && imp._geo_missing.celda_id) ? String(imp._geo_missing.celda_id) : (imp.tipo === 'gprs' ? (imp.celda || '—') : (imp.celda_id || '—'));
                geo =
                    '<div class="alert alert-warning py-1 px-2 small mb-2">' +
                    '<strong>Geolocalización: NO.</strong> La celda <strong>' + escapeHtml(String(celdaTxt)) + '</strong> no tiene latitud/longitud en <em>Datos Técnicos</em>. ' +
                    'Se podrá ubicar cuando se cargue un archivo que incluya esa celda con coordenadas.' +
                    '</div>';
            } else if (imp._coords_source === 'pin') {
                geo =
                    '<div class="alert alert-info py-1 px-2 small mb-2">' +
                    '<strong>Geolocalización: SÍ (pin).</strong> Coordenadas tomadas del pin (Datos Técnicos) para esta celda.' +
                    '</div>';
            } else if (imp._coords_source === 'other_carga') {
                geo =
                    '<div class="alert alert-info py-1 px-2 small mb-2">' +
                    '<strong>Geolocalización: SÍ (referencia).</strong> Coordenadas obtenidas desde otra carga que sí tiene esa celda mapeada.' +
                    '</div>';
            } else if (imp._has_coords === true || hasMarker) {
                geo =
                    '<div class="alert alert-success py-1 px-2 small mb-2">' +
                    '<strong>Geolocalización: SÍ.</strong> Este impacto tiene coordenadas disponibles para el mapa.' +
                    '</div>';
            } else {
                geo =
                    '<div class="alert alert-secondary py-1 px-2 small mb-2">' +
                    '<strong>Geolocalización:</strong> (sin dato). ' +
                    '</div>';
            }

            body.innerHTML = geo + '<table class="table table-sm"><tbody>' + rows.join('') + '</tbody></table>';
        }
        showPanel();
        updatePanelNav();
    }

    function updatePanelNav() {
        var pos = document.getElementById('sabana-panel-pos');
        var prev = document.getElementById('sabana-panel-prev');
        var next = document.getElementById('sabana-panel-next');
        if (!pos || !prev || !next) return;
        // En modo trazado (reproducción con autito), no mostramos navegación global ni local,
        // para no mezclar el # del trazado con el Orden global.
        if (currentPanelMode === 'detail' && currentPanelImpacto && currentPanelImpacto._from_trazado) {
            pos.classList.add('d-none');
            prev.classList.add('d-none');
            next.classList.add('d-none');
            return;
        }
        if (currentPanelMode !== 'detail' || !currentPanelImpacto) {
            pos.classList.add('d-none');
            prev.classList.add('d-none');
            next.classList.add('d-none');
            return;
        }

        // Navegación global por orden
        if (isOrdenEnabled() && currentPanelImpacto._ord != null && ordenImpactoTotal) {
            var o = parseInt(currentPanelImpacto._ord, 10);
            pos.textContent = o + ' / ' + ordenImpactoTotal;
            pos.classList.remove('d-none');
            prev.disabled = o <= 1;
            next.disabled = o >= ordenImpactoTotal;
            prev.classList.remove('d-none');
            next.classList.remove('d-none');
            return;
        }

        // Navegación dentro de la celda (solo si Orden está apagado)
        if (currentPanelImpactos && currentPanelImpactos.length) {
            var idx = -1;
            for (var i = 0; i < currentPanelImpactos.length; i++) {
                var it = currentPanelImpactos[i];
                if (it && currentPanelImpacto && it.id != null && currentPanelImpacto.id != null && String(it.id) === String(currentPanelImpacto.id)) {
                    idx = i;
                    break;
                }
            }
            if (idx >= 0) {
                pos.textContent = (idx + 1) + ' / ' + currentPanelImpactos.length;
                pos.classList.remove('d-none');
                prev.disabled = idx === 0;
                next.disabled = idx === currentPanelImpactos.length - 1;
                prev.classList.remove('d-none');
                next.classList.remove('d-none');
                return;
            }
        }

        pos.classList.add('d-none');
        prev.classList.add('d-none');
        next.classList.add('d-none');
    }

    function renderNumerosResultados(items) {
        var container = document.getElementById('filtro-numeros');
        if (!container) return;
        container.innerHTML = '';
        (items || []).forEach(function (num, idx) {
            var v = String(num || '').trim();
            if (!v) return;
            var id = 'cb-num-' + idx;
            var div = document.createElement('div');
            div.className = 'form-check';
            div.innerHTML = '<input class="form-check-input" type="checkbox" id="' + id + '" value="' + escapeHtmlAttr(v) + '"' + (selectedNumeros.has(v) ? ' checked' : '') + '>' +
                '<label class="form-check-label" for="' + id + '">' + escapeHtml(v) + '</label>';
            var cb = div.querySelector('input');
            cb.addEventListener('change', function () {
                if (this.checked) selectedNumeros.add(v); else selectedNumeros.delete(v);
                renderNumerosSelected();
                scheduleAutoApply(400);
            });
            container.appendChild(div);
        });
    }

    function renderImeisResultados(items) {
        var container = document.getElementById('filtro-imeis');
        if (!container) return;
        container.innerHTML = '';
        (items || []).forEach(function (num, idx) {
            var v = String(num || '').trim();
            if (!v) return;
            var id = 'cb-imei-' + idx;
            var div = document.createElement('div');
            div.className = 'form-check';
            div.innerHTML = '<input class="form-check-input" type="checkbox" id="' + id + '" value="' + escapeHtmlAttr(v) + '"' + (selectedImeis.has(v) ? ' checked' : '') + '>' +
                '<label class="form-check-label" for="' + id + '">' + escapeHtml(v) + '</label>';
            var cb = div.querySelector('input');
            cb.addEventListener('change', function () {
                if (this.checked) selectedImeis.add(v); else selectedImeis.delete(v);
                renderImeisSelected();
                scheduleAutoApply(400);
            });
            container.appendChild(div);
        });
    }

    function isVistaRuta() {
        var r = document.getElementById('vista-ruta');
        return r && r.checked;
    }

    function isOrdenEnabled() {
        var cb = document.getElementById('toggle-orden');
        return !!(cb && cb.checked);
    }

    function isOrdenProgressiveEnabled() {
        var cb = document.getElementById('toggle-orden-prog');
        return !!(cb && cb.checked);
    }

    function setOrdenVisibleMax(n) {
        var v = parseInt(String(n || '').trim(), 10);
        if (isNaN(v) || v < 1) v = 1;
        ordenVisibleMax = v;
        try { localStorage.setItem('sabana_orden_visible_max', String(v)); } catch (e) {}
    }

    function getOrdenProgressiveStartMax() {
        var sel = document.getElementById('orden-prog-max');
        if (sel && sel.value != null) {
            var v = parseInt(String(sel.value).trim(), 10);
            if (!isNaN(v) && v > 0) return v;
        }
        try {
            var saved = localStorage.getItem('sabana_orden_progressive_max');
            if (saved != null) {
                var s = parseInt(String(saved).trim(), 10);
                if (!isNaN(s) && s > 0) return s;
            }
        } catch (e) {}
        return 100;
    }

    function resetOrdenVisibleMax() {
        setOrdenVisibleMax(getOrdenProgressiveStartMax());
    }

    function updateOrdenProgressiveVisibility() {
        var wrap = document.getElementById('orden-prog-wrap');
        if (!wrap) return;
        var wrapMax = document.getElementById('orden-prog-max-wrap');
        if (isVistaRuta() || !isOrdenEnabled()) {
            wrap.classList.add('d-none');
            if (wrapMax) wrapMax.classList.add('d-none');
            return;
        }
        wrap.classList.remove('d-none');
        if (wrapMax) {
            if (isOrdenProgressiveEnabled()) wrapMax.classList.remove('d-none');
            else wrapMax.classList.add('d-none');
        }
    }

    function updateOrdenToggleVisibility() {
        var wrap = document.getElementById('orden-toggle-wrap');
        if (!wrap) return;
        if (isVistaRuta()) wrap.classList.add('d-none');
        else wrap.classList.remove('d-none');
        updateOrdenProgressiveVisibility();
    }

    function isTrazadoEnabled() {
        var cb = document.getElementById('toggle-trazado');
        return !!(cb && cb.checked);
    }

    function updateTrazadoToggleVisibility() {
        var wrap = document.getElementById('trazado-toggle-wrap');
        if (!wrap) return;
        // Solo en “Celdas”. Si está Ruta, no mostrar (esa vista ya tiene su propio recorrido).
        if (isVistaRuta()) {
            wrap.classList.add('d-none');
            return;
        }
        // Se habilita si hay mapa y hay filtros aplicables (en general siempre).
        wrap.classList.remove('d-none');
        updateTrazadoControlsVisibility();
    }

    function updateTrazadoControlsVisibility() {
        var ctrl = document.getElementById('trazado-controls');
        if (!ctrl) return;
        if (isVistaRuta()) {
            ctrl.classList.add('d-none');
            ctrl.classList.remove('d-flex');
            return;
        }
        ctrl.classList.remove('d-none');
        ctrl.classList.add('d-flex');
    }

    function clearTrazado() {
        stopTrazadoAnimacion();
        try {
            if (trazadoLayer) trazadoLayer.clearLayers();
        } catch (e) {}
        try {
            if (trazadoPolylineBase && map && map.hasLayer(trazadoPolylineBase)) map.removeLayer(trazadoPolylineBase);
            if (trazadoPolylineLive && map && map.hasLayer(trazadoPolylineLive)) map.removeLayer(trazadoPolylineLive);
        } catch (e2) {}
        trazadoPolylineBase = null;
        trazadoPolylineLive = null;
        trazadoPuntos = [];
        updateTrazadoTiempoLabel();
    }

    function drawTrazado(puntos, meta) {
        if (!map) return;
        if (!trazadoLayer) {
            trazadoLayer = L.layerGroup().addTo(map);
        }
        clearTrazado();
        trazadoPuntos = Array.isArray(puntos) ? puntos : [];
        var latlngs = (trazadoPuntos || []).map(function (p) { return [p.lat, p.lng]; }).filter(function (x) { return x && x.length === 2; });
        if (latlngs.length < 2) return;
        // Línea base completa (suave) + línea "live" que se va trazando al avanzar
        // Línea base bien visible (roja) + línea "live" un poco más gruesa
        trazadoPolylineBase = L.polyline(latlngs, {
            color: '#dc3545',
            weight: 3,
            opacity: 0.7
        }).addTo(trazadoLayer);
        trazadoPolylineLive = L.polyline([], {
            color: '#dc3545',
            weight: 4,
            opacity: 0.9
        }).addTo(trazadoLayer);
        try { if (trazadoPolylineLive.bringToFront) trazadoPolylineLive.bringToFront(); } catch (eF) {}
        resetTrazadoAnimacion();
    }

    function getTrazadoSegundosPorTramo() {
        var sel = document.getElementById('trazado-velocidad');
        if (sel) {
            var v = parseFloat(String(sel.value || '').replace(',', '.'));
            if (!isNaN(v) && v > 0) return v;
        }
        return 1;
    }

    function getTrazadoPausaMs() {
        var sel = document.getElementById('trazado-pausa');
        if (sel) {
            var v = parseInt(String(sel.value || '').trim(), 10);
            if (!isNaN(v) && v >= 0) return v * 1000;
        }
        return 3000;
    }

    function fmtMs(ms) {
        ms = Math.max(0, ms || 0);
        var s = Math.floor(ms / 1000);
        var h = Math.floor(s / 3600);
        var m = Math.floor((s % 3600) / 60);
        var ss = s % 60;
        function z(n) { return (n < 10 ? '0' : '') + n; }
        if (h > 0) return h + ':' + z(m) + ':' + z(ss);
        return m + ':' + z(ss);
    }

    function updateTrazadoTiempoLabel(extra) {
        var el = document.getElementById('trazado-tiempo');
        if (!el) return;
        if (!trazadoPuntos || trazadoPuntos.length < 2) {
            el.textContent = '';
            return;
        }
        var tramos = Math.max(0, trazadoPuntos.length - 1);
        var velSeg = getTrazadoSegundosPorTramo();
        var pausaMs = getTrazadoPausaMs();
        var estMove = tramos * velSeg * 1000;
        var estPause = tramos * pausaMs;
        var estTotal = estMove + estPause;
        var base = 'Vel: ' + String(velSeg).replace('.', ',') + 's/tramo · Pausa: ' + Math.round(pausaMs / 1000) + 's · Total est: ' + fmtMs(estTotal);
        el.textContent = extra ? (extra + ' · ' + base) : base;
    }

    function stopTrazadoAnimacion() {
        trazadoIsPlaying = false;
        if (trazadoAnimacionFrameId != null) {
            cancelAnimationFrame(trazadoAnimacionFrameId);
            trazadoAnimacionFrameId = null;
        }
        if (trazadoAnimacionTimeout) {
            clearTimeout(trazadoAnimacionTimeout);
            trazadoAnimacionTimeout = null;
        }
    }

    function ensureTrazadoMarker() {
        if (!map) return;
        if (trazadoMarkerAuto && map.hasLayer(trazadoMarkerAuto)) return;
        var iconAuto = L.divIcon({
            className: 'sabana-marker-auto',
            html: '<span class="sabana-auto-icon">🚗</span>',
            iconSize: [32, 32],
            iconAnchor: [16, 16]
        });
        trazadoMarkerAuto = L.marker([0, 0], {
            icon: iconAuto,
            keyboard: false,
            interactive: false,
            pane: 'sabanaHighlightPane',
            zIndexOffset: 100000
        }).addTo(map);
        try { if (trazadoMarkerAuto.setZIndexOffset) trazadoMarkerAuto.setZIndexOffset(100000); } catch (eZ) {}
    }

    function resetTrazadoAnimacion() {
        stopTrazadoAnimacion();
        closePanel();
        trazadoStartMs = 0;
        trazadoPauseAccumMs = 0;
        trazadoLastDetailIdx = -1;
        if (!trazadoPuntos || trazadoPuntos.length === 0) {
            try {
                if (trazadoMarkerAuto && map && map.hasLayer(trazadoMarkerAuto)) map.removeLayer(trazadoMarkerAuto);
            } catch (eRm) {}
            trazadoMarkerAuto = null;
            updateTrazadoTiempoLabel();
            return;
        }
        ensureTrazadoMarker();
        try { trazadoMarkerAuto.setLatLng([trazadoPuntos[0].lat, trazadoPuntos[0].lng]); } catch (eSet) {}
        try {
            if (trazadoPolylineLive && map && map.hasLayer(trazadoPolylineLive)) {
                trazadoPolylineLive.setLatLngs([[trazadoPuntos[0].lat, trazadoPuntos[0].lng]]);
            }
        } catch (eLive) {}
        updateTrazadoTiempoLabel('Listo');
    }

    function fetchImpactoParaTrazado(p) {
        if (!p || !p.tipo || p.impacto_id == null) return Promise.resolve(null);
        var key = String(p.tipo) + '|' + String(p.impacto_id);
        if (trazadoCache.has(key)) return Promise.resolve(trazadoCache.get(key));
        // Reusar impacto-loc para obtener payload del impacto (y coords si hace falta)
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/impacto-loc?tipo=' + encodeURIComponent(String(p.tipo)) + '&impacto_id=' + encodeURIComponent(String(p.impacto_id)), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (!data || !data.impacto) return null;
            var imp = data.impacto;
            try {
                if (p.numero != null) {
                    imp._trazado_num = p.numero;  // orden interno de este recorrido
                    // No tocamos _ord para no pelear con Orden global; el título puede usar _trazado_num.
                }
            } catch (eOrd) {}
            // Contexto del pin/coords para el panel
            try {
                imp._punto_tipo = p.tipo;
                imp._punto_carga_id = p.carga_id;
                imp._punto_celda_id = p.celda_id || null;
                imp._punto_lat = p.lat;
                imp._punto_lng = p.lng;
                // Azimut y radio de cobertura (si vienen en el payload)
                if (data.azimuth != null) imp._azimuth = data.azimuth;
                if (data.rad_cob_km != null) imp._rad_cob_km = data.rad_cob_km;
                if (data.a_horiz != null) imp._a_horiz = data.a_horiz;
                if (data.a_vert != null) imp._a_vert = data.a_vert;
            } catch (eCtx) {}
            trazadoCache.set(key, imp);
            return imp;
        }).catch(function () { return null; });
    }

    function _playTrazadoAnimacionCore() {
        if (!map || !trazadoPuntos || trazadoPuntos.length < 2) return;
        stopTrazadoAnimacion();
        trazadoIsPlaying = true;
        ensureTrazadoMarker();

        var puntos = trazadoPuntos;
        var segPorTramo = getTrazadoSegundosPorTramo();
        var pausaMs = getTrazadoPausaMs();
        var segMs = Math.max(1, segPorTramo * 1000);
        var tramos = Math.max(0, (puntos.length - 1));
        var duracionTotalEstMs = tramos * (segMs + pausaMs);

        trazadoStartMs = Date.now();
        trazadoPauseAccumMs = 0;
        trazadoLastDetailIdx = -1;

        var currentSeg = 0; // segmento entre puntos[currentSeg] y puntos[currentSeg+1]
        var segStartTime = performance.now();
        var pauseUntil = null;

        // Inicializar línea live con el primer punto y panel del primer impacto
        var livePoints = [];
        try {
            if (trazadoPolylineLive && map.hasLayer(trazadoPolylineLive)) {
                livePoints = [[puntos[0].lat, puntos[0].lng]];
                trazadoPolylineLive.setLatLngs(livePoints.slice());
            }
        } catch (ePL) {}
        try { trazadoMarkerAuto.setLatLng([puntos[0].lat, puntos[0].lng]); } catch (e0) {}
        (function (pt0) {
            fetchImpactoParaTrazado(pt0).then(function (imp) {
                if (!imp) return;
                openPanelDetalle(imp);
            });
        })(puntos[0]);

        function frame() {
            if (!trazadoIsPlaying || !trazadoMarkerAuto || !map.hasLayer(trazadoMarkerAuto)) {
                trazadoAnimacionFrameId = null;
                return;
            }

            var now = performance.now();

            // Pausa de lectura al llegar a cada punto
            if (pauseUntil != null) {
                if (now < pauseUntil) {
                    // Solo actualizar el texto de tiempo
                    var elapsedPause = Date.now() - trazadoStartMs;
                    var restPause = Math.max(0, duracionTotalEstMs - elapsedPause);
                    updateTrazadoTiempoLabel('En curso: ' + fmtMs(elapsedPause) + ' · Rest: ' + fmtMs(restPause));
                    trazadoAnimacionFrameId = requestAnimationFrame(frame);
                    return;
                }
                // Fin de pausa, siguiente segmento
                pauseUntil = null;
                currentSeg += 1;
                if (currentSeg >= tramos) {
                    // Terminó el último punto
                    try {
                        var last = puntos[puntos.length - 1];
                        if (last) trazadoMarkerAuto.setLatLng([last.lat, last.lng]);
                    } catch (eLast) {}
                    try {
                        if (trazadoPolylineLive && map.hasLayer(trazadoPolylineLive)) {
                            trazadoPolylineLive.setLatLngs(puntos.map(function (pp) { return [pp.lat, pp.lng]; }));
                        }
                    } catch (eEndL) {}
                    trazadoIsPlaying = false;
                    updateTrazadoTiempoLabel('Final: ' + fmtMs(Date.now() - trazadoStartMs) + ' · Rest: 0:00');
                    trazadoAnimacionFrameId = null;
                    return;
                }
                segStartTime = now;
            }

            var from = puntos[currentSeg];
            var to = puntos[currentSeg + 1];
            var segElapsed = now - segStartTime;
            var t = Math.min(1, segElapsed / segMs);

            var lat = from.lat + t * (to.lat - from.lat);
            var lng = from.lng + t * (to.lng - from.lng);
            try { trazadoMarkerAuto.setLatLng([lat, lng]); } catch (eM) {}

            // Línea live: desde todos los puntos anteriores + este punto interpolado
            try {
                if (trazadoPolylineLive && map.hasLayer(trazadoPolylineLive)) {
                    var pts = livePoints.slice();
                    pts.push([lat, lng]);
                    trazadoPolylineLive.setLatLngs(pts);
                }
            } catch (eLive) {}

            // Tiempo real (transcurrido / restante)
            var realElapsed = Date.now() - trazadoStartMs;
            var rest = Math.max(0, duracionTotalEstMs - realElapsed);
            updateTrazadoTiempoLabel('En curso: ' + fmtMs(realElapsed) + ' · Rest: ' + fmtMs(rest));

            if (t >= 1) {
                // Llegamos al punto final del segmento: fijar autito y extender base
                try { map.panTo([to.lat, to.lng], { animate: true, duration: 0.25 }); } catch (ePan) {}
                livePoints.push([to.lat, to.lng]);
                try {
                    if (trazadoPolylineLive && map.hasLayer(trazadoPolylineLive)) {
                        trazadoPolylineLive.setLatLngs(livePoints.slice());
                    }
                } catch (eLive2) {}

                // Abrir detalle del impacto en el punto de destino
                (function (ptLocal) {
                    fetchImpactoParaTrazado(ptLocal).then(function (imp) {
                        if (!imp) return;
                        openPanelDetalle(imp);
                    });
                })(to);
                trazadoLastDetailIdx = currentSeg + 1;

                // Programar pausa antes del siguiente segmento
                pauseUntil = performance.now() + pausaMs;
            }

            trazadoAnimacionFrameId = requestAnimationFrame(frame);
        }

        trazadoAnimacionFrameId = requestAnimationFrame(frame);
    }

    function playTrazadoAnimacion() {
        if (!map) return;
        // Si no tenemos puntos cargados (por ej. Trazado estaba apagado al aplicar filtros),
        // cargar primero desde el backend con los últimos filtros y recién después animar.
        if (!trazadoPuntos || trazadoPuntos.length < 2) {
            if (!lastAppliedParams) return;
            fetchTrazado(lastAppliedParams).then(function (res) {
                drawTrazado(res.puntos || [], res);
                // Si después de dibujar hay suficientes puntos, iniciar animación.
                if (trazadoPuntos && trazadoPuntos.length >= 2) {
                    _playTrazadoAnimacionCore();
                }
            }).catch(function () { });
            return;
        }
        _playTrazadoAnimacionCore();
    }

    function pauseTrazadoAnimacion() {
        stopTrazadoAnimacion();
        closePanel();
        updateTrazadoTiempoLabel('Pausado');
    }

    function updateClusterToggleVisibility() {
        var wrap = document.getElementById('cluster-toggle-wrap');
        if (!wrap) return;
        if (isVistaRuta()) wrap.classList.add('d-none');
        else wrap.classList.remove('d-none');
    }

    function isClusterEnabled() {
        var cb = document.getElementById('toggle-cluster');
        return !!(cb && cb.checked);
    }

    function _createMarkersLayer(clusterEnabled) {
        if (!map) return null;
        if (clusterEnabled && typeof L !== 'undefined' && typeof L.markerClusterGroup === 'function') {
            return L.markerClusterGroup({
                showCoverageOnHover: false,
                spiderfyOnMaxZoom: true,
                disableClusteringAtZoom: 16,
                maxClusterRadius: 55,
                // Mostrar suma de impactos (no cantidad de puntos)
                iconCreateFunction: function (cluster) {
                    var markers = cluster.getAllChildMarkers ? cluster.getAllChildMarkers() : [];
                    var sum = 0;
                    for (var i = 0; i < markers.length; i++) {
                        var m = markers[i];
                        var v = 0;
                        try { v = (m && m.options && m.options.sabanaImpactosCount != null) ? parseInt(m.options.sabanaImpactosCount, 10) : 0; } catch (e) {}
                        if (!isNaN(v) && v > 0) sum += v;
                    }
                    var size = (sum < 10) ? 'small' : (sum < 100 ? 'medium' : 'large');
                    return L.divIcon({
                        html: '<div><span>' + sum + '</span></div>',
                        className: 'marker-cluster marker-cluster-' + size,
                        iconSize: L.point(40, 40)
                    });
                }
            });
        }
        return L.layerGroup();
    }

    function rebuildMarkersLayer() {
        if (!map) return;
        try {
            if (markersLayer && map.hasLayer(markersLayer)) map.removeLayer(markersLayer);
        } catch (e) {}
        markersLayer = _createMarkersLayer(isClusterEnabled());
        if (markersLayer) markersLayer.addTo(map);
        // Re-render si estamos en vista Celdas
        if (!isVistaRuta()) {
            try { addMarkers(lastPuntosCeldas || []); } catch (e) {}
        }
    }

    function initMap() {
        if (map) return;
        map = L.map('mapa-sabana').setView([-34.6, -58.4], 10);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap'
        }).addTo(map);

        // Pane para resaltados: siempre al frente de los pines
        try {
            if (!map.getPane('sabanaHighlightPane')) {
                var p = map.createPane('sabanaHighlightPane');
                // markerPane suele ser ~600; popupPane ~700. Lo ponemos más alto.
                p.style.zIndex = 850;
                p.style.pointerEvents = 'none';
            }
        } catch (e) {}
        markersLayer = _createMarkersLayer(isClusterEnabled());
        if (markersLayer) markersLayer.addTo(map);
        rutaLayer = L.layerGroup().addTo(map);
        explosionLayer = L.layerGroup().addTo(map);

        // Cerrar spiderfy al click afuera (evita duplicaciones)
        map.on('click', function (ev) {
            try {
                var t = ev && ev.originalEvent ? ev.originalEvent.target : null;
                if (t && (t.closest('.leaflet-marker-icon') || t.closest('.leaflet-popup'))) return;
            } catch (e) {}
            clearExplosion();
            // si clickea afuera, también cerrar panel
            closePanel();
        });
        // Si el usuario hace zoom/pan, recomputamos spiderfy al final para que no se “cierre” y no quede desalineado.
        map.on('zoomstart', function () { clearExplosion(); });
        map.on('zoomend', function () {
            // Spiderfy deshabilitado (ver showSpiderfy)
        });
        // dragstart evita limpiar por autopan del popup (movestart) y permite re-click sin “alejar”
        map.on('dragstart', function () { clearExplosion(); });
        map.on('dragend', function () {
            // Spiderfy deshabilitado (ver showSpiderfy)
        });
    }

    function clearMarkers() {
        if (markersLayer) markersLayer.clearLayers();
        clearExplosion();
        clearAzimuth();
    }

    function clearExplosion() {
        if (explosionLayer) explosionLayer.clearLayers();
        spiderKey = null;
        // limpiar referencias a marcadores de spiderfy
        impactMarkerMap.clear();
    }

    function clearRuta() {
        if (rutaLayer) rutaLayer.clearLayers();
        if (polyline && map) map.removeLayer(polyline);
        polyline = null;
        rutaPuntos = [];
        stopAnimacion();
        if (markerAuto && map) map.removeLayer(markerAuto);
        markerAuto = null;
        impactMarkerMap.clear();
        clearAzimuth();
        if (highlightCircle && map && map.hasLayer(highlightCircle)) {
            map.removeLayer(highlightCircle);
        }
        highlightCircle = null;
        if (highlightMarker && map && map.hasLayer(highlightMarker)) {
            map.removeLayer(highlightMarker);
        }
        highlightMarker = null;
        var info = document.getElementById('ruta-info');
        if (info) info.textContent = 'Puntos: 0';
    }

    function highlightImpact(impacto, fallbackLatLng) {
        if (!map) return;
        var id = impacto && impacto.id != null ? String(impacto.id) : null;
        var tipo = impacto && impacto.tipo != null ? String(impacto.tipo) : '';
        var key = id ? (tipo + '|' + id) : null;
        var latlng = null;
        if (key && impactMarkerMap.has(key)) {
            latlng = impactMarkerMap.get(key).latlng;
        }
        if (!latlng && fallbackLatLng) latlng = fallbackLatLng;
        if (!latlng) return;
        try {
            if (highlightCircle && map.hasLayer(highlightCircle)) map.removeLayer(highlightCircle);
            if (highlightMarker && map.hasLayer(highlightMarker)) map.removeLayer(highlightMarker);
        } catch (e) {}
        highlightCircle = L.circleMarker(latlng, {
            radius: 14,
            color: '#ffc107',
            weight: 3,
            fillColor: '#ffc107',
            fillOpacity: 0.15,
            pane: 'sabanaHighlightPane'
        }).addTo(map);
        try { if (highlightCircle.bringToFront) highlightCircle.bringToFront(); } catch (eB) {}

        // Mostrar el número de orden arriba del punto seleccionado, para que “se vea el #1”
        if (impacto && impacto._ord != null) {
            var ordTxt = String(impacto._ord);
            var icon = L.divIcon({
                className: 'sabana-selected-ord-icon',
                html: '<span class="sabana-selected-ord">#' + escapeHtml(ordTxt) + '</span>',
                iconSize: [56, 56],
                iconAnchor: [28, 28]
            });
            highlightMarker = L.marker(latlng, {
                icon: icon,
                keyboard: false,
                interactive: false,
                pane: 'sabanaHighlightPane',
                zIndexOffset: 100000
            }).addTo(map);
            try { if (highlightMarker.setZIndexOffset) highlightMarker.setZIndexOffset(100000); } catch (eZ) {}
            try { if (highlightMarker.bringToFront) highlightMarker.bringToFront(); } catch (eF) {}
        } else {
            highlightMarker = null;
        }
        try { map.panTo(latlng, { animate: true, duration: 0.3 }); } catch (e2) {}
        // Sector de azimut (si hay info disponible)
        try { drawAzimuthForImpact(impacto, latlng); } catch (eAz) {}
        // Se mantiene hasta seleccionar otro registro o cerrar panel.
    }

    function clearAzimuth() {
        try {
            if (azimuthLayer && map) {
                map.removeLayer(azimuthLayer);
            }
        } catch (e) {}
        azimuthLayer = null;
    }

    function drawAzimuthForImpact(imp, latlngOverride) {
        if (!map) return;
        clearAzimuth();
        var lat = null;
        var lng = null;
        try {
            if (latlngOverride) {
                lat = latlngOverride.lat;
                lng = latlngOverride.lng;
            } else if (imp._punto_lat != null && imp._punto_lng != null) {
                lat = parseFloat(imp._punto_lat);
                lng = parseFloat(imp._punto_lng);
            }
        } catch (eLL) {}
        if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) return;

        // Azimuth y apertura horizontal
        var az = null;
        var aHoriz = null;
        try {
            if (imp._azimuth != null) az = parseFloat(String(imp._azimuth).replace(',', '.'));
            else if (imp.azimuth != null) az = parseFloat(String(imp.azimuth).replace(',', '.'));
        } catch (eAz) {}
        try {
            if (imp._a_horiz != null) aHoriz = parseFloat(String(imp._a_horiz).replace(',', '.'));
            else if (imp.a_horiz != null) aHoriz = parseFloat(String(imp.a_horiz).replace(',', '.'));
        } catch (eAH) {}
        if (isNaN(az)) return;
        if (isNaN(aHoriz) || !aHoriz || aHoriz <= 0) aHoriz = 60; // apertura por defecto

        // Radio de cobertura aproximado
        var radKm = null;
        try {
            if (imp._rad_cob_km != null) radKm = parseFloat(String(imp._rad_cob_km).replace(',', '.'));
            else if (imp.rad_cob_km != null) radKm = parseFloat(String(imp.rad_cob_km).replace(',', '.'));
        } catch (eRad) {}
        if (isNaN(radKm) || !radKm || radKm <= 0) radKm = 3; // 3 km por defecto

        var radiusMeters = radKm * 1000;
        var centerLat = lat;
        var centerLng = lng;

        // Aproximación simple: 1° lat ≈ 111_320 m, 1° lon ≈ 111_320 * cos(lat)
        var metersPerDegLat = 111320;
        var metersPerDegLng = metersPerDegLat * Math.cos(centerLat * Math.PI / 180);

        function offsetLatLng(centerLat, centerLng, distanceMeters, bearingDeg) {
            var brad = bearingDeg * Math.PI / 180;
            var dx = distanceMeters * Math.sin(brad);
            var dy = distanceMeters * Math.cos(brad);
            var dLat = dy / metersPerDegLat;
            var dLng = dx / metersPerDegLng;
            return [centerLat + dLat, centerLng + dLng];
        }

        var half = aHoriz / 2;
        var startAngle = az - half;
        var endAngle = az + half;
        var step = Math.max(5, Math.min(15, aHoriz / 6)); // ~6 segmentos

        var pts = [];
        pts.push([centerLat, centerLng]);
        for (var ang = startAngle; ang <= endAngle; ang += step) {
            pts.push(offsetLatLng(centerLat, centerLng, radiusMeters, ang));
        }
        pts.push(offsetLatLng(centerLat, centerLng, radiusMeters, endAngle));
        pts.push([centerLat, centerLng]);

        azimuthLayer = L.polygon(pts, {
            color: '#0d6efd',
            weight: 1,
            fillColor: '#0d6efd',
            fillOpacity: 0.15,
            pane: 'sabanaHighlightPane'
        }).addTo(map);
    }

    function _makeCeldaIcon(punto, txtOverride) {
        var col = (colorMode === 'sujeto' || colorMode === 'carga') ? getColorForImpact(null, punto) : null;
        var st = col ? (' style="background:' + col.bg + ';color:' + col.fg + ';"') : '';
        var txt = (txtOverride != null) ? String(txtOverride) : '';
        return L.divIcon({
            className: 'sabana-celda-pin',
            html: '<span class="sabana-celda-num"' + st + '>' + escapeHtml(txt) + '</span>',
            iconSize: [34, 34],
            iconAnchor: [17, 17]
        });
    }

    function updateSelectedCeldaMarker(punto, ord) {
        // Restaurar anterior (vuelve a su número base)
        try {
            if (lastSelectedCeldaKey && celdaMarkerMap && celdaMarkerMap.has(lastSelectedCeldaKey)) {
                var prevM = celdaMarkerMap.get(lastSelectedCeldaKey);
                if (prevM) {
                    var baseTxt = (prevM._baseTxt != null) ? prevM._baseTxt : '';
                    prevM.setIcon(_makeCeldaIcon(prevM._punto || punto, baseTxt));
                }
            }
        } catch (ePrev) {}

        var key = [String(punto.tipo || ''), normCeldaId(punto.celda_id)].join('|');
        lastSelectedCeldaKey = key;
        if (!celdaMarkerMap || !celdaMarkerMap.has(key)) return;
        var m = celdaMarkerMap.get(key);
        if (!m) return;
        if (m._baseTxt == null) m._baseTxt = '';
        m.setIcon(_makeCeldaIcon(m._punto || punto, String(ord)));
    }

    function formatFecha(fechaIso) {
        if (!fechaIso) return '—';
        try {
            var d = new Date(fechaIso);
            return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
        } catch (e) {
            return fechaIso;
        }
    }

    function _spiderfyPositions(centerLatLng, n) {
        if (!map) return [];
        var centerPt = map.latLngToLayerPoint(centerLatLng);
        var offsets = [];
        if (n <= 8) {
            var radius = 42;
            for (var i = 0; i < n; i++) {
                var a = (2 * Math.PI * i) / n;
                offsets.push([radius * Math.cos(a), radius * Math.sin(a)]);
            }
        } else {
            // Espiral: prolijo y sin solaparse con muchos elementos
            var separation = 10;
            var lengthFactor = 6;
            for (var j = 0; j < n; j++) {
                var angle = j * 0.55;
                var r = separation + j * lengthFactor;
                offsets.push([r * Math.cos(angle), r * Math.sin(angle)]);
            }
        }
        return offsets.map(function (xy) {
            var p = centerPt.add(L.point(xy[0], xy[1]));
            return map.layerPointToLatLng(p);
        });
    }

    function _impactoDateKey(imp) {
        if (!imp) return 0;
        var f = (imp.fecha || '').toString().trim(); // suele venir YYYY-MM-DD o ISO
        var h = (imp.hora || '').toString().trim();  // HH:MM(:SS)?
        if (!f) return 0;
        if (!h) h = '00:00:00';
        if (h.length === 5) h = h + ':00';
        try {
            var d = new Date(f + 'T' + h);
            var t = d.getTime();
            return isNaN(t) ? 0 : t;
        } catch (e) {
            // fallback lexicográfico
            return 0;
        }
    }

    function _sortImpactosCronologico(items) {
        return (items || []).slice().sort(function (a, b) {
            var ta = _impactoDateKey(a);
            var tb = _impactoDateKey(b);
            if (ta && tb && ta !== tb) return ta - tb;
            // fallback: fecha/hora string
            var sa = ((a && a.fecha) ? String(a.fecha) : '') + ' ' + ((a && a.hora) ? String(a.hora) : '');
            var sb = ((b && b.fecha) ? String(b.fecha) : '') + ' ' + ((b && b.hora) ? String(b.hora) : '');
            return sa.localeCompare(sb);
        });
    }

    function showSpiderfy(punto) {
        // Deshabilitado: el “enjambre/spiderfy” confunde el flujo de navegación por orden global.
        // La navegación se hace con Prev/Next (gotoOrden) y el mapa resalta un solo punto.
        return;
        if (!punto || !punto.impactos || punto.impactos.length === 0 || !map) return;

        var key = (punto.celda_id || '') + '|' + String(punto.lat) + '|' + String(punto.lng);
        clearExplosion();
        spiderKey = key;

        var center = L.latLng(parseFloat(punto.lat), parseFloat(punto.lng));
        // Se asume que ya viene numerado globalmente (imp._ord). Si no, ordenamos local como fallback.
        var items = (punto.impactos || []).slice();
        var anyOrd = items.some(function (x) { return x && x._ord != null; });
        if (!anyOrd) items = _sortImpactosCronologico(items);
        var n = items.length;
        var targets = _spiderfyPositions(center, n);

        for (var k = 0; k < n; k++) {
            var ll = targets[k];
            var imp = items[k];
            var num = (imp && imp._ord != null) ? imp._ord : (k + 1);
            var col = getColorForImpact(imp, punto);
            var style = col ? (' style="background:' + col.bg + ';color:' + col.fg + ';border-color:rgba(255,255,255,0.9);"') : '';
            var isSel = false;
            try {
                isSel = !!(currentPanelImpacto && imp && currentPanelImpacto.id != null && imp.id != null && String(currentPanelImpacto.id) === String(imp.id));
            } catch (eSel) {}
            var cls = 'sabana-spider-num' + (isSel ? ' sabana-spider-num-selected' : '');

            // Línea desde el centro
            var leg = L.polyline([center, ll], {
                color: '#6c757d',
                weight: 1,
                opacity: 0.85,
                interactive: false,
                className: 'sabana-spider-leg'
            });
            explosionLayer.addLayer(leg);

            // Pin numerado
            var icon = L.divIcon({
                className: 'sabana-spider-pin',
                html: '<span class="' + cls + '"' + style + '>' + num + '</span>',
                iconSize: [26, 26],
                iconAnchor: [13, 13]
            });
            var m = L.marker(ll, { icon: icon, keyboard: false });
            (function (impLocal, numLocal, atLat, atLng) {
                m.on('click', function (e) {
                    if (e && e.originalEvent) L.DomEvent.stopPropagation(e.originalEvent);
                    openPanelDetalle(impLocal);
                    highlightImpact(impLocal, L.latLng(atLat, atLng));
                });
                var celdaTxt = '';
                try {
                    var c = impLocal && impLocal._punto_celda_id ? impLocal._punto_celda_id :
                        (impLocal && impLocal.tipo === 'gprs' ? (impLocal.celda || '') : (impLocal && impLocal.celda_id ? impLocal.celda_id : ''));
                    if (c) celdaTxt = ' — ' + String(c);
                } catch (eCel2) {}
                m.bindTooltip('# ' + numLocal + ' ' + (impLocal.fecha ? formatFecha(impLocal.fecha) : '') + ' ' + (impLocal.hora || '') + celdaTxt, { permanent: false, direction: 'top' });
            })(imp, num, ll.lat, ll.lng);
            explosionLayer.addLayer(m);
            if (imp && imp.id != null) {
                impactMarkerMap.set(String(imp.tipo || '') + '|' + String(imp.id), { latlng: ll, marker: m });
            }
        }
    }

    // (popups/modales eliminados) — se usa panel sobre el mapa

    function addMarkers(puntos, opts) {
        if (!markersLayer || !map) return;
        opts = opts || {};
        lastPuntosCeldas = Array.isArray(puntos) ? puntos : [];
        clearMarkers();
        try { celdaMarkerMap.clear(); } catch (eCM) {}
        lastSelectedCeldaKey = null;
        if (!opts.keepPanel) closePanel();
        var bounds = [];

        // Si viene resumen (sin impactos), no podemos numerar global; se numera local al click.
        var anyImpactos = (puntos || []).some(function (pt) { return pt && Array.isArray(pt.impactos) && pt.impactos.length; });
        if (anyImpactos) {
            // Numeración cronológica GLOBAL (según filtros actuales)
            var flat = [];
            (puntos || []).forEach(function (pt) {
                (pt.impactos || []).forEach(function (imp) {
                    if (!imp) return;
                    flat.push(imp);
                });
            });
            var sorted = _sortImpactosCronologico(flat);
            for (var oi = 0; oi < sorted.length; oi++) {
                sorted[oi]._ord = oi + 1;
            }
        }

        var progressive = isOrdenEnabled() && isOrdenProgressiveEnabled();
        var visibleMax = progressive ? ordenVisibleMax : null;

        // Agrupar celdas técnicas por coordenada (muchas celdas pueden compartir el mismo lat/lng).
        // Si no agrupamos, un pin puede "tapar" al otro y se ve #39 aunque exista un #1 debajo.
        var groups = new Map(); // key: "tipo|lat|lng" -> { tipo, lat, lng, puntos:[], ordMinMin, ordMaxMax, countSum, repPunto }
        (puntos || []).forEach(function (p) {
            if (!p || p.lat == null || p.lng == null) return;
            var lat = parseFloat(p.lat);
            var lng = parseFloat(p.lng);
            if (isNaN(lat) || isNaN(lng)) return;
            var ck = String(p.tipo || '') + '|' + _coordKey(lat, lng);
            var g = groups.get(ck);
            if (!g) {
                g = {
                    tipo: p.tipo,
                    lat: lat,
                    lng: lng,
                    puntos: [],
                    ordMinMin: null,
                    ordMaxMax: null,
                    countSum: 0,
                    repPunto: p
                };
                groups.set(ck, g);
            }
            g.puntos.push(p);
            var count = (p.impactos && p.impactos.length) || (p.impactos_count || 0);
            g.countSum += (count || 0);

            var ordKey = [p.tipo, normCeldaId(p.celda_id)].join('|');
            var ordInfo = ordenMap ? ordenMap[ordKey] : null;
            var ordMin = ordInfo && ordInfo.ord_min != null ? ordInfo.ord_min : null;
            var ordMax = ordInfo && ordInfo.ord_max != null ? ordInfo.ord_max : null;
            if (ordMin != null) {
                if (g.ordMinMin == null || ordMin < g.ordMinMin) {
                    g.ordMinMin = ordMin;
                    g.repPunto = p;
                }
            }
            if (ordMax != null) {
                if (g.ordMaxMax == null || ordMax > g.ordMaxMax) g.ordMaxMax = ordMax;
            }
        });

        Array.from(groups.values()).forEach(function (g) {
            if (!g) return;
            // Modo “progresivo”: mostrar solo puntos cuyo primer impacto sea <= visibleMax
            if (progressive && visibleMax != null) {
                if (g.ordMinMin == null) return;
                if (g.ordMinMin > visibleMax) return;
            }

            var p = g.repPunto || (g.puntos && g.puntos[0]);
            if (!p) return;
            var lat = g.lat;
            var lng = g.lng;

            var label = (p.celda_direccion || p.celda_id || 'Celda') + ' — ' + (g.countSum || 0) + ' impacto(s)';
            if (g.puntos && g.puntos.length > 1) {
                label += ' (' + g.puntos.length + ' celdas)';
            }

            var baseTxt = (isOrdenEnabled())
                ? (g.ordMinMin != null ? g.ordMinMin : '?')
                : (g.countSum || 0);

            var icon = _makeCeldaIcon(p, String(baseTxt));
            var m = L.marker([lat, lng], { icon: icon, keyboard: false, sabanaImpactosCount: (g.countSum || 0) });
            m._punto = p;
            m._baseTxt = String(baseTxt);
            m._group = g;
            // Mapear TODAS las celdas del grupo al mismo marcador (para selección por gotoOrden)
            try {
                (g.puntos || []).forEach(function (pt) {
                    var k = [pt.tipo, normCeldaId(pt.celda_id)].join('|');
                    celdaMarkerMap.set(k, m);
                });
            } catch (eSet) {}

            m.on('click', function (e) {
                if (e && e.originalEvent) L.DomEvent.stopPropagation(e.originalEvent);

                function _sortByOrdOrTime(items) {
                    var arr = (items || []).slice();
                    var anyOrd = arr.some(function (x) { return x && x._ord != null; });
                    if (anyOrd) {
                        arr.sort(function (a, b) {
                            var oa = (a && a._ord != null) ? parseInt(a._ord, 10) : null;
                            var ob = (b && b._ord != null) ? parseInt(b._ord, 10) : null;
                            if (oa != null && ob != null && oa !== ob) return oa - ob;
                            return _impactoDateKey(a) - _impactoDateKey(b);
                        });
                        return arr;
                    }
                    return _sortImpactosCronologico(arr);
                }

                var openWithImpactos = function (impactos, puntoRef) {
                    var pr = puntoRef || p;
                    pr.impactos = Array.isArray(impactos) ? impactos : [];
                    try { pr.impactos_count = pr.impactos.length; } catch (eCnt) {}
                    pr._impactosLoaded = true;
                    // Guardar lista en memoria para "Volver", pero abrir detalle del primer registro.
                    currentPanelPunto = pr;
                    currentPanelImpactos = _sortByOrdOrTime(pr.impactos || []);
                    if (currentPanelImpactos && currentPanelImpactos.length) {
                        openPanelDetalle(currentPanelImpactos[0]);
                        try {
                            if (isOrdenEnabled() && currentPanelImpactos[0] && currentPanelImpactos[0]._ord != null) {
                                updateSelectedCeldaMarker(pr, currentPanelImpactos[0]._ord);
                            }
                        } catch (ePin2) {}
                    } else {
                        renderPanelList(pr, []);
                    }
                };

                var openSpiderAndPopup = function () {
                    var params = lastAppliedParams || {};
                    var siblings = (g && g.puntos && g.puntos.length) ? g.puntos : [p];
                    var tasks = siblings.map(function (pt) {
                        if (Array.isArray(pt.impactos) && pt.impactos.length) {
                            // Asegurar etiqueta de origen incluso si viene cacheado
                            try {
                                pt.impactos.forEach(function (imp) {
                                    if (!imp) return;
                                    if (imp._punto_celda_id == null) {
                                        imp._punto_tipo = pt.tipo;
                                        imp._punto_carga_id = pt.carga_id;
                                        imp._punto_celda_id = pt.celda_id;
                                        imp._punto_lat = pt.lat;
                                        imp._punto_lng = pt.lng;
                                    }
                                });
                            } catch (eTag2) {}
                            return Promise.resolve(pt.impactos);
                        }
                        return fetchCeldaImpactos(pt, params);
                    });
                    Promise.all(tasks).then(function (lists) {
                        var seen = {};
                        var merged = [];
                        (lists || []).forEach(function (arr) {
                            (Array.isArray(arr) ? arr : []).forEach(function (imp) {
                                if (!imp || imp.id == null) return;
                                var k = String(imp.tipo || '') + '|' + String(imp.id);
                                if (seen[k]) return;
                                seen[k] = true;
                                merged.push(imp);
                            });
                        });
                        // Usar un "punto ref" estable para el panel (el de menor ordMin si existe)
                        openWithImpactos(merged, p);
                    }).catch(function () {
                        openWithImpactos([], p);
                    });
                };

                if (map.getZoom() < 16) {
                    map.setView([lat, lng], 16);
                    map.once('moveend', openSpiderAndPopup);
                } else {
                    openSpiderAndPopup();
                }
            });
            var tip = label;
            if (isOrdenEnabled() && g.ordMinMin != null) {
                tip += ' — Primero: #' + g.ordMinMin + (g.ordMaxMax != null && g.ordMaxMax !== g.ordMinMin ? (' (hasta #' + g.ordMaxMax + ')') : '');
            }
            m.bindTooltip(tip, { permanent: false, direction: 'top' });
            markersLayer.addLayer(m);
            bounds.push([lat, lng]);
        });
        if (!opts.keepView) {
            if (bounds.length > 1) {
                map.fitBounds(bounds, { padding: [20, 20] });
            } else if (bounds.length === 1) {
                map.setView(bounds[0], 14);
            }
        }
    }

    function verLineaCompleta() {
        var cb = document.getElementById('ver-linea-completa');
        return cb && cb.checked;
    }

    function drawRuta(puntos, meta) {
        clearRuta();
        if (!puntos || puntos.length === 0) {
            var info = document.getElementById('ruta-info');
            if (info) info.textContent = 'Puntos: 0';
            return;
        }
        rutaPuntos = puntos;
        window._rutaMeta = meta || null;
        var latlngs = puntos.map(function (p) { return [p.lat, p.lng]; });
        if (verLineaCompleta()) {
            polyline = L.polyline(latlngs, { color: '#0d6efd', weight: 4, opacity: 0.8 }).addTo(map);
        } else {
            polyline = L.polyline([], { color: '#0d6efd', weight: 4, opacity: 0.8 }).addTo(map);
        }
        // Mostrar todos los puntos. (Antes se dibujaban ~600 para evitar saturación.)
        var step = 1;
        for (var i = 0; i < puntos.length; i++) {
            var p = puntos[i];
            var col = getColorForImpact(p && p.impacto ? p.impacto : null, p);
            var st = col ? (' style="background:' + col.bg + ';color:' + col.fg + ';"') : '';
            var icon = L.divIcon({
                className: 'sabana-ruta-num',
                html: '<span class="sabana-ruta-numero"' + st + '>' + (p.numero || (i + 1)) + '</span>',
                iconSize: [26, 26],
                iconAnchor: [13, 13]
            });
            var m = L.marker([p.lat, p.lng], { icon: icon });
            var imp = p.impacto;
            if (imp) {
                // asegurar que el panel muestre el orden cronológico
                if (p.numero != null) imp._ord = p.numero;
                m.on('click', function (ev) {
                    openPanelDetalle(ev.target._impacto);
                });
                m._impacto = imp;
            }
            m.bindTooltip('#' + (p.numero || (i + 1)) + ' ' + (p.hora || ''), { permanent: false, direction: 'top' });
            rutaLayer.addLayer(m);
            if (imp && imp.id != null) {
                impactMarkerMap.set(String(imp.tipo || '') + '|' + String(imp.id), { latlng: L.latLng(p.lat, p.lng), marker: m });
            }
        }
        if (latlngs.length > 0) {
            map.fitBounds(latlngs, { padding: [30, 30] });
        }
        var info = document.getElementById('ruta-info');
        if (info) {
            var txt = 'Puntos: ' + puntos.length + ' — Orden cronológico: 1 (primero) → … → ' + puntos.length + ' (último).';
            if (window._rutaMeta && window._rutaMeta.total != null && window._rutaMeta.total > puntos.length) {
                txt = 'Recorrido completo (de punta a punta) representado por ' + puntos.length + ' puntos de ' + window._rutaMeta.total + ' total. ' + txt;
            }
            info.textContent = txt + (verLineaCompleta() ? ' Use Play para recorrido.' : ' Dé Play: la línea se irá trazando con el auto.');
        }
    }

    var animacionFrameId = null;

    function stopAnimacion() {
        if (animacionFrameId != null) {
            cancelAnimationFrame(animacionFrameId);
            animacionFrameId = null;
        }
        if (animacionInterval) {
            clearTimeout(animacionInterval);
            animacionInterval = null;
        }
    }

    function getSegundosPorTramo() {
        var sel = document.getElementById('ruta-velocidad');
        if (sel) {
            var v = parseFloat(sel.value.replace(',', '.'));
            if (!isNaN(v) && v > 0) return v;
        }
        return 1;
    }

    function getPausaLecturaMs() {
        var sel = document.getElementById('ruta-pausa-lectura');
        if (sel) {
            var v = parseInt(sel.value, 10);
            if (!isNaN(v) && v > 0) return v * 1000;
        }
        return 3000;
    }

    function getDuracionAnimacionMs(numPuntos) {
        var segPorTramo = getSegundosPorTramo();
        var tramos = Math.max(0, (numPuntos || 0) - 1);
        return tramos * segPorTramo * 1000;
    }

    function playAnimacion() {
        if (!rutaPuntos || rutaPuntos.length < 2) return;
        if (!map) return;
        stopAnimacion();
        if (markerAuto && map) {
            map.removeLayer(markerAuto);
            markerAuto = null;
        }
        var iconAuto = L.divIcon({
            className: 'sabana-marker-auto',
            html: '<span class="sabana-auto-icon">🚗</span>',
            iconSize: [32, 32],
            iconAnchor: [16, 16]
        });
        markerAuto = L.marker([rutaPuntos[0].lat, rutaPuntos[0].lng], { icon: iconAuto }).addTo(map);
        var puntos = rutaPuntos;
        var duracionMs = getDuracionAnimacionMs(puntos.length);
        var start = Date.now();
        var trazarAlAvanzar = !verLineaCompleta();
        var lastDetailIdx = -1;
        var lastPolylineIdx = -1;
        var polyBase = [];
        if (trazarAlAvanzar && polyline && map.hasLayer(polyline) && puntos.length) {
            polyBase = [[puntos[0].lat, puntos[0].lng]];
            lastPolylineIdx = 0;
            polyline.setLatLngs([]);
        }

        // Distancia acumulada por punto para que el auto recorra la línea a velocidad constante
        function distKm(a, b) {
            var R = 6371;
            var dLat = (b.lat - a.lat) * Math.PI / 180;
            var dLon = (b.lng - a.lng) * Math.PI / 180;
            var x = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                Math.cos(a.lat * Math.PI / 180) * Math.cos(b.lat * Math.PI / 180) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
            return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
        }
        var distAcum = [0];
        for (var d = 1; d < puntos.length; d++) {
            distAcum[d] = distAcum[d - 1] + distKm(puntos[d - 1], puntos[d]);
        }
        var totalKm = Math.max(distAcum[distAcum.length - 1] || 0, 0.001);

        function tick() {
            try {
                if (!markerAuto || !map.hasLayer(markerAuto)) {
                    animacionFrameId = null;
                    return;
                }
                var elapsed = Date.now() - start;
                var progress = Math.min(1, elapsed / duracionMs);
                var distanciaRecorrida = progress * totalKm;

                var idx = 0;
                var t = 0;
                for (var k = 0; k < distAcum.length - 1; k++) {
                    if (distanciaRecorrida >= distAcum[k] && distanciaRecorrida <= distAcum[k + 1]) {
                        idx = k;
                        var segLen = distAcum[k + 1] - distAcum[k];
                        t = segLen > 0 ? (distanciaRecorrida - distAcum[k]) / segLen : 0;
                        break;
                    }
                    if (k === distAcum.length - 2) {
                        idx = distAcum.length - 2;
                        t = 1;
                    }
                }
                if (idx >= puntos.length - 1) idx = puntos.length - 2;
                if (idx < 0) idx = 0;

                if (idx !== lastDetailIdx && puntos[idx] && puntos[idx].impacto) {
                    lastDetailIdx = idx;
                    var fromPt = puntos[idx];
                    openPanelDetalle(puntos[idx].impacto);
                    start += getPausaLecturaMs();
                }
                var from = puntos[idx];
                var to = puntos[idx + 1];
                var lat, lng;
                if (from && to) {
                    lat = from.lat + t * (to.lat - from.lat);
                    lng = from.lng + t * (to.lng - from.lng);
                } else {
                    lat = from ? from.lat : puntos[0].lat;
                    lng = from ? from.lng : puntos[0].lng;
                }
                markerAuto.setLatLng([lat, lng]);
                if (trazarAlAvanzar && polyline && map.hasLayer(polyline)) {
                    // Evitar recomputar todo el path en cada frame (O(n^2)).
                    if (idx < lastPolylineIdx) {
                        polyBase = [[puntos[0].lat, puntos[0].lng]];
                        lastPolylineIdx = 0;
                    }
                    if (idx > lastPolylineIdx) {
                        for (var j = Math.max(1, lastPolylineIdx + 1); j <= idx; j++) {
                            polyBase.push([puntos[j].lat, puntos[j].lng]);
                        }
                        lastPolylineIdx = idx;
                    }
                    var live = polyBase.slice();
                    live.push([lat, lng]);
                    polyline.setLatLngs(live);
                }
                if (progress >= 1) {
                    markerAuto.setLatLng([puntos[puntos.length - 1].lat, puntos[puntos.length - 1].lng]);
                    if (trazarAlAvanzar && polyline && map.hasLayer(polyline)) {
                        polyline.setLatLngs(puntos.map(function (p) { return [p.lat, p.lng]; }));
                    }
                    if (puntos[puntos.length - 1] && puntos[puntos.length - 1].impacto && lastDetailIdx !== puntos.length - 1) {
                        var ult = puntos[puntos.length - 1];
                        openPanelDetalle(ult.impacto);
                    }
                    animacionFrameId = null;
                    return;
                }
                animacionFrameId = requestAnimationFrame(tick);
            } catch (e) {
                animacionFrameId = null;
            }
        }
        animacionFrameId = requestAnimationFrame(tick);
    }

    function pauseAnimacion() {
        stopAnimacion();
        closePanel();
    }

    function resetAnimacion() {
        stopAnimacion();
        closePanel();
        if (markerAuto && map) {
            map.removeLayer(markerAuto);
            markerAuto = null;
        }
        if (!verLineaCompleta() && polyline && map.hasLayer(polyline)) {
            polyline.setLatLngs([]);
        }
        if (rutaPuntos.length > 0) {
            var iconAuto = L.divIcon({
                className: 'sabana-marker-auto',
                html: '<span class="sabana-auto-icon">🚗</span>',
                iconSize: [32, 32],
                iconAnchor: [16, 16]
            });
            markerAuto = L.marker([rutaPuntos[0].lat, rutaPuntos[0].lng], { icon: iconAuto }).addTo(map);
        }
    }

    function aplicarFiltros() {
        var token = ++lastRequestToken;
        var sujetoIds = getSelectedIds('filtro-sujetos');
        var cargaIds = getSelectedIds('filtro-cargas');
        var tipos = getSelectedTipos();
        var provincias = getSelectedStrings('filtro-provincias');
        var localidades = getSelectedStrings('filtro-localidades');
        var params = {
            sujeto_ids: sujetoIds,
            carga_ids: cargaIds,
            tipos: tipos,
            provincias: provincias,
            localidades: localidades,
            fecha_desde: getValue('filtro-fecha-desde') || null,
            fecha_hasta: getValue('filtro-fecha-hasta') || null,
            hora_desde: getValue('filtro-hora-desde') || null,
            hora_hasta: getValue('filtro-hora-hasta') || null,
            numeros: getSelectedNumeros(),
            imeis: getSelectedImeis()
        };
        lastAppliedParams = params;
        resetColoring(params);

        if (isVistaRuta()) {
            var panel = document.getElementById('panel-ruta');
            if (panel) panel.classList.remove('d-none');
            fetchRuta(params).then(function (res) {
                if (token !== lastRequestToken) return;
                drawRuta(res.puntos, { total: res.total, mostrando: res.mostrando });
                resetAnimacion();
            }).catch(function () {
                if (token !== lastRequestToken) return;
                drawRuta([], null);
            });
            clearMarkers();
        } else {
            var panel = document.getElementById('panel-ruta');
            if (panel) panel.classList.add('d-none');
            clearRuta();
            // Si se quiere ver orden en los pines, mejor sin cluster (si no, se ocultan los números).
            if (isOrdenEnabled()) {
                try {
                    var cbCluster = document.getElementById('toggle-cluster');
                    if (cbCluster && cbCluster.checked) {
                        cbCluster.checked = false;
                        try { localStorage.setItem('sabana_cluster_enabled', '0'); } catch (e) {}
                        rebuildMarkersLayer();
                    }
                } catch (e) {}
            }
            // Modo progresivo: al aplicar filtros, arrancar mostrando solo los primeros N órdenes
            if (isOrdenEnabled() && isOrdenProgressiveEnabled()) {
                resetOrdenVisibleMax();
            }

            var pOrden = isOrdenEnabled()
                ? Promise.all([
                    fetchOrdenCeldas(params).catch(function () { ordenMap = {}; }),
                    fetchOrdenImpactos(params).catch(function () { ordenImpactoMap = {}; })
                ])
                : Promise.resolve(null);

            pOrden.then(function () {
                if (token !== lastRequestToken) return;
                fetchImpactos(params).then(function (puntos) {
                    if (token !== lastRequestToken) return;
                    addMarkers(puntos);
                    // Trazado cronológico encima de “Celdas” (si está activado)
                    try {
                        if (isTrazadoEnabled()) {
                            fetchTrazado(params).then(function (res) {
                                if (token !== lastRequestToken) return;
                                drawTrazado(res.puntos || [], res);
                            }).catch(function () {
                                clearTrazado();
                            });
                        } else {
                            clearTrazado();
                        }
                    } catch (eTr) {}
                    // En Orden: enfocar automáticamente el inicio global (#1) para evitar confusión con “#39” locales.
                    if (isOrdenEnabled()) {
                        try {
                            var key = JSON.stringify(params || {}) + '|ord:1';
                            if (lastAutoFocusOrdenKey !== key) {
                                lastAutoFocusOrdenKey = key;
                                setTimeout(function () {
                                    try { gotoOrden(1); } catch (e) {}
                                }, 200);
                            }
                        } catch (eKey) {}
                    }
                }).catch(function () {
                    if (token !== lastRequestToken) return;
                    addMarkers([]);
                    clearTrazado();
                });
            });
        }
    }

    function init() {
        var cbCluster = document.getElementById('toggle-cluster');
        if (cbCluster) {
            // Restaurar preferencia (default: true)
            try {
                var saved = localStorage.getItem('sabana_cluster_enabled');
                if (saved != null) {
                    var s = String(saved).toLowerCase().trim();
                    cbCluster.checked = !(s === '0' || s === 'false' || s === 'no');
                }
            } catch (e) {}
            cbCluster.addEventListener('change', function () {
                try { localStorage.setItem('sabana_cluster_enabled', this.checked ? '1' : '0'); } catch (e) {}
                rebuildMarkersLayer();
            });
        }

        var cbOrden = document.getElementById('toggle-orden');
        if (cbOrden) {
            // Restaurar preferencia (default: false)
            try {
                var savedO = localStorage.getItem('sabana_orden_enabled');
                if (savedO != null) {
                    var so = String(savedO).toLowerCase().trim();
                    cbOrden.checked = (so === '1' || so === 'true' || so === 'si' || so === 'sí');
                }
            } catch (e) {}
            cbOrden.addEventListener('change', function () {
                try { localStorage.setItem('sabana_orden_enabled', this.checked ? '1' : '0'); } catch (e) {}
                // Mostrar/ocultar “Progresivo” inmediatamente al cambiar Orden
                try { updateOrdenToggleVisibility(); } catch (eVis) {}
                scheduleAutoApply(0);
            });
        }

        var cbProg = document.getElementById('toggle-orden-prog');
        if (cbProg) {
            try {
                var savedP = localStorage.getItem('sabana_orden_progressive');
                if (savedP != null) {
                    var sp = String(savedP).toLowerCase().trim();
                    cbProg.checked = !(sp === '0' || sp === 'false' || sp === 'no');
                }
            } catch (e) {}
            // Preferencia: hasta qué # mostrar al iniciar (no confundir con el visible_max actual)
            var selMax = document.getElementById('orden-prog-max');
            if (selMax) {
                try {
                    var savedStart = localStorage.getItem('sabana_orden_progressive_max');
                    if (savedStart != null) {
                        selMax.value = String(savedStart);
                    }
                } catch (eS) {}
                selMax.addEventListener('change', function () {
                    try { localStorage.setItem('sabana_orden_progressive_max', String(this.value)); } catch (e) {}
                    // Si está activo, reiniciar el rango visible y re-aplicar para limpiar el mapa
                    if (isOrdenEnabled() && isOrdenProgressiveEnabled()) resetOrdenVisibleMax();
                    scheduleAutoApply(0);
                });
            }
            // Estado actual (persistente) del rango visible
            try {
                var savedMax = localStorage.getItem('sabana_orden_visible_max');
                if (savedMax != null) {
                    var sm = parseInt(String(savedMax).trim(), 10);
                    if (!isNaN(sm) && sm > 0) ordenVisibleMax = sm;
                }
            } catch (e2) {}
            cbProg.addEventListener('change', function () {
                try { localStorage.setItem('sabana_orden_progressive', this.checked ? '1' : '0'); } catch (e) {}
                if (this.checked) resetOrdenVisibleMax();
                updateOrdenProgressiveVisibility();
                scheduleAutoApply(0);
            });
        }

        var cbTrazado = document.getElementById('toggle-trazado');
        if (cbTrazado) {
            try {
                var savedT = localStorage.getItem('sabana_trazado_enabled');
                if (savedT != null) {
                    var st = String(savedT).toLowerCase().trim();
                    cbTrazado.checked = (st === '1' || st === 'true' || st === 'si' || st === 'sí');
                }
            } catch (eT) {}
            cbTrazado.addEventListener('change', function () {
                try { localStorage.setItem('sabana_trazado_enabled', this.checked ? '1' : '0'); } catch (e) {}
                updateTrazadoControlsVisibility();
                // No hace falta re-cargar todo: con los últimos filtros, dibujar/limpiar
                try {
                    if (this.checked && lastAppliedParams && !isVistaRuta()) {
                        fetchTrazado(lastAppliedParams).then(function (res) {
                            drawTrazado(res.puntos || [], res);
                        }).catch(function () { clearTrazado(); });
                    } else {
                        clearTrazado();
                    }
                } catch (e2) {}
            });
        }

        var btnPlayT = document.getElementById('btn-play-trazado');
        var btnPauseT = document.getElementById('btn-pause-trazado');
        var btnResetT = document.getElementById('btn-reset-trazado');
        if (btnPlayT) btnPlayT.addEventListener('click', function () { playTrazadoAnimacion(); });
        if (btnPauseT) btnPauseT.addEventListener('click', function () { pauseTrazadoAnimacion(); });
        if (btnResetT) btnResetT.addEventListener('click', function () { resetTrazadoAnimacion(); });
        var selVelT = document.getElementById('trazado-velocidad');
        if (selVelT) selVelT.addEventListener('change', function () { updateTrazadoTiempoLabel(trazadoIsPlaying ? 'En curso' : 'Listo'); });
        var selPauT = document.getElementById('trazado-pausa');
        if (selPauT) selPauT.addEventListener('change', function () { updateTrazadoTiempoLabel(trazadoIsPlaying ? 'En curso' : 'Listo'); });

        initMap();
        refreshMapSize(0);
        updateClusterToggleVisibility();
        updateOrdenToggleVisibility();
        updateTrazadoToggleVisibility();

        initPanelDrag();

        // Panel (sin modales)
        var btnPClose = document.getElementById('sabana-panel-close');
        if (btnPClose) btnPClose.addEventListener('click', function () { closePanel(); });
        var btnPBack = document.getElementById('sabana-panel-back');
        if (btnPBack) btnPBack.addEventListener('click', function () {
            if (!currentPanelPunto) return;
            // Si venimos de navegación global (gotoOrden), cargamos la lista recién al pedir "Volver"
            if (currentPanelPunto && currentPanelPunto._impactosLoaded === false) {
                var p = currentPanelPunto;
                fetchCeldaImpactos(p, lastAppliedParams || {}).then(function (items) {
                    if (!currentPanelPunto || !p) return;
                    // Si el usuario navegó a otra celda en el medio, no pisar
                    if (currentPanelPunto.celda_id !== p.celda_id || String(currentPanelPunto.carga_id) !== String(p.carga_id) || String(currentPanelPunto.tipo) !== String(p.tipo)) return;
                    p.impactos = Array.isArray(items) ? items : [];
                    p._impactosLoaded = true;
                    currentPanelImpactos = _sortImpactosCronologico(p.impactos || []);
                    renderPanelList(p, currentPanelImpactos);
                }).catch(function () {
                    p._impactosLoaded = true;
                    currentPanelImpactos = [];
                    renderPanelList(p, []);
                });
                return;
            }
            renderPanelList(currentPanelPunto, currentPanelImpactos);
        });
        var btnPrev = document.getElementById('sabana-panel-prev');
        var btnNext = document.getElementById('sabana-panel-next');
        if (btnPrev) btnPrev.addEventListener('click', function () {
            if (!currentPanelImpacto) return;
            // En modo Orden, Prev/Next siempre navega global por #ord (aunque cambie de celda)
            if (isOrdenEnabled() && currentPanelImpacto._ord != null) {
                gotoOrden(parseInt(currentPanelImpacto._ord, 10) - 1);
                return;
            }
            if (currentPanelImpactos && currentPanelImpactos.length) {
                var idx = currentPanelImpactos.findIndex(function (x) { return x && currentPanelImpacto && x.id != null && currentPanelImpacto.id != null && String(x.id) === String(currentPanelImpacto.id); });
                if (idx > 0) {
                    openPanelDetalle(currentPanelImpactos[idx - 1]);
                    return;
                }
            }
            if (currentPanelImpacto._ord != null) {
                gotoOrden(parseInt(currentPanelImpacto._ord, 10) - 1);
            }
        });
        if (btnNext) btnNext.addEventListener('click', function () {
            if (!currentPanelImpacto) return;
            // En modo Orden, Prev/Next siempre navega global por #ord (aunque cambie de celda)
            if (isOrdenEnabled() && currentPanelImpacto._ord != null) {
                gotoOrden(parseInt(currentPanelImpacto._ord, 10) + 1);
                return;
            }
            if (currentPanelImpactos && currentPanelImpactos.length) {
                var idx = currentPanelImpactos.findIndex(function (x) { return x && currentPanelImpacto && x.id != null && currentPanelImpacto.id != null && String(x.id) === String(currentPanelImpacto.id); });
                if (idx >= 0 && idx < currentPanelImpactos.length - 1) {
                    openPanelDetalle(currentPanelImpactos[idx + 1]);
                    return;
                }
            }
            if (currentPanelImpacto._ord != null) {
                gotoOrden(parseInt(currentPanelImpacto._ord, 10) + 1);
            }
        });

        // Ir a orden (buscador)
        var gotoInp = document.getElementById('goto-orden');
        var gotoBtn = document.getElementById('btn-goto-orden');
        var gotoInicioBtn = document.getElementById('btn-goto-inicio');
        function doGoto() {
            var v = gotoInp ? gotoInp.value : '';
            if (!v) return;
            // Necesita orden cargado (Orden=ON). Si no, lo activamos y reintentamos.
            var cbOrden = document.getElementById('toggle-orden');
            if (cbOrden && !cbOrden.checked) {
                cbOrden.checked = true;
                try { localStorage.setItem('sabana_orden_enabled', '1'); } catch (e) {}
                try { updateOrdenToggleVisibility(); } catch (eV) {}
                aplicarFiltros();
                // esperar un toque y reintentar
                setTimeout(function () { gotoOrden(v); }, 600);
                return;
            }
            gotoOrden(v);
        }
        if (gotoBtn) gotoBtn.addEventListener('click', doGoto);
        if (gotoInicioBtn) gotoInicioBtn.addEventListener('click', function () { gotoOrden(1); });
        if (gotoInp) gotoInp.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                doGoto();
            }
        });

        fetchFiltros().then(function (data) {
            renderCheckboxes('filtro-sujetos', data.sujetos || [], 'nombre', 'id');
            var cargas = (data.cargas || []).map(function (c) {
                return { id: c.id, nombre: (c.tipo || '') + ' - ' + (c.nombre_archivo || c.id) };
            });
            renderCheckboxes('filtro-cargas', cargas, 'nombre', 'id');
            updateDdCount('dd-sujetos', 'filtro-sujetos', 'Seleccionar…');
            updateDdCount('dd-cargas', 'filtro-cargas', 'Seleccionar…');
            updateDdTipos();
        });

        initDropdownSearch();
        renderNumerosSelected();
        renderImeisSelected();

        // Precargar provincias/localidades (desde datos subidos)
        fetchProvincias('', { sujeto_ids: [], carga_ids: [], tipos: [] }).then(function (items) {
            renderSimpleCheckboxList('filtro-provincias', items || [], 'prov');
            updateDdCount('dd-provincias', 'filtro-provincias', 'Seleccionar…');
        }).catch(function () {});
        fetchLocalidades('', { sujeto_ids: [], carga_ids: [], tipos: [], provincias: [] }).then(function (items) {
            renderSimpleCheckboxList('filtro-localidades', items || [], 'loc');
            updateDdCount('dd-localidades', 'filtro-localidades', 'Seleccionar…');
        }).catch(function () {});

        // Recalcular labels al tildar/destildar
        var sujetosEl = document.getElementById('filtro-sujetos');
        if (sujetosEl) sujetosEl.addEventListener('change', function () { updateDdCount('dd-sujetos', 'filtro-sujetos', 'Seleccionar…'); });
        var cargasEl = document.getElementById('filtro-cargas');
        if (cargasEl) cargasEl.addEventListener('change', function () { updateDdCount('dd-cargas', 'filtro-cargas', 'Seleccionar…'); });
        var tiposEl = document.getElementById('filtro-tipos');
        if (tiposEl) tiposEl.addEventListener('change', updateDdTipos);
        var provEl = document.getElementById('filtro-provincias');
        if (provEl) provEl.addEventListener('change', function () {
            updateDdCount('dd-provincias', 'filtro-provincias', 'Seleccionar…');
            // si cambian provincias, refrescar localidades (dependiente)
            var sujetoIds = getSelectedIds('filtro-sujetos');
            var cargaIds = getSelectedIds('filtro-cargas');
            var tipos = getSelectedTipos();
            var provincias = getSelectedStrings('filtro-provincias');
            fetchLocalidades('', { sujeto_ids: sujetoIds, carga_ids: cargaIds, tipos: tipos, provincias: provincias }).then(function (items) {
                renderSimpleCheckboxList('filtro-localidades', items || [], 'loc');
                updateDdCount('dd-localidades', 'filtro-localidades', 'Seleccionar…');
            }).catch(function () {});
        });
        var locEl = document.getElementById('filtro-localidades');
        if (locEl) locEl.addEventListener('change', function () { updateDdCount('dd-localidades', 'filtro-localidades', 'Seleccionar…'); });

        // Buscador de números (server-side) con debounce
        var numerosSearch = document.getElementById('numeros-search');
        if (numerosSearch) {
            numerosSearch.addEventListener('input', function () {
                var qTxt = (this.value || '').trim();
                if (numerosDebounceTimer) clearTimeout(numerosDebounceTimer);
                numerosDebounceTimer = setTimeout(function () {
                    var sujetoIds = getSelectedIds('filtro-sujetos');
                    var cargaIds = getSelectedIds('filtro-cargas');
                    var tipos = getSelectedTipos();
                    var provincias = getSelectedStrings('filtro-provincias');
                    var localidades = getSelectedStrings('filtro-localidades');
                    var tok = ++numerosQueryToken;
                    fetchNumeros(qTxt, {
                        sujeto_ids: sujetoIds,
                        carga_ids: cargaIds,
                        tipos: tipos,
                        provincias: provincias,
                        localidades: localidades,
                        fecha_desde: getValue('filtro-fecha-desde') || null,
                        fecha_hasta: getValue('filtro-fecha-hasta') || null,
                        hora_desde: getValue('filtro-hora-desde') || null,
                        hora_hasta: getValue('filtro-hora-hasta') || null
                    }).then(function (items) {
                        if (tok !== numerosQueryToken) return;
                        renderNumerosResultados(Array.isArray(items) ? items : []);
                    }).catch(function () {
                        if (tok !== numerosQueryToken) return;
                        renderNumerosResultados([]);
                    });
                }, 250);
            });
        }

        // Precargar números al abrir dropdown (desde archivos subidos)
        var ddNumeros = document.getElementById('dd-numeros');
        if (ddNumeros) {
            ddNumeros.addEventListener('shown.bs.dropdown', function () {
                var qTxt = (getValue('numeros-search') || '').trim();
                var sujetoIds = getSelectedIds('filtro-sujetos');
                var cargaIds = getSelectedIds('filtro-cargas');
                var tipos = getSelectedTipos();
                var provincias = getSelectedStrings('filtro-provincias');
                var localidades = getSelectedStrings('filtro-localidades');
                var tok = ++numerosQueryToken;
                fetchNumeros(qTxt, {
                    sujeto_ids: sujetoIds,
                    carga_ids: cargaIds,
                    tipos: tipos,
                    provincias: provincias,
                    localidades: localidades,
                    fecha_desde: getValue('filtro-fecha-desde') || null,
                    fecha_hasta: getValue('filtro-fecha-hasta') || null,
                    hora_desde: getValue('filtro-hora-desde') || null,
                    hora_hasta: getValue('filtro-hora-hasta') || null
                }).then(function (items) {
                    if (tok !== numerosQueryToken) return;
                    renderNumerosResultados(Array.isArray(items) ? items : []);
                }).catch(function () {});
            });
        }

        // Buscador de IMEIs (server-side) con debounce
        var imeisSearch = document.getElementById('imeis-search');
        if (imeisSearch) {
            imeisSearch.addEventListener('input', function () {
                var qTxt = (this.value || '').trim();
                if (imeisDebounceTimer) clearTimeout(imeisDebounceTimer);
                imeisDebounceTimer = setTimeout(function () {
                    var sujetoIds = getSelectedIds('filtro-sujetos');
                    var cargaIds = getSelectedIds('filtro-cargas');
                    var tipos = getSelectedTipos();
                    var provincias = getSelectedStrings('filtro-provincias');
                    var localidades = getSelectedStrings('filtro-localidades');
                    var tok = ++imeisQueryToken;
                    fetchImeis(qTxt, {
                        sujeto_ids: sujetoIds,
                        carga_ids: cargaIds,
                        tipos: tipos,
                        provincias: provincias,
                        localidades: localidades,
                        fecha_desde: getValue('filtro-fecha-desde') || null,
                        fecha_hasta: getValue('filtro-fecha-hasta') || null,
                        hora_desde: getValue('filtro-hora-desde') || null,
                        hora_hasta: getValue('filtro-hora-hasta') || null
                    }).then(function (items) {
                        if (tok !== imeisQueryToken) return;
                        renderImeisResultados(Array.isArray(items) ? items : []);
                    }).catch(function () {
                        if (tok !== imeisQueryToken) return;
                        renderImeisResultados([]);
                    });
                }, 250);
            });
        }

        // Precargar IMEIs al abrir dropdown
        var ddImeis = document.getElementById('dd-imeis');
        if (ddImeis) {
            ddImeis.addEventListener('shown.bs.dropdown', function () {
                var qTxt = (getValue('imeis-search') || '').trim();
                var sujetoIds = getSelectedIds('filtro-sujetos');
                var cargaIds = getSelectedIds('filtro-cargas');
                var tipos = getSelectedTipos();
                var provincias = getSelectedStrings('filtro-provincias');
                var localidades = getSelectedStrings('filtro-localidades');
                var tok = ++imeisQueryToken;
                fetchImeis(qTxt, {
                    sujeto_ids: sujetoIds,
                    carga_ids: cargaIds,
                    tipos: tipos,
                    provincias: provincias,
                    localidades: localidades,
                    fecha_desde: getValue('filtro-fecha-desde') || null,
                    fecha_hasta: getValue('filtro-fecha-hasta') || null,
                    hora_desde: getValue('filtro-hora-desde') || null,
                    hora_hasta: getValue('filtro-hora-hasta') || null
                }).then(function (items) {
                    if (tok !== imeisQueryToken) return;
                    renderImeisResultados(Array.isArray(items) ? items : []);
                }).catch(function () {});
            });
        }

        var btnLimpiar = document.getElementById('btn-limpiar-filtros');
        if (btnLimpiar) {
            btnLimpiar.addEventListener('click', function () {
                ['filtro-fecha-desde', 'filtro-fecha-hasta', 'filtro-hora-desde', 'filtro-hora-hasta', 'numeros-search', 'imeis-search', 'goto-orden'].forEach(function (id) {
                    var el = document.getElementById(id);
                    if (el) el.value = '';
                });
                selectedNumeros = new Set();
                renderNumerosSelected();
                selectedImeis = new Set();
                renderImeisSelected();

                // Apagar orden (y limpiar caches)
                var cbOrden = document.getElementById('toggle-orden');
                if (cbOrden) cbOrden.checked = false;
                try { localStorage.setItem('sabana_orden_enabled', '0'); } catch (e) {}
                ordenMap = {};
                ordenImpactoMap = {};
                ordenImpactoByOrd = {};
                ordenImpactoTotal = null;

                // desmarcar checkboxes de filtros avanzados
                ['filtro-sujetos', 'filtro-cargas', 'filtro-provincias', 'filtro-localidades', 'filtro-tipos', 'filtro-numeros', 'filtro-imeis'].forEach(function (cid) {
                    var c = document.getElementById(cid);
                    if (!c) return;
                    c.querySelectorAll('input[type=\"checkbox\"]').forEach(function (cb) { cb.checked = false; });
                });

                // reset vista
                var vc = document.getElementById('vista-celdas');
                if (vc) vc.checked = true;

                updateDdCount('dd-sujetos', 'filtro-sujetos', 'Seleccionar…');
                updateDdCount('dd-cargas', 'filtro-cargas', 'Seleccionar…');
                updateDdCount('dd-provincias', 'filtro-provincias', 'Seleccionar…');
                updateDdCount('dd-localidades', 'filtro-localidades', 'Seleccionar…');
                updateDdTipos();

                aplicarFiltros();
                refreshMapSize(50);
            });
        }
        var vistaCeldas = document.getElementById('vista-celdas');
        var vistaRuta = document.getElementById('vista-ruta');
        if (vistaCeldas) vistaCeldas.addEventListener('change', function () {
            updateClusterToggleVisibility();
            updateOrdenToggleVisibility();
            updateTrazadoToggleVisibility();
            scheduleAutoApply(0);
        });
        if (vistaRuta) vistaRuta.addEventListener('change', function () {
            updateClusterToggleVisibility();
            updateOrdenToggleVisibility();
            updateTrazadoToggleVisibility();
            // Al pasar a Ruta, evitar que quede el trazado superpuesto de Celdas
            clearTrazado();
            scheduleAutoApply(0);
        });
        var btnPlay = document.getElementById('btn-play-ruta');
        var btnPause = document.getElementById('btn-pause-ruta');
        var btnReset = document.getElementById('btn-reset-ruta');
        if (btnPlay) btnPlay.addEventListener('click', playAnimacion);
        if (btnPause) btnPause.addEventListener('click', pauseAnimacion);
        if (btnReset) btnReset.addEventListener('click', resetAnimacion);
        var cbLinea = document.getElementById('ver-linea-completa');
        if (cbLinea) {
            cbLinea.addEventListener('change', function () {
                if (!polyline || !map.hasLayer(polyline) || !rutaPuntos.length) return;
                if (verLineaCompleta()) {
                    polyline.setLatLngs(rutaPuntos.map(function (p) { return [p.lat, p.lng]; }));
                } else {
                    polyline.setLatLngs([]);
                }
            });
        }
        // Auto-aplicar cuando cambian inputs de fecha/hora
        ['filtro-fecha-desde', 'filtro-fecha-hasta', 'filtro-hora-desde', 'filtro-hora-hasta'].forEach(function (id) {
            var el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('change', function () { scheduleAutoApply(500); });
            el.addEventListener('input', function () { scheduleAutoApply(700); });
        });

        // Auto-aplicar cuando cambian checkboxes en dropdowns
        ['filtro-sujetos', 'filtro-cargas', 'filtro-provincias', 'filtro-localidades', 'filtro-tipos'].forEach(function (cid) {
            var c = document.getElementById(cid);
            if (!c) return;
            c.addEventListener('change', function () { scheduleAutoApply(500); });
        });

        // Auto-aplicar al cerrar dropdowns (multi-selección)
        ['dd-provincias', 'dd-localidades', 'dd-sujetos', 'dd-cargas', 'dd-tipos', 'dd-numeros', 'dd-imeis'].forEach(function (bid) {
            var b = document.getElementById(bid);
            if (!b) return;
            b.addEventListener('hidden.bs.dropdown', function () { scheduleAutoApply(0); });
        });

        // Si se colapsan/expanden filtros, Leaflet necesita recalcular tamaño
        var filtrosCollapse = document.getElementById('sabana-filtros-collapse');
        if (filtrosCollapse) {
            filtrosCollapse.addEventListener('shown.bs.collapse', function () { refreshMapSize(200); });
            filtrosCollapse.addEventListener('hidden.bs.collapse', function () { refreshMapSize(200); });
        }

        // Botón expandir mapa (pantalla completa real + fallback interno)
        var btnExpand = document.getElementById('btn-mapa-expand');
        if (btnExpand) {
            var wrap = document.querySelector('.sabana-mapa-wrap');

            // Estado inicial (por si el navegador restaura fullscreen)
            setExpandBtnState(btnExpand, isNativeFullscreen() || document.body.classList.contains('sabana-mapa-fullscreen'));

            btnExpand.addEventListener('click', function () {
                try {
                    // Si está en fullscreen nativo, salir
                    if (isNativeFullscreen()) {
                        if (document.exitFullscreen) document.exitFullscreen();
                        return;
                    }

                    // Intentar fullscreen nativo
                    if (wrap && wrap.requestFullscreen) {
                        wrap.requestFullscreen().catch(function () {
                            // Fallback: fullscreen interno
                            var isFs = document.body.classList.toggle('sabana-mapa-fullscreen');
                            setExpandBtnState(btnExpand, isFs);
                            refreshMapSize(200);
                        });
                        return;
                    }
                } catch (e) {}

                // Fallback: fullscreen interno
                var isFs2 = document.body.classList.toggle('sabana-mapa-fullscreen');
                setExpandBtnState(btnExpand, isFs2);
                refreshMapSize(200);
            });

            document.addEventListener('fullscreenchange', function () {
                var nativeFs = isNativeFullscreen();
                // Si entró/salió de fullscreen real, apagamos el fallback interno
                if (nativeFs) document.body.classList.remove('sabana-mapa-fullscreen');
                setExpandBtnState(btnExpand, nativeFs || document.body.classList.contains('sabana-mapa-fullscreen'));
                refreshMapSize(200);
            });
        }

        // Al redimensionar ventana, evitar mapa “cortado”
        window.addEventListener('resize', function () {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () { refreshMapSize(0); }, 120);
        });

        aplicarFiltros();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

(function () {
    'use strict';

    var map = null;
    var markersLayer = null;
    var explosionLayer = null;
    var recordRadioLayer = null;
    var recordTargetLayer = null;
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
    var trazadoFrameFn = null;        // función frame actual para poder reanudar
    var trazadoCache = new Map(); // key: "tipo|impacto_id" -> impacto payload (con _ord)
    var azimuthSingleLayer = null;
    /** Comparación: varios sectores de azimut a la vez (Ir a orden multiselección). */
    var azimuthMultiGroup = null;
    /** Toggle «Ver azimuts (todos)»: todos los sectores de impactos visibles, capa independiente. */
    var azimuthAllVizGroup = null;
    var animacionInterval = null;
    var animacionIndice = 0;
    var markerAuto = null;
    var baseUrl = document.body.getAttribute('data-sabana-base') || '';
    var puntosConImpactos = [];
    var lastRequestToken = 0;
    var lastAppliedParams = null;
    var lastPuntosCeldas = [];
    /** Si está definido, el mapa solo dibuja celdas/impactos cuyo _ord está en este Set (vista “solo seleccionados”). */
    var soloOrdenesVisibles = null;
    var ordenMap = {}; // key: "tipo|celda_id" -> {ord_min, ord_max} (orden por celda física)
    var ordenImpactoMap = {}; // key: "tipo|impacto_id" -> ord
    var ordenImpactoByOrd = {}; // ord -> {tipo, impacto_id}
    var ordenImpactoTotal = null;
    var ordenVisibleMax = 100; // para modo progresivo (Orden)
    var lastAutoFocusOrdenKey = null;
    var selectedNumeros = new Set();
    var selectedImeis = new Set();
    /** Snapshot sujeto/carga/tipo para limpiar números/IMEI si el contexto cambia (evita filtros inconsistentes). */
    var ctxSnapSujetos = new Set();
    var ctxSnapCargas = new Set();
    var ctxSnapTipos = '';
    var filtrosInfoTimer = null;
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
    var casoRefPickMode = false;
    var casoRefLayer = null;
    var casoRefModal = null;
    var casoRefItemsById = {};
    var pendingRecordRefPointId = null;
    /** Últimos puntos Record usados para radios de celda (redibujar al activar “Ver radios”). */
    var lastRecordRadioPuntos = [];

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

    function captureMapForInforme(showAlerts) {
        try {
            if (!window.html2canvas) return;
            // En el template el contenedor principal es .sabana-mapa-wrap y el mapa Leaflet tiene id="mapa-sabana"
            var container = document.querySelector('.sabana-mapa-wrap') || document.getElementById('mapa-sabana');
            if (!container) {
                if (showAlerts) {
                    alert('No se encontró el contenedor del mapa para capturar.');
                }
                return;
            }
            html2canvas(container, {
                useCORS: true,
                backgroundColor: '#ffffff',
                scale: 2
            }).then(function (canvas) {
                try {
                    var dataUrl = canvas.toDataURL('image/png');
                    localStorage.setItem('sabana_mapa_ultima_captura', dataUrl);
                    if (showAlerts) {
                        alert('Captura del mapa guardada. Se incluirá en el informe de Relaciones (VOZ).');
                    }
                } catch (e) {
                    console.warn('No se pudo guardar la captura del mapa para el informe:', e);
                    if (showAlerts) alert('No se pudo guardar la captura del mapa.');
                }
            }).catch(function (err) {
                console.warn('Error al capturar mapa para informe:', err);
                if (showAlerts) alert('No se pudo capturar el mapa.');
            });
        } catch (e) {
            console.warn('Captura mapa informe no disponible:', e);
            if (showAlerts) alert('Captura de mapa no disponible en este navegador.');
        }
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

    function setCheckedValues(containerId, valuesSet) {
        if (!valuesSet) return;
        var container = document.getElementById(containerId);
        if (!container) return;
        var set = valuesSet;
        container.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
            var v = String(cb.value || '').trim();
            cb.checked = set.has(v);
        });
    }

    function refreshProvinciasOptions() {
        // Nota: provincias/localidades no consideran fecha/hora en el backend (solo sujeto/carga/tipo).
        var prevProvs = new Set(getSelectedStrings('filtro-provincias').map(function (x) { return String(x); }));
        var sujetoIds = getSelectedIds('filtro-sujetos');
        var cargaIds = getSelectedIds('filtro-cargas');
        var tipos = getSelectedTipos();
        var snap = getFilterParamsSnapshot();

        return fetchProvincias('', Object.assign({}, snap, { sujeto_ids: sujetoIds, carga_ids: cargaIds, tipos: tipos })).then(function (items) {
            renderSimpleCheckboxList('filtro-provincias', Array.isArray(items) ? items : [], 'prov');
            setCheckedValues('filtro-provincias', prevProvs);
            updateDdCount('dd-provincias', 'filtro-provincias', 'Seleccionar…');
        }).catch(function () {});
    }

    function refreshLocalidadesOptions() {
        var prevLocs = new Set(getSelectedStrings('filtro-localidades').map(function (x) { return String(x); }));
        var sujetoIds = getSelectedIds('filtro-sujetos');
        var cargaIds = getSelectedIds('filtro-cargas');
        var tipos = getSelectedTipos();
        var provincias = getSelectedStrings('filtro-provincias');
        var snap = getFilterParamsSnapshot();

        return fetchLocalidades('', Object.assign({}, snap, { sujeto_ids: sujetoIds, carga_ids: cargaIds, tipos: tipos, provincias: provincias })).then(function (items) {
            renderSimpleCheckboxList('filtro-localidades', Array.isArray(items) ? items : [], 'loc');
            setCheckedValues('filtro-localidades', prevLocs);
            updateDdCount('dd-localidades', 'filtro-localidades', 'Seleccionar…');
        }).catch(function () {});
    }

    function refreshDropdownOptionsCascade() {
        // Cascada completa para los selects: provincias -> localidades -> números -> IMEIs.
        // El objetivo es que el usuario vea opciones coherentes con lo que ya seleccionó,
        // y que recién después el mapa se aplique cuando presiona “Aplicar filtros”.
        var sujetoIds = getSelectedIds('filtro-sujetos');
        var cargaIds = getSelectedIds('filtro-cargas');
        var tipos = getSelectedTipos();
        var snap0 = getFilterParamsSnapshot();

        // 1) Provincias
        return fetchProvincias('', Object.assign({}, snap0, { sujeto_ids: sujetoIds, carga_ids: cargaIds, tipos: tipos }))
            .then(function (items) {
                var prevProvs = new Set(getSelectedStrings('filtro-provincias').map(function (x) { return String(x); }));
                renderSimpleCheckboxList('filtro-provincias', Array.isArray(items) ? items : [], 'prov');
                setCheckedValues('filtro-provincias', prevProvs);
                updateDdCount('dd-provincias', 'filtro-provincias', 'Seleccionar…');

                // 2) Localidades (en base a provincias actuales ya recargadas)
                var provincias = getSelectedStrings('filtro-provincias');
                var prevLocs = new Set(getSelectedStrings('filtro-localidades').map(function (x) { return String(x); }));
                return fetchLocalidades('', Object.assign({}, snap0, { sujeto_ids: sujetoIds, carga_ids: cargaIds, tipos: tipos, provincias: provincias })).then(function (locItems) {
                    renderSimpleCheckboxList('filtro-localidades', Array.isArray(locItems) ? locItems : [], 'loc');
                    setCheckedValues('filtro-localidades', prevLocs);
                    updateDdCount('dd-localidades', 'filtro-localidades', 'Seleccionar…');

                    // 3) Números/IMEIs (incluyen fecha/hora en endpoints)
                    var fecha_desde = getValue('filtro-fecha-desde') || null;
                    var fecha_hasta = getValue('filtro-fecha-hasta') || null;
                    var hora_desde = getValue('filtro-hora-desde') || null;
                    var hora_hasta = getValue('filtro-hora-hasta') || null;
                    var finalProvs = getSelectedStrings('filtro-provincias');
                    var finalLocs = getSelectedStrings('filtro-localidades');

                    var base = Object.assign({}, getFilterParamsSnapshot(), {
                        sujeto_ids: sujetoIds,
                        carga_ids: cargaIds,
                        tipos: tipos,
                        provincias: finalProvs,
                        localidades: finalLocs,
                        fecha_desde: fecha_desde,
                        fecha_hasta: fecha_hasta,
                        hora_desde: hora_desde,
                        hora_hasta: hora_hasta
                    });

                    return Promise.all([
                        fetchNumeros('', base).then(function (nums) {
                            renderNumerosResultados(Array.isArray(nums) ? nums : []);
                        }).catch(function () {}),
                        fetchImeis('', base).then(function (imeis) {
                            renderImeisResultados(Array.isArray(imeis) ? imeis : []);
                        }).catch(function () {})
                    ]);
                });
            });
    }

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content');
        var input = document.querySelector('input[name="csrf_token"]');
        return input ? input.value : '';
    }

    function appendMapaCasoId(q, params) {
        if (params && params.caso_id != null && params.caso_id !== '') {
            q.append('caso_id', String(params.caso_id));
        }
    }

    /** Contexto del mapa para APIs de filtros (sábana vs record vs ambos). */
    function appendMapaFiltrosContext(q, params) {
        params = params || {};
        try {
            q.append('mapa_datos_modo', getMapaDatosModo());
        } catch (eM) {
            q.append('mapa_datos_modo', 'sabana');
        }
        appendMapaCasoId(q, params);
        try {
            if (isMapaRecordModo() || isMapaAmbosModo()) {
                getRecordFuenteIds().forEach(function (fid) {
                    if (fid != null && fid !== '') q.append('fuente_ids[]', String(fid));
                });
            }
        } catch (eF) {}
    }

    function fetchFiltros() {
        // Cargas: por defecto el backend limita; pedimos más para que el selector no quede “cortado” en 500.
        var q = new URLSearchParams();
        q.append('cargas_limit', '2000');
        var cid = getMapaCasoPrincipalId();
        if (cid != null) q.append('caso_id', String(cid));
        return fetch(baseUrl + '/sabana-llamadas/api/filtros?' + q.toString(), {
            method: 'GET',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) { return r.json(); });
    }

    function renderSabanaCargasOptions(data, preferredIds) {
        var keep = new Set((preferredIds || []).map(function (v) { return String(v); }));
        if (!keep.size) {
            getSelectedIds('filtro-cargas').forEach(function (id) { keep.add(String(id)); });
        }
        var cargas = ((data && data.cargas) || []).map(function (c) {
            return { id: c.id, nombre: (c.tipo || '') + ' - ' + (c.nombre_archivo || c.id) };
        });
        renderCheckboxes('filtro-cargas', cargas, 'nombre', 'id');
        setCheckedValues('filtro-cargas', keep);
        updateDdCount('dd-cargas', 'filtro-cargas', 'Seleccionar…');
    }

    function loadUnifiedCargasOptions(preferredIds) {
        if (isMapaRecordModo() || isMapaAmbosModo()) {
            var cid = getRecordCasoId();
            var st = getRecordSourceType();
            if (!cid) {
                renderRecordFuentesAsCargas([], preferredIds || []);
                return Promise.resolve();
            }
            return fetchRecordFuentes(cid, st).then(function (items) {
                renderRecordFuentesAsCargas(items, preferredIds || []);
            }).catch(function () {
                renderRecordFuentesAsCargas([], preferredIds || []);
            });
        }
        return fetchFiltros().then(function (data) {
            renderSabanaCargasOptions(data, preferredIds || []);
        }).catch(function () {});
    }

    /** Tipos (GPRS/VOZ) según archivos/cargas y modo — unificado con backend mapa-tipos. */
    function reloadMapaTiposOpciones() {
        var params = getFilterParamsSnapshot();
        var keep = new Set(getSelectedStrings('filtro-tipos').map(function (s) { return String(s).toLowerCase(); }));
        var q = new URLSearchParams();
        appendMapaFiltrosContext(q, params);
        (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', String(id)); });
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/mapa-tipos?' + q.toString(), { credentials: 'same-origin' }).then(function (r) {
            return r.json().then(function (arr) {
                var raw = (r.ok && Array.isArray(arr)) ? arr : ['gprs', 'voz'];
                var items = raw.map(function (t) {
                    var tid = String(t).toLowerCase();
                    var nombre = tid === 'gprs' ? 'GPRS' : (tid === 'voz' ? 'VOZ' : String(t).toUpperCase());
                    return { id: tid, nombre: nombre };
                });
                if (!items.length) {
                    items = [{ id: 'gprs', nombre: 'GPRS' }, { id: 'voz', nombre: 'VOZ' }];
                }
                renderCheckboxes('filtro-tipos', items, 'nombre', 'id');
                setCheckedValues('filtro-tipos', keep);
                updateDdTipos();
            });
        }).catch(function () {
            renderCheckboxes('filtro-tipos', [{ id: 'gprs', nombre: 'GPRS' }, { id: 'voz', nombre: 'VOZ' }], 'nombre', 'id');
            setCheckedValues('filtro-tipos', keep);
            updateDdTipos();
        });
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
        appendMapaCasoId(baseQ, params);

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
        appendMapaCasoId(q, params);
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
        appendMapaCasoId(q, params);
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

    /** Resuelve tipo + impacto_id para un #orden: API orden-impactos o impactos ya cargados (modo Record no rellena ordenImpactoByOrd). */
    function resolveImpactoRefForOrd(ord) {
        var o = parseInt(String(ord).trim(), 10);
        if (isNaN(o) || o < 1) return null;
        try {
            if (ordenImpactoByOrd && ordenImpactoByOrd[String(o)]) {
                var r0 = ordenImpactoByOrd[String(o)];
                if (r0 && r0.tipo && r0.impacto_id != null) return r0;
            }
        } catch (e0) {}
        try {
            var found = null;
            (lastPuntosCeldas || []).some(function (pt) {
                return (pt && pt.impactos || []).some(function (imp) {
                    if (!imp || imp._ord == null) return false;
                    if (parseInt(imp._ord, 10) !== o) return false;
                    if (imp.tipo && imp.id != null) {
                        found = { tipo: String(imp.tipo), impacto_id: imp.id };
                        return true;
                    }
                    return false;
                });
            });
            if (found) return found;
        } catch (e1) {}
        return null;
    }

    /** Solo pide orden-impactos si falta algún ref y el contexto no es solo Record (esa API no aplica al record puro). */
    function ensureOrdenImpactosForOrds(ords) {
        var needFetch = false;
        (ords || []).forEach(function (ord) {
            if (!resolveImpactoRefForOrd(ord)) needFetch = true;
        });
        if (!needFetch) return Promise.resolve();
        if (!lastAppliedParams || lastAppliedParams._record_mode) return Promise.resolve();
        return fetchOrdenImpactos(lastAppliedParams).catch(function () {});
    }

    function gotoOrden(n, opts) {
        opts = opts || {};
        var ord = parseInt(String(n || '').trim(), 10);
        if (isNaN(ord) || ord < 1) return Promise.resolve();

        function runWithRef(ref) {
        if (!ref) return Promise.resolve();

        // Modo progresivo: si navego más allá del visibleMax, ampliar lo visible sin recargar todo
        if (isOrdenEnabled() && isOrdenProgressiveEnabled() && ord > ordenVisibleMax) {
            setOrdenVisibleMax(ord);
                try { addMarkers(lastPuntosCeldas || [], { keepPanel: true, keepView: true, soloRedraw: !!(soloOrdenesVisibles && soloOrdenesVisibles.size) }); } catch (e) {}
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
            // Con varios órdenes en comparación ya encuadramos en drawAzimuthMultiForOrds; no forzar zoom a un solo punto.
            var multiComp = opts.compareOrds && opts.compareOrds.length > 1;
            if (!multiComp) {
            try { if (ll) map.setView([ll.lat, ll.lng], Math.max(map.getZoom(), 18)); } catch (e) {}
            }
            // Azimut y radio para este impacto (si vienen del backend)
            try {
                if (data.azimuth != null) imp._azimuth = data.azimuth;
                if (data.rad_cob_km != null) imp._rad_cob_km = data.rad_cob_km;
                if (data.a_horiz != null) imp._a_horiz = data.a_horiz;
                if (data.a_vert != null) imp._a_vert = data.a_vert;
            } catch (eAz) {}
            openPanelDetalle(imp);
            if (ll) {
                highlightImpact(imp, ll, {
                    keepAzimuthMulti: !!multiComp,
                    skipSingleAzimuth: !!multiComp
                });
            }
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

        var refGo = resolveImpactoRefForOrd(ord);
        if (refGo) return runWithRef(refGo);
        if (lastAppliedParams && !lastAppliedParams._record_mode) {
            return fetchOrdenImpactos(lastAppliedParams).then(function () {
                return runWithRef(resolveImpactoRefForOrd(ord));
            }).catch(function () { return Promise.resolve(); });
        }
        return Promise.resolve();
    }

    function focusOrden(n) {
        // Enfoca (pan/zoom + resaltado) sin abrir panel ni cargar lista.
        var ord = parseInt(String(n || '').trim(), 10);
        if (isNaN(ord) || ord < 1) return Promise.resolve();
        var ref = resolveImpactoRefForOrd(ord);
        if (!ref && lastAppliedParams && !lastAppliedParams._record_mode) {
            return fetchOrdenImpactos(lastAppliedParams).then(function () {
                ref = resolveImpactoRefForOrd(ord);
                if (!ref) return Promise.resolve();
                return focusOrdenFetch(ref, ord);
            }).catch(function () { return Promise.resolve(); });
        }
        if (!ref) return Promise.resolve();
        return focusOrdenFetch(ref, ord);
    }

    function focusOrdenFetch(ref, ord) {
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

    function filterPuntosBySoloOrdenes(puntos, ordSet) {
        if (!ordSet || !ordSet.size) return puntos;
        var out = [];
        (puntos || []).forEach(function (pt) {
            if (!pt) return;
            var imps = (pt.impactos || []).filter(function (imp) {
                if (!imp || imp._ord == null) return false;
                return ordSet.has(parseInt(imp._ord, 10));
            });
            if (!imps.length) return;
            var clone = Object.assign({}, pt);
            clone.impactos = imps;
            try { clone.impactos_count = imps.length; } catch (eCnt) {}
            out.push(clone);
        });
        return out;
    }

    function updateGotoSoloHint() {
        var el = document.getElementById('goto-orden-solo-active');
        var btnQ = document.getElementById('btn-goto-orden-quitar-solo');
        var active = soloOrdenesVisibles && soloOrdenesVisibles.size;
        if (el) {
            if (active) {
                var arr = Array.from(soloOrdenesVisibles).sort(function (a, b) { return a - b; });
                el.textContent = 'Solo se muestran en el mapa los órdenes: #' + arr.join(', #') + '.';
                el.classList.remove('d-none');
            } else {
                el.textContent = '';
                el.classList.add('d-none');
            }
        }
        if (btnQ) btnQ.classList.toggle('d-none', !active);
    }

    function gotoOrdenRowLabel(imp, ord, punto) {
        var celdaTxt = '';
        try {
            if (punto && punto.celda_id != null && String(punto.celda_id).trim() !== '') {
                celdaTxt = ' — celda ' + String(normCeldaId(punto.celda_id));
            } else {
                var c = imp && imp._punto_celda_id ? imp._punto_celda_id :
                    (imp && imp.tipo === 'gprs' ? (imp.celda || '') : (imp && imp.celda_id ? imp.celda_id : ''));
                if (c) celdaTxt = ' — ' + String(c);
            }
        } catch (eCel) {}
        var fh = '';
        try {
            fh = ((imp && imp.fecha) ? formatFecha(imp.fecha) : '').trim();
            if (imp && imp.hora) fh = (fh ? fh + ' ' : '') + String(imp.hora);
        } catch (eFh) { fh = ''; }
        fh = String(fh || '').trim();
        return '#' + ord + (fh ? ' · ' + fh : '') + celdaTxt;
    }

    function buildGotoOrdenRowsFromPuntos(puntos) {
        var flat = [];
        (puntos || []).forEach(function (pt) {
            (pt && pt.impactos || []).forEach(function (imp) {
                if (!imp || imp._ord == null) return;
                var o = parseInt(imp._ord, 10);
                if (isNaN(o) || o < 1) return;
                flat.push({ ord: o, imp: imp, punto: pt });
            });
        });
        flat.sort(function (a, b) { return a.ord - b.ord; });
        var seen = {};
        var out = [];
        flat.forEach(function (x) {
            if (seen[x.ord]) return;
            seen[x.ord] = true;
            out.push(x);
        });
        return out;
    }

    /** Texto de ayuda: la lista «Ir» solo refleja filtros acumulados (AND) ya aplicados al mapa. */
    function updateGotoOrdenFilterHint() {
        var el = document.getElementById('goto-orden-filter-hint');
        if (!el) return;
        var rows = buildGotoOrdenRowsFromPuntos(lastPuntosCeldas);
        if (!rows.length) {
            el.classList.add('d-none');
            el.textContent = '';
            return;
        }
        el.classList.remove('d-none');
        var parts = [];
        try {
            var snap = getFilterParamsSnapshot();
            if (snap.localidades && snap.localidades.length) {
                var labs = snap.localidades.map(function (x) { return String(x).trim(); }).filter(Boolean);
                parts.push('loc.: ' + labs.slice(0, 4).join(', ') + (labs.length > 4 ? '…' : ''));
            }
            if (snap.provincias && snap.provincias.length) {
                parts.push('prov.: ' + snap.provincias.length);
            }
            if (snap.fecha_desde || snap.fecha_hasta) {
                parts.push('fecha ' + (snap.fecha_desde || '…') + '→' + (snap.fecha_hasta || '…'));
            }
            if (snap.hora_desde || snap.hora_hasta) {
                parts.push('hora ' + (snap.hora_desde || '…') + '→' + (snap.hora_hasta || '…'));
            }
        } catch (e) {}
        el.textContent = parts.length
            ? ('Solo órdenes de los impactos ya filtrados en el mapa (' + parts.join(' · ') + ').')
            : 'Solo órdenes de los impactos que ves en el mapa con los filtros actuales (se combinan con AND).';
    }

    function getSelectedGotoOrdenOrds() {
        var list = document.getElementById('goto-orden-list');
        if (!list) return [];
        var ords = [];
        list.querySelectorAll('input.goto-orden-cb:checked').forEach(function (cb) {
            var v = parseInt(cb.getAttribute('data-ord') || cb.value, 10);
            if (!isNaN(v) && v >= 1) ords.push(v);
        });
        ords.sort(function (a, b) { return a - b; });
        return ords;
    }

    function updateGotoOrdenDropdownLabel() {
        var btn = document.getElementById('dd-goto-orden-btn');
        if (!btn) return;
        var ords = getSelectedGotoOrdenOrds();
        var n = ords.length;
        if (!n) {
            btn.textContent = 'Ir a orden…';
            return;
        }
        btn.textContent = n === 1 ? ('Ir a #' + ords[0]) : ('Ir a orden (' + n + ' seleccionados)');
    }

    function filterGotoOrdenList(q) {
        var list = document.getElementById('goto-orden-list');
        if (!list) return;
        var qq = String(q || '').trim().toLowerCase();
        list.querySelectorAll('.goto-orden-row').forEach(function (row) {
            var hay = !qq || (row.getAttribute('data-search') || '').indexOf(qq) !== -1;
            row.classList.toggle('d-none', !hay);
        });
    }

    function clearGotoOrdenSelection() {
        var list = document.getElementById('goto-orden-list');
        if (list) {
            list.querySelectorAll('input.goto-orden-cb').forEach(function (cb) { cb.checked = false; });
        }
        var s = document.getElementById('goto-orden-search');
        if (s) s.value = '';
        try { filterGotoOrdenList(''); } catch (eFl) {}
        updateGotoOrdenDropdownLabel();
    }

    function refreshGotoOrdenDropdownFromMarkers() {
        var listEl = document.getElementById('goto-orden-list');
        var hintEl = document.getElementById('goto-orden-empty-hint');
        if (!listEl) return;
        var prev = new Set(getSelectedGotoOrdenOrds());
        var rows = buildGotoOrdenRowsFromPuntos(lastPuntosCeldas);
        listEl.innerHTML = '';
        if (hintEl) hintEl.classList.toggle('d-none', rows.length > 0);
        if (!rows.length) {
            updateGotoOrdenDropdownLabel();
            return;
        }
        rows.forEach(function (row) {
            var ord = row.ord;
            var imp = row.imp;
            var id = 'goto-orden-cb-' + ord;
            var lbl = gotoOrdenRowLabel(imp, ord, row.punto);
            var search = (lbl + ' ' + ord).toLowerCase();
            var wrap = document.createElement('div');
            wrap.className = 'form-check goto-orden-row';
            wrap.setAttribute('data-search', search);
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'form-check-input goto-orden-cb';
            cb.id = id;
            cb.setAttribute('data-ord', String(ord));
            cb.value = String(ord);
            if (prev.has(ord)) cb.checked = true;
            var label = document.createElement('label');
            label.className = 'form-check-label small';
            label.setAttribute('for', id);
            label.textContent = lbl;
            wrap.appendChild(cb);
            wrap.appendChild(label);
            listEl.appendChild(wrap);
        });
        var gos = document.getElementById('goto-orden-search');
        try { filterGotoOrdenList(gos ? gos.value : ''); } catch (eF2) {}
        updateGotoOrdenDropdownLabel();
        updateGotoSoloHint();
        try { updateGotoOrdenFilterHint(); } catch (eHint) {}
    }

    function collectLatLngsForOrds(ords) {
        return ensureOrdenImpactosForOrds(ords).then(function () {
            return Promise.all((ords || []).map(function (ord) {
                var ref = resolveImpactoRefForOrd(ord);
                if (!ref) return Promise.resolve(null);
                return fetch(baseUrl + '/sabana-llamadas/api/mapa/impacto-loc?tipo=' + encodeURIComponent(ref.tipo) + '&impacto_id=' + encodeURIComponent(String(ref.impacto_id)), {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' }
                }).then(function (r) { return r.json(); }).then(function (data) {
                    if (data && data.lat != null && data.lng != null) return L.latLng(data.lat, data.lng);
                    return null;
                });
            }));
        }).then(function (arr) {
            return (arr || []).filter(function (x) { return x != null; });
        });
    }

    function doGotoOrdenNavigate(ords) {
        ords = (ords || []).slice().sort(function (a, b) { return a - b; });
        if (!ords.length) return;
        var minOrd = ords[0];
        var isMulti = ords.length > 1;
        collectLatLngsForOrds(ords).then(function (lls) {
            if (!isMulti) {
                try {
                    if (lls.length >= 2) {
                        map.fitBounds(L.latLngBounds(lls), { padding: [48, 48], maxZoom: 18 });
                    } else if (lls.length === 1) {
                        map.setView(lls[0], Math.max(map.getZoom(), 15));
                    }
                } catch (eFB) {}
            }
            if (isMulti) {
                return drawAzimuthMultiForOrds(ords).then(function () {
                    return gotoOrden(minOrd, { compareOrds: ords });
                });
            }
            return gotoOrden(minOrd);
        }).catch(function () {
            try {
                if (isMulti) {
                    drawAzimuthMultiForOrds(ords).then(function () {
                        return gotoOrden(minOrd, { compareOrds: ords });
                    });
                } else {
                    gotoOrden(minOrd);
                }
            } catch (eGo) {}
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
            appendMapaCasoId(q, params);
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
        appendMapaCasoId(q, params);
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
        appendMapaCasoId(q, params);
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
        return getSelectedStrings('filtro-tipos').map(function (s) { return String(s).toLowerCase(); }).filter(Boolean);
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

    function filterMapaToolbarOptList(listId, query) {
        var container = document.getElementById(listId);
        if (!container) return;
        var q = (query || '').toLowerCase().trim();
        container.querySelectorAll('.mapa-toolbar-opt').forEach(function (btn) {
            var txt = (btn.textContent || '').toLowerCase();
            btn.style.display = (!q || txt.indexOf(q) !== -1) ? '' : 'none';
        });
    }

    function syncMapaCasoDropdownButton() {
        var sel = document.getElementById('mapa-caso-principal');
        var btn = document.getElementById('dd-mapa-caso-btn');
        if (!sel || !btn) return;
        var v = String(sel.value || '');
        var lab = '— Sin caso —';
        if (v) {
            var opt = null;
            Array.prototype.forEach.call(sel.options || [], function (o) {
                if (String(o.value) === v) opt = o;
            });
            if (opt) lab = String(opt.textContent || '').trim() || lab;
        }
        btn.textContent = lab;
    }

    function syncMapaModoDropdownButton() {
        var sel = document.getElementById('mapa-datos-modo');
        var btn = document.getElementById('dd-mapa-modo-btn');
        if (!sel || !btn) return;
        var v = String(sel.value || 'sabana').trim();
        var lab = 'Sábana';
        var list = document.getElementById('mapa-datos-modo-list');
        if (list) {
            var b = list.querySelector('.mapa-toolbar-opt[data-value="' + v + '"]');
            if (b) {
                lab = String(b.getAttribute('data-label') || b.textContent || '').trim() || lab;
            } else if (v === 'record') lab = 'Record';
            else if (v === 'ambos') lab = 'Sábana + Record';
        }
        btn.textContent = lab;
    }

    function initMapaToolbarDropdowns() {
        syncMapaCasoDropdownButton();
        syncMapaModoDropdownButton();
        var casoSearch = document.getElementById('mapa-caso-search');
        if (casoSearch) {
            casoSearch.addEventListener('input', function () {
                filterMapaToolbarOptList('mapa-caso-principal-list', this.value);
            });
        }
        var modoSearch = document.getElementById('mapa-modo-search');
        if (modoSearch) {
            modoSearch.addEventListener('input', function () {
                filterMapaToolbarOptList('mapa-datos-modo-list', this.value);
            });
        }
        var casoList = document.getElementById('mapa-caso-principal-list');
        if (casoList) {
            casoList.addEventListener('click', function (ev) {
                var t = ev.target && ev.target.closest ? ev.target.closest('.mapa-toolbar-opt') : null;
                if (!t) return;
                var val = t.getAttribute('data-value');
                var sel = document.getElementById('mapa-caso-principal');
                if (!sel) return;
                sel.value = val != null ? String(val) : '';
                try {
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                } catch (eCh) {}
                syncMapaCasoDropdownButton();
                var dd = document.getElementById('dd-mapa-caso-btn');
                if (dd && window.bootstrap && window.bootstrap.Dropdown) {
                    var inst = window.bootstrap.Dropdown.getInstance(dd);
                    if (inst) inst.hide();
                }
            });
        }
        var modoList = document.getElementById('mapa-datos-modo-list');
        if (modoList) {
            modoList.addEventListener('click', function (ev) {
                var t = ev.target && ev.target.closest ? ev.target.closest('.mapa-toolbar-opt') : null;
                if (!t) return;
                var val = t.getAttribute('data-value');
                var sel = document.getElementById('mapa-datos-modo');
                if (!sel) return;
                sel.value = val != null ? String(val) : 'sabana';
                try {
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                } catch (eCh2) {}
                syncMapaModoDropdownButton();
                var ddM = document.getElementById('dd-mapa-modo-btn');
                if (ddM && window.bootstrap && window.bootstrap.Dropdown) {
                    var instM = window.bootstrap.Dropdown.getInstance(ddM);
                    if (instM) instM.hide();
                }
            });
        }
    }

    function fetchNumeros(qTxt, params) {
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
        q.append('limit', '50');
        appendMapaFiltrosContext(q, params);
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
        appendMapaFiltrosContext(q, params);
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
        appendMapaFiltrosContext(q, params);
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
        appendMapaFiltrosContext(q, params);
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
        var wasRefNumeros = (currentPanelMode === 'ref_numeros');
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
        if (wasRefNumeros) {
            try { _setSabanaPanelExtraControlsHidden(false); } catch (ePn) {}
        }
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

            var notaHtml =
                '<hr class="my-2">' +
                '<div class="d-flex justify-content-between align-items-center mb-1">' +
                '<span class="small fw-bold">Nota del investigador</span>' +
                '<div class="btn-group btn-group-sm" role="group" aria-label="Color de marca">' +
                '<button type="button" class="btn btn-outline-secondary sabana-nota-color" data-color="">' +
                'Sin color' +
                '</button>' +
                '<button type="button" class="btn btn-outline-danger sabana-nota-color" data-color="rojo">Rojo</button>' +
                '<button type="button" class="btn btn-outline-warning sabana-nota-color" data-color="amarillo">Amarillo</button>' +
                '<button type="button" class="btn btn-outline-success sabana-nota-color" data-color="verde">Verde</button>' +
                '<button type="button" class="btn btn-outline-primary sabana-nota-color" data-color="azul">Azul</button>' +
                '</div>' +
                '</div>' +
                '<textarea class="form-control form-control-sm mb-2" rows="3" id="sabana-nota-texto" placeholder="Escriba aquí una observación sobre este punto..."></textarea>' +
                '<div class="d-flex justify-content-between align-items-center">' +
                '<small class="text-muted" id="sabana-nota-status"></small>' +
                '<button type="button" class="btn btn-sm btn-outline-primary" id="sabana-nota-guardar">Guardar nota</button>' +
                '</div>';

            body.innerHTML =
                geo +
                '<table class="table table-sm mb-2"><tbody>' +
                rows.join('') +
                '</tbody></table>' +
                '<div id="sabana-nota-container" class="mt-1">' +
                notaHtml +
                '</div>';

            inicializarNotaImpacto(imp);
        }
        showPanel();
        updatePanelNav();
    }

    function inicializarNotaImpacto(imp) {
        try {
            if (!imp || imp.id == null || !imp.tipo) return;
            var tipo = String(imp.tipo || '').toLowerCase();
            var impactoId = String(imp.id);
            var baseUrl = document.body.getAttribute('data-sabana-base') || '';
            var url = baseUrl + '/sabana-llamadas/api/mapa/impacto-nota?tipo=' +
                encodeURIComponent(tipo) + '&impacto_id=' + encodeURIComponent(impactoId);

            var txt = document.getElementById('sabana-nota-texto');
            var status = document.getElementById('sabana-nota-status');
            var btnGuardar = document.getElementById('sabana-nota-guardar');
            var colorButtons = Array.prototype.slice.call(document.querySelectorAll('.sabana-nota-color'));

            function setActiveColor(color) {
                colorButtons.forEach(function (btn) {
                    var c = btn.getAttribute('data-color') || '';
                    if (c === (color || '')) btn.classList.add('active');
                    else btn.classList.remove('active');
                });
            }

            var currentColor = '';

            colorButtons.forEach(function (btn) {
                btn.addEventListener('click', function () {
                    currentColor = this.getAttribute('data-color') || '';
                    setActiveColor(currentColor);
                });
            });

            if (btnGuardar) {
                btnGuardar.addEventListener('click', function () {
                    if (!txt) return;
                    var payload = {
                        tipo: tipo,
                        impacto_id: impactoId,
                        nota: txt.value || '',
                        color: currentColor || ''
                    };
                    status.textContent = 'Guardando...';
                    var token = getCsrfToken();
                    var headers = {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    };
                    if (token) {
                        headers['X-CSRFToken'] = token;
                        headers['X-CSRF-Token'] = token;
                    }
                    fetch(baseUrl + '/sabana-llamadas/api/mapa/impacto-nota', {
                        method: 'POST',
                        headers: headers,
                        body: JSON.stringify(payload),
                        credentials: 'same-origin'
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (data) {
                            if (data && data.ok) {
                                currentColor = data.color || '';
                                setActiveColor(currentColor);
                                status.textContent = 'Nota guardada.';
                                setTimeout(function () { status.textContent = ''; }, 2500);
                            } else {
                                status.textContent = 'No se pudo guardar.';
                            }
                        })
                        .catch(function () {
                            status.textContent = 'Error al guardar.';
                        });
                });
            }

            // Cargar nota existente
            if (txt) {
                status.textContent = 'Cargando nota...';
                fetch(url, { credentials: 'same-origin' })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (!data) {
                            status.textContent = '';
                            return;
                        }
                        txt.value = data.nota || '';
                        currentColor = data.color || '';
                        setActiveColor(currentColor);
                        status.textContent = '';
                    })
                    .catch(function () {
                        status.textContent = '';
                    });
            }
        } catch (e) {
            // Silencioso: las notas no deben romper el panel
        }
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
                // No aplicar aún: esperamos a que el usuario termine y cierre el dropdown
                // (hidden.bs.dropdown) para evitar múltiples recargas pesadas.
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
                // No aplicar aún: esperamos a que el usuario termine y cierre el dropdown
                // (hidden.bs.dropdown) para evitar múltiples recargas pesadas.
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
        if (isVistaRuta() || isMapaAmbosModo()) wrap.classList.add('d-none');
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
        if (isVistaRuta() || isMapaAmbosModo()) {
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

    /** Recorrido cronológico para trazado: mismos impactos y #_ord que el mapa (respeta «solo órdenes» si aplica). */
    function buildTrazadoPuntosFromLastPuntosCeldas() {
        var puntos = lastPuntosCeldas;
        if (soloOrdenesVisibles && soloOrdenesVisibles.size) {
            puntos = filterPuntosBySoloOrdenes(lastPuntosCeldas, soloOrdenesVisibles);
        }
        if (!puntos || !puntos.length) return [];
        var flat = [];
        puntos.forEach(function (pt) {
            if (!pt || pt.lat == null || pt.lng == null) return;
            var la = parseFloat(pt.lat);
            var lo = parseFloat(pt.lng);
            if (isNaN(la) || isNaN(lo)) return;
            (pt.impactos || []).forEach(function (imp) {
                if (!imp || imp.id == null) return;
                flat.push({ imp: imp, pt: pt, la: la, lo: lo });
            });
        });
        flat.sort(function (a, b) {
            var oa = a.imp && a.imp._ord != null ? parseInt(a.imp._ord, 10) : NaN;
            var ob = b.imp && b.imp._ord != null ? parseInt(b.imp._ord, 10) : NaN;
            if (!isNaN(oa) && !isNaN(ob) && oa !== ob) return oa - ob;
            return _impactoDateKey(a.imp) - _impactoDateKey(b.imp);
        });
        var out = [];
        var n = 0;
        flat.forEach(function (x) {
            n++;
            var imp = x.imp;
            var pt = x.pt;
            out.push({
                lat: x.la,
                lng: x.lo,
                tipo: imp.tipo || 'voz',
                impacto_id: imp.id,
                carga_id: pt.carga_id,
                celda_id: pt.celda_id,
                numero: n
            });
        });
        return out;
    }

    function refreshTrazadoLayerIfNeeded() {
        if (!isTrazadoEnabled() || isVistaRuta()) return;
        if (isMapaAmbosModo()) return;
        if (isMapaRecordModo()) {
            var pts = buildTrazadoPuntosFromLastPuntosCeldas();
            if (pts.length >= 2) {
                drawTrazado(pts, { record: true });
            } else {
                clearTrazado();
            }
            return;
        }
        if (!lastAppliedParams) {
            clearTrazado();
            return;
        }
        fetchTrazado(lastAppliedParams).then(function (res) {
            drawTrazado(res.puntos || [], res);
        }).catch(function () {
            clearTrazado();
        });
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

        // Guardamos referencia para poder reanudar tras un "pausa"
        trazadoFrameFn = frame;
        trazadoAnimacionFrameId = requestAnimationFrame(frame);
    }

    function playTrazadoAnimacion() {
        if (!map) return;

        // Si la animación está pausada pero ya existe un frame y puntos, simplemente reanudar.
        if (!trazadoIsPlaying && trazadoFrameFn && trazadoPuntos && trazadoPuntos.length >= 2) {
            trazadoIsPlaying = true;
            trazadoAnimacionFrameId = requestAnimationFrame(trazadoFrameFn);
            return;
        }

        // Si no tenemos puntos cargados (por ej. Trazado estaba apagado al aplicar filtros),
        // cargar primero desde el backend con los últimos filtros y recién después animar.
        if (!trazadoPuntos || trazadoPuntos.length < 2) {
            if (isMapaRecordModo()) {
                var ptsRec = buildTrazadoPuntosFromLastPuntosCeldas();
                if (ptsRec.length >= 2) {
                    drawTrazado(ptsRec, { record: true });
                    if (trazadoPuntos && trazadoPuntos.length >= 2) {
                        _playTrazadoAnimacionCore();
                    }
                }
                return;
            }
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

        // Si ya se está reproduciendo, no hacer nada más.
        if (trazadoIsPlaying) return;

        _playTrazadoAnimacionCore();
    }

    function pauseTrazadoAnimacion() {
        // Pausar sin destruir el estado, para poder reanudar luego.
        trazadoIsPlaying = false;
        updateTrazadoTiempoLabel('Pausado');
    }

    function updateClusterToggleVisibility() {
        var wrap = document.getElementById('cluster-toggle-wrap');
        if (!wrap) return;
        if (isVistaRuta()) wrap.classList.add('d-none');
        else wrap.classList.remove('d-none');
    }

    function updateRecordVizToggleVisibility() {
        var wrap = document.getElementById('record-viz-wrap');
        if (!wrap) return;
        var show = isMapaRecordModo() || isMapaAmbosModo();
        wrap.classList.toggle('d-none', !show);
        if (!show) {
            try { if (recordRadioLayer) recordRadioLayer.clearLayers(); } catch (eR) {}
            try { clearRecordTargetOverlay(); } catch (eT) {}
        }
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
                    if (sum <= 0 && markers.length) sum = markers.length;
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
            try {
                addMarkers(lastPuntosCeldas || [], (soloOrdenesVisibles && soloOrdenesVisibles.size) ? { soloRedraw: true } : {});
                try {
                    if (isMapaRecordModo() && isTrazadoEnabled()) refreshTrazadoLayerIfNeeded();
                } catch (eTrzRb) {}
            } catch (e) {}
        }
        try { bindMarkerClusterAzimuthClicks(); } catch (eBc) {}
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
        recordRadioLayer = L.layerGroup().addTo(map);
        recordTargetLayer = L.layerGroup().addTo(map);
        try {
            if (!map.getPane('casoRefPane')) {
                var crp = map.createPane('casoRefPane');
                crp.style.zIndex = 860;
            }
        } catch (eCasoPane) {}
        casoRefLayer = L.layerGroup().addTo(map);
        try {
            if (!map.getPane('recordPerimeterPane')) {
                var ppRec = map.createPane('recordPerimeterPane');
                ppRec.style.zIndex = '402';
            }
            if (!map.getPane('recordRadioPane')) {
                var prRec = map.createPane('recordRadioPane');
                prRec.style.zIndex = '450';
            }
        } catch (ePaneRec) {}

        // Cerrar spiderfy al click afuera (evita duplicaciones)
        map.on('click', function (ev) {
            if (casoRefPickMode && ev && ev.latlng) {
                if (!getCasoIdParaReferencias()) {
                    showFiltrosAlerta('Seleccione un caso de análisis para guardar el punto.', 'warning');
                    setCasoRefPickMode(false);
                    return;
                }
                openCasoRefModal(ev.latlng.lat, ev.latlng.lng);
                setCasoRefPickMode(false);
                showFiltrosAlerta('');
                return;
            }
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
        try { bindMarkerClusterAzimuthClicks(); } catch (eBc0) {}
    }

    function clearMarkers() {
        if (markersLayer) markersLayer.clearLayers();
        try {
            if (recordRadioLayer) recordRadioLayer.clearLayers();
        } catch (eR) {}
        clearExplosion();
        clearAzimuth();
    }

    function isRecordRadioVizEnabled() {
        var cb = document.getElementById('toggle-record-radio-viz');
        return !!(cb && cb.checked);
    }

    function isRecordPerimetroVizEnabled() {
        var cb = document.getElementById('toggle-record-perimetro-viz');
        return !!(cb && cb.checked);
    }

    function drawRecordRadios(puntos) {
        lastRecordRadioPuntos = Array.isArray(puntos) ? puntos.slice() : [];
        if (!recordRadioLayer || !map) return;
        try { recordRadioLayer.clearLayers(); } catch (e0) {}
        if (!isRecordRadioVizEnabled()) return;
        var puntosVisibles = Array.isArray(puntos) ? puntos.slice() : [];
        if (soloOrdenesVisibles && soloOrdenesVisibles.size) {
            puntosVisibles = filterPuntosBySoloOrdenes(puntosVisibles, soloOrdenesVisibles);
        }
        if (isOrdenEnabled() && isOrdenProgressiveEnabled() && ordenVisibleMax != null) {
            puntosVisibles = puntosVisibles.filter(function (p) {
                if (!p) return false;
                var ordMin = null;
                (p.impactos || []).forEach(function (imp) {
                    if (!imp || imp._ord == null) return;
                    var o = parseInt(imp._ord, 10);
                    if (isNaN(o)) return;
                    if (ordMin == null || o < ordMin) ordMin = o;
                });
                if (ordMin == null) return true;
                return ordMin <= ordenVisibleMax;
            });
        }
        (puntosVisibles || []).forEach(function (p) {
            if (!p || p.radius_draw_m == null || p.lat == null || p.lng == null) return;
            var r = parseInt(p.radius_draw_m, 10);
            if (isNaN(r) || r <= 0) return;
            try {
                var celdaTxt = (p.celda_id != null && String(p.celda_id).trim() !== '') ? String(p.celda_id).trim() : '—';
                var rf = p.radius_full_m != null ? parseInt(p.radius_full_m, 10) : null;
                var popupHtml = '<strong>Radio de cobertura (celda)</strong><br>' +
                    'Celda: ' + escapeHtml(celdaTxt) + '<br>' +
                    'Radio dibujado: ' + r + ' m';
                if (!isNaN(rf) && rf > 0) {
                    popupHtml += '<br>Radio completo (BD): ' + rf + ' m';
                }
                if (p.distance_to_center_m != null) {
                    popupHtml += '<br>Dist. al ref.: ' + parseInt(p.distance_to_center_m, 10) + ' m';
                }
                var circ = L.circle([parseFloat(p.lat), parseFloat(p.lng)], {
                    radius: r,
                    color: '#0aa2c0',
                    fillColor: '#0dcaf0',
                    fillOpacity: 0.06,
                    weight: 1,
                    pane: 'recordRadioPane'
                });
                circ.bindPopup(popupHtml, { maxWidth: 300 });
                circ.bindTooltip('Celda ' + celdaTxt + ' · ' + r + ' m', { sticky: true });
                circ.addTo(recordRadioLayer);
            } catch (eC) {}
        });
    }

    function clearRecordTargetOverlay() {
        if (!recordTargetLayer || !map) return;
        try { recordTargetLayer.clearLayers(); } catch (e0) {}
    }

    /** Dibuja marcador(es) y perímetro(es) según puntos de referencia seleccionados (multiselección). */
    function drawRecordRefTargetsOverlay(perimetroM) {
        if (!recordTargetLayer || !map) return;
        clearRecordTargetOverlay();
        if (!isRecordPerimetroVizEnabled()) return;
        var pm = perimetroM != null && perimetroM !== '' ? parseInt(perimetroM, 10) : null;
        if (isNaN(pm) || pm <= 0) pm = null;
        var ids = getRecordRefPointIds();
        ids.forEach(function (pid) {
            var item = casoRefItemsById[String(pid)];
            if (!item || item.lat == null) return;
            var loRaw = item.lon != null && item.lon !== '' ? item.lon : item.lng;
            if (loRaw == null || loRaw === '') return;
            var la = parseFloat(item.lat);
            var lo = parseFloat(loRaw);
            if (isNaN(la) || isNaN(lo)) return;
            var tit = (item.etiqueta && String(item.etiqueta).trim()) ? String(item.etiqueta).trim() : casoRefTipoLabel(item.tipo);
            var popupHtml = '<strong>' + escapeHtml(tit) + '</strong><br>' +
                '<span class="text-muted">' + escapeHtml(casoRefTipoLabel(item.tipo)) + '</span>';
            if (pm != null) popupHtml += '<br>Perímetro: ' + pm + ' m';
            try {
                /* El centro del punto ya se dibuja en casoRefLayer; aquí solo el anillo de perímetro,
                   en un pane por debajo de los radios de celda para que no los tape. */
                if (pm != null) {
                    var circ = L.circle([la, lo], {
                        radius: pm,
                        color: '#dc3545',
                        weight: 2,
                        fillColor: '#dc3545',
                        fillOpacity: 0.04,
                        dashArray: '6 8',
                        pane: 'recordPerimeterPane'
                    }).addTo(recordTargetLayer);
                    circ.bindPopup(popupHtml, { maxWidth: 280 });
                }
            } catch (e1) {}
        });
    }

    function getMapaCasoPrincipalId() {
        var el = document.getElementById('mapa-caso-principal');
        if (!el || !el.value) return null;
        var n = parseInt(el.value, 10);
        return isNaN(n) ? null : n;
    }

    function getMapaDatosModo() {
        var el = document.getElementById('mapa-datos-modo');
        return el ? String(el.value || 'sabana').trim() : 'sabana';
    }

    function isMapaRecordModo() {
        return getMapaDatosModo() === 'record';
    }

    function isMapaAmbosModo() {
        return getMapaDatosModo() === 'ambos';
    }

    function getCasoIdParaReferencias() {
        return getMapaCasoPrincipalId();
    }

    function casoRefTipoLabel(tipo) {
        var m = { domicilio: 'Domicilio', encuentro: 'Punto de encuentro', hecho: 'Lugar del hecho', otro: 'Otro' };
        var t = (tipo || 'otro').toString().trim().toLowerCase();
        return m[t] || 'Otro';
    }

    function casoRefTipoColor(tipo) {
        var m = { domicilio: '#198754', encuentro: '#fd7e14', hecho: '#dc3545', otro: '#6f42c1' };
        var t = (tipo || 'otro').toString().trim().toLowerCase();
        return m[t] || '#6f42c1';
    }

    var CASO_REF_ICON_DEF = {
        pin: { glyph: '📍', title: 'Pin' },
        casa: { glyph: '🏠', title: 'Casa' },
        hecho: { glyph: '⚠️', title: 'Hecho' },
        encuentro: { glyph: '🤝', title: 'Encuentro' },
        auto: { glyph: '🚗', title: 'Vehículo' },
        tienda: { glyph: '🏪', title: 'Comercio' },
        cruz: { glyph: '➕', title: 'Salud' }
    };

    function normalizeCasoRefIconKey(raw) {
        var s = (raw == null ? '' : String(raw)).trim().toLowerCase();
        if (CASO_REF_ICON_DEF[s]) return s;
        return 'pin';
    }

    function casoRefDefaultIconForTipo(tipo) {
        var t = (tipo || 'otro').toString().trim().toLowerCase();
        if (t === 'domicilio') return 'casa';
        if (t === 'encuentro') return 'encuentro';
        if (t === 'hecho') return 'hecho';
        return 'pin';
    }

    function casoRefIconGlyph(key) {
        var k = normalizeCasoRefIconKey(key);
        return (CASO_REF_ICON_DEF[k] || CASO_REF_ICON_DEF.pin).glyph;
    }

    function makeCasoRefDivIcon(iconKey, borderColor) {
        var k = normalizeCasoRefIconKey(iconKey);
        var g = CASO_REF_ICON_DEF[k] || CASO_REF_ICON_DEF.pin;
        var html = '<div class="sabana-caso-ref-pin" style="border-color:' + escapeHtmlAttr(borderColor) + '" title="' + escapeHtmlAttr(g.title) + '">' + g.glyph + '</div>';
        /* Centro del icono = lat/lng (marcar en mapa / clic). Un ancla abajo desplaza el círculo ~radio px hacia arriba; con zoom bajo esos píxeles se ven “cuadras” enteras de desfase. */
        var w = 44;
        var h = 44;
        return L.divIcon({
            className: 'sabana-caso-ref-marker-wrap',
            html: html,
            iconSize: [w, h],
            iconAnchor: [w / 2, h / 2]
        });
    }

    function setCasoRefModalIcon(iconKey) {
        var hid = document.getElementById('modal-caso-ref-icono');
        var grp = document.getElementById('modal-caso-ref-icono-group');
        if (!hid || !grp) return;
        var k = normalizeCasoRefIconKey(iconKey);
        hid.value = k;
        grp.querySelectorAll('.sabana-caso-ref-icono-btn').forEach(function (btn) {
            var isSel = btn.getAttribute('data-caso-ref-icon') === k;
            btn.classList.toggle('active', isSel);
        });
    }

    function clearCasoRefLayer() {
        if (!casoRefLayer) return;
        try { casoRefLayer.clearLayers(); } catch (e0) {}
    }

    function drawCasoRefMarkers(items) {
        clearCasoRefLayer();
        casoRefItemsById = {};
        if (!casoRefLayer || !map || !Array.isArray(items)) return;
        items.forEach(function (p) {
            if (!p || p.lat == null || p.lng == null) return;
            var la = parseFloat(p.lat);
            var lo = parseFloat(p.lng);
            if (isNaN(la) || isNaN(lo)) return;
            if (p.id != null) casoRefItemsById[String(p.id)] = p;
            var col = casoRefTipoColor(p.tipo);
            var iconKey = normalizeCasoRefIconKey(p.icono || casoRefDefaultIconForTipo(p.tipo));
            var mk = L.marker([la, lo], {
                icon: makeCasoRefDivIcon(iconKey, col),
                pane: 'casoRefPane',
                keyboard: false
            });
            var tit = (p.etiqueta && String(p.etiqueta).trim()) ? escapeHtml(String(p.etiqueta).trim()) : escapeHtml(casoRefTipoLabel(p.tipo));
            var lines = [];
            lines.push('<strong>' + tit + '</strong>');
            lines.push('<span class="text-muted">' + escapeHtml(casoRefTipoLabel(p.tipo)) + '</span>');
            if (p.nota) lines.push('<div class="small mt-1">' + escapeHtml(p.nota) + '</div>');
            if (p.created_by) lines.push('<div class="small text-muted mt-1">Registró: ' + escapeHtml(p.created_by) + '</div>');
            lines.push('<div class="mt-2 d-flex gap-2">' +
                '<button type="button" class="btn btn-sm btn-outline-primary caso-ref-edit" data-id="' + String(p.id) + '">Editar</button>' +
                '<button type="button" class="btn btn-sm btn-outline-danger caso-ref-del" data-id="' + String(p.id) + '">Eliminar</button>' +
                '</div>');
            mk.bindPopup(lines.join('<br>'), { maxWidth: 280 });
            mk.on('click', function (e) {
                try {
                    if (e && e.originalEvent) L.DomEvent.stopPropagation(e.originalEvent);
                } catch (eStop) {}
                if (!isRefNumerosClickEnabled() || p.id == null) return;
                var refLabel = (p.etiqueta && String(p.etiqueta).trim()) ? String(p.etiqueta).trim() : casoRefTipoLabel(p.tipo || 'otro');
                openPanelRefNumerosCercanos(p, true);
                fetchRefPuntoNumerosCercanos(p.id).then(function (data) {
                    renderPanelRefNumerosResult(data, refLabel);
                });
            });
            mk.addTo(casoRefLayer);
        });
    }

    function fetchCasoRefPuntos(casoId) {
        if (!casoId) return Promise.resolve([]);
        var q = 'caso_id=' + encodeURIComponent(String(casoId));
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/caso-puntos?' + q, { credentials: 'same-origin' }).then(function (r) {
            return r.json().then(function (j) {
                if (!r.ok) return [];
                return Array.isArray(j) ? j : [];
            });
        }).catch(function () { return []; });
    }

    function appendRecordSharedFiltersToQuery(q, params) {
        if (!params) return;
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

    function isRefNumerosClickEnabled() {
        var cb = document.getElementById('toggle-ref-numeros-click');
        return !!(cb && cb.checked && (isMapaRecordModo() || isMapaAmbosModo()));
    }

    function getRefNumerosBuscarRadioM() {
        var el = document.getElementById('ref-numeros-buscar-radio-m');
        if (!el) return 2000;
        var n = parseInt(String(el.value || '').trim(), 10);
        if (isNaN(n) || n < 50) return 2000;
        return Math.min(n, 500000);
    }

    function getRefNumerosLimit() {
        var el = document.getElementById('ref-numeros-limit');
        if (!el) return 50;
        var n = parseInt(String(el.value || '').trim(), 10);
        if (isNaN(n) || n < 1) return 50;
        return Math.min(n, 500);
    }

    function getRefNumerosGeoMode() {
        var el = document.getElementById('ref-numeros-geo-mode');
        if (!el || !el.value) return 'centro';
        var v = String(el.value).trim().toLowerCase();
        if (v === 'disco' || v === 'sector') return v;
        return 'centro';
    }

    function _setSabanaPanelExtraControlsHidden(hide) {
        ['sabana-panel-prev', 'sabana-panel-next', 'sabana-panel-pos', 'sabana-panel-play', 'sabana-panel-pause'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.classList.toggle('d-none', !!hide);
        });
    }

    function fetchRefPuntoNumerosCercanos(refPuntoId) {
        var cid = getRecordCasoId();
        if (!cid || refPuntoId == null) return Promise.resolve(null);
        var q = new URLSearchParams();
        q.append('caso_id', String(cid));
        q.append('ref_punto_id', String(refPuntoId));
        q.append('perimetro_m', String(getRefNumerosBuscarRadioM()));
        q.append('limit', String(getRefNumerosLimit()));
        q.append('ref_geo_mode', getRefNumerosGeoMode());
        appendRecordSharedFiltersToQuery(q, getFilterParamsSnapshot());
        var fuentes = getRecordFuenteIds();
        (fuentes || []).forEach(function (fid) {
            if (fid != null && fid !== '') q.append('fuente_ids[]', String(fid));
        });
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/ref-punto-numeros-cercanos?' + q.toString(), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) {
            return r.json().then(function (j) {
                if (!r.ok) {
                    return { _error: (j && j.error) ? String(j.error) : ('HTTP ' + r.status) };
                }
                return j;
            });
        }).catch(function () {
            return { _error: 'Error de red.' };
        });
    }

    function openPanelRefNumerosCercanos(refPunto, loading) {
        var refLabel = '';
        try {
            if (refPunto && refPunto.etiqueta && String(refPunto.etiqueta).trim()) refLabel = String(refPunto.etiqueta).trim();
            else if (refPunto) refLabel = casoRefTipoLabel(refPunto.tipo || 'otro');
        } catch (eL) { refLabel = 'Punto de referencia'; }
        currentPanelMode = 'ref_numeros';
        currentPanelPunto = refPunto || null;
        currentPanelImpactos = [];
        currentPanelImpacto = null;
        setPanelTitle('Números cercanos — ' + refLabel);
        setPanelBackVisible(false);
        _setSabanaPanelExtraControlsHidden(true);
        var body = document.getElementById('sabana-panel-body');
        if (body) {
            body.innerHTML = loading
                ? '<div class="text-muted small">Buscando números en celdas cercanas (según filtros del mapa)…</div>'
                : '';
        }
        showPanel();
    }

    function renderPanelRefNumerosResult(data, refLabel) {
        var body = document.getElementById('sabana-panel-body');
        if (!body) return;
        if (data && data._error) {
            body.innerHTML = '<div class="text-danger small">' + escapeHtml(data._error) + '</div>';
            return;
        }
        if (!data || !data.ok) {
            body.innerHTML = '<div class="text-muted small">Sin datos.</div>';
            return;
        }
        var total = data.total_distintos != null ? data.total_distintos : 0;
        var most = data.mostrando != null ? data.mostrando : 0;
        var radio = data.perimetro_m != null ? data.perimetro_m : '—';
        var geoDesc = (data.ref_geo_mode_desc != null && String(data.ref_geo_mode_desc).trim() !== '')
            ? String(data.ref_geo_mode_desc).trim()
            : '';
        var intro = '<p class="small text-muted mb-2">Punto: <strong>' + escapeHtml(refLabel) + '</strong> · Radio búsqueda: ' +
            escapeHtml(String(radio)) + ' m · Distintos encontrados: ' + String(total) +
            (most < total ? (' · Mostrando ' + String(most) + ' (límite)') : '') +
            '. Orden: distancia ref. → antena (menor primero).</p>' +
            (geoDesc ? ('<p class="small text-secondary mb-2">' + escapeHtml(geoDesc) + '</p>') : '');
        var rows = (data.numeros || []).map(function (row, idx) {
            var num = row && row.numero != null ? String(row.numero) : '—';
            var dm = row && row.min_dist_m != null ? String(row.min_dist_m) : '—';
            var im = row && row.impactos != null ? String(row.impactos) : '—';
            var cel = row && row.celda_mas_cercana != null ? String(row.celda_mas_cercana) : '—';
            return '<tr><td class="text-nowrap">' + String(idx + 1) + '</td><td class="text-nowrap fw-semibold">' +
                escapeHtml(num) + '</td><td class="text-nowrap">' + escapeHtml(dm) + '</td><td class="text-nowrap">' +
                escapeHtml(im) + '</td><td class="text-nowrap small">' + escapeHtml(cel) + '</td></tr>';
        }).join('');
        body.innerHTML = intro +
            '<div class="table-responsive"><table class="table table-sm table-hover mb-0">' +
            '<thead><tr><th>#</th><th>Número</th><th>Dist. ref. (m)</th><th>Impactos</th><th>Celda más cercana</th></tr></thead>' +
            '<tbody>' + (rows || '<tr><td colspan="5" class="text-muted">Ningún número en ese radio con los filtros actuales.</td></tr>') + '</tbody></table></div>';
    }

    function reloadCasoRefMarkers() {
        if (!map) return;
        var cid = getCasoIdParaReferencias();
        if (!cid) {
            clearCasoRefLayer();
            renderRecordRefPointOptions([], null);
            return;
        }
        fetchCasoRefPuntos(cid).then(function (items) {
            drawCasoRefMarkers(items);
            var pref = pendingRecordRefPointId != null ? pendingRecordRefPointId : getRecordRefPointId();
            renderRecordRefPointOptions(items, pref);
            if (pendingRecordRefPointId != null) pendingRecordRefPointId = null;
            drawRecordRefTargetsOverlay(getRecordPerimetroM());
        });
    }

    function openCasoRefModal(lat, lng, existing) {
        var latS = Number(lat).toFixed(6);
        var lngS = Number(lng).toFixed(6);
        var idIn = document.getElementById('modal-caso-ref-id');
        var latIn = document.getElementById('modal-caso-ref-lat');
        var lngIn = document.getElementById('modal-caso-ref-lng');
        var lab = document.getElementById('modal-caso-ref-coord-label');
        var tipo = document.getElementById('modal-caso-ref-tipo');
        var etq = document.getElementById('modal-caso-ref-etiqueta');
        var nota = document.getElementById('modal-caso-ref-nota');
        var saveBtn = document.getElementById('modal-caso-ref-guardar');
        if (latIn) latIn.value = latS;
        if (lngIn) lngIn.value = lngS;
        if (lab) lab.textContent = latS + ', ' + lngS;
        if (idIn) idIn.value = (existing && existing.id != null) ? String(existing.id) : '';
        if (tipo) tipo.value = (existing && existing.tipo) ? String(existing.tipo) : 'domicilio';
        if (etq) etq.value = (existing && existing.etiqueta) ? String(existing.etiqueta) : '';
        if (nota) nota.value = (existing && existing.nota) ? String(existing.nota) : '';
        if (saveBtn) saveBtn.textContent = (existing && existing.id != null) ? 'Guardar cambios' : 'Guardar';
        var iconPref = (existing && existing.icono) ? existing.icono : null;
        if (!iconPref && tipo) iconPref = casoRefDefaultIconForTipo(tipo.value);
        setCasoRefModalIcon(iconPref || 'pin');
        var el = document.getElementById('modalCasoMapaPunto');
        if (!el || !window.bootstrap || !window.bootstrap.Modal) {
            alert('Modal no disponible.');
            return;
        }
        if (!casoRefModal) casoRefModal = new window.bootstrap.Modal(el);
        casoRefModal.show();
    }

    function setCasoRefPickMode(active) {
        casoRefPickMode = !!active;
        var btn = document.getElementById('btn-caso-ref-pick');
        if (!btn) return;
        if (casoRefPickMode) {
            btn.classList.remove('btn-outline-primary');
            btn.classList.add('btn-danger');
            btn.innerHTML = '<i class="bi bi-cursor-fill"></i> Clic en el mapa…';
        } else {
            btn.classList.remove('btn-danger');
            btn.classList.add('btn-outline-primary');
            btn.innerHTML = '<i class="bi bi-geo-alt-fill"></i> Punto de referencia';
        }
    }

    function getRecordCasoId() {
        return getMapaCasoPrincipalId();
    }

    function getRecordMaxM() {
        var el = document.getElementById('mapa-record-radio-m');
        if (!el || el.value === '' || el.value == null) return null;
        var n = parseInt(el.value, 10);
        return isNaN(n) ? null : n;
    }

    function getRecordSourceType() {
        // Fuente se maneja con el filtro global "Tipo".
        return '';
    }

    function getRecordFuenteIds() {
        return getSelectedIds('filtro-cargas');
    }

    function getRecordFuenteId() {
        var ids = getRecordFuenteIds();
        return (ids && ids.length) ? ids[0] : null;
    }

    function getRecordRefPointIds() {
        return getSelectedIds('filtro-record-ref-puntos');
    }

    /** Primer punto seleccionado (compatibilidad con resúmenes / foco). */
    function getRecordRefPointId() {
        var ids = getRecordRefPointIds();
        return ids.length ? ids[0] : null;
    }

    function renderRecordRefPointOptions(items, preferredIds) {
        var keep = new Set();
        if (preferredIds != null) {
            if (Array.isArray(preferredIds)) {
                preferredIds.forEach(function (x) { if (x != null) keep.add(String(x)); });
            } else {
                keep.add(String(preferredIds));
            }
        }
        if (!keep.size) {
            getRecordRefPointIds().forEach(function (id) { keep.add(String(id)); });
        }
        var mapped = (items || []).map(function (p) {
            if (!p || p.id == null || p.lat == null || p.lng == null) return null;
            var tipoTxt = casoRefTipoLabel(p.tipo || 'otro');
            var base = (p.etiqueta && String(p.etiqueta).trim()) ? String(p.etiqueta).trim() : tipoTxt;
            var coords = Number(p.lat).toFixed(6) + ', ' + Number(p.lng).toFixed(6);
            var ig = casoRefIconGlyph(p.icono || casoRefDefaultIconForTipo(p.tipo));
            var lbl = ig + ' ' + base + ' (' + tipoTxt + ') — ' + coords;
            return { id: p.id, nombre: lbl };
        }).filter(Boolean);
        renderCheckboxes('filtro-record-ref-puntos', mapped, 'nombre', 'id');
        setCheckedValues('filtro-record-ref-puntos', keep);
        updateDdCount('dd-record-ref-punto', 'filtro-record-ref-puntos', 'Sin punto seleccionado');
    }

    function getRecordCenterLat() {
        var pid = getRecordRefPointId();
        if (pid == null) return null;
        var item = casoRefItemsById[String(pid)];
        if (item && item.lat != null) {
            var n = parseFloat(item.lat);
            return isNaN(n) ? null : n;
        }
        return null;
    }

    function getRecordCenterLng() {
        var pid = getRecordRefPointId();
        if (pid == null) return null;
        var item = casoRefItemsById[String(pid)];
        if (item && item.lng != null) {
            var n = parseFloat(item.lng);
            return isNaN(n) ? null : n;
        }
        return null;
    }

    function getRecordPerimetroM() {
        var el = document.getElementById('mapa-record-perimetro-m');
        if (!el || el.value === '' || el.value == null) return null;
        var n = parseInt(el.value, 10);
        return isNaN(n) ? null : n;
    }

    function fetchRecordFuentes(casoId, sourceType) {
        if (!casoId) return Promise.resolve([]);
        var q = 'caso_id=' + encodeURIComponent(String(casoId));
        if (sourceType) q += '&source_type=' + encodeURIComponent(sourceType);
        q += '&_ts=' + encodeURIComponent(String(Date.now()));
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/record-fuentes?' + q, { credentials: 'same-origin' }).then(function (r) {
            return r.json().then(function (j) {
                if (!r.ok) return [];
                return Array.isArray(j) ? j : [];
            });
        });
    }

    function renderRecordFuentesAsCargas(items, preferredIds) {
        var keep = new Set((preferredIds || []).map(function (v) { return String(v); }));
        if (!keep.size) {
            getSelectedIds('filtro-cargas').forEach(function (id) { keep.add(String(id)); });
        }
        var mapped = (items || []).map(function (it) {
            var nm = String(it && (it.nombre_archivo || ('Fuente #' + it.id)) || '');
            var st = String((it && it.source_type) || '').trim();
            var op = String((it && it.operadora) || '').trim();
            var extra = ['Record'];
            if (st) extra.push(st);
            if (op) extra.push(op);
            return {
                id: it.id,
                nombre: nm + ' [' + extra.join(' · ') + ']'
            };
        }).filter(function (it) { return it && it.id != null; });
        renderCheckboxes('filtro-cargas', mapped, 'nombre', 'id');
        setCheckedValues('filtro-cargas', keep);
        updateDdCount('dd-cargas', 'filtro-cargas', 'Seleccionar…');
    }

    function buildRecordImpactosSearchParams(casoId, maxM, sourceType, fuenteIds, centerLat, centerLng, perimetroM, params, refPuntoIds) {
        var q = new URLSearchParams();
        q.append('caso_id', String(casoId));
        if (maxM != null) q.append('max_m', String(maxM));
        if (sourceType) q.append('source_type', sourceType);
        var ids = Array.isArray(fuenteIds) ? fuenteIds : [];
        ids.forEach(function (fid) {
            if (fid != null && fid !== '') q.append('fuente_ids[]', String(fid));
        });
        var rids = Array.isArray(refPuntoIds) ? refPuntoIds : [];
        rids.forEach(function (rid) {
            if (rid != null && rid !== '') q.append('ref_punto_ids[]', String(rid));
        });
        if (!rids.length) {
            if (centerLat != null) q.append('center_lat', String(centerLat));
            if (centerLng != null) q.append('center_lng', String(centerLng));
        }
        if (perimetroM != null) q.append('perimetro_m', String(perimetroM));
        if (params) {
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
        return q;
    }

    function fetchRecordImpactos(casoId, maxM, sourceType, fuenteIds, centerLat, centerLng, perimetroM, params, refPuntoIds) {
        var q = buildRecordImpactosSearchParams(casoId, maxM, sourceType, fuenteIds, centerLat, centerLng, perimetroM, params, refPuntoIds);
        return fetch(baseUrl + '/sabana-llamadas/api/mapa/record-impactos?' + q.toString(), { credentials: 'same-origin' }).then(function (r) {
            return r.json().then(function (j) {
                if (!r.ok) {
                    var msg = (j && j.error) ? String(j.error) : ('Error HTTP ' + r.status);
                    try { showFiltrosAlerta(msg, 'warning'); } catch (eA) {}
                    return [];
                }
                return Array.isArray(j) ? j : [];
            });
        });
    }

    function appendImpactosFilterParams(q, params) {
        params = params || {};
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
        appendMapaCasoId(q, params);
    }

    function buildExportKmzUrl() {
        var params = getFilterParamsSnapshot();
        var modo = getMapaDatosModo();
        var source = 'sabana';
        if (modo === 'record') source = 'record';
        else if (modo === 'ambos') source = 'ambos';

        var q = new URLSearchParams();
        q.append('source', source);

        if (source === 'sabana') {
            if (!hasFiltroBasicoParams(params)) {
                showFiltrosAlerta('Seleccione al menos sujeto, carga, número o IMEI (o un caso) para exportar.', 'warning');
                return null;
            }
            appendImpactosFilterParams(q, params);
            return baseUrl + '/sabana-llamadas/api/mapa/export-kmz?' + q.toString();
        }

        var casoIdRec = getRecordCasoId();
        if (!casoIdRec) {
            showFiltrosAlerta('Seleccione un caso de análisis para exportar KMZ.', 'warning');
            return null;
        }
        var maxMR = getRecordMaxM();
        var srcT = getRecordSourceType();
        var fuenteIds = getRecordFuenteIds();
        var refPuntoIds = getRecordRefPointIds();
        var centerLat = getRecordCenterLat();
        var centerLng = getRecordCenterLng();
        var perimetroM = getRecordPerimetroM();
        var hasGeo = (refPuntoIds.length > 0 || perimetroM != null);
        if (hasGeo) {
            if (!refPuntoIds.length || perimetroM == null || perimetroM <= 0) {
                showFiltrosAlerta('Para filtro geográfico complete punto de referencia y perímetro.', 'warning');
                return null;
            }
        }
        var rq = buildRecordImpactosSearchParams(casoIdRec, maxMR, srcT || null, fuenteIds, centerLat, centerLng, perimetroM, params, refPuntoIds);
        rq.forEach(function (value, key) { q.append(key, value); });
        if (source === 'ambos') {
            if (!hasFiltroBasicoParams(params)) {
                showFiltrosAlerta('En modo combinado se necesitan también filtros de sábana (sujeto/carga/número/IMEI o caso).', 'warning');
                return null;
            }
            (params.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
            (params.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        }
        return baseUrl + '/sabana-llamadas/api/mapa/export-kmz?' + q.toString();
    }

    function _filenameFromContentDisposition(r) {
        var cd = (r && r.headers && r.headers.get('Content-Disposition')) || '';
        var m = /filename\*=UTF-8''([^;\n]+)|filename="([^"]+)"|filename=([^;\n]+)/i.exec(cd);
        if (!m) return 'mapa_sioc.kmz';
        var raw = (m[1] || m[2] || m[3] || '').trim();
        try {
            return decodeURIComponent(raw.replace(/^["']|["']$/g, ''));
        } catch (e) {
            return raw.replace(/^["']|["']$/g, '') || 'mapa_sioc.kmz';
        }
    }

    function downloadMapaKmz() {
        var url = buildExportKmzUrl();
        if (!url) return;
        fetch(url, { credentials: 'same-origin' }).then(function (r) {
            var ct = (r.headers.get('Content-Type') || '').toLowerCase();
            if (!r.ok) {
                if (ct.indexOf('json') >= 0) {
                    return r.json().then(function (j) {
                        var msg = (j && j.error) ? String(j.error) : ('Error ' + r.status);
                        showFiltrosAlerta(msg, 'warning');
                    });
                }
                showFiltrosAlerta('No se pudo generar el KMZ (HTTP ' + r.status + ').', 'warning');
                return null;
            }
            return r.blob().then(function (blob) {
                return { blob: blob, fname: _filenameFromContentDisposition(r) };
            });
        }).then(function (pack) {
            if (!pack || !pack.blob) return;
            var a = document.createElement('a');
            a.href = URL.createObjectURL(pack.blob);
            a.download = pack.fname || 'mapa_sioc.kmz';
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(function () { try { URL.revokeObjectURL(a.href); } catch (eR) {} }, 2000);
        }).catch(function () {
            showFiltrosAlerta('Error de red al exportar KMZ.', 'warning');
        });
    }

    function updateMapaModoUI() {
        var modoEl = document.getElementById('mapa-datos-modo');
        var wrap = document.getElementById('mapa-record-filtros-wrap');
        var cargasWrap = document.getElementById('mapa-cargas-wrap');
        var ayS = document.getElementById('sabana-filtros-ayuda-sabana');
        var ayR = document.getElementById('sabana-filtros-ayuda-record');
        var sabWrap = document.getElementById('mapa-sabana-caso-wrap');
        var hint = document.getElementById('mapa-caso-ref-hint');
        var modo = modoEl ? String(modoEl.value || '').trim() : 'sabana';
        var recOrAmbos = (modo === 'record' || modo === 'ambos');
        var soloSabana = (modo === 'sabana');
        if (wrap) wrap.classList.toggle('d-none', !recOrAmbos);
        if (cargasWrap) cargasWrap.classList.remove('d-none');
        if (ayS) ayS.classList.toggle('d-none', !soloSabana);
        if (ayR) ayR.classList.toggle('d-none', soloSabana);
        if (sabWrap) sabWrap.classList.toggle('d-none', recOrAmbos);
        if (hint) hint.textContent = '';
        try {
            var cbOrden = document.getElementById('toggle-orden');
            var cbTraz = document.getElementById('toggle-trazado');
            var cbProg = document.getElementById('toggle-orden-prog');
            if (modo === 'ambos') {
                if (cbOrden) { cbOrden.disabled = true; cbOrden.checked = false; }
                if (cbTraz) { cbTraz.disabled = true; cbTraz.checked = false; }
                if (cbProg) { cbProg.disabled = true; }
            } else {
                if (cbOrden) cbOrden.disabled = false;
                if (cbTraz) cbTraz.disabled = false;
                if (cbProg) cbProg.disabled = false;
            }
        } catch (eDis) {}
        try { updateOrdenToggleVisibility(); } catch (eOt) {}
        try { updateTrazadoToggleVisibility(); } catch (eTt) {}
        try { updateRecordVizToggleVisibility(); } catch (eRvz) {}
        try { reloadCasoRefMarkers(); } catch (eMr) {}
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

    function highlightImpact(impacto, fallbackLatLng, hOpts) {
        hOpts = hOpts || {};
        if (!map) return;
        if (!hOpts.keepAzimuthMulti) {
            try { clearAzimuthMulti(); } catch (eCm) {}
        }
        try { clearAzimuthSingle(); } catch (eCs) {}
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
        if (!hOpts.skipSingleAzimuth) {
            try { drawAzimuthForImpact(impacto, latlng); } catch (eAz) {}
        }
    }

    function clearAzimuthSingle() {
        try {
            if (azimuthSingleLayer && map && map.hasLayer(azimuthSingleLayer)) {
                map.removeLayer(azimuthSingleLayer);
            }
        } catch (e) {}
        azimuthSingleLayer = null;
    }

    function clearAzimuthMulti() {
        try {
            if (azimuthMultiGroup && map && map.hasLayer(azimuthMultiGroup)) {
                map.removeLayer(azimuthMultiGroup);
            }
        } catch (e) {}
        azimuthMultiGroup = null;
    }

    function clearAzimuthAllViz() {
        try {
            if (azimuthAllVizGroup && map && map.hasLayer(azimuthAllVizGroup)) {
                map.removeLayer(azimuthAllVizGroup);
            }
        } catch (eA) {}
        azimuthAllVizGroup = null;
    }

    function clearAzimuth() {
        clearAzimuthSingle();
        clearAzimuthMulti();
        clearAzimuthAllViz();
    }

    function isAzimuthAllVizEnabled() {
        var cb = document.getElementById('toggle-azimuth-all-viz');
        return !!(cb && cb.checked);
    }

    /** Órdenes (#_ord) para la capa «Ver azimuts (todos)»: respeta solo-órdenes del mapa (botón Ir) y, si hay checkboxes en «Ir a orden», solo esos # (aunque aún no se haya pulsado Ir). */
    function collectOrdsFromVisiblePuntosForAzimuthAll() {
        var puntos = lastPuntosCeldas;
        if (soloOrdenesVisibles && soloOrdenesVisibles.size) {
            puntos = filterPuntosBySoloOrdenes(lastPuntosCeldas, soloOrdenesVisibles);
        }
        var rows = buildGotoOrdenRowsFromPuntos(puntos);
        var ords = rows.map(function (r) { return r.ord; });
        try {
            var picked = getSelectedGotoOrdenOrds();
            if (picked && picked.length) {
                var want = {};
                picked.forEach(function (o) { want[o] = true; });
                ords = ords.filter(function (o) { return want[o]; });
            }
        } catch (eP) {}
        return ords;
    }

    function fetchAzimuthLocPairsForOrds(ords) {
        if (!ords || !ords.length) return Promise.resolve([]);
        return ensureOrdenImpactosForOrds(ords).then(function () {
            return Promise.all((ords || []).map(function (ord) {
                var ref = resolveImpactoRefForOrd(ord);
                if (!ref) return Promise.resolve(null);
                return fetch(baseUrl + '/sabana-llamadas/api/mapa/impacto-loc?tipo=' + encodeURIComponent(ref.tipo) + '&impacto_id=' + encodeURIComponent(String(ref.impacto_id)), {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' }
                }).then(function (r) { return r.json(); }).then(function (data) {
                    return { ord: ord, data: data };
                });
            }));
        });
    }

    function appendAzimuthPairsToLayerGroup(pairs, layerGroup) {
        var palette = ['#fd7e14', '#d63384', '#198754', '#6f42c1', '#0d6efd', '#20c997'];
        var nDrawn = 0;
        (pairs || []).forEach(function (pair, idx) {
            if (!pair || !pair.data || !pair.data.impacto) return;
            var ord = pair.ord;
            var data = pair.data;
            var imp = data.impacto;
            imp._ord = ord;
            try {
                if (data.azimuth != null) imp._azimuth = data.azimuth;
                if (data.rad_cob_km != null) imp._rad_cob_km = data.rad_cob_km;
                if (data.a_horiz != null) imp._a_horiz = data.a_horiz;
                if (data.a_vert != null) imp._a_vert = data.a_vert;
            } catch (eAz) {}
            var ll = (data.lat != null && data.lng != null) ? L.latLng(data.lat, data.lng) : null;
            if (!ll) return;
            var col = palette[idx % palette.length];
            var poly = buildAzimuthPolygonFromImp(imp, ll, {
                color: col,
                fillColor: col,
                fillOpacity: 0.14,
                weight: 2
            });
            // Record / BD sin azimut: sector no dibuja; mostrar círculo de radio de cobertura aproximado
            if (!poly) {
                var radKmFb = null;
                try {
                    if (data.rad_cob_km != null) radKmFb = parseFloat(String(data.rad_cob_km).replace(',', '.'));
                } catch (eR0) {}
                if (radKmFb == null || isNaN(radKmFb) || radKmFb <= 0) {
                    try {
                        if (imp._rad_cob_km != null) radKmFb = parseFloat(String(imp._rad_cob_km).replace(',', '.'));
                    } catch (eR1) {}
                }
                if (radKmFb == null || isNaN(radKmFb) || radKmFb <= 0) radKmFb = 3;
                try {
                    poly = L.circle(ll, {
                        radius: radKmFb * 1000,
                        color: col,
                        weight: 2,
                        fillColor: col,
                        fillOpacity: 0.08,
                        pane: 'sabanaHighlightPane'
                    });
                } catch (eCirc) {}
            }
            if (!poly) return;
            var celdaTxt = '';
            try {
                var cid = data.celda_id || (imp.tipo === 'gprs' ? (imp.celda || '') : (imp.celda_id || ''));
                if (cid) celdaTxt = ' · ' + String(cid);
            } catch (eC) {}
            var tipAz = (data.azimuth != null || imp._azimuth != null || imp.azimuth != null)
                ? ('Azimut #' + ord + celdaTxt)
                : ('Cobertura #' + ord + celdaTxt + ' (sin sector en BD)');
            poly.bindTooltip(tipAz, { sticky: true, direction: 'center' });
            try {
                poly.addTo(layerGroup);
                nDrawn++;
            } catch (eP) {}
        });
        return nDrawn;
    }

    /** Redibuja la capa «todos los azimuts» según filtros / puntos visibles (independiente de cluster, radios, perímetro). */
    function refreshAzimuthAllViz() {
        clearAzimuthAllViz();
        if (!map || !isAzimuthAllVizEnabled()) return Promise.resolve();
        var ords = collectOrdsFromVisiblePuntosForAzimuthAll();
        if (!ords.length) return Promise.resolve();
        return fetchAzimuthLocPairsForOrds(ords).then(function (pairs) {
            azimuthAllVizGroup = L.layerGroup();
            var nDrawn = appendAzimuthPairsToLayerGroup(pairs, azimuthAllVizGroup);
            if (!nDrawn) {
                azimuthAllVizGroup = null;
                return;
            }
            try {
                azimuthAllVizGroup.addTo(map);
                var b = azimuthAllVizGroup.getBounds();
                if (b && typeof b.isValid === 'function' && b.isValid()) {
                    map.fitBounds(b, { padding: [52, 52], maxZoom: 17 });
                }
            } catch (eF) {}
        }).catch(function () {
            azimuthAllVizGroup = null;
        });
    }

    /** Construye un sector de azimut (polígono) o null si no hay datos. */
    function buildAzimuthPolygonFromImp(imp, latlngOverride, styleOpts) {
        styleOpts = styleOpts || {};
        if (!map) return null;
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
        if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) return null;

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
        if (isNaN(az)) return null;
        if (isNaN(aHoriz) || !aHoriz || aHoriz <= 0) aHoriz = 60;

        var radKm = null;
        try {
            if (imp._rad_cob_km != null) radKm = parseFloat(String(imp._rad_cob_km).replace(',', '.'));
            else if (imp.rad_cob_km != null) radKm = parseFloat(String(imp.rad_cob_km).replace(',', '.'));
        } catch (eRad) {}
        if (isNaN(radKm) || !radKm || radKm <= 0) radKm = 3;

        var radiusMeters = radKm * 1000;
        var centerLat = lat;
        var centerLng = lng;
        var metersPerDegLat = 111320;
        var metersPerDegLng = metersPerDegLat * Math.cos(centerLat * Math.PI / 180);

        function offsetLatLng(cLa, cLo, distanceMeters, bearingDeg) {
            var brad = bearingDeg * Math.PI / 180;
            var dx = distanceMeters * Math.sin(brad);
            var dy = distanceMeters * Math.cos(brad);
            var dLat = dy / metersPerDegLat;
            var dLng = dx / metersPerDegLng;
            return [cLa + dLat, cLo + dLng];
        }

        var half = aHoriz / 2;
        var startAngle = az - half;
        var endAngle = az + half;
        var step = Math.max(5, Math.min(15, aHoriz / 6));

        var pts = [];
        pts.push([centerLat, centerLng]);
        for (var ang = startAngle; ang <= endAngle; ang += step) {
            pts.push(offsetLatLng(centerLat, centerLng, radiusMeters, ang));
        }
        pts.push(offsetLatLng(centerLat, centerLng, radiusMeters, endAngle));
        pts.push([centerLat, centerLng]);

        var col = styleOpts.color || '#fd7e14';
        return L.polygon(pts, {
            color: col,
            weight: styleOpts.weight != null ? styleOpts.weight : 1,
            fillColor: styleOpts.fillColor || col,
            fillOpacity: styleOpts.fillOpacity != null ? styleOpts.fillOpacity : 0.18,
            pane: 'sabanaHighlightPane'
        });
    }

    function drawAzimuthForImpact(imp, latlngOverride) {
        if (!map) return;
        clearAzimuthSingle();
        var poly = buildAzimuthPolygonFromImp(imp, latlngOverride, {
            color: '#fd7e14',
            fillColor: '#fd7e14',
            fillOpacity: 0.18,
            weight: 1
        });
        if (poly) {
            try {
                poly.addTo(map);
                azimuthSingleLayer = poly;
            } catch (eAdd) {}
        }
    }

    /** Dibuja sectores de azimut para varios #orden a la vez (triangulación visual). Un solo # también (p. ej. clic en cluster). No toca la capa del toggle «Ver azimuts (todos)». */
    function drawAzimuthMultiForOrds(ords) {
        clearAzimuthMulti();
        if (!map || !ords || !ords.length) return Promise.resolve();

        return fetchAzimuthLocPairsForOrds(ords).then(function (pairs) {
            azimuthMultiGroup = L.layerGroup();
            var nDrawn = appendAzimuthPairsToLayerGroup(pairs, azimuthMultiGroup);
            if (!nDrawn) {
                azimuthMultiGroup = null;
                return;
            }
            try {
                azimuthMultiGroup.addTo(map);
                var b = azimuthMultiGroup.getBounds();
                if (b && typeof b.isValid === 'function' && b.isValid()) {
                    map.fitBounds(b, { padding: [52, 52], maxZoom: 17 });
                }
            } catch (eF) {}
        }).catch(function () {
            azimuthMultiGroup = null;
        });
    }

    /** Órdenes globales (#_ord) presentes en los marcadores hijos de un cluster. */
    function collectOrdsFromClusterChildMarkers(markers) {
        var set = {};
        (markers || []).forEach(function (mk) {
            var g = mk && mk._group;
            if (!g || !g.puntos) return;
            (g.puntos || []).forEach(function (pt) {
                (pt.impactos || []).forEach(function (imp) {
                    if (!imp || imp._ord == null) return;
                    var o = parseInt(imp._ord, 10);
                    if (!isNaN(o) && o >= 1) set[o] = true;
                });
            });
        });
        return Object.keys(set).map(function (k) { return parseInt(k, 10); }).sort(function (a, b) { return a - b; });
    }

    function onSabanaMarkerClusterClick(ev) {
        try {
            var cluster = ev.layer;
            if (!cluster || typeof cluster.getAllChildMarkers !== 'function') return;
            var ch = cluster.getAllChildMarkers();
            if (!ch || !ch.length) return;
            var ords = collectOrdsFromClusterChildMarkers(ch);
            if (!ords.length) return;
            drawAzimuthMultiForOrds(ords);
        } catch (eCl) {}
    }

    function bindMarkerClusterAzimuthClicks() {
        if (!markersLayer || typeof markersLayer.off !== 'function') return;
        try { markersLayer.off('clusterclick', onSabanaMarkerClusterClick); } catch (eOff) {}
        if (!isClusterEnabled()) return;
        try { markersLayer.on('clusterclick', onSabanaMarkerClusterClick); } catch (eOn) {}
    }

    function _makeCeldaIcon(punto, txtOverride) {
        var col = (colorMode === 'sujeto' || colorMode === 'carga') ? getColorForImpact(null, punto) : null;
        var st = col ? (' style="background:' + col.bg + ';color:' + col.fg + ';"') : '';
        var txt = (txtOverride != null) ? String(txtOverride) : '';
        var rangeCls = (txt.indexOf(' - ') !== -1) ? ' sabana-celda-num--range' : '';
        return L.divIcon({
            className: 'sabana-celda-pin',
            html: '<span class="sabana-celda-num' + rangeCls + '"' + st + '>' + escapeHtml(txt) + '</span>',
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
        if (!opts.soloRedraw) {
            soloOrdenesVisibles = null;
        }
        lastPuntosCeldas = Array.isArray(puntos) ? puntos : [];
        clearMarkers();
        try { celdaMarkerMap.clear(); } catch (eCM) {}
        lastSelectedCeldaKey = null;
        if (!opts.keepPanel) closePanel();
        var bounds = [];

        // Si viene resumen (sin impactos), no podemos numerar global; se numera local al click.
        var anyImpactos = (lastPuntosCeldas || []).some(function (pt) { return pt && Array.isArray(pt.impactos) && pt.impactos.length; });
        if (anyImpactos) {
            // Numeración cronológica GLOBAL (según filtros actuales)
            var flat = [];
            (lastPuntosCeldas || []).forEach(function (pt) {
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

        var puntosParaGrupos = lastPuntosCeldas;
        if (soloOrdenesVisibles && soloOrdenesVisibles.size) {
            puntosParaGrupos = filterPuntosBySoloOrdenes(lastPuntosCeldas, soloOrdenesVisibles);
        }

        var progressive = isOrdenEnabled() && isOrdenProgressiveEnabled();
        var visibleMax = progressive ? ordenVisibleMax : null;

        // Agrupar celdas técnicas por coordenada (muchas celdas pueden compartir el mismo lat/lng).
        // Si no agrupamos, un pin puede "tapar" al otro y se ve #39 aunque exista un #1 debajo.
        var groups = new Map(); // key: "tipo|lat|lng" -> { tipo, lat, lng, puntos:[], ordMinMin, ordMaxMax, countSum, repPunto }
        (puntosParaGrupos || []).forEach(function (p) {
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
            // ord_min/ord_max desde API (sábana); en Record u otros modos ordenMap puede venir vacío: usar # cronológico global (_ord) ya asignado en impactos.
            var impOrdMin = null;
            var impOrdMax = null;
            (g.puntos || []).forEach(function (pt) {
                (pt.impactos || []).forEach(function (imp) {
                    if (!imp || imp._ord == null) return;
                    var o = parseInt(imp._ord, 10);
                    if (isNaN(o)) return;
                    if (impOrdMin == null || o < impOrdMin) impOrdMin = o;
                    if (impOrdMax == null || o > impOrdMax) impOrdMax = o;
                });
            });
            // Pin: siempre el rango cronológico global (#_ord). No mezclar ord_min del API con ord_max de otro origen (evita “46–759”).
            var ordPinMin = impOrdMin != null ? impOrdMin : g.ordMinMin;
            var ordPinMax = impOrdMax != null ? impOrdMax : g.ordMaxMax;

            // Modo “progresivo”: ocultar grupo si el primer # visible queda por encima del máximo mostrado.
            if (progressive && visibleMax != null && ordPinMin != null) {
                if (ordPinMin > visibleMax) return;
            }

            var p = g.repPunto || (g.puntos && g.puntos[0]);
            if (!p) return;
            var lat = g.lat;
            var lng = g.lng;

            var label = (p.celda_direccion || p.celda_id || 'Celda') + ' — ' + (g.countSum || 0) + ' impacto(s)';
            if (g.puntos && g.puntos.length > 1) {
                label += ' (' + g.puntos.length + ' celdas)';
            }

            var baseTxt;
            if (isOrdenEnabled()) {
                if (ordPinMin != null) {
                    if (ordPinMax != null && ordPinMax !== ordPinMin) {
                        baseTxt = ordPinMin + ' - ' + ordPinMax;
                    } else {
                        baseTxt = ordPinMin;
                    }
                } else {
                    baseTxt = '?';
                }
            } else {
                baseTxt = g.countSum || 0;
            }

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
            if (isOrdenEnabled() && ordPinMin != null) {
                tip += ' — Orden: #' + ordPinMin + (ordPinMax != null && ordPinMax !== ordPinMin ? (' → #' + ordPinMax) : '');
            }
            try {
                var cidTip = p.celda_id ? String(normCeldaId(p.celda_id)) : '';
                if (cidTip) tip += '\nCelda: ' + cidTip;
            } catch (eTip) {}
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
        try { refreshGotoOrdenDropdownFromMarkers(); } catch (eGoto) {}
        try {
            if (isAzimuthAllVizEnabled()) {
                setTimeout(function () { try { refreshAzimuthAllViz(); } catch (eAzR) {} }, 0);
            }
        } catch (eAz2) {}
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

    function getFilterParamsSnapshot() {
        var casoId = getMapaCasoPrincipalId();
        var sujetoIds = getSelectedIds('filtro-sujetos');
        var cargaIds = getSelectedIds('filtro-cargas');
        var tipos = getSelectedTipos();
        var provincias = getSelectedStrings('filtro-provincias');
        var localidades = getSelectedStrings('filtro-localidades');
        return {
            caso_id: casoId != null ? casoId : null,
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
    }

    function hasFiltroBasicoParams(params) {
        if (!params) return false;
        var modo = getMapaDatosModo();
        if (params.caso_id != null && params.caso_id !== '') {
            if (modo === 'sabana' || modo === 'ambos' || modo === 'record') return true;
        }
        return (params.sujeto_ids && params.sujeto_ids.length) ||
            (params.carga_ids && params.carga_ids.length) ||
            (params.numeros && params.numeros.length) ||
            (params.imeis && params.imeis.length);
    }

    function showFiltrosAlerta(texto, kind) {
        kind = kind || 'warning';
        var el = document.getElementById('sabana-filtros-alerta');
        if (!el) return;
        if (filtrosInfoTimer) {
            clearTimeout(filtrosInfoTimer);
            filtrosInfoTimer = null;
        }
        if (texto) {
            el.textContent = texto;
            el.className = 'alert py-2 px-3 small mb-2 ' + (kind === 'info' ? 'alert-info' : 'alert-warning');
            el.classList.remove('d-none');
            if (kind === 'info') {
                filtrosInfoTimer = setTimeout(function () {
                    filtrosInfoTimer = null;
                    el.textContent = '';
                    el.classList.add('d-none');
                    el.className = 'alert alert-warning py-2 px-3 small mb-2 d-none';
                }, 10000);
            }
        } else {
            el.textContent = '';
            el.classList.add('d-none');
            el.className = 'alert alert-warning py-2 px-3 small mb-2 d-none';
        }
    }

    function syncFiltroContextSnapshot() {
        var p = getFilterParamsSnapshot();
        ctxSnapSujetos = new Set(p.sujeto_ids || []);
        ctxSnapCargas = new Set(p.carga_ids || []);
        ctxSnapTipos = (p.tipos || []).slice().sort().join(',');
    }

    function resetFiltroContextSnapshot() {
        ctxSnapSujetos = new Set();
        ctxSnapCargas = new Set();
        ctxSnapTipos = '';
    }

    function setsEqualIds(a, b) {
        var aa = Array.from(a).sort(function (x, y) { return x - y; });
        var bb = Array.from(b).sort(function (x, y) { return x - y; });
        if (aa.length !== bb.length) return false;
        for (var i = 0; i < aa.length; i++) {
            if (aa[i] !== bb[i]) return false;
        }
        return true;
    }

    function clearNumerosImeisSelection() {
        selectedNumeros = new Set();
        selectedImeis = new Set();
        var listNum = document.getElementById('filtro-numeros');
        if (listNum) {
            listNum.querySelectorAll('input[type="checkbox"]').forEach(function (cb) { cb.checked = false; });
        }
        var listIm = document.getElementById('filtro-imeis');
        if (listIm) {
            listIm.querySelectorAll('input[type="checkbox"]').forEach(function (cb) { cb.checked = false; });
        }
        renderNumerosSelected();
        renderImeisSelected();
    }

    /**
     * Si ya había números/IMEI y cambia tipo, o cambia carga (cuando ya había cargas), o sujeto (cuando ya había sujetos),
     * limpiamos selección para no mezclar contextos. No limpia al pasar de 0→1 sujeto/carga (ej. enlace desde Relaciones).
     */
    function maybeClearNumerosImeisIfContextChanged() {
        var suj = new Set(getSelectedIds('filtro-sujetos'));
        var car = new Set(getSelectedIds('filtro-cargas'));
        var tip = getSelectedTipos().slice().sort().join(',');
        var hadNumOrIm = selectedNumeros.size > 0 || selectedImeis.size > 0;
        var shouldClear = false;
        if (hadNumOrIm && tip !== ctxSnapTipos) shouldClear = true;
        if (hadNumOrIm && ctxSnapCargas.size > 0 && !setsEqualIds(car, ctxSnapCargas)) shouldClear = true;
        if (hadNumOrIm && ctxSnapSujetos.size > 0 && !setsEqualIds(suj, ctxSnapSujetos)) shouldClear = true;
        if (shouldClear) {
            clearNumerosImeisSelection();
            showFiltrosAlerta('Se quitaron los números e IMEIs seleccionados porque cambió sujeto, carga o tipo. Elija de nuevo y pulse Aplicar filtros.', 'info');
        }
        ctxSnapSujetos = suj;
        ctxSnapCargas = car;
        ctxSnapTipos = tip;
    }

    function getCheckedLabelTexts(containerId) {
        var c = document.getElementById(containerId);
        if (!c) return [];
        var out = [];
        c.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
            var id = cb.id;
            var lab = id ? c.querySelector('label[for="' + id + '"]') : null;
            var t = (lab && lab.textContent) ? String(lab.textContent).trim() : String(cb.value || '').trim();
            if (t) out.push(t);
        });
        return out;
    }

    function buildSabanaResumenParts(params) {
        if (!params) return [];
        var parts = [];
        if (params.caso_id != null && params.caso_id !== '') {
            parts.push('Caso expediente #' + params.caso_id);
        }
        var ns = params.numeros ? params.numeros.length : 0;
        var ni = params.imeis ? params.imeis.length : 0;
        var nSuj = params.sujeto_ids ? params.sujeto_ids.length : 0;
        var nCar = params.carga_ids ? params.carga_ids.length : 0;
        if (nSuj) {
            var labs = getCheckedLabelTexts('filtro-sujetos');
            if (labs.length <= 2) parts.push('Sujetos: ' + labs.join(', '));
            else parts.push('Sujetos: ' + nSuj + ' seleccionado(s)');
        }
        if (nCar) {
            var clabs = getCheckedLabelTexts('filtro-cargas');
            if (clabs.length <= 1) parts.push('Cargas: ' + clabs.join(', '));
            else parts.push('Cargas: ' + nCar + ' seleccionada(s)');
        }
        if (params.tipos && params.tipos.length) {
            parts.push('Tipo: ' + params.tipos.map(function (t) { return String(t).toUpperCase(); }).join(' + '));
        }
        if (params.fecha_desde || params.fecha_hasta) {
            parts.push('Fecha: ' + (params.fecha_desde || '…') + ' → ' + (params.fecha_hasta || '…'));
        }
        if (params.hora_desde || params.hora_hasta) {
            parts.push('Hora: ' + (params.hora_desde || '…') + ' → ' + (params.hora_hasta || '…'));
        }
        var np = params.provincias ? params.provincias.length : 0;
        var nl = params.localidades ? params.localidades.length : 0;
        if (np) parts.push('Prov.: ' + np);
        if (nl) parts.push('Loc.: ' + nl);
        if (ns) parts.push('Nº: ' + ns);
        if (ni) parts.push('IMEI: ' + ni);
        return parts;
    }

    function updateFiltrosResumenUI(params, recordInfo) {
        var el = document.getElementById('sabana-filtros-resumen');
        if (!el) return;
        if (recordInfo && recordInfo.caso_id != null) {
            var parts = [recordInfo._ambos ? 'Sábana + Record' : 'Modo Record'];
            if (recordInfo.max_m != null && recordInfo.max_m !== '') {
                parts.push('Radio máx. ' + recordInfo.max_m + ' m');
            } else {
                parts.push('Radio: completo por celda');
            }
            if (recordInfo.fuente_ids && recordInfo.fuente_ids.length) {
                parts.push('Archivo: ' + (recordInfo.fuente_label || ('#' + recordInfo.fuente_ids[0])));
            } else {
                parts.push('Archivo: todos');
            }
            var nRef = recordInfo.ref_punto_ids ? recordInfo.ref_punto_ids.length : 0;
            if (recordInfo.perimetro_m != null && (nRef > 0 || (recordInfo.center_lat != null && recordInfo.center_lng != null))) {
                if (recordInfo.ref_punto_label) parts.push('Punto ref.: ' + String(recordInfo.ref_punto_label));
                else if (nRef > 1) parts.push('Puntos ref.: ' + nRef + ' seleccionados');
                else if (recordInfo.center_lat != null && recordInfo.center_lng != null) {
                    parts.push('Punto: ' + Number(recordInfo.center_lat).toFixed(6) + ', ' + Number(recordInfo.center_lng).toFixed(6));
                }
                parts.push('Perímetro: ' + recordInfo.perimetro_m + ' m');
            }
            if (recordInfo._ambos) {
                var sabExtra = buildSabanaResumenParts(params);
                if (sabExtra.length) parts.push('Capa sábana: ' + sabExtra.join(' · '));
            }
            el.textContent = 'Filtros activos en el mapa: ' + parts.join(' · ');
            el.classList.remove('d-none');
            return;
        }
        if (!params || !hasFiltroBasicoParams(params)) {
            el.textContent = '';
            el.classList.add('d-none');
            return;
        }
        var parts = [];
        var ns = params.numeros ? params.numeros.length : 0;
        var ni = params.imeis ? params.imeis.length : 0;
        var nSuj = params.sujeto_ids ? params.sujeto_ids.length : 0;
        var nCar = params.carga_ids ? params.carga_ids.length : 0;

        if (nSuj) {
            var labs = getCheckedLabelTexts('filtro-sujetos');
            if (labs.length <= 2) parts.push('Sujetos: ' + labs.join(', '));
            else parts.push('Sujetos: ' + nSuj + ' seleccionado(s)');
        }
        if (nCar) {
            var clabs = getCheckedLabelTexts('filtro-cargas');
            if (clabs.length <= 1) parts.push('Cargas: ' + clabs.join(', '));
            else parts.push('Cargas: ' + nCar + ' seleccionada(s)');
        }
        if (params.tipos && params.tipos.length) {
            parts.push('Tipo: ' + params.tipos.map(function (t) { return String(t).toUpperCase(); }).join(' + '));
        }
        if (params.fecha_desde || params.fecha_hasta) {
            parts.push('Fecha: ' + (params.fecha_desde || '…') + ' → ' + (params.fecha_hasta || '…'));
        }
        if (params.hora_desde || params.hora_hasta) {
            parts.push('Hora: ' + (params.hora_desde || '…') + ' → ' + (params.hora_hasta || '…'));
        }
        var np = params.provincias ? params.provincias.length : 0;
        var nl = params.localidades ? params.localidades.length : 0;
        if (np) parts.push('Prov.: ' + np);
        if (nl) parts.push('Loc.: ' + nl);
        if (ns) parts.push('Nº: ' + ns);
        if (ni) parts.push('IMEI: ' + ni);

        el.textContent = 'Filtros activos en el mapa: ' + parts.join(' · ');
        el.classList.remove('d-none');
    }

    function aplicarFiltros(opts) {
        opts = opts || {};
        var skipAutoFocusOrden1 = opts.skipAutoFocusOrden1 === true;
        var onComplete = opts.onComplete;
        function fireComplete() {
            try {
                if (isMapaRecordModo() && getRecordCasoId()) {
                    /* modo record: no sincronizar snapshot de sujetos/cargas de sábana */
                } else if (hasFiltroBasicoParams(getFilterParamsSnapshot())) {
                    syncFiltroContextSnapshot();
                } else {
                    resetFiltroContextSnapshot();
                }
            } catch (eSnap) {}
            if (typeof onComplete !== 'function') return;
            try { onComplete(); } catch (eCb) {}
        }
        var token = ++lastRequestToken;
        var params = getFilterParamsSnapshot();

        if (isMapaRecordModo()) {
            var casoIdRec = getRecordCasoId();
            if (!casoIdRec) {
                lastAppliedParams = null;
                clearMarkers();
                clearRuta();
                try { clearTrazado(); } catch (eTr0) {}
                updateFiltrosResumenUI(null, null);
                showFiltrosAlerta('Seleccione un caso de análisis (record) y pulse Aplicar filtros.');
                fireComplete();
                return;
            }
            var maxMR = getRecordMaxM();
            var srcT = getRecordSourceType();
            var fuenteIds = getRecordFuenteIds();
            var refPuntoIds = getRecordRefPointIds();
            var centerLat = getRecordCenterLat();
            var centerLng = getRecordCenterLng();
            var perimetroM = getRecordPerimetroM();
            var hasGeoAny = (refPuntoIds.length > 0 || perimetroM != null);
            if (hasGeoAny) {
                if (!refPuntoIds.length || perimetroM == null || perimetroM <= 0) {
                    showFiltrosAlerta('Para filtro geográfico en record seleccione al menos un punto de referencia y perímetro (> 0).');
                    fireComplete();
                    return;
                }
            }
            var selCaso = document.getElementById('mapa-caso-principal');
            var casoLabel = '';
            var fuenteLabel = '';
            var refLabel = '';
            try {
                if (selCaso && selCaso.selectedIndex >= 0) {
                    casoLabel = String(selCaso.options[selCaso.selectedIndex].textContent || '').trim();
                }
                var flabs = getCheckedLabelTexts('filtro-cargas');
                if (flabs.length === 1) fuenteLabel = flabs[0];
                else if (flabs.length > 1) fuenteLabel = flabs.length + ' archivo(s) seleccionado(s)';
                var refLabs = getCheckedLabelTexts('filtro-record-ref-puntos');
                if (refLabs.length === 1) refLabel = refLabs[0];
                else if (refLabs.length > 1) refLabel = refLabs.length + ' punto(s) de referencia';
            } catch (eLb) {}
            lastAppliedParams = {
                _record_mode: true,
                caso_id: casoIdRec,
                max_m: maxMR,
                source_type: srcT,
                fuente_id: (fuenteIds.length ? fuenteIds[0] : null),
                fuente_ids: fuenteIds,
                ref_punto_ids: refPuntoIds,
                ref_punto_id: refPuntoIds.length ? refPuntoIds[0] : null,
                ref_punto_label: refLabel,
                center_lat: centerLat,
                center_lng: centerLng,
                perimetro_m: perimetroM
            };
            resetColoring(params);
            drawRecordRefTargetsOverlay(perimetroM);
            var panelRec = document.getElementById('panel-ruta');
            if (panelRec) panelRec.classList.add('d-none');
            clearRuta();
            try { clearTrazado(); } catch (eTr1) {}

            fetchRecordImpactos(casoIdRec, maxMR, srcT || null, fuenteIds, centerLat, centerLng, perimetroM, params, refPuntoIds).then(function (puntos) {
                if (token !== lastRequestToken) return;
                addMarkers(puntos);
                drawRecordRadios(puntos);
                try {
                    if (isTrazadoEnabled()) refreshTrazadoLayerIfNeeded();
                } catch (eTrz) {}
                setTimeout(captureMapForInforme, 800);
                updateFiltrosResumenUI(null, {
                    caso_id: casoIdRec,
                    caso_label: casoLabel,
                    max_m: maxMR,
                    source_type: srcT,
                    fuente_id: (fuenteIds.length ? fuenteIds[0] : null),
                    fuente_ids: fuenteIds,
                    fuente_label: fuenteLabel,
                    ref_punto_ids: refPuntoIds,
                    ref_punto_id: refPuntoIds.length ? refPuntoIds[0] : null,
                    ref_punto_label: refLabel,
                    center_lat: centerLat,
                    center_lng: centerLng,
                    perimetro_m: perimetroM
                });
                fireComplete();
            }).catch(function () {
                if (token !== lastRequestToken) return;
                addMarkers([]);
                try { drawRecordRadios([]); } catch (eDr) {}
                clearRecordTargetOverlay();
                updateFiltrosResumenUI(null, null);
                fireComplete();
            });
            return;
        }

        if (isMapaAmbosModo()) {
            var casoIdAmb = getRecordCasoId();
            if (!casoIdAmb) {
                lastAppliedParams = null;
                clearMarkers();
                clearRuta();
                try { clearTrazado(); } catch (eTrAmb0) {}
                updateFiltrosResumenUI(null, null);
                showFiltrosAlerta('Seleccione un caso y pulse Aplicar filtros.');
                fireComplete();
                return;
            }
            if (!hasFiltroBasicoParams(params)) {
                lastAppliedParams = null;
                clearMarkers();
                clearRuta();
                try { clearTrazado(); } catch (eTrAmb1) {}
                updateFiltrosResumenUI(null, null);
                fireComplete();
                return;
            }
            var maxMAmb = getRecordMaxM();
            var srcTAmb = getRecordSourceType();
            var fuenteIdsAmb = getRecordFuenteIds();
            var refPuntoIdsAmb = getRecordRefPointIds();
            var centerLatAmb = getRecordCenterLat();
            var centerLngAmb = getRecordCenterLng();
            var perimetroMAmb = getRecordPerimetroM();
            var hasGeoAmb = (refPuntoIdsAmb.length > 0 || perimetroMAmb != null);
            if (hasGeoAmb) {
                if (!refPuntoIdsAmb.length || perimetroMAmb == null || perimetroMAmb <= 0) {
                    showFiltrosAlerta('Para filtro geográfico en record seleccione al menos un punto de referencia y perímetro (> 0).');
                    fireComplete();
                    return;
                }
            }
            var selCasoAmb = document.getElementById('mapa-caso-principal');
            var casoLabelAmb = '';
            var fuenteLabelAmb = '';
            var refLabelAmb = '';
            try {
                if (selCasoAmb && selCasoAmb.selectedIndex >= 0) {
                    casoLabelAmb = String(selCasoAmb.options[selCasoAmb.selectedIndex].textContent || '').trim();
                }
                var flabsAmb = getCheckedLabelTexts('filtro-cargas');
                if (flabsAmb.length === 1) fuenteLabelAmb = flabsAmb[0];
                else if (flabsAmb.length > 1) fuenteLabelAmb = flabsAmb.length + ' archivo(s) seleccionado(s)';
                var refLabsAmb = getCheckedLabelTexts('filtro-record-ref-puntos');
                if (refLabsAmb.length === 1) refLabelAmb = refLabsAmb[0];
                else if (refLabsAmb.length > 1) refLabelAmb = refLabsAmb.length + ' punto(s) de referencia';
            } catch (eLbAmb) {}
            lastAppliedParams = params;
            resetColoring(params);
            drawRecordRefTargetsOverlay(perimetroMAmb);
            var panelAmb = document.getElementById('panel-ruta');
            if (panelAmb) panelAmb.classList.add('d-none');
            clearRuta();
            try { clearTrazado(); } catch (eTrAmb2) {}

            Promise.all([
                fetchRecordImpactos(casoIdAmb, maxMAmb, srcTAmb || null, fuenteIdsAmb, centerLatAmb, centerLngAmb, perimetroMAmb, params, refPuntoIdsAmb),
                fetchImpactos(params)
            ]).then(function (results) {
                var puntosRec = Array.isArray(results[0]) ? results[0] : [];
                var puntosSab = Array.isArray(results[1]) ? results[1] : [];
                if (token !== lastRequestToken) return;
                addMarkers(puntosSab.concat(puntosRec));
                try { drawRecordRadios(puntosRec); } catch (eDrAmb) {}
                setTimeout(captureMapForInforme, 800);
                updateFiltrosResumenUI(params, {
                    _ambos: true,
                    caso_id: casoIdAmb,
                    caso_label: casoLabelAmb,
                    max_m: maxMAmb,
                    source_type: srcTAmb,
                    fuente_id: (fuenteIdsAmb.length ? fuenteIdsAmb[0] : null),
                    fuente_ids: fuenteIdsAmb,
                    fuente_label: fuenteLabelAmb,
                    ref_punto_ids: refPuntoIdsAmb,
                    ref_punto_id: refPuntoIdsAmb.length ? refPuntoIdsAmb[0] : null,
                    ref_punto_label: refLabelAmb,
                    center_lat: centerLatAmb,
                    center_lng: centerLngAmb,
                    perimetro_m: perimetroMAmb
                });
                fireComplete();
            }).catch(function () {
                if (token !== lastRequestToken) return;
                addMarkers([]);
                try { drawRecordRadios([]); } catch (eDrAmb2) {}
                updateFiltrosResumenUI(null, null);
                fireComplete();
            });
            return;
        }

        clearRecordTargetOverlay();

        // Para evitar que se carguen "todos los archivos" al entrar como SUPERADMIN
        // o sin filtros, sólo aplicamos si hay al menos una carga, sujeto, número o IMEI seleccionado.
        if (!hasFiltroBasicoParams(params)) {
            lastAppliedParams = null;
            clearMarkers();
            clearRuta();
            updateFiltrosResumenUI(null, null);
            fireComplete();
            return;
        }
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
            }).finally(function () {
                if (token !== lastRequestToken) return;
                updateFiltrosResumenUI(lastAppliedParams);
                fireComplete();
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
                    // Guardar captura del mapa para el informe (Relaciones)
                    setTimeout(captureMapForInforme, 800);
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
                    if (isOrdenEnabled() && !skipAutoFocusOrden1) {
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
                    updateFiltrosResumenUI(lastAppliedParams);
                    fireComplete();
                }).catch(function () {
                    if (token !== lastRequestToken) return;
                    addMarkers([]);
                    clearTrazado();
                    updateFiltrosResumenUI(lastAppliedParams);
                    fireComplete();
                });
            }).catch(function () {
                if (token !== lastRequestToken) return;
                updateFiltrosResumenUI(lastAppliedParams);
                fireComplete();
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
                if (!this.checked) {
                    try { clearAzimuthMulti(); } catch (eAz) {}
                }
                rebuildMarkersLayer();
            });
        }

        var cbAzimuthAll = document.getElementById('toggle-azimuth-all-viz');
        if (cbAzimuthAll) {
            try {
                var savedAz = localStorage.getItem('sabana_viz_azimuth_all');
                if (savedAz != null) {
                    var sa = String(savedAz).toLowerCase().trim();
                    cbAzimuthAll.checked = (sa === '1' || sa === 'true' || sa === 'si' || sa === 'sí');
                }
            } catch (eAzLs) {}
            cbAzimuthAll.addEventListener('change', function () {
                try { localStorage.setItem('sabana_viz_azimuth_all', this.checked ? '1' : '0'); } catch (eAzSt) {}
                if (this.checked) {
                    try { refreshAzimuthAllViz(); } catch (eAzRf) {}
                } else {
                    try { clearAzimuthAllViz(); } catch (eAzCl) {}
                }
            });
        }

        var cbRecRadioViz = document.getElementById('toggle-record-radio-viz');
        if (cbRecRadioViz) {
            try {
                var sVr = localStorage.getItem('sabana_viz_record_radio');
                if (sVr != null) cbRecRadioViz.checked = sVr === '1';
            } catch (eVr) {}
            cbRecRadioViz.addEventListener('change', function () {
                try { localStorage.setItem('sabana_viz_record_radio', this.checked ? '1' : '0'); } catch (eL) {}
                try { drawRecordRadios(lastRecordRadioPuntos); } catch (eDr) {}
            });
        }
        var cbRecPeriViz = document.getElementById('toggle-record-perimetro-viz');
        if (cbRecPeriViz) {
            try {
                var sVp = localStorage.getItem('sabana_viz_record_perimetro');
                if (sVp != null) cbRecPeriViz.checked = sVp === '1';
            } catch (eVp) {}
            cbRecPeriViz.addEventListener('change', function () {
                try { localStorage.setItem('sabana_viz_record_perimetro', this.checked ? '1' : '0'); } catch (eL2) {}
                try { drawRecordRefTargetsOverlay(getRecordPerimetroM()); } catch (eDp) {}
            });
        }
        var cbRefNumerosClick = document.getElementById('toggle-ref-numeros-click');
        if (cbRefNumerosClick) {
            try {
                var sRn = localStorage.getItem('sabana_ref_numeros_click');
                if (sRn != null) cbRefNumerosClick.checked = sRn === '1';
            } catch (eRn) {}
            cbRefNumerosClick.addEventListener('change', function () {
                try { localStorage.setItem('sabana_ref_numeros_click', this.checked ? '1' : '0'); } catch (eRnSt) {}
            });
        }
        var inpRefRnRadio = document.getElementById('ref-numeros-buscar-radio-m');
        if (inpRefRnRadio) {
            try {
                var sRr = localStorage.getItem('sabana_ref_numeros_radio_m');
                if (sRr != null && String(sRr).trim() !== '') inpRefRnRadio.value = String(sRr).trim();
            } catch (eRr) {}
            inpRefRnRadio.addEventListener('change', function () {
                try { localStorage.setItem('sabana_ref_numeros_radio_m', String(this.value || '').trim()); } catch (eRrSt) {}
            });
        }
        var inpRefRnLim = document.getElementById('ref-numeros-limit');
        if (inpRefRnLim) {
            try {
                var sRl = localStorage.getItem('sabana_ref_numeros_limit');
                if (sRl != null && String(sRl).trim() !== '') inpRefRnLim.value = String(sRl).trim();
            } catch (eRl) {}
            inpRefRnLim.addEventListener('change', function () {
                try { localStorage.setItem('sabana_ref_numeros_limit', String(this.value || '').trim()); } catch (eRlSt) {}
            });
        }
        var selRefGeo = document.getElementById('ref-numeros-geo-mode');
        if (selRefGeo) {
            try {
                var sGm = localStorage.getItem('sabana_ref_numeros_geo_mode');
                if (sGm === 'centro' || sGm === 'disco' || sGm === 'sector') selRefGeo.value = sGm;
            } catch (eGm) {}
            selRefGeo.addEventListener('change', function () {
                try {
                    var gv = String(this.value || 'centro').trim().toLowerCase();
                    if (gv === 'disco' || gv === 'sector' || gv === 'centro') {
                        localStorage.setItem('sabana_ref_numeros_geo_mode', gv);
                    }
                } catch (eGmSt) {}
            });
        }
        try { updateRecordVizToggleVisibility(); } catch (eRw) {}

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
                try {
                    if (this.checked && !isVistaRuta()) {
                        refreshTrazadoLayerIfNeeded();
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

        // Ir a orden (lista cronológica multiselección): filtra el mapa a solo esos #orden y acota la vista.
        var gotoBtn = document.getElementById('btn-goto-orden');
        var gotoInicioBtn = document.getElementById('btn-goto-inicio');
        var gotoSearch = document.getElementById('goto-orden-search');
        function applySoloOrdenAMapa(ords) {
            ords = (ords || []).slice().sort(function (a, b) { return a - b; });
            if (!ords.length) return;
            soloOrdenesVisibles = new Set(ords);
            addMarkers(lastPuntosCeldas, { soloRedraw: true, keepPanel: true, keepView: false });
            try {
                if (isMapaRecordModo() || isMapaAmbosModo()) drawRecordRadios(lastRecordRadioPuntos);
            } catch (eDrGo) {}
            try {
                if (isMapaRecordModo() && isTrazadoEnabled()) refreshTrazadoLayerIfNeeded();
            } catch (eTrzGo) {}
        }
        function doGoto() {
            var ords = getSelectedGotoOrdenOrds();
            if (!ords.length) return;
            var pending = ords.slice().sort(function (a, b) { return a - b; });
            var cbOrden = document.getElementById('toggle-orden');
            function focusSelection() {
                doGotoOrdenNavigate(pending);
            }
            if (cbOrden && !cbOrden.checked) {
                cbOrden.checked = true;
                try { localStorage.setItem('sabana_orden_enabled', '1'); } catch (e) {}
                try { updateOrdenToggleVisibility(); } catch (eV) {}
                aplicarFiltros({
                    skipAutoFocusOrden1: true,
                    onComplete: function () {
                        applySoloOrdenAMapa(pending);
                        focusSelection();
                    }
                });
                return;
            }
            applySoloOrdenAMapa(pending);
            focusSelection();
        }
        if (gotoBtn) gotoBtn.addEventListener('click', doGoto);
        if (gotoInicioBtn) gotoInicioBtn.addEventListener('click', function () {
            soloOrdenesVisibles = null;
            try {
                addMarkers(lastPuntosCeldas, { soloRedraw: true, keepPanel: true, keepView: false });
                try {
                    if (isMapaRecordModo() || isMapaAmbosModo()) drawRecordRadios(lastRecordRadioPuntos);
                } catch (eDrIni) {}
                try {
                    if (isMapaRecordModo() && isTrazadoEnabled()) refreshTrazadoLayerIfNeeded();
                } catch (eTrzIni) {}
            } catch (eIni) {}
            gotoOrden(1);
        });
        if (gotoSearch) gotoSearch.addEventListener('input', function () { filterGotoOrdenList(this.value); });
        var gotoSelTodas = document.getElementById('goto-orden-sel-todas');
        if (gotoSelTodas) gotoSelTodas.addEventListener('click', function (e) {
                e.preventDefault();
            var list = document.getElementById('goto-orden-list');
            if (!list) return;
            list.querySelectorAll('input.goto-orden-cb').forEach(function (cb) { cb.checked = true; });
            updateGotoOrdenDropdownLabel();
        });
        var gotoSelNinguna = document.getElementById('goto-orden-sel-ninguna');
        if (gotoSelNinguna) gotoSelNinguna.addEventListener('click', function (e) {
            e.preventDefault();
            clearGotoOrdenSelection();
        });
        var gotoWrap = document.querySelector('.sabana-goto-orden-wrap');
        if (gotoWrap && !gotoWrap._gotoOrdenDelegated) {
            gotoWrap._gotoOrdenDelegated = true;
            gotoWrap.addEventListener('change', function (e) {
                if (e.target && e.target.classList && e.target.classList.contains('goto-orden-cb')) {
                    updateGotoOrdenDropdownLabel();
                    if (isAzimuthAllVizEnabled()) {
                        try { refreshAzimuthAllViz(); } catch (eAzG) {}
                    }
                }
            });
        }
        var btnQuitarSoloOrden = document.getElementById('btn-goto-orden-quitar-solo');
        if (btnQuitarSoloOrden) btnQuitarSoloOrden.addEventListener('click', function (e) {
            e.preventDefault();
            soloOrdenesVisibles = null;
            try {
                addMarkers(lastPuntosCeldas, { soloRedraw: true, keepPanel: true, keepView: false });
            } catch (eQs) {}
        });

        // Inicializar selección de números/IMEIs desde la URL (por ejemplo, links desde Relaciones)
        var hadUrlNumeros = false;
        try {
            var sp = new URLSearchParams(window.location.search || '');
            var urlNumeros = [];
            sp.getAll('numeros').forEach(function (v) {
                if (v != null && String(v).trim()) urlNumeros.push(String(v).trim());
            });
            sp.getAll('numeros[]').forEach(function (v) {
                if (v != null && String(v).trim()) urlNumeros.push(String(v).trim());
            });
            urlNumeros.forEach(function (n) { selectedNumeros.add(n); });
            hadUrlNumeros = urlNumeros.length > 0;
        } catch (e) {}

        // Si venimos desde Relaciones (números en URL), por defecto sin cluster (tipo VOZ se aplica tras cargar opciones)
        if (hadUrlNumeros) {
            try {
                var cbCluster = document.getElementById('toggle-cluster');
                if (cbCluster && cbCluster.checked) {
                    cbCluster.checked = false;
                    try { localStorage.setItem('sabana_cluster_enabled', '0'); } catch (eLs) {}
                    rebuildMarkersLayer();
                }
            } catch (eCl) {}
        }

        try {
            var spMap = new URLSearchParams(window.location.search || '');
            var modoQ = String(spMap.get('modo') || '').trim().toLowerCase();
            var mcInit = document.getElementById('mapa-datos-modo');
            if (modoQ === 'record' && mcInit) mcInit.value = 'record';
            if (modoQ === 'ambos' && mcInit) mcInit.value = 'ambos';
            var cidQ = parseInt(String(spMap.get('caso_id') || '').trim(), 10);
            var selPrincipalInit = document.getElementById('mapa-caso-principal');
            if (!isNaN(cidQ) && cidQ > 0 && selPrincipalInit) {
                var optInit = selPrincipalInit.querySelector('option[value="' + cidQ + '"]');
                if (optInit) selPrincipalInit.value = String(cidQ);
            }
            var mmQ = spMap.get('max_m');
            var rInInit = document.getElementById('mapa-record-radio-m');
            if (mmQ != null && mmQ !== '' && rInInit) rInInit.value = String(mmQ);
            var fidQ = parseInt(String(spMap.get('fuente_id') || '').trim(), 10);
            var fuentePrefInit = (!isNaN(fidQ) && fidQ > 0) ? [fidQ] : [];
            var refQ = parseInt(String(spMap.get('punto_ref_id') || '').trim(), 10);
            pendingRecordRefPointId = (!isNaN(refQ) && refQ > 0) ? refQ : null;
            var perQ = spMap.get('perimetro_m');
            var rPerInit = document.getElementById('mapa-record-perimetro-m');
            if (perQ != null && perQ !== '' && rPerInit) rPerInit.value = String(perQ);
        } catch (eUrlEarly) {}
        try { syncMapaCasoDropdownButton(); syncMapaModoDropdownButton(); } catch (eSyncTb) {}
        try { updateMapaModoUI(); } catch (eMuEarly) {}

        fetchFiltros().then(function (data) {
            renderCheckboxes('filtro-sujetos', data.sujetos || [], 'nombre', 'id');
            updateDdCount('dd-sujetos', 'filtro-sujetos', 'Seleccionar…');
            return loadUnifiedCargasOptions(fuentePrefInit || []);
        }).then(function () {
            return reloadMapaTiposOpciones();
        }).then(function () {
            var fs = getFilterParamsSnapshot();
            return Promise.all([
                fetchProvincias('', fs).then(function (items) {
                    renderSimpleCheckboxList('filtro-provincias', items || [], 'prov');
                    updateDdCount('dd-provincias', 'filtro-provincias', 'Seleccionar…');
                }).catch(function () {}),
                fetchLocalidades('', fs).then(function (items) {
                    renderSimpleCheckboxList('filtro-localidades', items || [], 'loc');
                    updateDdCount('dd-localidades', 'filtro-localidades', 'Seleccionar…');
                }).catch(function () {})
            ]);
        }).then(function () {
            try {
                if (hadUrlNumeros) {
                    setCheckedValues('filtro-tipos', new Set(['voz']));
            updateDdTipos();
                }
            } catch (eUrlT) {}
            try { syncFiltroContextSnapshot(); } catch (eFc) {}
        });

        initDropdownSearch();
        initMapaToolbarDropdowns();
        renderNumerosSelected();
        renderImeisSelected();

        // Si venimos desde Relaciones con números en la URL, aplicar filtros automáticamente
        if (hadUrlNumeros) {
            scheduleAutoApply(400);
        }

        // Cascada: cuando abrimos el dropdown de provincias/localidades,
        // recargamos las opciones basadas en los filtros ya seleccionados (sin aplicar aún el mapa).
        var ddProvsEl = document.getElementById('dd-provincias');
        if (ddProvsEl) {
            ddProvsEl.addEventListener('shown.bs.dropdown', function () {
                refreshProvinciasOptions();
            });
        }
        var ddLocEl = document.getElementById('dd-localidades');
        if (ddLocEl) {
            ddLocEl.addEventListener('shown.bs.dropdown', function () {
                refreshLocalidadesOptions();
            });
        }

        // Recalcular labels al tildar/destildar; si cambia contexto y había números/IMEI, limpiarlos
        var sujetosEl = document.getElementById('filtro-sujetos');
        if (sujetosEl) sujetosEl.addEventListener('change', function () {
            updateDdCount('dd-sujetos', 'filtro-sujetos', 'Seleccionar…');
            maybeClearNumerosImeisIfContextChanged();
        });
        var cargasEl = document.getElementById('filtro-cargas');
        if (cargasEl) cargasEl.addEventListener('change', function () {
            updateDdCount('dd-cargas', 'filtro-cargas', 'Seleccionar…');
            try { reloadMapaTiposOpciones(); } catch (eT) {}
            maybeClearNumerosImeisIfContextChanged();
        });
        var tiposEl = document.getElementById('filtro-tipos');
        if (tiposEl) tiposEl.addEventListener('change', function () {
            updateDdTipos();
            maybeClearNumerosImeisIfContextChanged();
        });
        var provEl = document.getElementById('filtro-provincias');
        if (provEl) provEl.addEventListener('change', function () {
            updateDdCount('dd-provincias', 'filtro-provincias', 'Seleccionar…');
            // si cambian provincias, refrescar localidades (dependiente)
            var sujetoIds = getSelectedIds('filtro-sujetos');
            var cargaIds = getSelectedIds('filtro-cargas');
            var tipos = getSelectedTipos();
            var provincias = getSelectedStrings('filtro-provincias');
            fetchLocalidades('', Object.assign({}, getFilterParamsSnapshot(), { sujeto_ids: sujetoIds, carga_ids: cargaIds, tipos: tipos, provincias: provincias })).then(function (items) {
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
                    fetchNumeros(qTxt, Object.assign({}, getFilterParamsSnapshot(), {
                        sujeto_ids: sujetoIds,
                        carga_ids: cargaIds,
                        tipos: tipos,
                        provincias: provincias,
                        localidades: localidades,
                        fecha_desde: getValue('filtro-fecha-desde') || null,
                        fecha_hasta: getValue('filtro-fecha-hasta') || null,
                        hora_desde: getValue('filtro-hora-desde') || null,
                        hora_hasta: getValue('filtro-hora-hasta') || null
                    })).then(function (items) {
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
                fetchNumeros(qTxt, Object.assign({}, getFilterParamsSnapshot(), {
                    sujeto_ids: sujetoIds,
                    carga_ids: cargaIds,
                    tipos: tipos,
                    provincias: provincias,
                    localidades: localidades,
                    fecha_desde: getValue('filtro-fecha-desde') || null,
                    fecha_hasta: getValue('filtro-fecha-hasta') || null,
                    hora_desde: getValue('filtro-hora-desde') || null,
                    hora_hasta: getValue('filtro-hora-hasta') || null
                })).then(function (items) {
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
                    fetchImeis(qTxt, Object.assign({}, getFilterParamsSnapshot(), {
                        sujeto_ids: sujetoIds,
                        carga_ids: cargaIds,
                        tipos: tipos,
                        provincias: provincias,
                        localidades: localidades,
                        fecha_desde: getValue('filtro-fecha-desde') || null,
                        fecha_hasta: getValue('filtro-fecha-hasta') || null,
                        hora_desde: getValue('filtro-hora-desde') || null,
                        hora_hasta: getValue('filtro-hora-hasta') || null
                    })).then(function (items) {
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
                fetchImeis(qTxt, Object.assign({}, getFilterParamsSnapshot(), {
                    sujeto_ids: sujetoIds,
                    carga_ids: cargaIds,
                    tipos: tipos,
                    provincias: provincias,
                    localidades: localidades,
                    fecha_desde: getValue('filtro-fecha-desde') || null,
                    fecha_hasta: getValue('filtro-fecha-hasta') || null,
                    hora_desde: getValue('filtro-hora-desde') || null,
                    hora_hasta: getValue('filtro-hora-hasta') || null
                })).then(function (items) {
                    if (tok !== imeisQueryToken) return;
                    renderImeisResultados(Array.isArray(items) ? items : []);
                }).catch(function () {});
            });
        }

        var btnLimpiar = document.getElementById('btn-limpiar-filtros');
        if (btnLimpiar) {
            btnLimpiar.addEventListener('click', function () {
                ['filtro-fecha-desde', 'filtro-fecha-hasta', 'filtro-hora-desde', 'filtro-hora-hasta', 'numeros-search', 'imeis-search', 'goto-orden-search'].forEach(function (id) {
                    var el = document.getElementById(id);
                    if (el) el.value = '';
                });
                try { clearGotoOrdenSelection(); } catch (eGoc) {}
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

                var modoEl = document.getElementById('mapa-datos-modo');
                if (modoEl) modoEl.value = 'sabana';
                var pcaso = document.getElementById('mapa-caso-principal');
                if (pcaso) pcaso.value = '';
                var rr = document.getElementById('mapa-record-radio-m');
                if (rr) rr.value = '';
                var rrp = document.getElementById('filtro-record-ref-puntos');
                if (rrp) rrp.querySelectorAll('input[type="checkbox"]').forEach(function (cb) { cb.checked = false; });
                updateDdCount('dd-record-ref-punto', 'filtro-record-ref-puntos', 'Sin punto seleccionado');
                var rpm = document.getElementById('mapa-record-perimetro-m');
                if (rpm) rpm.value = '';
                try { setCasoRefPickMode(false); } catch (eCR0) {}
                try { clearCasoRefLayer(); } catch (eCR1) {}
                clearRecordTargetOverlay();
                try { syncMapaCasoDropdownButton(); } catch (eSyncC) {}
                try { syncMapaModoDropdownButton(); } catch (eSyncM) {}
                try { updateMapaModoUI(); } catch (eM) {}
                try { reloadMapaTiposOpciones(); } catch (eRt) {}

                resetFiltroContextSnapshot();
                aplicarFiltros();
                refreshMapSize(50);
            });
        }

        // Botón explícito: validar → cascada → aplicar mapa (con feedback y resumen)
        var btnAplicar = document.getElementById('btn-aplicar-filtros');
        if (btnAplicar) {
            var btnAplicarHtmlOriginal = btnAplicar.innerHTML;
            btnAplicar.addEventListener('click', function () {
                if (btnAplicar.disabled) return;
                var snap = getFilterParamsSnapshot();
                if (isMapaRecordModo()) {
                    if (!getRecordCasoId()) {
                        showFiltrosAlerta('Seleccione un caso de análisis (record) y pulse Aplicar filtros.');
                        return;
                    }
                } else if (isMapaAmbosModo()) {
                    if (!getMapaCasoPrincipalId()) {
                        showFiltrosAlerta('Seleccione un caso y pulse Aplicar filtros.');
                        return;
                    }
                    if (!hasFiltroBasicoParams(snap)) {
                        showFiltrosAlerta('Seleccione filtros válidos (caso del expediente y/o sujeto, carga, número o IMEI) y pulse Aplicar.');
                        return;
                    }
                } else if (!hasFiltroBasicoParams(snap)) {
                    showFiltrosAlerta('Seleccione un caso para acotar la sábana o al menos un sujeto, una carga, un número o un IMEI y pulse Aplicar filtros.');
                    return;
                }
                showFiltrosAlerta('');
                btnAplicar.disabled = true;
                btnAplicar.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Aplicando…';
                var cascadeP;
                if (isMapaRecordModo() || isMapaAmbosModo()) {
                    cascadeP = loadUnifiedCargasOptions(getRecordFuenteIds());
                } else {
                    cascadeP = refreshDropdownOptionsCascade();
                }
                cascadeP.then(function () {
                    aplicarFiltros({
                        onComplete: function () {
                            refreshMapSize(50);
                            btnAplicar.disabled = false;
                            btnAplicar.innerHTML = btnAplicarHtmlOriginal;
                        }
                    });
                }).catch(function () {
                    aplicarFiltros({
                        onComplete: function () {
                            refreshMapSize(50);
                            btnAplicar.disabled = false;
                            btnAplicar.innerHTML = btnAplicarHtmlOriginal;
                        }
                    });
                });
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

        // Controles de Play/Pausa también en el panel de detalle (para el trazado global)
        var panelPlay = document.getElementById('sabana-panel-play');
        var panelPause = document.getElementById('sabana-panel-pause');
        if (panelPlay) panelPlay.addEventListener('click', playTrazadoAnimacion);
        if (panelPause) panelPause.addEventListener('click', pauseTrazadoAnimacion);
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
            // En este modo, el mapa se aplica SOLO con el botón “Aplicar filtros”.
            // Los endpoints para números/IMEIs ya leen fecha/hora cuando se abre el dropdown.
            el.addEventListener('change', function () {});
        });

        // Nota: no aplicamos al cambiar checkboxes del dropdown.
        // El apply ocurre al cerrar el dropdown (hidden.bs.dropdown), que evita ráfagas de requests.

        // Auto-aplicar al cerrar dropdowns (multi-selección)
        ['dd-provincias', 'dd-localidades', 'dd-sujetos', 'dd-cargas', 'dd-tipos', 'dd-numeros', 'dd-imeis'].forEach(function (bid) {
            var b = document.getElementById(bid);
            if (!b) return;
            b.addEventListener('hidden.bs.dropdown', function () {});
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

        var btnCaptura = document.getElementById('btn-captura-informe');
        if (btnCaptura && window.html2canvas) {
            btnCaptura.addEventListener('click', function () {
                btnCaptura.disabled = true;
                captureMapForInforme(true);
                setTimeout(function () { btnCaptura.disabled = false; }, 1500);
            });
        }
        var btnKmz = document.getElementById('btn-exportar-kmz');
        if (btnKmz && !btnKmz.disabled) {
            btnKmz.addEventListener('click', function () {
                btnKmz.disabled = true;
                try { downloadMapaKmz(); } finally {
                    setTimeout(function () { btnKmz.disabled = false; }, 800);
                }
            });
        }

        // Al redimensionar ventana, evitar mapa “cortado”
        window.addEventListener('resize', function () {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () { refreshMapSize(0); }, 120);
        });

        var modoSelect = document.getElementById('mapa-datos-modo');
        if (modoSelect) {
            modoSelect.addEventListener('change', function () {
                try { syncMapaModoDropdownButton(); } catch (eSm) {}
                try { updateMapaModoUI(); } catch (eM) {}
                try { setCasoRefPickMode(false); } catch (eCRm) {}
                if (isMapaRecordModo() || isMapaAmbosModo()) {
                    loadUnifiedCargasOptions(getRecordFuenteIds()).then(function () {
                        return reloadMapaTiposOpciones();
                    }).finally(function () { scheduleAutoApply(0); });
                } else {
                    loadUnifiedCargasOptions(getSelectedIds('filtro-cargas')).then(function () {
                        return reloadMapaTiposOpciones();
                    }).finally(function () { scheduleAutoApply(0); }).catch(function () {});
                }
                if (!isMapaRecordModo() && !isMapaAmbosModo()) {
                    clearRecordTargetOverlay();
                }
            });
        }
        var casoPrincipalSel = document.getElementById('mapa-caso-principal');
        var recRadioIn = document.getElementById('mapa-record-radio-m');
        var recRefWrap = document.getElementById('filtro-record-ref-puntos');
        var recPerimetroIn = document.getElementById('mapa-record-perimetro-m');

        function onCasoPrincipalChange() {
            fetchFiltros().then(function (data) {
                renderCheckboxes('filtro-sujetos', data.sujetos || [], 'nombre', 'id');
                updateDdCount('dd-sujetos', 'filtro-sujetos', 'Seleccionar…');
            }).catch(function () {});
            loadUnifiedCargasOptions([]).then(function () {
                return reloadMapaTiposOpciones();
            }).finally(function () { scheduleAutoApply(0); });
            try { reloadCasoRefMarkers(); } catch (eCRM) {}
        }
        if (casoPrincipalSel) {
            casoPrincipalSel.addEventListener('change', function () {
                try { syncMapaCasoDropdownButton(); } catch (eSc) {}
                onCasoPrincipalChange();
            });
        }
        if (recRadioIn) {
            recRadioIn.addEventListener('change', function () { scheduleAutoApply(0); });
        }
        if (recRefWrap) recRefWrap.addEventListener('change', function () {
            updateDdCount('dd-record-ref-punto', 'filtro-record-ref-puntos', 'Sin punto seleccionado');
            drawRecordRefTargetsOverlay(getRecordPerimetroM());
            scheduleAutoApply(0);
        });
        if (recPerimetroIn) recPerimetroIn.addEventListener('change', function () {
            drawRecordRefTargetsOverlay(getRecordPerimetroM());
            scheduleAutoApply(0);
        });

        var modalIconGrp = document.getElementById('modal-caso-ref-icono-group');
        if (modalIconGrp) {
            modalIconGrp.addEventListener('click', function (e) {
                var btn = e.target && e.target.closest ? e.target.closest('[data-caso-ref-icon]') : null;
                if (!btn || !btn.hasAttribute('data-caso-ref-icon')) return;
                e.preventDefault();
                var v = btn.getAttribute('data-caso-ref-icon');
                setCasoRefModalIcon(v);
            });
        }
        var modalTipoRef = document.getElementById('modal-caso-ref-tipo');
        if (modalTipoRef) {
            modalTipoRef.addEventListener('change', function () {
                var idIn = document.getElementById('modal-caso-ref-id');
                if (idIn && idIn.value) return;
                setCasoRefModalIcon(casoRefDefaultIconForTipo(this.value));
            });
        }

        var btnCasoRefPick = document.getElementById('btn-caso-ref-pick');
        if (btnCasoRefPick) {
            btnCasoRefPick.addEventListener('click', function () {
                if (!getCasoIdParaReferencias()) {
                    showFiltrosAlerta('Seleccione un caso de análisis (selector de caso en Sábana o en Record, según el modo).', 'warning');
                    return;
                }
                setCasoRefPickMode(!casoRefPickMode);
                if (casoRefPickMode) showFiltrosAlerta('Haga clic en el mapa para ubicar el punto de referencia.', 'info');
                else showFiltrosAlerta('');
            });
        }
        var btnModalCasoRefGuardar = document.getElementById('modal-caso-ref-guardar');
        if (btnModalCasoRefGuardar) {
            btnModalCasoRefGuardar.addEventListener('click', function () {
                var cid = getCasoIdParaReferencias();
                var idIn = document.getElementById('modal-caso-ref-id');
                var latIn = document.getElementById('modal-caso-ref-lat');
                var lngIn = document.getElementById('modal-caso-ref-lng');
                var tipoEl = document.getElementById('modal-caso-ref-tipo');
                var etqEl = document.getElementById('modal-caso-ref-etiqueta');
                var notaEl = document.getElementById('modal-caso-ref-nota');
                var iconoEl = document.getElementById('modal-caso-ref-icono');
                if (!cid || !latIn || !lngIn) return;
                var la = parseFloat(latIn.value);
                var lo = parseFloat(lngIn.value);
                if (isNaN(la) || isNaN(lo)) return;
                var editId = null;
                try {
                    editId = idIn && idIn.value ? parseInt(String(idIn.value), 10) : null;
                    if (editId != null && isNaN(editId)) editId = null;
                } catch (eId) { editId = null; }
                btnModalCasoRefGuardar.disabled = true;
                var url = editId != null
                    ? (baseUrl + '/sabana-llamadas/api/mapa/caso-puntos/' + encodeURIComponent(String(editId)))
                    : (baseUrl + '/sabana-llamadas/api/mapa/caso-puntos');
                var method = editId != null ? 'PUT' : 'POST';
                var token = getCsrfToken();
                var headers = {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                };
                if (token) {
                    headers['X-CSRFToken'] = token;
                    headers['X-CSRF-Token'] = token;
                }
                fetch(url, {
                    method: method,
                    headers: headers,
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        caso_id: cid,
                        lat: la,
                        lng: lo,
                        tipo: tipoEl ? tipoEl.value : 'otro',
                        etiqueta: etqEl ? etqEl.value : '',
                        nota: notaEl ? notaEl.value : '',
                        icono: normalizeCasoRefIconKey(iconoEl ? iconoEl.value : 'pin'),
                        origen_contexto: (isMapaRecordModo() || isMapaAmbosModo()) ? 'record' : 'sabana'
                    })
                }).then(function (r) {
                    return r.text().then(function (txt) {
                        var j = {};
                        try { j = txt ? JSON.parse(txt) : {}; } catch (eJson) { j = {}; }
                        btnModalCasoRefGuardar.disabled = false;
                        if (!r.ok) {
                            alert((j && j.error) ? String(j.error) : 'No se pudo guardar el punto.');
                            return;
                        }
                        try {
                            var mel = document.getElementById('modalCasoMapaPunto');
                            if (mel && window.bootstrap && window.bootstrap.Modal) {
                                var inst = window.bootstrap.Modal.getInstance(mel);
                                if (inst) inst.hide();
                            }
                        } catch (eH) {}
                        try { reloadCasoRefMarkers(); } catch (eRel) {}
                    });
                }).catch(function () {
                    btnModalCasoRefGuardar.disabled = false;
                    alert('Error de red al guardar.');
                });
            });
        }
        document.addEventListener('click', function (e) {
            var te = e.target && e.target.closest ? e.target.closest('.caso-ref-edit') : null;
            if (te) {
                e.preventDefault();
                var peid = te.getAttribute('data-id');
                if (!peid) return;
                var item = casoRefItemsById[String(peid)];
                if (!item) return;
                openCasoRefModal(item.lat, item.lng, item);
                return;
            }
            var t = e.target && e.target.closest ? e.target.closest('.caso-ref-del') : null;
            if (!t) return;
            e.preventDefault();
            var pid = t.getAttribute('data-id');
            if (!pid) return;
            if (!window.confirm('¿Eliminar este punto de referencia del caso?')) return;
            var tokenDel = getCsrfToken();
            var headersDel = { 'Accept': 'application/json' };
            if (tokenDel) {
                headersDel['X-CSRFToken'] = tokenDel;
                headersDel['X-CSRF-Token'] = tokenDel;
            }
            fetch(baseUrl + '/sabana-llamadas/api/mapa/caso-puntos/' + encodeURIComponent(pid), {
                method: 'DELETE',
                headers: headersDel,
                credentials: 'same-origin'
            }).then(function (r) {
                if (!r.ok) {
                    alert('No se pudo eliminar.');
                    return;
                }
                try { reloadCasoRefMarkers(); } catch (eDel) {}
            }).catch(function () { alert('Error de red.'); });
        });

        syncFiltroContextSnapshot();
        aplicarFiltros();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

(function () {
    'use strict';

    var baseUrl = document.body.getAttribute('data-sabana-base') || '';
    var numerosTok = 0;
    var imeisTok = 0;
    var numerosTimer = null;
    var imeisTimer = null;

    var selectedNumeros = new Set();
    var selectedImeis = new Set();
    var prefillProvincias = new Set();
    var prefillLocalidades = new Set();

    function getVal(id) {
        var el = document.getElementById(id);
        return el ? String(el.value || '').trim() : '';
    }

    function escapeHtml(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function escapeHtmlAttr(s) {
        return escapeHtml(s).replace(/"/g, '&quot;');
    }

    function filterCheckboxList(containerId, query) {
        var container = document.getElementById(containerId);
        if (!container) return;
        var q = (query || '').toLowerCase().trim();
        var visible = 0;
        container.querySelectorAll('.form-check').forEach(function (row) {
            var txt = (row.textContent || '').toLowerCase();
            var show = (!q || txt.indexOf(q) !== -1);
            row.style.display = show ? '' : 'none';
            if (show) visible += 1;
        });
        setListEmptyState(container, visible === 0, q ? 'Sin coincidencias para la búsqueda.' : 'Sin opciones disponibles.');
    }

    function initDropdownSearch() {
        document.querySelectorAll('.sabana-dd-search').forEach(function (inp) {
            inp.addEventListener('input', function () {
                var target = this.getAttribute('data-target');
                if (target) filterCheckboxList(target, this.value);
            });
        });
    }

    function updateDdButtonText(btnId, text) {
        var btn = document.getElementById(btnId);
        if (btn) btn.textContent = text;
    }

    function updateDdCount(btnId, containerId, emptyLabel) {
        var container = document.getElementById(containerId);
        if (!container) return;
        var n = container.querySelectorAll('input[type="checkbox"]:checked').length;
        updateDdButtonText(btnId, n > 0 ? (n + ' seleccionado(s)') : (emptyLabel || 'Seleccionar…'));
    }

    function getSelectedIds(containerId) {
        var c = document.getElementById(containerId);
        if (!c) return [];
        var out = [];
        c.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
            var v = parseInt(cb.value, 10);
            if (!isNaN(v)) out.push(v);
        });
        return out;
    }

    function getSelectedStrings(containerId) {
        var c = document.getElementById(containerId);
        if (!c) return [];
        var out = [];
        c.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
            var v = String(cb.value || '').trim();
            if (v) out.push(v);
        });
        return out;
    }

    function setListEmptyState(container, show, text) {
        if (!container) return;
        var node = container.querySelector('.rel-empty-msg');
        if (!show) {
            if (node) node.remove();
            return;
        }
        if (!node) {
            node = document.createElement('div');
            node.className = 'rel-empty-msg text-muted small fst-italic py-1';
            container.appendChild(node);
        }
        node.textContent = text || 'Sin opciones disponibles.';
    }

    function appendRelacionesApiContext(q) {
        var origen = (getVal('filtro-origen') || 'sabana').toLowerCase();
        q.append('mapa_datos_modo', origen === 'record' ? 'record' : 'sabana');
        var caso = getVal('caso_id');
        if (caso) q.append('caso_id', caso);
        if (origen === 'record') {
            document.querySelectorAll('input[name="fuente_ids[]"]:checked').forEach(function (cb) {
                q.append('fuente_ids[]', cb.value);
            });
        }
    }

    function relacionesFiltrosSnapshot() {
        var origen = (getVal('filtro-origen') || 'sabana').toLowerCase();
        var tipo = (getVal('filtro-tipo-trafico') || 'voz').toLowerCase();
        return {
            origen: origen,
            caso_id: getVal('caso_id') || null,
            tipo_trafico: tipo,
            sujeto_ids: getSelectedIds('rel-filtro-sujetos'),
            carga_ids: getSelectedIds('rel-filtro-cargas'),
            tipos: (tipo === 'gprs' || tipo === 'voz') ? [tipo] : [],
            provincias: getSelectedStrings('rel-filtro-provincias'),
            localidades: getSelectedStrings('rel-filtro-localidades'),
            fecha_desde: getVal('fecha_desde') || null,
            fecha_hasta: getVal('fecha_hasta') || null,
            hora_desde: getVal('hora_desde') || null,
            hora_hasta: getVal('hora_hasta') || null,
        };
    }

    function fetchProvincias(qTxt, snap) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (snap.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (snap.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (snap.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        q.append('limit', '120');
        appendRelacionesApiContext(q);
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/provincias?' + q.toString(), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        }).then(function (r) { return r.json(); });
    }

    function fetchLocalidades(qTxt, snap) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (snap.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (snap.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (snap.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (snap.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        q.append('limit', '160');
        appendRelacionesApiContext(q);
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/localidades?' + q.toString(), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        }).then(function (r) { return r.json(); });
    }

    function fetchNumeros(qTxt, snap) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (snap.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (snap.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (snap.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (snap.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (snap.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (snap.fecha_desde) q.append('fecha_desde', snap.fecha_desde);
        if (snap.fecha_hasta) q.append('fecha_hasta', snap.fecha_hasta);
        if (snap.hora_desde) q.append('hora_desde', snap.hora_desde);
        if (snap.hora_hasta) q.append('hora_hasta', snap.hora_hasta);
        q.append('limit', '50');
        appendRelacionesApiContext(q);
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/numeros?' + q.toString(), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        }).then(function (r) { return r.json(); });
    }

    function fetchImeis(qTxt, snap) {
        var q = new URLSearchParams();
        if (qTxt) q.append('q', qTxt);
        (snap.sujeto_ids || []).forEach(function (id) { q.append('sujeto_ids[]', id); });
        (snap.carga_ids || []).forEach(function (id) { q.append('carga_ids[]', id); });
        (snap.tipos || []).forEach(function (t) { q.append('tipos[]', t); });
        (snap.provincias || []).forEach(function (p) { q.append('provincias[]', p); });
        (snap.localidades || []).forEach(function (l) { q.append('localidades[]', l); });
        if (snap.fecha_desde) q.append('fecha_desde', snap.fecha_desde);
        if (snap.fecha_hasta) q.append('fecha_hasta', snap.fecha_hasta);
        if (snap.hora_desde) q.append('hora_desde', snap.hora_desde);
        if (snap.hora_hasta) q.append('hora_hasta', snap.hora_hasta);
        q.append('limit', '80');
        appendRelacionesApiContext(q);
        return fetch(baseUrl + '/sabana-llamadas/api/filtros/imeis?' + q.toString(), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        }).then(function (r) { return r.json(); });
    }

    function renderNamedCheckboxList(containerId, values, nameAttr, idPrefix, selectedSet) {
        var container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';
        var count = 0;
        (values || []).forEach(function (raw, idx) {
            var val = String(raw || '').trim();
            if (!val) return;
            var id = (idPrefix || 'cb') + '-' + containerId + '-' + idx;
            var div = document.createElement('div');
            div.className = 'form-check';
            var checked = selectedSet && selectedSet.has(val) ? ' checked' : '';
            div.innerHTML = '<input class="form-check-input" type="checkbox" name="' + escapeHtmlAttr(nameAttr) + '" id="' + id + '" value="' + escapeHtmlAttr(val) + '"' + checked + '>' +
                '<label class="form-check-label" for="' + id + '">' + escapeHtml(val) + '</label>';
            container.appendChild(div);
            count += 1;
        });
        setListEmptyState(container, count === 0, 'Sin resultados para filtros actuales.');
    }

    function setCheckedByValue(containerId, valueSet) {
        if (!valueSet) return;
        var container = document.getElementById(containerId);
        if (!container) return;
        container.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
            var v = String(cb.value || '').trim();
            cb.checked = valueSet.has(v);
        });
    }

    function refreshProvincias() {
        var snap = relacionesFiltrosSnapshot();
        var prev = new Set(getSelectedStrings('rel-filtro-provincias').map(function (x) { return String(x); }));
        prefillProvincias.forEach(function (x) { prev.add(x); });
        fetchProvincias('', snap).then(function (items) {
            var arr = Array.isArray(items) ? items.slice() : [];
            prev.forEach(function (p) {
                if (arr.indexOf(p) === -1) arr.push(p);
            });
            renderNamedCheckboxList('rel-filtro-provincias', arr, 'provincias[]', 'rel-pr', prev);
            setCheckedByValue('rel-filtro-provincias', prev);
            prefillProvincias.clear();
            updateDdCount('dd-rel-provincias', 'rel-filtro-provincias', 'Provincias…');
        }).catch(function () {});
    }

    function refreshLocalidades() {
        var snap = relacionesFiltrosSnapshot();
        var prev = new Set(getSelectedStrings('rel-filtro-localidades').map(function (x) { return String(x); }));
        prefillLocalidades.forEach(function (x) { prev.add(x); });
        fetchLocalidades('', snap).then(function (items) {
            var arr = Array.isArray(items) ? items.slice() : [];
            prev.forEach(function (p) {
                if (arr.indexOf(p) === -1) arr.push(p);
            });
            renderNamedCheckboxList('rel-filtro-localidades', arr, 'localidades[]', 'rel-loc', prev);
            setCheckedByValue('rel-filtro-localidades', prev);
            prefillLocalidades.clear();
            updateDdCount('dd-rel-localidades', 'rel-filtro-localidades', 'Localidades…');
        }).catch(function () {});
    }

    function renderNumerosResultados(items) {
        var container = document.getElementById('rel-filtro-numeros');
        if (!container) return;
        container.innerHTML = '';
        var arr = Array.isArray(items) ? items.slice() : [];
        selectedNumeros.forEach(function (n) {
            if (arr.indexOf(n) === -1) arr.push(n);
        });
        var count = 0;
        arr.forEach(function (num, idx) {
            var v = String(num || '').trim();
            if (!v) return;
            var id = 'rel-cb-num-' + idx;
            var div = document.createElement('div');
            div.className = 'form-check';
            var checked = selectedNumeros.has(v) ? ' checked' : '';
            div.innerHTML = '<input class="form-check-input" type="checkbox" id="' + id + '" value="' + escapeHtmlAttr(v) + '"' + checked + '>' +
                '<label class="form-check-label" for="' + id + '">' + escapeHtml(v) + '</label>';
            var cb = div.querySelector('input');
            cb.addEventListener('change', function () {
                if (this.checked) selectedNumeros.add(v); else selectedNumeros.delete(v);
                updateDdButtonText('dd-rel-numeros', selectedNumeros.size ? ('Números: ' + selectedNumeros.size + ' seleccionado(s)') : 'Números…');
                renderFiltrosResumen();
            });
            container.appendChild(div);
            count += 1;
        });
        setListEmptyState(container, count === 0, 'Sin resultados para filtros actuales.');
    }

    function renderImeisResultados(items) {
        var container = document.getElementById('rel-filtro-imeis');
        if (!container) return;
        container.innerHTML = '';
        var arr = Array.isArray(items) ? items.slice() : [];
        selectedImeis.forEach(function (n) {
            if (arr.indexOf(n) === -1) arr.push(n);
        });
        var count = 0;
        arr.forEach(function (num, idx) {
            var v = String(num || '').trim();
            if (!v) return;
            var id = 'rel-cb-imei-' + idx;
            var div = document.createElement('div');
            div.className = 'form-check';
            var checked = selectedImeis.has(v) ? ' checked' : '';
            div.innerHTML = '<input class="form-check-input" type="checkbox" id="' + id + '" value="' + escapeHtmlAttr(v) + '"' + checked + '>' +
                '<label class="form-check-label" for="' + id + '">' + escapeHtml(v) + '</label>';
            var cb = div.querySelector('input');
            cb.addEventListener('change', function () {
                if (this.checked) selectedImeis.add(v); else selectedImeis.delete(v);
                updateDdButtonText('dd-rel-imeis', selectedImeis.size ? ('IMEIs: ' + selectedImeis.size + ' seleccionado(s)') : 'IMEIs…');
                renderFiltrosResumen();
            });
            container.appendChild(div);
            count += 1;
        });
        setListEmptyState(container, count === 0, 'Sin resultados para filtros actuales.');
    }

    function loadPrefillSets() {
        var el = document.getElementById('rel-mf-prefill');
        if (!el) return;
        try {
            var raw = el.textContent || el.innerText || '{}';
            var o = JSON.parse(raw);
            (o.numeros || []).forEach(function (n) {
                var v = String(n || '').trim();
                if (v) selectedNumeros.add(v);
            });
            (o.imeis || []).forEach(function (n) {
                var v = String(n || '').trim();
                if (v) selectedImeis.add(v);
            });
            (o.provincias || []).forEach(function (n) {
                var v = String(n || '').trim();
                if (v) prefillProvincias.add(v);
            });
            (o.localidades || []).forEach(function (n) {
                var v = String(n || '').trim();
                if (v) prefillLocalidades.add(v);
            });
        } catch (e) {}
    }

    function renderFiltrosResumen() {
        var box = document.getElementById('rel-filtros-resumen');
        if (!box) return;
        var partes = [];
        var origen = (getVal('filtro-origen') || 'sabana').toUpperCase();
        var tipo = (getVal('filtro-tipo-trafico') || '').toUpperCase();
        if (origen) partes.push('Origen: ' + origen);
        if (tipo) partes.push('Tráfico: ' + tipo);
        var s = getSelectedIds('rel-filtro-sujetos').length;
        var c = getSelectedIds('rel-filtro-cargas').length;
        var f = getSelectedIds('rel-filtro-fuentes-record').length;
        var p = getSelectedStrings('rel-filtro-provincias').length;
        var l = getSelectedStrings('rel-filtro-localidades').length;
        if (s) partes.push('Sujetos: ' + s);
        if (c) partes.push('Cargas: ' + c);
        if (f) partes.push('Archivos Record: ' + f);
        if (p) partes.push('Provincias: ' + p);
        if (l) partes.push('Localidades: ' + l);
        if (selectedNumeros.size) partes.push('Números: ' + selectedNumeros.size);
        if (selectedImeis.size) partes.push('IMEIs: ' + selectedImeis.size);
        var fd = getVal('fecha_desde');
        var fh = getVal('fecha_hasta');
        if (fd || fh) partes.push('Fechas: ' + (fd || '-') + ' a ' + (fh || '-'));
        if (!partes.length) {
            box.classList.add('d-none');
            box.textContent = '';
            return;
        }
        box.classList.remove('d-none');
        box.textContent = partes.join(' | ');
    }

    function refreshNumerosFromContext() {
        var qTxt = (getVal('rel-numeros-search') || '').trim();
        var snap = relacionesFiltrosSnapshot();
        var tok = ++numerosTok;
        return fetchNumeros(qTxt, snap).then(function (items) {
            if (tok !== numerosTok) return;
            renderNumerosResultados(Array.isArray(items) ? items : []);
        }).catch(function () {
            if (tok !== numerosTok) return;
            renderNumerosResultados([]);
        });
    }

    function refreshImeisFromContext() {
        var qTxt = (getVal('rel-imeis-search') || '').trim();
        var snap = relacionesFiltrosSnapshot();
        var tok = ++imeisTok;
        return fetchImeis(qTxt, snap).then(function (items) {
            if (tok !== imeisTok) return;
            renderImeisResultados(Array.isArray(items) ? items : []);
        }).catch(function () {
            if (tok !== imeisTok) return;
            renderImeisResultados([]);
        });
    }

    function isDropdownOpen(btnId) {
        var btn = document.getElementById(btnId);
        return !!(btn && btn.classList.contains('show'));
    }

    var cascadeRefreshTimer = null;
    function scheduleCascadeRefresh() {
        if (cascadeRefreshTimer) clearTimeout(cascadeRefreshTimer);
        cascadeRefreshTimer = setTimeout(function () {
            refreshProvincias();
            refreshLocalidades();
            // Para aliviar carga: refrescar números/IMEIs solo si hay contexto activo o dropdown abierto.
            if (selectedNumeros.size || isDropdownOpen('dd-rel-numeros') || !!getVal('rel-numeros-search')) {
                refreshNumerosFromContext();
            }
            if (selectedImeis.size || isDropdownOpen('dd-rel-imeis') || !!getVal('rel-imeis-search')) {
                refreshImeisFromContext();
            }
            renderFiltrosResumen();
        }, 180);
    }

    function wireMultiselect() {
        var form = document.getElementById('form-relaciones');
        if (!form) return;

        ['rel-filtro-sujetos', 'rel-filtro-cargas', 'rel-filtro-fuentes-record'].forEach(function (cid) {
            var c = document.getElementById(cid);
            if (!c) return;
            c.addEventListener('change', function () {
                if (cid === 'rel-filtro-sujetos') updateDdCount('dd-rel-sujetos', 'rel-filtro-sujetos', 'Sujetos…');
                if (cid === 'rel-filtro-cargas') updateDdCount('dd-rel-cargas', 'rel-filtro-cargas', 'Cargas…');
                if (cid === 'rel-filtro-fuentes-record') updateDdCount('dd-rel-fuentes', 'rel-filtro-fuentes-record', 'Archivos Record…');
                renderFiltrosResumen();
                scheduleCascadeRefresh();
            });
        });

        updateDdCount('dd-rel-sujetos', 'rel-filtro-sujetos', 'Sujetos…');
        updateDdCount('dd-rel-cargas', 'rel-filtro-cargas', 'Cargas…');
        var ff = document.getElementById('rel-filtro-fuentes-record');
        if (ff) updateDdCount('dd-rel-fuentes', 'rel-filtro-fuentes-record', 'Archivos Record…');
        updateDdCount('dd-rel-provincias', 'rel-filtro-provincias', 'Provincias…');
        updateDdCount('dd-rel-localidades', 'rel-filtro-localidades', 'Localidades…');
        setListEmptyState(document.getElementById('rel-filtro-sujetos'), !document.querySelector('#rel-filtro-sujetos .form-check'), 'Sin sujetos disponibles.');
        setListEmptyState(document.getElementById('rel-filtro-cargas'), !document.querySelector('#rel-filtro-cargas .form-check'), 'Sin cargas disponibles.');
        setListEmptyState(document.getElementById('rel-filtro-fuentes-record'), !document.querySelector('#rel-filtro-fuentes-record .form-check'), 'Sin archivos para este caso/tipo.');

        var ddProv = document.getElementById('dd-rel-provincias');
        if (ddProv) {
            ddProv.addEventListener('shown.bs.dropdown', function () {
                refreshProvincias();
            });
        }
        var searchProv = document.getElementById('rel-provincias-search');
        if (searchProv) {
            searchProv.addEventListener('input', function () {
                var qTxt = (this.value || '').trim();
                var snap = relacionesFiltrosSnapshot();
                fetchProvincias(qTxt, snap).then(function (items) {
                    var prev = new Set(getSelectedStrings('rel-filtro-provincias').map(function (x) { return String(x); }));
                    var arr = Array.isArray(items) ? items.slice() : [];
                    prev.forEach(function (p) {
                        if (arr.indexOf(p) === -1) arr.push(p);
                    });
                    renderNamedCheckboxList('rel-filtro-provincias', arr, 'provincias[]', 'rel-pr', prev);
                    setCheckedByValue('rel-filtro-provincias', prev);
                    updateDdCount('dd-rel-provincias', 'rel-filtro-provincias', 'Provincias…');
                }).catch(function () {});
            });
        }
        var provList = document.getElementById('rel-filtro-provincias');
        if (provList) {
            provList.addEventListener('change', function () {
                updateDdCount('dd-rel-provincias', 'rel-filtro-provincias', 'Provincias…');
                renderFiltrosResumen();
                scheduleCascadeRefresh();
            });
        }

        var ddLoc = document.getElementById('dd-rel-localidades');
        if (ddLoc) {
            ddLoc.addEventListener('shown.bs.dropdown', function () {
                refreshLocalidades();
            });
        }
        var searchLoc = document.getElementById('rel-localidades-search');
        if (searchLoc) {
            searchLoc.addEventListener('input', function () {
                var qTxt = (this.value || '').trim();
                var snap = relacionesFiltrosSnapshot();
                fetchLocalidades(qTxt, snap).then(function (items) {
                    var prev = new Set(getSelectedStrings('rel-filtro-localidades').map(function (x) { return String(x); }));
                    var arr = Array.isArray(items) ? items.slice() : [];
                    prev.forEach(function (p) {
                        if (arr.indexOf(p) === -1) arr.push(p);
                    });
                    renderNamedCheckboxList('rel-filtro-localidades', arr, 'localidades[]', 'rel-loc', prev);
                    setCheckedByValue('rel-filtro-localidades', prev);
                    updateDdCount('dd-rel-localidades', 'rel-filtro-localidades', 'Localidades…');
                }).catch(function () {});
            });
        }
        var locList = document.getElementById('rel-filtro-localidades');
        if (locList) {
            locList.addEventListener('change', function () {
                updateDdCount('dd-rel-localidades', 'rel-filtro-localidades', 'Localidades…');
                renderFiltrosResumen();
                scheduleCascadeRefresh();
            });
        }

        var searchNum = document.getElementById('rel-numeros-search');
        if (searchNum) {
            searchNum.addEventListener('input', function () {
                var qTxt = (this.value || '').trim();
                if (numerosTimer) clearTimeout(numerosTimer);
                numerosTimer = setTimeout(function () {
                    var snap = relacionesFiltrosSnapshot();
                    var tok = ++numerosTok;
                    fetchNumeros(qTxt, snap).then(function (items) {
                        if (tok !== numerosTok) return;
                        renderNumerosResultados(Array.isArray(items) ? items : []);
                    }).catch(function () {
                        if (tok !== numerosTok) return;
                        renderNumerosResultados([]);
                    });
                }, 180);
            });
        }
        var ddNum = document.getElementById('dd-rel-numeros');
        if (ddNum) {
            ddNum.addEventListener('shown.bs.dropdown', function () {
                var qTxt = (getVal('rel-numeros-search') || '').trim();
                var snap = relacionesFiltrosSnapshot();
                var tok = ++numerosTok;
                fetchNumeros(qTxt, snap).then(function (items) {
                    if (tok !== numerosTok) return;
                    renderNumerosResultados(Array.isArray(items) ? items : []);
                }).catch(function () {});
            });
        }

        var searchImei = document.getElementById('rel-imeis-search');
        if (searchImei) {
            searchImei.addEventListener('input', function () {
                var qTxt = (this.value || '').trim();
                if (imeisTimer) clearTimeout(imeisTimer);
                imeisTimer = setTimeout(function () {
                    var snap = relacionesFiltrosSnapshot();
                    var tok = ++imeisTok;
                    fetchImeis(qTxt, snap).then(function (items) {
                        if (tok !== imeisTok) return;
                        renderImeisResultados(Array.isArray(items) ? items : []);
                    }).catch(function () {
                        if (tok !== imeisTok) return;
                        renderImeisResultados([]);
                    });
                }, 180);
            });
        }
        var ddImei = document.getElementById('dd-rel-imeis');
        if (ddImei) {
            ddImei.addEventListener('shown.bs.dropdown', function () {
                var qTxt = (getVal('rel-imeis-search') || '').trim();
                var snap = relacionesFiltrosSnapshot();
                var tok = ++imeisTok;
                fetchImeis(qTxt, snap).then(function (items) {
                    if (tok !== imeisTok) return;
                    renderImeisResultados(Array.isArray(items) ? items : []);
                }).catch(function () {});
            });
        }

        if (selectedNumeros.size) {
            updateDdButtonText('dd-rel-numeros', 'Números: ' + selectedNumeros.size + ' seleccionado(s)');
        }
        if (selectedImeis.size) {
            updateDdButtonText('dd-rel-imeis', 'IMEIs: ' + selectedImeis.size + ' seleccionado(s)');
        }

        form.addEventListener('submit', function () {
            form.querySelectorAll('input[data-rel-mf-hidden="1"]').forEach(function (el) { el.remove(); });
            form.querySelectorAll('input[name="numeros[]"], input[name="imeis[]"]').forEach(function (el) {
                if (el.closest('#rel-filtro-numeros') || el.closest('#rel-filtro-imeis')) el.removeAttribute('name');
            });
            selectedNumeros.forEach(function (n) {
                var inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = 'numeros[]';
                inp.value = n;
                inp.setAttribute('data-rel-mf-hidden', '1');
                form.appendChild(inp);
            });
            selectedImeis.forEach(function (i) {
                var inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = 'imeis[]';
                inp.value = i;
                inp.setAttribute('data-rel-mf-hidden', '1');
                form.appendChild(inp);
            });
            renderFiltrosResumen();
        });

        ['fecha_desde', 'fecha_hasta', 'hora_desde', 'hora_hasta', 'filtro-tipo-trafico', 'caso_id', 'filtro-origen'].forEach(function (fid) {
            var el = document.getElementById(fid);
            if (!el) return;
            el.addEventListener('change', function () {
                scheduleCascadeRefresh();
                renderFiltrosResumen();
            });
        });

        renderFiltrosResumen();
    }

    function init() {
        loadPrefillSets();
        initDropdownSearch();
        wireMultiselect();
        scheduleCascadeRefresh();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

(function () {
    'use strict';

    function getContainer(id) { return document.getElementById(id); }

    function getCheckedValues(containerId) {
        var c = getContainer(containerId);
        if (!c) return [];
        var out = [];
        c.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
            var v = String(cb.value || '').trim();
            if (v) out.push(v);
        });
        return out;
    }

    function filterList(containerId, query) {
        var c = getContainer(containerId);
        if (!c) return;
        var q = String(query || '').toLowerCase().trim();
        c.querySelectorAll('.form-check').forEach(function (row) {
            var txt = (row.textContent || '').toLowerCase();
            row.style.display = (!q || txt.indexOf(q) !== -1) ? '' : 'none';
        });
    }

    function updateDdCount(btnId, containerId, emptyLabel) {
        var btn = document.getElementById(btnId);
        if (!btn) return;
        var n = getCheckedValues(containerId).length;
        btn.textContent = n > 0 ? (n + ' seleccionado(s)') : (emptyLabel || 'Seleccionar...');
    }

    function attachSearch() {
        document.querySelectorAll('.sabana-dd-search').forEach(function (inp) {
            inp.addEventListener('input', function () {
                var target = this.getAttribute('data-target');
                if (target) filterList(target, this.value);
            });
        });
    }

    function attachCountUpdates() {
        var defs = [
            { btn: 'dd-bv-casos', list: 'bv-filtro-casos', empty: 'Casos...' },
            { btn: 'dd-bv-sujetos', list: 'bv-filtro-sujetos', empty: 'Sujetos...' },
            { btn: 'dd-bv-tipos', list: 'bv-filtro-tipos', empty: 'Tipos...' },
            { btn: 'dd-bv-estados', list: 'bv-filtro-estados', empty: 'Estados...' },
            { btn: 'dd-bv-entidades', list: 'bv-filtro-entidades', empty: 'Entidades...' }
        ];
        defs.forEach(function (d) {
            var c = getContainer(d.list);
            if (c) {
                c.addEventListener('change', function () { updateDdCount(d.btn, d.list, d.empty); });
                updateDdCount(d.btn, d.list, d.empty);
            }
        });
    }

    function appendHiddenList(form, name, values) {
        values.forEach(function (v) {
            var i = document.createElement('input');
            i.type = 'hidden';
            i.name = name;
            i.value = v;
            i.setAttribute('data-bv-mf-hidden', '1');
            form.appendChild(i);
        });
    }

    var PRESETS_KEY = 'bv-analisis-presets-v1';
    var PRESETS_DEFAULT_KEY = 'bv-analisis-presets-default-v1';

    function readPresets() {
        try {
            var raw = localStorage.getItem(PRESETS_KEY);
            if (!raw) return {};
            var obj = JSON.parse(raw);
            return (obj && typeof obj === 'object') ? obj : {};
        } catch (e) {
            return {};
        }
    }

    function writePresets(map) {
        try {
            localStorage.setItem(PRESETS_KEY, JSON.stringify(map || {}));
        } catch (e) {
            // Ignorar errores de storage (quota, modo privado, etc.)
        }
    }

    function getDefaultPresetName() {
        try {
            return String(localStorage.getItem(PRESETS_DEFAULT_KEY) || '').trim();
        } catch (e) {
            return '';
        }
    }

    function setDefaultPresetName(name) {
        try {
            var n = String(name || '').trim();
            if (!n) localStorage.removeItem(PRESETS_DEFAULT_KEY);
            else localStorage.setItem(PRESETS_DEFAULT_KEY, n);
        } catch (e) {
            // noop
        }
    }

    function setCheckedValues(containerId, values) {
        var c = getContainer(containerId);
        if (!c) return;
        var bag = Object.create(null);
        (values || []).forEach(function (v) { bag[String(v)] = true; });
        c.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
            cb.checked = !!bag[String(cb.value || '').trim()];
        });
    }

    function getByName(form, name) {
        return form ? form.querySelector('[name="' + name + '"]') : null;
    }

    function collectCurrentFilters(form) {
        if (!form) return {};
        function val(name) {
            var el = getByName(form, name);
            return el ? String(el.value || '').trim() : '';
        }
        return {
            desde: val('desde'),
            hasta: val('hasta'),
            de_q: val('de_q'),
            hacia_q: val('hacia_q'),
            min_tx_vinculo: val('min_tx_vinculo') || '1',
            lim_mov: val('lim_mov'),
            lim_sal: val('lim_sal'),
            q: val('q'),
            caso_ids: getCheckedValues('bv-filtro-casos'),
            sujeto_ids: getCheckedValues('bv-filtro-sujetos'),
            tipos: getCheckedValues('bv-filtro-tipos'),
            estados: getCheckedValues('bv-filtro-estados'),
            entidades: getCheckedValues('bv-filtro-entidades'),
        };
    }

    function applyPresetToForm(form, data) {
        if (!form || !data) return;
        function setVal(name, v) {
            var el = getByName(form, name);
            if (el) el.value = (v == null ? '' : String(v));
        }
        setVal('desde', data.desde || '');
        setVal('hasta', data.hasta || '');
        setVal('de_q', data.de_q || '');
        setVal('hacia_q', data.hacia_q || '');
        setVal('min_tx_vinculo', data.min_tx_vinculo || '1');
        setVal('lim_mov', data.lim_mov || '');
        setVal('lim_sal', data.lim_sal || '');
        setVal('q', data.q || '');

        setCheckedValues('bv-filtro-casos', data.caso_ids || []);
        setCheckedValues('bv-filtro-sujetos', data.sujeto_ids || []);
        setCheckedValues('bv-filtro-tipos', data.tipos || []);
        setCheckedValues('bv-filtro-estados', data.estados || []);
        setCheckedValues('bv-filtro-entidades', data.entidades || []);

        updateDdCount('dd-bv-casos', 'bv-filtro-casos', 'Casos...');
        updateDdCount('dd-bv-sujetos', 'bv-filtro-sujetos', 'Sujetos...');
        updateDdCount('dd-bv-tipos', 'bv-filtro-tipos', 'Tipos...');
        updateDdCount('dd-bv-estados', 'bv-filtro-estados', 'Estados...');
        updateDdCount('dd-bv-entidades', 'bv-filtro-entidades', 'Entidades...');

        var sl = document.getElementById('bv-rel-edge-min');
        var inpMin = document.getElementById('bv-input-min-tx');
        if (sl && inpMin) {
            sl.value = inpMin.value || '1';
            sl.dispatchEvent(new Event('input'));
        }
    }

    function refreshPresetSelect(selectEl) {
        if (!selectEl) return;
        var cur = String(selectEl.value || '');
        var presets = readPresets();
        var names = Object.keys(presets).sort();
        selectEl.innerHTML = '<option value="">Seleccionar preset...</option>';
        names.forEach(function (name) {
            var op = document.createElement('option');
            op.value = name;
            op.textContent = name;
            selectEl.appendChild(op);
        });
        if (cur && presets[cur]) selectEl.value = cur;
    }

    function refreshDefaultPresetLabel(labelEl) {
        if (!labelEl) return;
        var def = getDefaultPresetName();
        labelEl.textContent = def ? ('Por defecto: ' + def) : 'Sin preset por defecto';
    }

    function wirePresets() {
        var form = document.getElementById('form-bv-analisis');
        var selectEl = document.getElementById('bv-preset-select');
        var btnSave = document.getElementById('bv-preset-save');
        var btnLoad = document.getElementById('bv-preset-load');
        var btnDefault = document.getElementById('bv-preset-default');
        var btnDelete = document.getElementById('bv-preset-delete');
        var defaultLabel = document.getElementById('bv-preset-default-name');
        if (!form || !selectEl || !btnSave || !btnLoad || !btnDelete || !btnDefault || !defaultLabel) return;

        refreshPresetSelect(selectEl);
        refreshDefaultPresetLabel(defaultLabel);

        // Si el usuario abre sin query explícita, aplicamos su preset por defecto.
        var hasSearch = String(window.location.search || '').trim().length > 1;
        if (!hasSearch) {
            var defName = getDefaultPresetName();
            var presetMap = readPresets();
            if (defName && presetMap[defName]) {
                selectEl.value = defName;
                applyPresetToForm(form, presetMap[defName]);
                form.requestSubmit();
                return;
            }
        }

        btnSave.addEventListener('click', function () {
            var def = String(selectEl.value || '').trim();
            var name = String(window.prompt('Nombre del preset:', def) || '').trim();
            if (!name) return;
            var presets = readPresets();
            presets[name] = collectCurrentFilters(form);
            writePresets(presets);
            refreshPresetSelect(selectEl);
            selectEl.value = name;
        });

        btnLoad.addEventListener('click', function () {
            var name = String(selectEl.value || '').trim();
            if (!name) {
                alert('Seleccione un preset.');
                return;
            }
            var presets = readPresets();
            var data = presets[name];
            if (!data) {
                alert('Preset no encontrado.');
                refreshPresetSelect(selectEl);
                return;
            }
            applyPresetToForm(form, data);
            form.requestSubmit();
        });

        btnDefault.addEventListener('click', function () {
            var name = String(selectEl.value || '').trim();
            if (!name) {
                if (window.confirm('No hay preset seleccionado. ¿Quitar preset por defecto?')) {
                    setDefaultPresetName('');
                    refreshDefaultPresetLabel(defaultLabel);
                }
                return;
            }
            var presets = readPresets();
            if (!presets[name]) {
                alert('El preset seleccionado no existe.');
                refreshPresetSelect(selectEl);
                return;
            }
            setDefaultPresetName(name);
            refreshDefaultPresetLabel(defaultLabel);
        });

        btnDelete.addEventListener('click', function () {
            var name = String(selectEl.value || '').trim();
            if (!name) {
                alert('Seleccione un preset para borrar.');
                return;
            }
            if (!window.confirm('¿Eliminar preset "' + name + '"?')) return;
            var presets = readPresets();
            if (presets[name]) {
                delete presets[name];
                writePresets(presets);
            }
            if (getDefaultPresetName() === name) {
                setDefaultPresetName('');
            }
            refreshPresetSelect(selectEl);
            refreshDefaultPresetLabel(defaultLabel);
        });
    }

    function wireSubmit() {
        var form = document.getElementById('form-bv-analisis');
        if (!form) return;
        form.addEventListener('submit', function () {
            form.querySelectorAll('input[data-bv-mf-hidden="1"]').forEach(function (el) { el.remove(); });
            appendHiddenList(form, 'caso_ids[]', getCheckedValues('bv-filtro-casos'));
            appendHiddenList(form, 'sujeto_ids[]', getCheckedValues('bv-filtro-sujetos'));
            appendHiddenList(form, 'tipos_movimiento[]', getCheckedValues('bv-filtro-tipos'));
            appendHiddenList(form, 'estados[]', getCheckedValues('bv-filtro-estados'));
            appendHiddenList(form, 'entidades[]', getCheckedValues('bv-filtro-entidades'));
            var sl = document.getElementById('bv-rel-edge-min');
            var inpMin = document.getElementById('bv-input-min-tx');
            if (sl && inpMin) {
                inpMin.value = sl.value;
            }
        });
    }

    function syncMinTxGrafoConFormulario() {
        var inp = document.getElementById('bv-input-min-tx');
        var sl = document.getElementById('bv-rel-edge-min');
        if (!inp || !sl) return;
        sl.value = inp.value || '1';
        sl.addEventListener('input', function () {
            inp.value = sl.value;
        });
        inp.addEventListener('input', function () {
            var v = parseInt(inp.value, 10);
            if (!isFinite(v) || v < 1) v = 1;
            if (v > 50) v = 50;
            inp.value = String(v);
            sl.value = String(v);
        });
    }

    function init() {
        attachSearch();
        attachCountUpdates();
        wireSubmit();
        syncMinTxGrafoConFormulario();
        wirePresets();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

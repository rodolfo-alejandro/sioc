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
        });
    }

    function init() {
        attachSearch();
        attachCountUpdates();
        wireSubmit();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

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

    function updateDdCount(btnId, containerId, emptyLabel) {
        var btn = document.getElementById(btnId);
        if (!btn) return;
        var n = getCheckedValues(containerId).length;
        btn.textContent = n > 0 ? (n + ' seleccionado(s)') : (emptyLabel || 'Seleccionar...');
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

    function appendHiddenList(form, name, values) {
        values.forEach(function (v) {
            var i = document.createElement('input');
            i.type = 'hidden';
            i.name = name;
            i.value = v;
            i.setAttribute('data-ad-hidden', '1');
            form.appendChild(i);
        });
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
            { btn: 'dd-ad-departamentos', list: 'ad-filtro-departamentos', empty: 'Departamentos...' },
            { btn: 'dd-ad-dep-reg', list: 'ad-filtro-dep-reg', empty: 'Dependencias...' },
            { btn: 'dd-ad-dep-act', list: 'ad-filtro-dep-act', empty: 'Dependencias...' },
            { btn: 'dd-ad-estados', list: 'ad-filtro-estados', empty: 'Estados...' },
            { btn: 'dd-ad-localidades', list: 'ad-filtro-localidades', empty: 'Localidades...' },
            { btn: 'dd-ad-barrios', list: 'ad-filtro-barrios', empty: 'Barrios...' },
            { btn: 'dd-ad-actuarios', list: 'ad-filtro-actuarios', empty: 'Actuarios...' }
        ];
        defs.forEach(function (d) {
            var c = getContainer(d.list);
            if (!c) return;
            c.addEventListener('change', function () { updateDdCount(d.btn, d.list, d.empty); });
            updateDdCount(d.btn, d.list, d.empty);
        });
    }

    function wireSubmit() {
        var form = document.getElementById('ad-form-filtros');
        if (!form) return;
        form.addEventListener('submit', function () {
            form.querySelectorAll('input[data-ad-hidden="1"]').forEach(function (el) { el.remove(); });
            appendHiddenList(form, 'departamentos[]', getCheckedValues('ad-filtro-departamentos'));
            appendHiddenList(form, 'dep_registro[]', getCheckedValues('ad-filtro-dep-reg'));
            appendHiddenList(form, 'dep_actuario[]', getCheckedValues('ad-filtro-dep-act'));
            appendHiddenList(form, 'causa_estado[]', getCheckedValues('ad-filtro-estados'));
            appendHiddenList(form, 'localidad[]', getCheckedValues('ad-filtro-localidades'));
            appendHiddenList(form, 'barrio[]', getCheckedValues('ad-filtro-barrios'));
            appendHiddenList(form, 'actuario[]', getCheckedValues('ad-filtro-actuarios'));
        });
    }

    function init() {
        var collapseEl = document.getElementById('ad-filtros-collapse');
        if (collapseEl) {
            var hasQuery = String(window.location.search || '').trim().length > 1;
            if (hasQuery && window.bootstrap && window.bootstrap.Collapse) {
                window.bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false }).show();
            }
        }
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

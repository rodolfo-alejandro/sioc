(function () {
    'use strict';

    function setGroup(gid, open) {
        var parent = document.querySelector('.ad-pivot-parent[data-group="' + gid + '"]');
        var btn = document.querySelector('.ad-pivot-toggle[data-group="' + gid + '"]');
        var ico = btn ? btn.querySelector('.ad-pivot-ico') : null;
        document.querySelectorAll('.ad-pivot-child[data-parent="' + gid + '"]').forEach(function (row) {
            row.classList.toggle('d-none', !open);
        });
        if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (ico) {
            ico.classList.toggle('bi-plus-square', !open);
            ico.classList.toggle('bi-dash-square', open);
        }
        if (parent) parent.classList.toggle('is-open', open);
    }

    function toggleGroup(gid) {
        var btn = document.querySelector('.ad-pivot-toggle[data-group="' + gid + '"]');
        if (!btn) return;
        var open = btn.getAttribute('aria-expanded') !== 'true';
        setGroup(gid, open);
    }

    function allGroupIds() {
        var ids = [];
        document.querySelectorAll('.ad-pivot-parent[data-group]').forEach(function (el) {
            if (el.classList.contains('ad-pivot-leaf')) return;
            ids.push(el.getAttribute('data-group'));
        });
        return ids;
    }

    function wireToggles() {
        document.querySelectorAll('.ad-pivot-toggle').forEach(function (btn) {
            btn.addEventListener('click', function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                toggleGroup(this.getAttribute('data-group'));
            });
        });

        document.querySelectorAll('.ad-pivot-parent[data-group]:not(.ad-pivot-leaf)').forEach(function (row) {
            row.addEventListener('click', function (ev) {
                if (ev.target.closest('a, input, select, textarea, button')) return;
                toggleGroup(this.getAttribute('data-group'));
            });
            row.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault();
                    toggleGroup(this.getAttribute('data-group'));
                }
            });
        });

        var expand = document.getElementById('ad-pivot-expand-all');
        var collapse = document.getElementById('ad-pivot-collapse-all');
        if (expand) {
            expand.addEventListener('click', function () {
                allGroupIds().forEach(function (id) { setGroup(id, true); });
            });
        }
        if (collapse) {
            collapse.addEventListener('click', function () {
                allGroupIds().forEach(function (id) { setGroup(id, false); });
            });
        }
    }

    function injectGruposIntoFiltros() {
        var form = document.getElementById('ad-form-filtros');
        var g1 = document.getElementById('ad-grupo1');
        var g2 = document.getElementById('ad-grupo2');
        var modo = document.getElementById('ad-modo');
        if (!form || !g1 || !g2) return;
        form.addEventListener('submit', function () {
            form.querySelectorAll('input[data-ad-grupo="1"]').forEach(function (el) { el.remove(); });
            var pairs = [['grupo1', g1.value], ['grupo2', g2.value]];
            if (modo) pairs.push(['modo', modo.value]);
            pairs.forEach(function (pair) {
                var i = document.createElement('input');
                i.type = 'hidden';
                i.name = pair[0];
                i.value = pair[1];
                i.setAttribute('data-ad-grupo', '1');
                form.appendChild(i);
            });
        });
    }

    function init() {
        wireToggles();
        injectGruposIntoFiltros();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

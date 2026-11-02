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

    function colKey(th, idx) {
        if (th.classList.contains('ad-pivot-sticky')) return 'sticky';
        if (th.classList.contains('ad-pivot-total-col')) return 'total';
        return 'c' + idx;
    }

    function applyColWidth(table, colIdx, px) {
        var width = Math.max(40, Math.round(px)) + 'px';
        table.querySelectorAll('tr').forEach(function (tr) {
            var cell = tr.children[colIdx];
            if (!cell) return;
            cell.style.width = width;
            cell.style.minWidth = width;
            cell.style.maxWidth = width;
        });
    }

    function wireColumnResize() {
        var table = document.getElementById('ad-pivot-table');
        if (!table) return;
        var theadRow = table.querySelector('thead tr');
        if (!theadRow) return;

        var storageKey = 'ad-pivot-col-widths';
        var saved = {};
        try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch (e) { saved = {}; }

        Array.prototype.forEach.call(theadRow.children, function (th, idx) {
            th.style.position = th.style.position || '';
            var key = colKey(th, idx);
            if (saved[key]) applyColWidth(table, idx, saved[key]);

            if (th.querySelector('.ad-col-resizer')) return;
            var handle = document.createElement('span');
            handle.className = 'ad-col-resizer';
            handle.title = 'Arrastrar para cambiar ancho';
            th.appendChild(handle);

            handle.addEventListener('mousedown', function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                var startX = ev.clientX;
                var startW = th.getBoundingClientRect().width;

                function onMove(e2) {
                    applyColWidth(table, idx, startW + (e2.clientX - startX));
                }
                function onUp(e2) {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    document.body.classList.remove('ad-col-resizing');
                    var finalW = Math.max(40, Math.round(startW + (e2.clientX - startX)));
                    try {
                        var cur = JSON.parse(localStorage.getItem(storageKey) || '{}') || {};
                        cur[key] = finalW;
                        localStorage.setItem(storageKey, JSON.stringify(cur));
                    } catch (err) { /* ignore */ }
                }
                document.body.classList.add('ad-col-resizing');
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });
        });
    }

    function init() {
        wireToggles();
        injectGruposIntoFiltros();
        wireColumnResize();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

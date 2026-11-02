(function () {
    'use strict';

    var STORAGE_KEY = 'ad-pivot-col-widths-v2';

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
                if (ev.target.closest('a, input, select, textarea, button, .ad-col-resizer')) return;
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

    function loadSaved() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {}; }
        catch (e) { return {}; }
    }

    function saveWidths(map) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(map)); }
        catch (e) { /* ignore */ }
    }

    function defaultWidth(th, idx) {
        if (th.classList.contains('ad-pivot-sticky')) return 260;
        if (th.classList.contains('ad-pivot-total-col')) return 56;
        return 58;
    }

    function ensureColgroup(table, count) {
        var cg = table.querySelector('colgroup');
        if (cg) cg.remove();
        cg = document.createElement('colgroup');
        for (var i = 0; i < count; i++) {
            cg.appendChild(document.createElement('col'));
        }
        table.insertBefore(cg, table.firstChild);
        return cg;
    }

    function setColWidth(col, px) {
        var w = Math.max(48, Math.round(px)) + 'px';
        col.style.width = w;
        col.style.minWidth = w;
    }

    function wireColumnResize() {
        var table = document.getElementById('ad-pivot-table');
        if (!table) return;
        var theadRow = table.querySelector('thead tr');
        if (!theadRow) return;

        var headers = Array.prototype.slice.call(theadRow.children);
        if (!headers.length) return;

        var colgroup = ensureColgroup(table, headers.length);
        var cols = Array.prototype.slice.call(colgroup.children);
        var saved = loadSaved();

        headers.forEach(function (th, idx) {
            var key = String(idx);
            var px = saved[key] || defaultWidth(th, idx);
            setColWidth(cols[idx], px);

            th.querySelectorAll('.ad-col-resizer').forEach(function (el) { el.remove(); });
            var handle = document.createElement('span');
            handle.className = 'ad-col-resizer';
            handle.title = 'Arrastrá para agrandar / achicar';
            th.appendChild(handle);

            function startDrag(clientX, ev) {
                if (ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                }
                var startX = clientX;
                var startW = cols[idx].getBoundingClientRect().width || defaultWidth(th, idx);
                handle.classList.add('is-active');
                document.body.classList.add('ad-col-resizing');

                function onMove(e2) {
                    var x = e2.touches ? e2.touches[0].clientX : e2.clientX;
                    if (e2.cancelable) e2.preventDefault();
                    setColWidth(cols[idx], startW + (x - startX));
                }
                function onUp(e2) {
                    var x = (e2.changedTouches && e2.changedTouches[0])
                        ? e2.changedTouches[0].clientX
                        : e2.clientX;
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    document.removeEventListener('touchmove', onMove);
                    document.removeEventListener('touchend', onUp);
                    handle.classList.remove('is-active');
                    document.body.classList.remove('ad-col-resizing');
                    var finalW = Math.max(48, Math.round(startW + (x - startX)));
                    setColWidth(cols[idx], finalW);
                    var map = loadSaved();
                    map[key] = finalW;
                    saveWidths(map);
                }

                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
                document.addEventListener('touchmove', onMove, { passive: false });
                document.addEventListener('touchend', onUp);
            }

            handle.addEventListener('mousedown', function (ev) {
                startDrag(ev.clientX, ev);
            });
            handle.addEventListener('touchstart', function (ev) {
                if (!ev.touches || !ev.touches[0]) return;
                startDrag(ev.touches[0].clientX, ev);
            }, { passive: false });
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

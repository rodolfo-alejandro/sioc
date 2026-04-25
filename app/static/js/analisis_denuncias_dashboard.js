(function () {
    'use strict';

    function parseData(elId) {
        var el = document.getElementById(elId);
        if (!el) return null;
        try {
            return JSON.parse(el.value || '{}');
        } catch (e) {
            return null;
        }
    }

    function plotBar(elId, labels, values, color, onClick) {
        var el = document.getElementById(elId);
        if (!el || !window.Plotly) return;
        window.Plotly.newPlot(el, [{
            type: 'bar',
            x: labels,
            y: values,
            marker: { color: color || '#0d6efd' }
        }], {
            margin: { l: 40, r: 10, t: 10, b: 80 }
        }, { displayModeBar: false, responsive: true });
        if (onClick && el.removeAllListeners) {
            el.removeAllListeners('plotly_click');
            el.on('plotly_click', function (ev) {
                var p = ev && ev.points && ev.points[0];
                if (!p) return;
                onClick(String(p.x || ''));
            });
        }
    }

    function plotPie(elId, labels, values, onClick) {
        var el = document.getElementById(elId);
        if (!el || !window.Plotly) return;
        window.Plotly.newPlot(el, [{
            type: 'pie',
            labels: labels,
            values: values,
            textinfo: 'label+percent',
        }], {
            margin: { l: 10, r: 10, t: 10, b: 10 }
        }, { displayModeBar: false, responsive: true });
        if (onClick && el.removeAllListeners) {
            el.removeAllListeners('plotly_click');
            el.on('plotly_click', function (ev) {
                var p = ev && ev.points && ev.points[0];
                if (!p) return;
                onClick(String(p.label || ''));
            });
        }
    }

    function parseRows() {
        var el = document.getElementById('ad-dashboard-rows');
        if (!el) return [];
        try {
            return JSON.parse(el.value || '[]');
        } catch (e) {
            return [];
        }
    }

    function monthLabelEs(iso) {
        if (!iso) return 'Sin fecha';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return 'Sin fecha';
        var m = d.toLocaleDateString('es-AR', { month: 'long', year: 'numeric' });
        return m.charAt(0).toUpperCase() + m.slice(1);
    }

    function dayLabelEs(iso) {
        if (!iso) return 'Sin fecha';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return 'Sin fecha';
        var x = d.toLocaleDateString('es-AR', { weekday: 'long' });
        return x.charAt(0).toUpperCase() + x.slice(1);
    }

    function hourLabel(iso1, iso2) {
        var iso = iso1 || iso2;
        if (!iso) return 'Sin hora';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return 'Sin hora';
        return String(d.getHours()).padStart(2, '0') + ':00';
    }

    function toActuario(gr, ap) {
        var g = String(gr || '').trim();
        var a = String(ap || '').trim();
        var out = (g + ' ' + a).trim();
        return out || 'Sin actuario';
    }

    function byCount(rows, keyFn, topN) {
        var m = Object.create(null);
        rows.forEach(function (r) {
            var k = String(keyFn(r) || '').trim() || 'Sin dato';
            m[k] = (m[k] || 0) + 1;
        });
        var arr = Object.keys(m).map(function (k) { return { label: k, value: m[k] }; });
        arr.sort(function (a, b) { return b.value - a.value; });
        if (topN && arr.length > topN) arr = arr.slice(0, topN);
        return arr;
    }

    function setText(id, val) {
        var el = document.getElementById(id);
        if (el) el.textContent = Number(val || 0).toLocaleString('es-AR');
    }

    function renderActiveInfo(state) {
        var el = document.getElementById('ad-active-chart-filters');
        if (!el) return;
        var parts = [];
        Object.keys(state).forEach(function (k) {
            if (state[k]) parts.push(k + ': ' + state[k]);
        });
        el.textContent = parts.length ? ('Filtros gráficos activos → ' + parts.join(' | ')) : 'Sin filtros gráficos activos';
    }

    function makeRows(rowsRaw) {
        return (rowsRaw || []).map(function (r) {
            return {
                mes: monthLabelEs(r.fecha_denuncia),
                dia: dayLabelEs(r.fecha_denuncia),
                hora: hourLabel(r.fecha_recepcion, r.fecha_denuncia),
                estado: String(r.causa_estado || '').trim() || 'Sin estado',
                barrio: (String(r.barrio || '').trim() || 'Sin barrio') + ' (' + (String(r.localidad || '').trim() || 'Sin localidad') + ')',
                departamento: String(r.departamento || '').trim() || 'Sin departamento',
                division: String(r.division || '').trim() || 'Sin división',
                dep_actuario: String(r.dep_actuario || '').trim() || 'Sin dependencia actuario',
                actuario: toActuario(r.actuario_grado, r.actuario_apenom),
                coords: (typeof r.latitud === 'number' && typeof r.longitud === 'number') ? 'Con coordenadas' : 'Sin coordenadas',
                investigados: String(r.investigados || '').trim() ? 'Con investigados' : 'Sin investigados',
                allanamiento: String(r.fecha_sol_allanamiento || '').trim() ? 'Con allanamiento' : 'Sin allanamiento',
                desestimada: String(r.fecha_desestimada || '').trim() ? 'Desestimada' : 'No desestimada'
            };
        });
    }

    function init() {
        if (!window.Plotly) return;
        var baseRows = makeRows(parseRows());
        if (!baseRows.length) return;
        var state = {
            mes: '', dia: '', hora: '', estado: '', barrio: '', departamento: '',
            division: '', dep_actuario: '', actuario: '', coords: '', investigados: '',
            allanamiento: '', desestimada: ''
        };

        function filteredRows() {
            return baseRows.filter(function (r) {
                return Object.keys(state).every(function (k) {
                    return !state[k] || String(r[k] || '') === String(state[k]);
                });
            });
        }

        function toggle(key, label) {
            state[key] = (state[key] === label) ? '' : label;
            renderAll();
        }

        function renderAll() {
            var rows = filteredRows();
            setText('ad-kpi-total', rows.length);
            setText('ad-kpi-concoords', rows.filter(function (r) { return r.coords === 'Con coordenadas'; }).length);
            setText('ad-kpi-sincoords', rows.filter(function (r) { return r.coords === 'Sin coordenadas'; }).length);
            setText('ad-kpi-allanamiento', rows.filter(function (r) { return r.allanamiento === 'Con allanamiento'; }).length);
            setText('ad-kpi-desestimadas', rows.filter(function (r) { return r.desestimada === 'Desestimada'; }).length);
            setText('ad-kpi-investigados', rows.filter(function (r) { return r.investigados === 'Con investigados'; }).length);

            var mes = byCount(rows, function (r) { return r.mes; });
            plotBar('ad-chart-mes', mes.map(function (x) { return x.label; }), mes.map(function (x) { return x.value; }), '#198754', function (x) { toggle('mes', x); });
            var dia = byCount(rows, function (r) { return r.dia; });
            plotBar('ad-chart-dia', dia.map(function (x) { return x.label; }), dia.map(function (x) { return x.value; }), '#0d6efd', function (x) { toggle('dia', x); });
            var hora = byCount(rows, function (r) { return r.hora; });
            plotBar('ad-chart-hora', hora.map(function (x) { return x.label; }), hora.map(function (x) { return x.value; }), '#6f42c1', function (x) { toggle('hora', x); });
            var est = byCount(rows, function (r) { return r.estado; });
            plotBar('ad-chart-estado', est.map(function (x) { return x.label; }), est.map(function (x) { return x.value; }), '#fd7e14', function (x) { toggle('estado', x); });
            var bar = byCount(rows, function (r) { return r.barrio; }, 30);
            plotBar('ad-chart-barrio', bar.map(function (x) { return x.label; }), bar.map(function (x) { return x.value; }), '#7952b3', function (x) { toggle('barrio', x); });
            var dep = byCount(rows, function (r) { return r.departamento; });
            plotBar('ad-chart-departamento', dep.map(function (x) { return x.label; }), dep.map(function (x) { return x.value; }), '#198754', function (x) { toggle('departamento', x); });
            var div = byCount(rows, function (r) { return r.division; }, 25);
            plotBar('ad-chart-division', div.map(function (x) { return x.label; }), div.map(function (x) { return x.value; }), '#0dcaf0', function (x) { toggle('division', x); });
            var dact = byCount(rows, function (r) { return r.dep_actuario; }, 25);
            plotBar('ad-chart-dep-actuario', dact.map(function (x) { return x.label; }), dact.map(function (x) { return x.value; }), '#20c997', function (x) { toggle('dep_actuario', x); });
            var act = byCount(rows, function (r) { return r.actuario; }, 30);
            plotBar('ad-chart-actuario', act.map(function (x) { return x.label; }), act.map(function (x) { return x.value; }), '#6610f2', function (x) { toggle('actuario', x); });

            var c1 = byCount(rows, function (r) { return r.coords; });
            plotPie('ad-chart-coords', c1.map(function (x) { return x.label; }), c1.map(function (x) { return x.value; }), function (x) { toggle('coords', x); });
            var c2 = byCount(rows, function (r) { return r.investigados; });
            plotPie('ad-chart-investigados', c2.map(function (x) { return x.label; }), c2.map(function (x) { return x.value; }), function (x) { toggle('investigados', x); });
            var c3 = byCount(rows, function (r) { return r.allanamiento; });
            plotPie('ad-chart-allanamiento', c3.map(function (x) { return x.label; }), c3.map(function (x) { return x.value; }), function (x) { toggle('allanamiento', x); });
            var c4 = byCount(rows, function (r) { return r.desestimada; });
            plotPie('ad-chart-desestimada', c4.map(function (x) { return x.label; }), c4.map(function (x) { return x.value; }), function (x) { toggle('desestimada', x); });

            renderActiveInfo(state);
        }

        var btnClear = document.getElementById('ad-clear-chart-filters');
        if (btnClear) {
            btnClear.addEventListener('click', function () {
                Object.keys(state).forEach(function (k) { state[k] = ''; });
                renderAll();
            });
        }
        renderAll();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

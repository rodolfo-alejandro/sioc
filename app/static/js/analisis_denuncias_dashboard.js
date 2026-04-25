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

    function plotBar(elId, labels, values, color) {
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
    }

    function plotPie(elId, labels, values) {
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
    }

    function init() {
        var data = parseData('ad-dashboard-data');
        if (!data) return;

        var mensual = data.mensual || [];
        plotBar('ad-chart-mensual', mensual.map(function (x) { return x.label; }), mensual.map(function (x) { return x.value; }), '#198754');

        var barrios = data.top_barrios || [];
        plotBar('ad-chart-barrios', barrios.map(function (x) { return x.label; }), barrios.map(function (x) { return x.value; }), '#6f42c1');

        var deps = data.top_dependencias || [];
        plotBar('ad-chart-deps', deps.map(function (x) { return x.label; }), deps.map(function (x) { return x.value; }), '#fd7e14');

        var est = data.estados || [];
        plotPie('ad-chart-estados', est.map(function (x) { return x.label; }), est.map(function (x) { return x.value; }));

        var coords = data.coords || [];
        plotPie('ad-chart-coords', coords.map(function (x) { return x.label; }), coords.map(function (x) { return x.value; }));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

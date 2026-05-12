(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  function parseData() {
    try { return JSON.parse((byId("ai-dashboard-data") || {}).value || "{}"); }
    catch (e) { return {}; }
  }

  function formatNumber(value, digits) {
    return Number(value || 0).toLocaleString("es-AR", {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0,
    });
  }

  var PLOT_CONFIG = {
    responsive: true,
    displayModeBar: false,
    displaylogo: false
  };

  function bar(elId, items, color, options) {
    if (!window.Plotly || !items || !items.length) return;
    options = options || {};
    var horizontal = !!options.horizontal;
    var digits = (typeof options.digits === "number") ? options.digits : 2;
    var labels = items.map(function (x) { return x.label; });
    var values = items.map(function (x) { return x.value; });
    var trace = {
      type: "bar",
      x: horizontal ? values : labels,
      y: horizontal ? labels : values,
      orientation: horizontal ? "h" : "v",
      marker: { color: color || "#0d6efd" },
      text: values.map(function (v) { return formatNumber(v, digits); }),
      textposition: "outside",
      cliponaxis: false,
      hovertemplate: horizontal
        ? "%{y}: %{x}<extra></extra>"
        : "%{x}: %{y}<extra></extra>",
    };
    window.Plotly.newPlot(elId, [trace], {
      margin: horizontal ? { l: 180, r: 20, t: 10, b: 40 } : { l: 50, r: 20, t: 10, b: 70 },
      yaxis: horizontal ? { automargin: true, type: "category" } : { rangemode: "tozero" },
      xaxis: horizontal
        ? { rangemode: "tozero" }
        : { automargin: true, type: "category", categoryorder: "array", categoryarray: labels },
      bargap: 0.35,
    }, PLOT_CONFIG);
  }

  function groupedBar(elId, data) {
    if (!window.Plotly || !data || !data.categories || !data.series || !data.series.length) return;
    var traces = data.series.map(function (serie) {
      return {
        type: "bar",
        name: serie.name,
        x: data.categories,
        y: serie.values,
        text: serie.values.map(function (v) { return formatNumber(v, 0); }),
        textposition: "outside",
        cliponaxis: false,
      };
    });
    window.Plotly.newPlot(elId, traces, {
      barmode: "group",
      margin: { l: 50, r: 20, t: 10, b: 60 },
      xaxis: { type: "category", categoryorder: "array", categoryarray: data.categories },
      yaxis: { rangemode: "tozero" },
    }, PLOT_CONFIG);
  }

  function renderDimensionCompare(data, key) {
    var map = {
      depops: data.chart_compare_depops || {},
      sinares: data.chart_compare_sinares || {},
      zonas: data.chart_compare_zonas || {}
    };
    groupedBar("ai-chart-dimension-compare", map[key] || map.depops || {});
  }

  function wireDimensionToggle(data) {
    var radios = document.querySelectorAll('input[name="ai-dim-mode"]');
    if (!radios.length) return;
    function currentValue() {
      var checked = document.querySelector('input[name="ai-dim-mode"]:checked');
      return checked ? checked.value : "depops";
    }
    radios.forEach(function (radio) {
      radio.addEventListener("change", function () {
        renderDimensionCompare(data, currentValue());
      });
    });
    renderDimensionCompare(data, currentValue());
  }

  function multiLine(elId, data) {
    if (!window.Plotly || !data || !data.categories || !data.series || !data.series.length) return;
    var traces = data.series.map(function (serie) {
      return {
        type: "scatter",
        mode: "lines+markers",
        name: serie.name,
        x: data.categories,
        y: serie.values,
      };
    });
    window.Plotly.newPlot(elId, traces, {
      margin: { l: 50, r: 20, t: 10, b: 60 },
      yaxis: { rangemode: "tozero" },
    }, PLOT_CONFIG);
  }

  function init() {
    var data = parseData();
    if (!data || !Object.keys(data).length) return;

    bar("ai-chart-anio-total", data.chart_anio_total || [], "#198754", { digits: 0 });
    bar("ai-chart-anio-allanamientos", data.chart_anio_allanamientos || [], "#dc3545", { digits: 0 });
    bar("ai-chart-anio-causas-allanadas", data.chart_anio_causas_allanadas || [], "#fd7e14", { digits: 0 });
    bar("ai-chart-anio-procedimientos", data.chart_anio_procedimientos || [], "#0d6efd", { digits: 0 });
    bar("ai-chart-anio-marihuana", data.chart_anio_marihuana || [], "#198754", { digits: 2 });
    bar("ai-chart-anio-cocaina", data.chart_anio_cocaina || [], "#dc3545", { digits: 2 });
    bar("ai-chart-anio-plantas", data.chart_anio_plantas || [], "#20c997", { digits: 2 });
    bar("ai-chart-anio-plantines", data.chart_anio_plantines || [], "#6610f2", { digits: 2 });
    bar("ai-chart-anio-semillas", data.chart_anio_semillas || [], "#6f42c1", { digits: 2 });
    bar("ai-chart-anio-hojas-coca", data.chart_anio_hojas_coca || [], "#fd7e14", { digits: 2 });
    bar("ai-chart-anio-detenidos", data.chart_anio_detenidos || [], "#6c757d", { digits: 0 });
    bar("ai-chart-anio-identificados", data.chart_anio_identificados || [], "#0dcaf0", { digits: 0 });
    wireDimensionToggle(data);
    multiLine("ai-chart-mensual", data.chart_mensual_por_anio || {});
    groupedBar("ai-chart-trimestral", data.chart_trimestral_por_anio || {});
    bar("ai-chart-zonas", data.chart_zonas || [], "#0d6efd", { horizontal: true, digits: 0 });
    bar("ai-chart-sinares", data.chart_sinares || [], "#6f42c1", { horizontal: true, digits: 0 });
    bar("ai-chart-depops", data.chart_depops || [], "#fd7e14", { horizontal: true, digits: 0 });
    bar("ai-chart-tipos", data.chart_tipos || [], "#20c997", { digits: 0 });
    bar("ai-chart-secuestros", data.chart_secuestros || [], "#dc3545", { digits: 2 });
    bar("ai-chart-dinero", data.chart_dinero || [], "#198754", { digits: 2 });
    bar("ai-chart-localidades", data.chart_localidades || [], "#6610f2", { horizontal: true, digits: 0 });
    bar("ai-chart-personas", data.chart_personas || [], "#6c757d", { digits: 0 });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

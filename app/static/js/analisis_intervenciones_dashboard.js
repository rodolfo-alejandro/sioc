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

  function bar(elId, items, color, horizontal) {
    if (!window.Plotly || !items || !items.length) return;
    var labels = items.map(function (x) { return x.label; });
    var values = items.map(function (x) { return x.value; });
    var trace = {
      type: "bar",
      x: horizontal ? values : labels,
      y: horizontal ? labels : values,
      orientation: horizontal ? "h" : "v",
      marker: { color: color || "#0d6efd" },
      text: values.map(function (v) { return formatNumber(v, 2); }),
      textposition: "outside",
      cliponaxis: false,
    };
    window.Plotly.newPlot(elId, [trace], {
      margin: horizontal ? { l: 180, r: 20, t: 10, b: 40 } : { l: 50, r: 20, t: 10, b: 100 },
      yaxis: horizontal ? { automargin: true } : { rangemode: "tozero" },
      xaxis: horizontal ? { rangemode: "tozero" } : { automargin: true },
    }, { responsive: true });
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
      yaxis: { rangemode: "tozero" },
    }, { responsive: true });
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
    }, { responsive: true });
  }

  function init() {
    var data = parseData();
    if (!data || !Object.keys(data).length) return;

    bar("ai-chart-anio-total", data.chart_anio_total || [], "#198754");
    groupedBar("ai-chart-tipo-anio", data.chart_tipo_por_anio || {});
    multiLine("ai-chart-mensual", data.chart_mensual_por_anio || {});
    groupedBar("ai-chart-trimestral", data.chart_trimestral_por_anio || {});
    bar("ai-chart-zonas", data.chart_zonas || [], "#0d6efd", true);
    bar("ai-chart-sinares", data.chart_sinares || [], "#6f42c1", true);
    bar("ai-chart-depops", data.chart_depops || [], "#fd7e14", true);
    bar("ai-chart-tipos", data.chart_tipos || [], "#20c997");
    bar("ai-chart-secuestros", data.chart_secuestros || [], "#dc3545");
    bar("ai-chart-dinero", data.chart_dinero || [], "#198754");
    bar("ai-chart-localidades", data.chart_localidades || [], "#6610f2", true);
    bar("ai-chart-personas", data.chart_personas || [], "#6c757d");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

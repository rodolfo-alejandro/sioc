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

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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

  function groupedBar(elId, data, options) {
    if (!window.Plotly || !data || !data.categories || !data.series || !data.series.length) return;
    options = options || {};
    var digits = (typeof options.digits === "number") ? options.digits : 0;
    var traces = data.series.map(function (serie) {
      return {
        type: "bar",
        name: serie.name,
        x: data.categories,
        y: serie.values,
        text: serie.values.map(function (v) { return formatNumber(v, digits); }),
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

  function renderDimensionTable(bundle, labels) {
    var tbody = byId("ai-dim-table-body");
    var labelHead = byId("ai-dim-table-label");
    if (labelHead) labelHead.textContent = labels.label;
    if (!tbody) return;
    var rows = (bundle && bundle.table_rows) || [];
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted">Sin datos.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(function (row) {
      return [
        "<tr>",
        "<td>" + escapeHtml(row.label) + "</td>",
        "<td>" + escapeHtml(row.anio) + "</td>",
        "<td>" + formatNumber(row.total, 0) + "</td>",
        "<td>" + formatNumber(row.allanamientos, 0) + "</td>",
        "<td>" + formatNumber(row.causas_allanadas, 0) + "</td>",
        "<td>" + formatNumber(row.procedimientos, 0) + "</td>",
        "<td>" + formatNumber(row.marihuana, 2) + "</td>",
        "<td>" + formatNumber(row.cocaina, 2) + "</td>",
        "<td>" + formatNumber(row.pesos_arg, 2) + "</td>",
        "<td>" + formatNumber(row.detenidos, 0) + "</td>",
        "<td>" + formatNumber(row.identificados, 0) + "</td>",
        "</tr>"
      ].join("");
    }).join("");
  }

  function renderDimensionCompare(data, key) {
    var map = {
      depops: {
        label: "Departamento operativo",
        title: "Comparativo anual por departamento operativo",
        bundle: (data.dimension_compare || {}).depops || {}
      },
      sinares: {
        label: "SINAR / División",
        title: "Comparativo anual por SINAR / División",
        bundle: (data.dimension_compare || {}).sinares || {}
      },
      zonas: {
        label: "DINAR",
        title: "Comparativo anual por DINAR",
        bundle: (data.dimension_compare || {}).zonas || {}
      }
    };
    var selected = map[key] || map.depops;
    var title = byId("ai-dim-compare-title");
    if (title) title.textContent = selected.title;
    var metrics = (selected.bundle && selected.bundle.metrics) || {};
    groupedBar("ai-dim-chart-total", metrics.total || {}, { digits: 0 });
    groupedBar("ai-dim-chart-allanamientos", metrics.allanamientos || {}, { digits: 0 });
    groupedBar("ai-dim-chart-causas-allanadas", metrics.causas_allanadas || {}, { digits: 0 });
    groupedBar("ai-dim-chart-procedimientos", metrics.procedimientos || {}, { digits: 0 });
    groupedBar("ai-dim-chart-marihuana", metrics.marihuana || {}, { digits: 2 });
    groupedBar("ai-dim-chart-cocaina", metrics.cocaina || {}, { digits: 2 });
    groupedBar("ai-dim-chart-pesos", metrics.pesos_arg || {}, { digits: 2 });
    groupedBar("ai-dim-chart-detenidos", metrics.detenidos || {}, { digits: 0 });
    groupedBar("ai-dim-chart-identificados", metrics.identificados || {}, { digits: 0 });
    renderDimensionTable(selected.bundle, selected);
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
    bar("ai-chart-anio-pesos", data.chart_anio_pesos || [], "#198754", { digits: 2 });
    bar("ai-chart-anio-detenidos", data.chart_anio_detenidos || [], "#6c757d", { digits: 0 });
    bar("ai-chart-anio-identificados", data.chart_anio_identificados || [], "#0dcaf0", { digits: 0 });
    wireDimensionToggle(data);
    multiLine("ai-chart-mensual", data.chart_mensual_por_anio || {});
    groupedBar("ai-chart-trimestral", data.chart_trimestral_por_anio || {}, { digits: 0 });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

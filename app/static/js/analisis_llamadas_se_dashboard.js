(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }
  function monthLabelEs(iso, mesRaw) {
    if (mesRaw && String(mesRaw).trim()) return String(mesRaw).trim();
    if (!iso) return "Sin fecha";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "Sin fecha";
    var m = d.toLocaleDateString("es-AR", { month: "long" });
    return m.charAt(0).toUpperCase() + m.slice(1);
  }
  function dayLabelEs(iso, diaRaw) {
    if (diaRaw && String(diaRaw).trim()) return String(diaRaw).trim();
    if (!iso) return "Sin fecha";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "Sin fecha";
    var x = d.toLocaleDateString("es-AR", { weekday: "long" });
    return x.charAt(0).toUpperCase() + x.slice(1);
  }
  function hourLabel(iso) {
    if (!iso) return "Sin hora";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "Sin hora";
    return String(d.getHours()).padStart(2, "0") + ":00";
  }
  function parseRows() {
    try { return JSON.parse((byId("als-dashboard-rows") || {}).value || "[]"); }
    catch (e) { return []; }
  }
  function byCount(rows, keyFn, topN) {
    var m = Object.create(null);
    rows.forEach(function (r) {
      var k = String(keyFn(r) || "").trim() || "Sin dato";
      m[k] = (m[k] || 0) + 1;
    });
    var arr = Object.keys(m).map(function (k) { return { label: k, value: m[k] }; });
    arr.sort(function (a, b) { return b.value - a.value; });
    if (topN && arr.length > topN) arr = arr.slice(0, topN);
    return arr;
  }
  function labelsByMode(values, mode) {
    var total = values.reduce(function (a, b) { return a + (Number(b) || 0); }, 0);
    if (mode === "porcentaje") {
      return values.map(function (v) {
        var p = total ? (100 * Number(v || 0) / total) : 0;
        return p.toFixed(1) + "%";
      });
    }
    return values.map(function (v) { return Number(v || 0).toLocaleString("es-AR"); });
  }
  function bar(elId, items, color, onClick, mode) {
    if (!window.Plotly) return;
    var x = items.map(function (r) { return r.label; });
    var y = items.map(function (r) { return r.value; });
    window.Plotly.newPlot(elId, [{
      type: "bar", x: x, y: y,
      marker: { color: color || "#0d6efd" },
      text: labelsByMode(y, mode || "cantidad"),
      textposition: "outside",
      cliponaxis: false,
    }], {
      margin: { l: 40, r: 20, t: 10, b: 110 },
      yaxis: { rangemode: "tozero" },
      uniformtext: { minsize: 10, mode: "hide" },
    }, { responsive: true });
    var el = byId(elId);
    if (onClick && el && el.removeAllListeners) {
      el.removeAllListeners("plotly_click");
      el.on("plotly_click", function (ev) {
        var p = ev && ev.points && ev.points[0];
        if (!p) return;
        onClick(String(p.x || ""));
      });
    }
  }
  function line(elId, items, onClick, mode) {
    if (!window.Plotly) return;
    var x = items.map(function (r) { return r.label; });
    var y = items.map(function (r) { return r.value; });
    window.Plotly.newPlot(elId, [{
      type: "scatter", mode: "lines+markers+text", x: x, y: y,
      text: labelsByMode(y, mode || "cantidad"), textposition: "top center",
    }], {
      margin: { l: 40, r: 20, t: 10, b: 60 },
      yaxis: { rangemode: "tozero" },
    }, { responsive: true });
    var el = byId(elId);
    if (onClick && el && el.removeAllListeners) {
      el.removeAllListeners("plotly_click");
      el.on("plotly_click", function (ev) {
        var p = ev && ev.points && ev.points[0];
        if (!p) return;
        onClick(String(p.x || ""));
      });
    }
  }
  function pie(elId, items, onClick, mode) {
    if (!window.Plotly) return;
    window.Plotly.newPlot(elId, [{
      type: "pie",
      labels: items.map(function (r) { return r.label; }),
      values: items.map(function (r) { return r.value; }),
      textinfo: mode === "porcentaje" ? "label+percent" : "label+value",
      texttemplate: mode === "porcentaje" ? "%{label}<br>%{percent}" : "%{label}<br>%{value}",
      textposition: "inside",
    }], {
      margin: { l: 10, r: 10, t: 10, b: 10 },
    }, { responsive: true });
    var el = byId(elId);
    if (onClick && el && el.removeAllListeners) {
      el.removeAllListeners("plotly_click");
      el.on("plotly_click", function (ev) {
        var p = ev && ev.points && ev.points[0];
        if (!p) return;
        onClick(String(p.label || ""));
      });
    }
  }
  function setText(id, val) {
    var el = byId(id);
    if (el) el.textContent = Number(val || 0).toLocaleString("es-AR");
  }
  function renderActiveInfo(state) {
    var el = byId("als-active-chart-filters");
    if (!el) return;
    var parts = [];
    Object.keys(state).forEach(function (k) { if (state[k]) parts.push(k + ": " + state[k]); });
    el.textContent = parts.length ? ("Filtros de gráficos activos -> " + parts.join(" | ")) : "Sin filtros gráficos activos";
  }
  function downloadTextFile(filename, text, mimeType) {
    var blob = new Blob([text], { type: mimeType || "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
  function toCsv(rows) {
    if (!rows.length) return "sin_datos\n";
    var headers = ["llamada_fecha", "alerta", "dep", "juris", "localidad", "barrio", "dia", "detalle"];
    var out = [headers.join(",")];
    rows.forEach(function (r) {
      var vals = [
        r.llamada_fecha_raw || "",
        r.alerta || "",
        r.dep || "",
        r.juris || "",
        r.localidad || "",
        r.barrio || "",
        r.dia || "",
        r.detalle || "",
      ].map(function (v) { return '"' + String(v).replace(/"/g, '""') + '"'; });
      out.push(vals.join(","));
    });
    return out.join("\n");
  }
  function reportHtml(rows, state) {
    var total = rows.length;
    if (!total) return '<p class="text-muted mb-0">Sin datos para el filtro actual.</p>';
    function topLabel(arr) { return (arr[0] && arr[0].label) ? arr[0].label : "Sin dato"; }
    function topValue(arr) { return (arr[0] && arr[0].value) ? arr[0].value : 0; }
    var alertas = byCount(rows, function (r) { return r.alerta; }, 5);
    var barrios = byCount(rows, function (r) { return r.barrio; }, 5);
    var deps = byCount(rows, function (r) { return r.dep; }, 5);
    var juris = byCount(rows, function (r) { return r.juris; }, 5);
    var dias = byCount(rows, function (r) { return r.dia; }, 7);
    var conCoords = rows.filter(function (r) { return r.con_coord; }).length;
    var venta = rows.filter(function (r) { return String(r.alerta).toLowerCase().indexOf("venta") >= 0; }).length;
    var consumo = rows.filter(function (r) { return String(r.alerta).toLowerCase().indexOf("consumo") >= 0; }).length;
    var topBarrioVal = topValue(barrios);
    var topDepVal = topValue(deps);
    var riesgoZona = topBarrioVal >= 30 ? "Alta" : (topBarrioVal >= 15 ? "Media" : "Baja");
    var riesgoDep = topDepVal >= 30 ? "Alta" : (topDepVal >= 15 ? "Media" : "Baja");
    var coordPct = total ? (100 * conCoords / total) : 0;
    var active = [];
    Object.keys(state).forEach(function (k) { if (state[k]) active.push(k + ": " + state[k]); });
    return [
      '<div class="row g-3">',
      '<div class="col-lg-6"><div class="border rounded p-3 h-100"><h6 class="mb-2">Resumen ejecutivo</h6><ul class="mb-0">',
      '<li><strong>Total analizado:</strong> ' + total.toLocaleString("es-AR") + ' llamadas.</li>',
      '<li><strong>Alerta predominante:</strong> ' + topLabel(alertas) + ' (' + topValue(alertas).toLocaleString("es-AR") + ').</li>',
      '<li><strong>Con coordenadas:</strong> ' + conCoords.toLocaleString("es-AR") + ' (' + (100 * conCoords / total).toFixed(1) + '%).</li>',
      '<li><strong>Venta:</strong> ' + venta.toLocaleString("es-AR") + ' (' + (100 * venta / total).toFixed(1) + '%).</li>',
      '<li><strong>Consumo:</strong> ' + consumo.toLocaleString("es-AR") + ' (' + (100 * consumo / total).toFixed(1) + '%).</li>',
      '</ul></div></div>',
      '<div class="col-lg-6"><div class="border rounded p-3 h-100"><h6 class="mb-2">Foco territorial</h6><ul class="mb-0">',
      '<li><strong>Barrio crítico:</strong> ' + topLabel(barrios) + ' (' + topValue(barrios).toLocaleString("es-AR") + ').</li>',
      '<li><strong>Dependencia con mayor carga:</strong> ' + topLabel(deps) + '.</li>',
      '<li><strong>Jurisdicción dominante:</strong> ' + topLabel(juris) + '.</li>',
      '<li><strong>Día más incidente:</strong> ' + topLabel(dias) + ' (' + topValue(dias).toLocaleString("es-AR") + ').</li>',
      '</ul></div></div>',
      '<div class="col-lg-12"><div class="border rounded p-3 h-100"><h6 class="mb-2">Recomendaciones operativas</h6><ul class="mb-0">',
      '<li><strong>Zona prioritaria (' + riesgoZona + '):</strong> reforzar patrullaje y tareas preventivas en <strong>' + topLabel(barrios) + '</strong> con monitoreo diario.</li>',
      '<li><strong>Dependencia foco (' + riesgoDep + '):</strong> revisar distribución de recursos en <strong>' + topLabel(deps) + '</strong> y medir evolución semanal.</li>',
      '<li><strong>Plan temporal:</strong> intensificar acciones en <strong>' + topLabel(dias) + '</strong> y en franja de fechas con mayor concentración.</li>',
      '<li><strong>Calidad geográfica:</strong> ' + coordPct.toFixed(1) + '% de llamadas con coordenadas. ' + (coordPct < 70 ? 'Reforzar carga de coordenadas para mejorar precisión operativa.' : 'Cobertura geográfica aceptable; mantener estándar de registro.') + '</li>',
      '<li><strong>Tipología dominante:</strong> si prevalece <strong>' + topLabel(alertas) + '</strong>, orientar controles específicos y campañas focalizadas.</li>',
      '</ul></div></div>',
      '</div>',
      active.length ? '<p class="small text-muted mb-0"><strong>Selección de gráficos activa:</strong> ' + active.join(" | ") + "</p>" : "",
    ].join("");
  }
  function reportText(rows, state) {
    var total = rows.length;
    if (!total) return "Sin datos para el filtro actual.";
    function topLabel(arr) { return (arr[0] && arr[0].label) ? arr[0].label : "Sin dato"; }
    function topValue(arr) { return (arr[0] && arr[0].value) ? arr[0].value : 0; }
    var alertas = byCount(rows, function (r) { return r.alerta; }, 5);
    var barrios = byCount(rows, function (r) { return r.barrio; }, 5);
    var deps = byCount(rows, function (r) { return r.dep; }, 5);
    var juris = byCount(rows, function (r) { return r.juris; }, 5);
    var dias = byCount(rows, function (r) { return r.dia; }, 7);
    var conCoords = rows.filter(function (r) { return r.con_coord; }).length;
    var venta = rows.filter(function (r) { return String(r.alerta).toLowerCase().indexOf("venta") >= 0; }).length;
    var consumo = rows.filter(function (r) { return String(r.alerta).toLowerCase().indexOf("consumo") >= 0; }).length;
    var topBarrioVal = topValue(barrios);
    var topDepVal = topValue(deps);
    var riesgoZona = topBarrioVal >= 30 ? "ALTA" : (topBarrioVal >= 15 ? "MEDIA" : "BAJA");
    var riesgoDep = topDepVal >= 30 ? "ALTA" : (topDepVal >= 15 ? "MEDIA" : "BAJA");
    var coordPct = total ? (100 * conCoords / total) : 0;
    var active = [];
    Object.keys(state).forEach(function (k) { if (state[k]) active.push(k + ": " + state[k]); });
    var lines = [];
    lines.push("INFORME ANALITICO - LLAMADAS SE");
    lines.push("Fecha: " + new Date().toLocaleString("es-AR"));
    lines.push("");
    lines.push("RESUMEN");
    lines.push("- Total analizado: " + total.toLocaleString("es-AR"));
    lines.push("- Alerta predominante: " + topLabel(alertas) + " (" + topValue(alertas).toLocaleString("es-AR") + ")");
    lines.push("- Barrio crítico: " + topLabel(barrios));
    lines.push("- Dependencia con mayor carga: " + topLabel(deps));
    lines.push("- Jurisdicción dominante: " + topLabel(juris));
    lines.push("- Día con mayor incidencia: " + topLabel(dias) + " (" + topValue(dias).toLocaleString("es-AR") + ")");
    lines.push("- Con coordenadas: " + conCoords.toLocaleString("es-AR") + " (" + (100 * conCoords / total).toFixed(1) + "%)");
    lines.push("- Alertas venta: " + venta.toLocaleString("es-AR") + " | Alertas consumo: " + consumo.toLocaleString("es-AR"));
    lines.push("");
    lines.push("RECOMENDACIONES OPERATIVAS");
    lines.push("- Zona prioritaria (" + riesgoZona + "): reforzar despliegue en " + topLabel(barrios) + ".");
    lines.push("- Dependencia foco (" + riesgoDep + "): revisar recursos en " + topLabel(deps) + " y seguimiento semanal.");
    lines.push("- Acción temporal: concentrar operativos en " + topLabel(dias) + ".");
    lines.push("- Calidad geográfica: " + coordPct.toFixed(1) + "% con coordenadas (" + (coordPct < 70 ? "mejorar carga georreferenciada" : "nivel aceptable") + ").");
    lines.push("- Tipología dominante: " + topLabel(alertas) + "; ajustar estrategia preventiva específica.");
    if (active.length) {
      lines.push("");
      lines.push("SELECCION GRAFICOS ACTIVA");
      lines.push(active.join(" | "));
    }
    return lines.join("\n");
  }
  function reportHtmlForPdf(rows, state) {
    return [
      '<!doctype html><html><head><meta charset="utf-8"><title>Informe Llamadas SE</title>',
      "<style>@page { size: A4; margin: 18mm; } body{font-family: Arial, sans-serif; color:#1f2937; font-size:12px;} .head{border-bottom:2px solid #1d4ed8; padding-bottom:8px; margin-bottom:12px;} .title{font-size:18px; font-weight:700; color:#1d4ed8;} .sub{font-size:11px; color:#4b5563;} .row{display:flex; flex-wrap:wrap; gap:12px;} .col-lg-6{width:48%;} .border{border:1px solid #d1d5db;} .rounded{border-radius:6px;} .p-3{padding:10px;} ul{margin:0; padding-left:16px;} li{margin:0 0 4px;}</style></head><body>",
      '<div class="head"><div class="title">SIOC - Informe Analítico Llamadas SE</div><div class="sub">Generado: ' + new Date().toLocaleString("es-AR") + "</div></div>",
      reportHtml(rows, state),
      "</body></html>",
    ].join("");
  }
  function init() {
    var baseRows = parseRows();
    if (!baseRows.length) return;
    var state = { mes: "", dia: "", hora: "", alerta: "", barrio: "", localidad: "", dep: "", juris: "", semana: "", diario: "", coords: "", tipologia: "" };
    var mode = "cantidad";

    var lastRows = [];
    function normalizedRows() {
      return baseRows.map(function (r) {
        return {
          llamada_fecha_raw: r.llamada_fecha || "",
          mes: monthLabelEs(r.llamada_fecha, r.llamada_mes),
          alerta: r.llamada_alerta_desc || "Sin dato",
          barrio: r.llamada_barrio_nombre || "Sin dato",
          dep: r.llamada_dep_nombre || "Sin dato",
          juris: r.llamada_jurisdiccion || "Sin dato",
          localidad: r.llamada_local_nombre || "Sin dato",
          detalle: r.llamada_detalle || "",
          dia: dayLabelEs(r.llamada_fecha, r.llamada_dia_semana),
          hora: hourLabel(r.llamada_fecha),
          semana: r.llamada_semana || "Sin semana",
          diario: (r.llamada_fecha || "").slice(0, 10) || "Sin fecha",
          con_coord: (typeof r.llamada_coordx === "number" && typeof r.llamada_coordy === "number"),
          coords: (typeof r.llamada_coordx === "number" && typeof r.llamada_coordy === "number") ? "Con coordenadas" : "Sin coordenadas",
          tipologia: (String(r.llamada_alerta_desc || "").toLowerCase().indexOf("venta") >= 0)
            ? "Venta"
            : ((String(r.llamada_alerta_desc || "").toLowerCase().indexOf("consumo") >= 0) ? "Consumo" : "Otra"),
        };
      });
    }
    var rowsN = normalizedRows();
    function rowsFiltered() {
      return rowsN.filter(function (r) {
        return (!state.mes || r.mes === state.mes)
          && (!state.dia || r.dia === state.dia)
          && (!state.hora || r.hora === state.hora)
          && (!state.alerta || r.alerta === state.alerta)
          && (!state.barrio || r.barrio === state.barrio)
          && (!state.localidad || r.localidad === state.localidad)
          && (!state.dep || r.dep === state.dep)
          && (!state.juris || r.juris === state.juris)
          && (!state.semana || r.semana === state.semana)
          && (!state.diario || r.diario === state.diario)
          && (!state.coords || r.coords === state.coords)
          && (!state.tipologia || r.tipologia === state.tipologia);
      });
    }
    function toggle(k, v) { state[k] = state[k] === v ? "" : v; render(); }
    function render() {
      var rows = rowsFiltered();
      lastRows = rows.slice();
      setText("als-kpi-total", rows.length);
      setText("als-kpi-concoords", rows.filter(function (r) { return r.con_coord; }).length);
      setText("als-kpi-venta", rows.filter(function (r) { return String(r.alerta).toLowerCase().indexOf("venta") >= 0; }).length);
      setText("als-kpi-consumo", rows.filter(function (r) { return String(r.alerta).toLowerCase().indexOf("consumo") >= 0; }).length);

      bar("als-chart-mes", byCount(rows, function (r) { return r.mes; }), "#198754", function (x) { toggle("mes", x); }, mode);
      bar("als-chart-dia", byCount(rows, function (r) { return r.dia; }), "#fd7e14", function (x) { toggle("dia", x); }, mode);
      bar("als-chart-hora", byCount(rows, function (r) { return r.hora; }), "#6f42c1", function (x) { toggle("hora", x); }, mode);
      bar("als-chart-alertas", byCount(rows, function (r) { return r.alerta; }), "#0d6efd", function (x) { toggle("alerta", x); }, mode);
      bar("als-chart-barrios", byCount(rows, function (r) { return r.barrio; }, 30), "#7952b3", function (x) { toggle("barrio", x); }, mode);
      bar("als-chart-localidades", byCount(rows, function (r) { return r.localidad; }, 25), "#20c997", function (x) { toggle("localidad", x); }, mode);
      bar("als-chart-juris", byCount(rows, function (r) { return r.juris; }, 25), "#0dcaf0", function (x) { toggle("juris", x); }, mode);
      bar("als-chart-deps", byCount(rows, function (r) { return r.dep; }, 25), "#198754", function (x) { toggle("dep", x); }, mode);
      bar("als-chart-semana", byCount(rows, function (r) { return r.semana; }), "#dc3545", function (x) { toggle("semana", x); }, mode);
      line("als-chart-diario", byCount(rows, function (r) { return r.diario; }), function (x) { toggle("diario", x); }, mode);
      pie("als-chart-coords", byCount(rows, function (r) { return r.coords; }), function (x) { toggle("coords", x); }, mode);
      pie("als-chart-tipologia", byCount(rows, function (r) { return r.tipologia; }), function (x) { toggle("tipologia", x); }, mode);
      renderActiveInfo(state);
      var rep = byId("als-ai-report");
      if (rep) rep.innerHTML = reportHtml(rows, state);
    }
    var clearBtn = byId("als-clear-chart-filters");
    if (clearBtn) clearBtn.addEventListener("click", function () {
      Object.keys(state).forEach(function (k) { state[k] = ""; });
      render();
    });
    document.querySelectorAll('input[name="als-chart-mode"]').forEach(function (rb) {
      rb.addEventListener("change", function () { mode = this.value || "cantidad"; render(); });
    });
    var btnTxt = byId("als-export-report-txt");
    if (btnTxt) btnTxt.addEventListener("click", function () {
      downloadTextFile("analisis_llamadas_se_informe.txt", reportText(lastRows, state), "text/plain;charset=utf-8");
    });
    var btnCsv = byId("als-export-report-csv");
    if (btnCsv) btnCsv.addEventListener("click", function () {
      downloadTextFile("analisis_llamadas_se_analisis_filtrado.csv", toCsv(lastRows), "text/csv;charset=utf-8");
    });
    var btnPdf = byId("als-export-report-pdf");
    if (btnPdf) btnPdf.addEventListener("click", function () {
      var html = reportHtmlForPdf(lastRows, state);
      var w = window.open("", "_blank");
      if (!w) return;
      w.document.open();
      w.document.write(html);
      w.document.close();
      w.focus();
      setTimeout(function () { w.print(); }, 250);
    });
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();


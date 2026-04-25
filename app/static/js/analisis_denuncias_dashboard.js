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

    function labelValues(values, mode) {
        var total = values.reduce(function (a, b) { return a + (Number(b) || 0); }, 0);
        if (mode === 'porcentaje') {
            return values.map(function (v) {
                var p = total ? (100 * Number(v || 0) / total) : 0;
                return p.toFixed(1) + '%';
            });
        }
        return values.map(function (v) { return Number(v || 0).toLocaleString('es-AR'); });
    }

    function plotBar(elId, labels, values, color, onClick, mode) {
        var el = document.getElementById(elId);
        if (!el || !window.Plotly) return;
        var textVals = labelValues(values, mode || 'cantidad');
        window.Plotly.newPlot(el, [{
            type: 'bar',
            x: labels,
            y: values,
            marker: { color: color || '#0d6efd' },
            text: textVals,
            textposition: 'outside',
            cliponaxis: false,
        }], {
            margin: { l: 40, r: 10, t: 20, b: 95 },
            uniformtext: { minsize: 10, mode: 'hide' }
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

    function plotPie(elId, labels, values, onClick, mode) {
        var el = document.getElementById(elId);
        if (!el || !window.Plotly) return;
        window.Plotly.newPlot(el, [{
            type: 'pie',
            labels: labels,
            values: values,
            textinfo: mode === 'porcentaje' ? 'label+percent' : 'label+value',
            texttemplate: mode === 'porcentaje' ? '%{label}<br>%{percent}' : '%{label}<br>%{value}',
            textposition: 'inside',
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

    function parseIsoDate(iso) {
        if (!iso) return null;
        var d = new Date(iso);
        return isNaN(d.getTime()) ? null : d;
    }

    function daysRangeLabel(days) {
        if (days == null || days < 0) return 'Sin fecha de inicio';
        if (days <= 15) return '1-15 días';
        if (days <= 30) return '16-30 días';
        if (days <= 60) return '31-60 días';
        if (days <= 90) return '61-90 días';
        if (days <= 180) return '91-180 días';
        return '181+ días';
    }

    function normalizeText(x) {
        return String(x || '').toLowerCase()
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
            .trim();
    }

    function isUnresolvedEstado(estado) {
        var s = normalizeText(estado);
        if (!s) return true;
        var unresolvedTokens = ['pend', 'investig', 'tramite', 'curso', 'abierta', 'iniciad', 'proceso', 'analisis'];
        var closedTokens = ['desestim', 'archiv', 'resuel', 'cerrad', 'finaliz', 'elevad', 'conden', 'sentenc'];
        if (closedTokens.some(function (t) { return s.indexOf(t) >= 0; })) return false;
        if (unresolvedTokens.some(function (t) { return s.indexOf(t) >= 0; })) return true;
        return true;
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

    function reportHtml(rows, state) {
        var total = rows.length;
        if (!total) return '<p class="text-muted mb-0">Sin datos para el filtro actual.</p>';
        function topLabel(arr) { return (arr[0] && arr[0].label) ? arr[0].label : 'Sin dato'; }
        function topValue(arr) { return (arr[0] && arr[0].value) ? arr[0].value : 0; }
        var est = byCount(rows, function (r) { return r.estado; }, 5);
        var dep = byCount(rows, function (r) { return r.departamento; }, 5);
        var div = byCount(rows, function (r) { return r.division; }, 5);
        var bar = byCount(rows, function (r) { return r.barrio; }, 5);
        var act = byCount(rows, function (r) { return r.actuario; }, 5);
        var conCoords = rows.filter(function (r) { return r.coords === 'Con coordenadas'; }).length;
        var conInv = rows.filter(function (r) { return r.investigados === 'Con investigados'; }).length;
        var conAlla = rows.filter(function (r) { return r.allanamiento === 'Con allanamiento'; }).length;
        var desest = rows.filter(function (r) { return r.desestimada === 'Desestimada'; }).length;
        var topMes = byCount(rows, function (r) { return r.mes; }, 5);
        var topDia = byCount(rows, function (r) { return r.dia; }, 5);
        var topHora = byCount(rows, function (r) { return r.hora; }, 8);
        var topLoc = byCount(rows, function (r) { return r.localidad_simple; }, 5);
        var dias = byCount(rows, function (r) { return r.rango_dias; });
        var actRows = rows.filter(function (r) { return r.actuario !== 'Sin actuario'; });
        var unresolvedByAct = Object.create(null);
        var totalByAct = Object.create(null);
        actRows.forEach(function (r) {
            totalByAct[r.actuario] = (totalByAct[r.actuario] || 0) + 1;
            if (r.estado_pendiente) unresolvedByAct[r.actuario] = (unresolvedByAct[r.actuario] || 0) + 1;
        });
        var actRisk = Object.keys(totalByAct).map(function (a) {
            var tot = totalByAct[a] || 0;
            var pend = unresolvedByAct[a] || 0;
            var pct = tot ? (100 * pend / tot) : 0;
            return { label: a, total: tot, pendientes: pend, pct: pct };
        }).sort(function (a, b) { return b.pct - a.pct || b.total - a.total; }).slice(0, 5);
        var rawKeys = Object.keys((rows[0] && rows[0].raw) || {});
        var ignored = { id: true, unidad_id: true, created_at: true, updated_at: true, fecha_importacion: true };
        var fieldsToAudit = rawKeys.filter(function (k) { return !ignored[k]; });
        var bajas = fieldsToAudit.map(function (k) {
            var filled = rows.filter(function (r) {
                var v = r.raw[k];
                if (v === null || v === undefined) return false;
                if (typeof v === 'string' && !v.trim()) return false;
                return true;
            }).length;
            return { k: k, pct: total ? (100 * filled / total) : 0 };
        }).sort(function (a, b) { return a.pct - b.pct; }).slice(0, 5);
        var repInvest = byCount(
            rows.filter(function (r) { return r.investigados_texto; }),
            function (r) { return r.investigados_texto; }
        ).filter(function (x) { return x.value > 1; }).slice(0, 5);
        var repLugar = byCount(rows, function (r) { return r.barrio; }).filter(function (x) { return x.value > 1; }).slice(0, 5);
        var repInvLugarMap = Object.create(null);
        rows.forEach(function (r) {
            if (!r.investigados_texto) return;
            var key = r.investigados_texto + ' || ' + r.barrio;
            repInvLugarMap[key] = (repInvLugarMap[key] || 0) + 1;
        });
        var repInvLugar = Object.keys(repInvLugarMap).map(function (k) {
            return { label: k, value: repInvLugarMap[k] };
        }).filter(function (x) { return x.value > 1; }).sort(function (a, b) { return b.value - a.value; }).slice(0, 5);
        var active = [];
        Object.keys(state).forEach(function (k) { if (state[k]) active.push(k + ': ' + state[k]); });
        return [
            '<div class="row g-3">',
            '<div class="col-lg-6"><div class="border rounded p-3 h-100">',
            '<h6 class="mb-2">Resumen ejecutivo</h6>',
            '<ul class="mb-0">',
            '<li><strong>Total analizado:</strong> ' + total.toLocaleString('es-AR') + ' denuncias.</li>',
            '<li><strong>Estado predominante:</strong> ' + topLabel(est) + ' (' + topValue(est).toLocaleString('es-AR') + ').</li>',
            '<li><strong>Allanamientos:</strong> ' + conAlla.toLocaleString('es-AR') + ' (' + (100 * conAlla / total).toFixed(1) + '%).</li>',
            '<li><strong>Desestimadas:</strong> ' + desest.toLocaleString('es-AR') + ' (' + (100 * desest / total).toFixed(1) + '%).</li>',
            '<li><strong>Con investigados:</strong> ' + conInv.toLocaleString('es-AR') + ' (' + (100 * conInv / total).toFixed(1) + '%).</li>',
            '<li><strong>Con coordenadas:</strong> ' + conCoords.toLocaleString('es-AR') + ' (' + (100 * conCoords / total).toFixed(1) + '%).</li>',
            '</ul></div></div>',
            '<div class="col-lg-6"><div class="border rounded p-3 h-100">',
            '<h6 class="mb-2">Patrón temporal</h6>',
            '<ul class="mb-0">',
            '<li><strong>Mes con mayor incidencia:</strong> ' + topLabel(topMes) + ' (' + topValue(topMes).toLocaleString('es-AR') + ').</li>',
            '<li><strong>Día con mayor incidencia:</strong> ' + topLabel(topDia) + ' (' + topValue(topDia).toLocaleString('es-AR') + ').</li>',
            '<li><strong>Franja horaria crítica:</strong> ' + topLabel(topHora) + ' (' + topValue(topHora).toLocaleString('es-AR') + ').</li>',
            '<li><strong>Tramo de investigación dominante:</strong> ' + topLabel(dias) + ' (' + topValue(dias).toLocaleString('es-AR') + ').</li>',
            '</ul></div></div>',
            '<div class="col-lg-6"><div class="border rounded p-3 h-100">',
            '<h6 class="mb-2">Foco territorial</h6>',
            '<ul class="mb-0">',
            '<li><strong>Departamento prioritario:</strong> ' + topLabel(dep) + '.</li>',
            '<li><strong>División con mayor carga:</strong> ' + topLabel(div) + '.</li>',
            '<li><strong>Barrio crítico:</strong> ' + topLabel(bar) + ' (' + topValue(bar).toLocaleString('es-AR') + ').</li>',
            '<li><strong>Localidad principal:</strong> ' + topLabel(topLoc) + '.</li>',
            '</ul></div></div>',
            '<div class="col-lg-6"><div class="border rounded p-3 h-100">',
            '<h6 class="mb-2">Evaluación de actuarios</h6>',
            '<ul class="mb-0">',
            '<li><strong>Actuario con mayor carga:</strong> ' + topLabel(act) + ' (' + topValue(act).toLocaleString('es-AR') + ').</li>',
            (actRisk.length ? actRisk.map(function (a) {
                var rec = a.pct >= 70
                    ? 'Seguimiento prioritario y posible redistribución.'
                    : (a.pct >= 50 ? 'Refuerzo operativo y control semanal.' : 'Desempeño estable; sostener trazabilidad.');
                return '<li><strong>' + a.label + ':</strong> ' + a.pendientes.toLocaleString('es-AR') + '/' + a.total.toLocaleString('es-AR') + ' sin resolver (' + a.pct.toFixed(1) + '%). ' + rec + '</li>';
            }).join('') : '<li>Sin datos suficientes para evaluar actuarios.</li>'),
            '</ul></div></div>',
            '<div class="col-12"><div class="border rounded p-3">',
            '<h6 class="mb-2">Coincidencias relevantes para investigación</h6>',
            '<div class="row g-3">',
            '<div class="col-lg-4"><strong>Investigados repetidos</strong><ul class="mb-0 mt-1">',
            (repInvest.length ? repInvest.map(function (x) { return '<li>' + x.label + ': ' + x.value.toLocaleString('es-AR') + '</li>'; }).join('') : '<li>Sin repeticiones detectadas.</li>'),
            '</ul></div>',
            '<div class="col-lg-4"><strong>Lugares recurrentes</strong><ul class="mb-0 mt-1">',
            (repLugar.length ? repLugar.map(function (x) { return '<li>' + x.label + ': ' + x.value.toLocaleString('es-AR') + '</li>'; }).join('') : '<li>Sin repeticiones relevantes.</li>'),
            '</ul></div>',
            '<div class="col-lg-4"><strong>Coincidencia investigado + lugar</strong><ul class="mb-0 mt-1">',
            (repInvLugar.length ? repInvLugar.map(function (x) { return '<li>' + x.label + ': ' + x.value.toLocaleString('es-AR') + '</li>'; }).join('') : '<li>Sin coincidencias repetidas.</li>'),
            '</ul></div></div></div></div>',
            '<div class="col-12"><div class="border rounded p-3">',
            '<h6 class="mb-2">Cobertura de campos (análisis completo)</h6>',
            '<p class="mb-2">Se analizaron todos los campos del dataset filtrado. Campos con menor completitud:</p>',
            '<ul class="mb-0">',
            (bajas.length ? bajas.map(function (x) {
                return '<li><strong>' + x.k + ':</strong> ' + x.pct.toFixed(1) + '% con dato.</li>';
            }).join('') : '<li>Sin observaciones de completitud.</li>'),
            '</ul></div></div>',
            '</div>',
            active.length ? '<p class="small text-muted mb-0"><strong>Selección de gráficos activa:</strong> ' + active.join(' | ') + '</p>' : ''
        ].join('');
    }

    function reportText(rows, state) {
        var total = rows.length;
        if (!total) return 'Sin datos para el filtro actual.';
        function topLabel(arr) { return (arr[0] && arr[0].label) ? arr[0].label : 'Sin dato'; }
        function topValue(arr) { return (arr[0] && arr[0].value) ? arr[0].value : 0; }
        var est = byCount(rows, function (r) { return r.estado; }, 5);
        var dep = byCount(rows, function (r) { return r.departamento; }, 5);
        var div = byCount(rows, function (r) { return r.division; }, 5);
        var bar = byCount(rows, function (r) { return r.barrio; }, 5);
        var act = byCount(rows, function (r) { return r.actuario; }, 5);
        var dias = byCount(rows, function (r) { return r.rango_dias; });
        var conCoords = rows.filter(function (r) { return r.coords === 'Con coordenadas'; }).length;
        var conInv = rows.filter(function (r) { return r.investigados === 'Con investigados'; }).length;
        var conAlla = rows.filter(function (r) { return r.allanamiento === 'Con allanamiento'; }).length;
        var desest = rows.filter(function (r) { return r.desestimada === 'Desestimada'; }).length;

        var actRows = rows.filter(function (r) { return r.actuario !== 'Sin actuario'; });
        var unresolvedByAct = Object.create(null);
        var totalByAct = Object.create(null);
        var sumDaysByAct = Object.create(null);
        var cntDaysByAct = Object.create(null);
        actRows.forEach(function (r) {
            totalByAct[r.actuario] = (totalByAct[r.actuario] || 0) + 1;
            if (r.estado_pendiente) unresolvedByAct[r.actuario] = (unresolvedByAct[r.actuario] || 0) + 1;
            if (typeof r.dias_investigacion === 'number') {
                sumDaysByAct[r.actuario] = (sumDaysByAct[r.actuario] || 0) + r.dias_investigacion;
                cntDaysByAct[r.actuario] = (cntDaysByAct[r.actuario] || 0) + 1;
            }
        });
        var actRisk = Object.keys(totalByAct).map(function (a) {
            var tot = totalByAct[a] || 0;
            var pend = unresolvedByAct[a] || 0;
            var pct = tot ? (100 * pend / tot) : 0;
            var avg = (cntDaysByAct[a] || 0) ? (sumDaysByAct[a] / cntDaysByAct[a]) : 0;
            return { label: a, total: tot, pendientes: pend, pct: pct, avgDias: avg };
        }).sort(function (x, y) { return y.total - x.total || y.avgDias - x.avgDias; }).slice(0, 10);

        var active = [];
        Object.keys(state).forEach(function (k) { if (state[k]) active.push(k + ': ' + state[k]); });
        var topMes = byCount(rows, function (r) { return r.mes; }, 5);
        var topDia = byCount(rows, function (r) { return r.dia; }, 5);
        var topHora = byCount(rows, function (r) { return r.hora; }, 8);
        var topLoc = byCount(rows, function (r) { return r.localidad_simple; }, 5);
        var lines = [];
        lines.push('INFORME ANALITICO - DENUNCIAS WEB');
        lines.push('Fecha: ' + new Date().toLocaleString('es-AR'));
        lines.push('');
        lines.push('RESUMEN');
        lines.push('- Total analizado: ' + total.toLocaleString('es-AR'));
        lines.push('- Estado predominante: ' + topLabel(est) + ' (' + topValue(est).toLocaleString('es-AR') + ')');
        lines.push('- Foco territorial: ' + topLabel(dep) + ' / ' + topLabel(div));
        lines.push('- Zona critica: ' + topLabel(bar));
        lines.push('- Actuario con mayor carga: ' + topLabel(act));
        lines.push('- Tramo de antiguedad dominante: ' + topLabel(dias) + ' (' + topValue(dias).toLocaleString('es-AR') + ')');
        lines.push('- Mes de mayor incidencia: ' + topLabel(topMes) + ' (' + topValue(topMes).toLocaleString('es-AR') + ')');
        lines.push('- Dia de mayor incidencia: ' + topLabel(topDia) + ' (' + topValue(topDia).toLocaleString('es-AR') + ')');
        lines.push('- Hora de mayor incidencia: ' + topLabel(topHora) + ' (' + topValue(topHora).toLocaleString('es-AR') + ')');
        lines.push('- Localidad principal: ' + topLabel(topLoc));
        lines.push('- Cobertura georreferenciada: ' + conCoords.toLocaleString('es-AR') + ' (' + (100 * conCoords / total).toFixed(1) + '%)');
        lines.push('- Con investigados: ' + conInv.toLocaleString('es-AR') + ' (' + (100 * conInv / total).toFixed(1) + '%)');
        lines.push('- Con allanamiento: ' + conAlla.toLocaleString('es-AR') + ' | Desestimadas: ' + desest.toLocaleString('es-AR'));
        lines.push('');
        lines.push('RANKING DE ACTUARIOS (carga y antiguedad promedio)');
        if (!actRisk.length) {
            lines.push('- Sin datos suficientes.');
        } else {
            actRisk.forEach(function (a, idx) {
                lines.push(
                    (idx + 1) + '. ' + a.label +
                    ' | Carga: ' + a.total.toLocaleString('es-AR') +
                    ' | Sin resolver: ' + a.pendientes.toLocaleString('es-AR') + ' (' + a.pct.toFixed(1) + '%)' +
                    ' | Antiguedad prom.: ' + a.avgDias.toFixed(1) + ' dias'
                );
            });
        }
        if (active.length) {
            lines.push('');
            lines.push('SELECCION GRAFICOS ACTIVA');
            lines.push(active.join(' | '));
        }
        return lines.join('\n');
    }

    function reportHtmlForPdf(rows, state) {
        var now = new Date().toLocaleString('es-AR');
        var body = reportHtml(rows, state);
        return [
            '<!doctype html><html><head><meta charset="utf-8"><title>Informe Analitico Denuncias Web</title>',
            '<style>',
            '@page { size: A4; margin: 18mm; }',
            'body{font-family: Arial, sans-serif; color:#1f2937; font-size:12px;}',
            '.head{border-bottom:2px solid #1d4ed8; padding-bottom:8px; margin-bottom:12px;}',
            '.title{font-size:18px; font-weight:700; color:#1d4ed8;}',
            '.sub{font-size:11px; color:#4b5563;}',
            '.note{margin-top:10px; font-size:11px; color:#374151;}',
            '.row{display:flex; flex-wrap:wrap; gap:12px;} .col-lg-6{width:48%;} .col-12{width:100%;} .col-lg-4{width:31%;}',
            '.border{border:1px solid #d1d5db;} .rounded{border-radius:6px;} .p-3{padding:10px;} .h-100{height:100%;}',
            'h6{margin:0 0 6px 0; font-size:13px;} ul{margin:0; padding-left:16px;} li{margin:0 0 4px;} p{margin:0 0 6px;}',
            '.small{font-size:10px;} .text-muted{color:#6b7280;}',
            '</style></head><body>',
            '<div class="head"><div class="title">SIOC - Informe Analitico de Denuncias Web</div>',
            '<div class="sub">Generado: ' + now + '</div>',
            '<div class="sub">Fuente: filtros actuales y selecciones activas de graficos</div></div>',
            body,
            '<p class="note"><strong>Uso sugerido:</strong> este informe esta disenado para seguimiento operativo con jefaturas, priorizacion territorial y evaluacion de desempeno por personal actuante.</p>',
            '</body></html>'
        ].join('');
    }

    function downloadTextFile(filename, text, mimeType) {
        var blob = new Blob([text], { type: mimeType || 'text/plain;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function toCsv(rows) {
        if (!rows.length) return 'sin_datos\n';
        var headers = Object.keys(rows[0].raw || {});
        var out = [headers.join(',')];
        rows.forEach(function (r) {
            var vals = headers.map(function (h) {
                var v = (r.raw || {})[h];
                if (v === null || v === undefined) v = '';
                var s = String(v).replace(/"/g, '""');
                return '"' + s + '"';
            });
            out.push(vals.join(','));
        });
        return out.join('\n');
    }

    function makeRows(rowsRaw) {
        var now = new Date();
        return (rowsRaw || []).map(function (r) {
            var fInicio = parseIsoDate(r.fecha_denuncia || r.fecha_apertura || r.fecha_recepcion);
            var dias = fInicio ? Math.max(0, Math.floor((now.getTime() - fInicio.getTime()) / 86400000)) : null;
            return {
                mes: monthLabelEs(r.fecha_denuncia || r.fecha_apertura),
                dia: dayLabelEs(r.fecha_denuncia || r.fecha_apertura),
                hora: hourLabel(r.fecha_recepcion, r.fecha_denuncia || r.fecha_apertura),
                estado: String(r.causa_estado || '').trim() || 'Sin estado',
                barrio: (String(r.barrio || '').trim() || 'Sin barrio') + ' (' + (String(r.localidad || '').trim() || 'Sin localidad') + ')',
                departamento: String(r.departamento || r.desc_dep_padre || '').trim() || 'Sin departamento',
                division: String(r.division || r.desc_dep_registro || '').trim() || 'Sin división',
                dep_actuario: String(r.dep_actuario || r.desc_dep_actuario || '').trim() || 'Sin dependencia actuario',
                localidad_simple: String(r.localidad || '').trim() || 'Sin localidad',
                actuario: toActuario(r.actuario_grado, r.actuario_apenom),
                coords: (typeof r.latitud === 'number' && typeof r.longitud === 'number') ? 'Con coordenadas' : 'Sin coordenadas',
                investigados: String(r.investigados || '').trim() ? 'Con investigados' : 'Sin investigados',
                investigados_texto: String(r.investigados || '').trim(),
                allanamiento: String(r.fecha_sol_allanamiento || '').trim() ? 'Con allanamiento' : 'Sin allanamiento',
                desestimada: String(r.fecha_desestimada || '').trim() ? 'Desestimada' : 'No desestimada',
                dias_investigacion: dias,
                rango_dias: daysRangeLabel(dias),
                estado_pendiente: isUnresolvedEstado(r.causa_estado),
                raw: r
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
            allanamiento: '', desestimada: '', rango_dias: ''
        };
        var displayMode = 'cantidad';
        var lastFilteredRows = [];

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
            lastFilteredRows = rows.slice();
            setText('ad-kpi-total', rows.length);
            setText('ad-kpi-concoords', rows.filter(function (r) { return r.coords === 'Con coordenadas'; }).length);
            setText('ad-kpi-sincoords', rows.filter(function (r) { return r.coords === 'Sin coordenadas'; }).length);
            setText('ad-kpi-allanamiento', rows.filter(function (r) { return r.allanamiento === 'Con allanamiento'; }).length);
            setText('ad-kpi-desestimadas', rows.filter(function (r) { return r.desestimada === 'Desestimada'; }).length);
            setText('ad-kpi-investigados', rows.filter(function (r) { return r.investigados === 'Con investigados'; }).length);

            var mes = byCount(rows, function (r) { return r.mes; });
            plotBar('ad-chart-mes', mes.map(function (x) { return x.label; }), mes.map(function (x) { return x.value; }), '#198754', function (x) { toggle('mes', x); }, displayMode);
            var dia = byCount(rows, function (r) { return r.dia; });
            plotBar('ad-chart-dia', dia.map(function (x) { return x.label; }), dia.map(function (x) { return x.value; }), '#0d6efd', function (x) { toggle('dia', x); }, displayMode);
            var hora = byCount(rows, function (r) { return r.hora; });
            plotBar('ad-chart-hora', hora.map(function (x) { return x.label; }), hora.map(function (x) { return x.value; }), '#6f42c1', function (x) { toggle('hora', x); }, displayMode);
            var edad = byCount(rows, function (r) { return r.rango_dias; });
            plotBar('ad-chart-dias-investigacion', edad.map(function (x) { return x.label; }), edad.map(function (x) { return x.value; }), '#dc3545', function (x) { toggle('rango_dias', x); }, displayMode);
            var est = byCount(rows, function (r) { return r.estado; });
            plotBar('ad-chart-estado', est.map(function (x) { return x.label; }), est.map(function (x) { return x.value; }), '#fd7e14', function (x) { toggle('estado', x); }, displayMode);
            var bar = byCount(rows, function (r) { return r.barrio; }, 30);
            plotBar('ad-chart-barrio', bar.map(function (x) { return x.label; }), bar.map(function (x) { return x.value; }), '#7952b3', function (x) { toggle('barrio', x); }, displayMode);
            var dep = byCount(rows, function (r) { return r.departamento; });
            plotBar('ad-chart-departamento', dep.map(function (x) { return x.label; }), dep.map(function (x) { return x.value; }), '#198754', function (x) { toggle('departamento', x); }, displayMode);
            var div = byCount(rows, function (r) { return r.division; }, 25);
            plotBar('ad-chart-division', div.map(function (x) { return x.label; }), div.map(function (x) { return x.value; }), '#0dcaf0', function (x) { toggle('division', x); }, displayMode);
            var dact = byCount(rows, function (r) { return r.dep_actuario; }, 25);
            plotBar('ad-chart-dep-actuario', dact.map(function (x) { return x.label; }), dact.map(function (x) { return x.value; }), '#20c997', function (x) { toggle('dep_actuario', x); }, displayMode);
            var act = byCount(rows, function (r) { return r.actuario; }, 30);
            plotBar('ad-chart-actuario', act.map(function (x) { return x.label; }), act.map(function (x) { return x.value; }), '#6610f2', function (x) { toggle('actuario', x); }, displayMode);

            var c1 = byCount(rows, function (r) { return r.coords; });
            plotPie('ad-chart-coords', c1.map(function (x) { return x.label; }), c1.map(function (x) { return x.value; }), function (x) { toggle('coords', x); }, displayMode);
            var c2 = byCount(rows, function (r) { return r.investigados; });
            plotPie('ad-chart-investigados', c2.map(function (x) { return x.label; }), c2.map(function (x) { return x.value; }), function (x) { toggle('investigados', x); }, displayMode);
            var c3 = byCount(rows, function (r) { return r.allanamiento; });
            plotPie('ad-chart-allanamiento', c3.map(function (x) { return x.label; }), c3.map(function (x) { return x.value; }), function (x) { toggle('allanamiento', x); }, displayMode);
            var c4 = byCount(rows, function (r) { return r.desestimada; });
            plotPie('ad-chart-desestimada', c4.map(function (x) { return x.label; }), c4.map(function (x) { return x.value; }), function (x) { toggle('desestimada', x); }, displayMode);

            renderActiveInfo(state);
            var rep = document.getElementById('ad-ai-report');
            if (rep) rep.innerHTML = reportHtml(rows, state);
        }

        var btnClear = document.getElementById('ad-clear-chart-filters');
        if (btnClear) {
            btnClear.addEventListener('click', function () {
                Object.keys(state).forEach(function (k) { state[k] = ''; });
                renderAll();
            });
        }
        document.querySelectorAll('input[name="ad-chart-mode"]').forEach(function (rb) {
            rb.addEventListener('change', function () {
                displayMode = this.value || 'cantidad';
                renderAll();
            });
        });
        var btnExportTxt = document.getElementById('ad-export-report-txt');
        if (btnExportTxt) {
            btnExportTxt.addEventListener('click', function () {
                var text = reportText(lastFilteredRows, state);
                downloadTextFile('analisis_denuncias_informe.txt', text, 'text/plain;charset=utf-8');
            });
        }
        var btnExportCsv = document.getElementById('ad-export-report-csv');
        if (btnExportCsv) {
            btnExportCsv.addEventListener('click', function () {
                var csv = toCsv(lastFilteredRows);
                downloadTextFile('analisis_denuncias_analisis_filtrado.csv', csv, 'text/csv;charset=utf-8');
            });
        }
        var btnExportPdf = document.getElementById('ad-export-report-pdf');
        if (btnExportPdf) {
            btnExportPdf.addEventListener('click', function () {
                var html = reportHtmlForPdf(lastFilteredRows, state);
                var w = window.open('', '_blank');
                if (!w) return;
                w.document.open();
                w.document.write(html);
                w.document.close();
                w.focus();
                setTimeout(function () { w.print(); }, 250);
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

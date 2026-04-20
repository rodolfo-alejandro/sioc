(function () {
    'use strict';

    var graphState = null;
    var lastInformeData = null;
    var patronesState = { loaded: false, data: null };
    var TAB_STORAGE_KEY = 'sabana_relaciones_active_tab';
    var relContext = {
        tipo: 'VOZ',
        label: 'VOZ',
        apiInforme: null,
        informeSabana: true,
    };

    function parseRelacionesFromDom() {
        var el = document.getElementById('relaciones-data');
        if (!el) return [];
        try {
            var txt = el.textContent || el.innerText || '[]';
            var data = JSON.parse(txt);
            if (Array.isArray(data)) return data;
        } catch (e) {
            console.error('Error parseando relaciones-data', e);
        }
        return [];
    }

    function parseMetaFromDom() {
        var el = document.getElementById('relaciones-meta');
        if (!el) return {};
        try {
            var txt = el.textContent || el.innerText || '{}';
            var data = JSON.parse(txt);
            return data || {};
        } catch (e) {
            console.error('Error parseando relaciones-meta', e);
            return {};
        }
    }

    function buildGraph(relaciones, opts) {
        opts = opts || {};
        var avatarSizeBonus = typeof opts.avatarSizeBonus === 'number' ? opts.avatarSizeBonus : 6;
        var nodeScale = typeof opts.nodeScale === 'number' && opts.nodeScale > 0 ? opts.nodeScale : 1;
        var edgeLabelFontSize = typeof opts.edgeLabelFontSize === 'number' && opts.edgeLabelFontSize > 0 ? opts.edgeLabelFontSize : 10;
        var edgeMin = typeof opts.edgeMin === 'number' && opts.edgeMin > 0 ? opts.edgeMin : 1;
        var container = document.getElementById('relaciones-graph');
        if (!container) return;

        var width = container.clientWidth || 800;
        // Altura responsive basada en el contenedor real (evita recortes con overflow:hidden)
        var height = container.clientHeight || Math.max(260, Math.min(480, Math.round(width * 0.62)));
        height = Math.max(260, Math.min(560, height));
        var padding = 36;

        // Construir nodos y links a partir de relaciones
        var nodesMap = Object.create(null);
        var links = [];
        var maxCantidad = 0;

        (relaciones || []).forEach(function (r) {
            if (!r || !r.numero_a || !r.numero_b) return;
            var cant = parseInt(r.cantidad || 0, 10) || 0;
            if (cant < edgeMin) return;
            var a = String(r.numero_a);
            var b = String(r.numero_b);
            if (!nodesMap[a]) nodesMap[a] = { id: a, label: a, degree: 0, sujeto: r.sujeto_a || null };
            else if (!nodesMap[a].sujeto && r.sujeto_a) nodesMap[a].sujeto = r.sujeto_a;
            if (!nodesMap[b]) nodesMap[b] = { id: b, label: b, degree: 0, sujeto: r.sujeto_b || null };
            else if (!nodesMap[b].sujeto && r.sujeto_b) nodesMap[b].sujeto = r.sujeto_b;
            nodesMap[a].degree += 1;
            nodesMap[b].degree += 1;
            if (cant > maxCantidad) maxCantidad = cant;
            links.push({ source: a, target: b, cantidad: cant });
        });

        var nodes = Object.keys(nodesMap).map(function (k) { return nodesMap[k]; });
        if (!nodes.length) {
            container.innerHTML = '<p class="text-muted mb-0">No hay datos suficientes para dibujar el grafo con el umbral actual (>= ' + edgeMin + ').</p>';
            return;
        }

        // Disposición simple en círculo (ajuste de radio para que TODOS los nodos entren)
        var cx = width / 2;
        var cy = height / 2;
        // Calcular radios de nodos según grado (esto define el margen real para que no se corte)
        var maxDegree = nodes.reduce(function (m, n) { return Math.max(m, n.degree || 0); }, 0);

        function nodeRadius(deg) {
            if (maxDegree <= 0) return 8;
            return 8 + (deg / maxDegree) * 10;
        }

        // Radio disponible descontando padding y el tamaño máximo de nodo (incluye avatares)
        var maxNodeR = (nodeRadius(maxDegree) + (avatarSizeBonus || 0)) * nodeScale;
        var margin = padding + maxNodeR + 6;
        var radius = Math.max(80, Math.min(width, height) / 2 - margin);
        // Si por algún motivo queda demasiado pequeño, forzar un mínimo para que el grafo no colapse
        if (!isFinite(radius) || radius < 10) radius = 120;

        nodes.forEach(function (n, idx) {
            var angle = (2 * Math.PI * idx) / nodes.length;
            n.x = cx + radius * Math.cos(angle);
            n.y = cy + radius * Math.sin(angle);
        });

        function linkWidth(cant) {
            if (maxCantidad <= 0) return 1;
            return 1 + (cant / maxCantidad) * 4;
        }

        // Crear SVG
        var svgNS = 'http://www.w3.org/2000/svg';
        var svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('width', width);
        svg.setAttribute('height', height);
        svg.classList.add('w-100');

        var defs = document.createElementNS(svgNS, 'defs');
        svg.appendChild(defs);

        // Fondo
        var bg = document.createElementNS(svgNS, 'rect');
        bg.setAttribute('x', '0');
        bg.setAttribute('y', '0');
        bg.setAttribute('width', width);
        bg.setAttribute('height', height);
        bg.setAttribute('fill', '#ffffff');
        svg.appendChild(bg);

        // Dibujar aristas
        links.forEach(function (l) {
            var a = nodesMap[l.source];
            var b = nodesMap[l.target];
            if (!a || !b) return;
            var line = document.createElementNS(svgNS, 'line');
            line.setAttribute('x1', a.x);
            line.setAttribute('y1', a.y);
            line.setAttribute('x2', b.x);
            line.setAttribute('y2', b.y);
            line.setAttribute('stroke', '#ced4da');
            line.setAttribute('stroke-width', linkWidth(l.cantidad));
            line.setAttribute('stroke-linecap', 'round');
            line.setAttribute('data-source', a.id);
            line.setAttribute('data-target', b.id);
            line.setAttribute('data-cantidad', String(l.cantidad));
            line.appendChild(createTitle(svgNS, a.id + ' ↔ ' + b.id + ' (' + l.cantidad + (relContext.tipo === 'GPRS' ? ' accesos)' : ' llamadas)')));
            svg.appendChild(line);

            // Etiqueta con cantidad de llamadas en el medio de la arista (se actualiza al arrastrar)
            if (l.cantidad && l.cantidad > 0) {
                var midX = (a.x + b.x) / 2;
                var midY = (a.y + b.y) / 2;
                var t = document.createElementNS(svgNS, 'text');
                t.setAttribute('x', midX);
                t.setAttribute('y', midY - 4);
                t.setAttribute('text-anchor', 'middle');
                t.setAttribute('font-size', String(edgeLabelFontSize));
                t.setAttribute('fill', '#6c757d');
                t.setAttribute('font-weight', 'bold');
                t.setAttribute('data-edge-label', '1');
                t.setAttribute('data-source', a.id);
                t.setAttribute('data-target', b.id);
                t.textContent = String(l.cantidad);
                svg.appendChild(t);
            }
        });

        // Dibujar nodos (grupo con transform para que etiqueta y nodo se muevan juntos)
        nodes.forEach(function (n) {
            var group = document.createElementNS(svgNS, 'g');
            group.setAttribute('class', 'rel-node');
            group.setAttribute('data-id', n.id);
            group.setAttribute('transform', 'translate(' + n.x + ',' + n.y + ')');

            var rNode = (nodeRadius(n.degree) + (n.sujeto ? avatarSizeBonus : 0)) * nodeScale;
            n._baseR = rNode;
            n._rNode = rNode;

            // Imagen dentro del nodo (clip circle relativo a la imagen para que siempre se vea)
            if (n.sujeto && n.sujeto.imagen_url) {
                var clipId = 'rel-clip-' + n.id.replace(/[^a-zA-Z0-9_-]/g, '_');
                var clip = document.createElementNS(svgNS, 'clipPath');
                clip.setAttribute('id', clipId);
                clip.setAttribute('clipPathUnits', 'objectBoundingBox');
                var clipCircle = document.createElementNS(svgNS, 'circle');
                clipCircle.setAttribute('cx', '0.5');
                clipCircle.setAttribute('cy', '0.5');
                clipCircle.setAttribute('r', '0.5');
                clip.appendChild(clipCircle);
                svg.querySelector('defs').appendChild(clip);

                var img = document.createElementNS(svgNS, 'image');
                img.setAttributeNS('http://www.w3.org/1999/xlink', 'href', n.sujeto.imagen_url || '');
                img.setAttribute('x', -rNode);
                img.setAttribute('y', -rNode);
                img.setAttribute('width', rNode * 2);
                img.setAttribute('height', rNode * 2);
                img.setAttribute('preserveAspectRatio', 'xMidYMid slice');
                img.setAttribute('clip-path', 'url(#' + clipId + ')');
                group.appendChild(img);
                group.setAttribute('data-clip-id', clipId);
            }

            var circle = document.createElementNS(svgNS, 'circle');
            circle.setAttribute('cx', 0);
            circle.setAttribute('cy', 0);
            circle.setAttribute('r', rNode);
            if (n.sujeto && n.sujeto.imagen_url) {
                circle.setAttribute('fill', '#fff');
                circle.setAttribute('fill-opacity', '0.001');
            } else {
                circle.setAttribute('fill', '#0d6efd');
            }
            circle.setAttribute('stroke', '#ffffff');
            circle.setAttribute('stroke-width', '2');
            circle.setAttribute('pointer-events', 'all');
            group.appendChild(circle);

            var titleLabel = n.id;
            if (n.sujeto && n.sujeto.display) {
                titleLabel = n.id + ' - ' + n.sujeto.display;
            }
            var titleEl = createTitle(svgNS, titleLabel + ' (' + n.degree + ' relaciones)');
            titleEl.setAttribute('pointer-events', 'none');
            group.appendChild(titleEl);

            var text = document.createElementNS(svgNS, 'text');
            text.setAttribute('x', 0);
            text.setAttribute('y', rNode + 16);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('font-size', '11');
            text.setAttribute('fill', '#212529');
            text.setAttribute('pointer-events', 'none');
            if (n.sujeto && n.sujeto.display) {
                text.textContent = n.sujeto.display + ' (' + n.id + ')';
            } else {
                text.textContent = n.id;
            }
            group.appendChild(text);

            svg.appendChild(group);
        });

        container.innerHTML = '';
        container.appendChild(svg);

        function applyNodeScale(svgEl, node, scale) {
            var newR = node._baseR * scale;
            node._rNode = newR;
            var groups = svgEl.querySelectorAll('.rel-node');
            for (var i = 0; i < groups.length; i++) {
                if (groups[i].getAttribute('data-id') !== node.id) continue;
                var circle = groups[i].querySelector('circle');
                if (circle) circle.setAttribute('r', newR);
                var img = groups[i].querySelector('image');
                if (img) {
                    img.setAttribute('x', -newR);
                    img.setAttribute('y', -newR);
                    img.setAttribute('width', newR * 2);
                    img.setAttribute('height', newR * 2);
                }
                var text = groups[i].querySelector('text');
                if (text) text.setAttribute('y', newR + 16);
                break;
            }
        }

        // Guardar estado global para drag, escalado por nodo, etc.
        graphState = {
            svg: svg,
            nodesMap: nodesMap,
            nodeScaleByNode: graphState && graphState.nodeScaleByNode ? graphState.nodeScaleByNode : {},
            selectedNodeId: (graphState && graphState.selectedNodeId) || null
        };

        // Aplicar escala individual por nodo si existe
        Object.keys(graphState.nodeScaleByNode).forEach(function (id) {
            var scale = graphState.nodeScaleByNode[id];
            if (scale && scale !== 1 && nodesMap[id]) {
                applyNodeScale(svg, nodesMap[id], scale);
            }
        });

        // Resaltar al hacer click en un nodo
        container.addEventListener('click', function (ev) {
            var g = ev.target.closest('.rel-node');
            if (!g) return;
            var id = g.getAttribute('data-id');
            if (!id) return;
            graphState.selectedNodeId = id;
            highlightNode(svg, id);
            highlightRowsForNode(id);
        });

        // Doble clic: agrandar/reducir este nodo (1 → 1.5 → 2 → 1)
        container.addEventListener('dblclick', function (ev) {
            var g = ev.target.closest('.rel-node');
            if (!g || !graphState || !graphState.nodesMap) return;
            var id = g.getAttribute('data-id');
            if (!id) return;
            ev.preventDefault();
            var n = graphState.nodesMap[id];
            if (!n) return;
            var scales = [1, 1.5, 2];
            var current = graphState.nodeScaleByNode[id] || 1;
            var idx = scales.indexOf(current);
            if (idx === -1) idx = 0;
            var next = scales[(idx + 1) % scales.length];
            graphState.nodeScaleByNode[id] = next;
            applyNodeScale(graphState.svg, n, next);
        });

        // Doble tap en touch (equivalente a dblclick, pero confiable en móviles)
        var lastTap = { time: 0, nodeId: null };
        container.addEventListener('pointerup', function (ev) {
            if (!ev || ev.pointerType !== 'touch') return;
            var g = ev.target.closest('.rel-node');
            if (!g || !graphState || !graphState.nodesMap) return;
            var id = g.getAttribute('data-id');
            if (!id) return;

            // No escalar si el drag se movió (para no chocar con el arrastre)
            if (drag && drag.active && drag.moved) return;

            var now = Date.now();
            var dt = now - (lastTap.time || 0);
            if (lastTap.nodeId === id && dt > 0 && dt < 320) {
                ev.preventDefault();
                ev.stopPropagation();
                var n = graphState.nodesMap[id];
                if (!n) return;
                var scales = [1, 1.5, 2];
                var current = graphState.nodeScaleByNode[id] || 1;
                var idx = scales.indexOf(current);
                if (idx === -1) idx = 0;
                var next = scales[(idx + 1) % scales.length];
                graphState.nodeScaleByNode[id] = next;
                applyNodeScale(graphState.svg, n, next);
            }
            lastTap = { time: now, nodeId: id };
        });

        // Soporte de arrastre simple de nodos
        var drag = { active: false, nodeId: null, pointerId: null, startX: 0, startY: 0, moved: false };
        try { svg.style.touchAction = 'none'; } catch (eTA) {}

        svg.addEventListener('pointerdown', function (ev) {
            if (!ev) return;
            var g = ev.target.closest('.rel-node');

            var nodeId = null;
            if (g) {
                nodeId = g.getAttribute('data-id');
            } else {
                // Permitir arrastrar iniciando desde una línea o etiqueta de arista:
                // si el usuario toca una línea (visible aunque el nodo esté parcialmente fuera),
                // movemos el nodo más cercano a ese punto.
                var elEp = ev.target.closest('[data-source][data-target]');
                if (elEp && elEp.getAttribute('data-source') && elEp.getAttribute('data-target')) {
                    var aId = elEp.getAttribute('data-source');
                    var bId = elEp.getAttribute('data-target');
                    var rect = svg.getBoundingClientRect();
                    var localX = ev.clientX - rect.left;
                    var localY = ev.clientY - rect.top;
                    var aNode = graphState.nodesMap[aId];
                    var bNode = graphState.nodesMap[bId];
                    if (aNode && bNode) {
                        var da = Math.hypot(localX - aNode.x, localY - aNode.y);
                        var db = Math.hypot(localX - bNode.x, localY - bNode.y);
                        nodeId = da <= db ? aId : bId;
                    } else {
                        nodeId = graphState.nodesMap[aId] ? aId : (graphState.nodesMap[bId] ? bId : null);
                    }
                }
            }

            if (!nodeId) return;
            ev.preventDefault();

            if (!graphState || !graphState.nodesMap[nodeId]) return;

            drag.active = true;
            drag.nodeId = nodeId;
            drag.pointerId = ev.pointerId;
            drag.moved = false;
            drag.startX = ev.clientX;
            drag.startY = ev.clientY;

            try { svg.setPointerCapture(ev.pointerId); } catch (eCap) {}
        });

        svg.addEventListener('pointermove', function (ev) {
            if (!ev) return;
            if (!drag.active || !graphState || !graphState.nodesMap[drag.nodeId]) return;
            if (drag.pointerId != null && ev.pointerId !== drag.pointerId) return;
            ev.preventDefault();

            var n = graphState.nodesMap[drag.nodeId];
            var dx = ev.clientX - drag.startX;
            var dy = ev.clientY - drag.startY;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;

            n.x = n.x + dx;
            n.y = n.y + dy;
            drag.startX = ev.clientX;
            drag.startY = ev.clientY;

            // Mover todo el grupo (nodo + etiqueta) con transform
            svg.querySelectorAll('.rel-node').forEach(function (g) {
                if (g.getAttribute('data-id') !== drag.nodeId) return;
                g.setAttribute('transform', 'translate(' + n.x + ',' + n.y + ')');
            });

            // Líneas y etiquetas de arista
            svg.querySelectorAll('line').forEach(function (l) {
                var aId = l.getAttribute('data-source');
                var bId = l.getAttribute('data-target');
                if (aId === drag.nodeId) {
                    l.setAttribute('x1', n.x);
                    l.setAttribute('y1', n.y);
                }
                if (bId === drag.nodeId) {
                    l.setAttribute('x2', n.x);
                    l.setAttribute('y2', n.y);
                }
                var next = l.nextElementSibling;
                if (next && next.getAttribute('data-edge-label') === '1') {
                    var x1 = parseFloat(l.getAttribute('x1'));
                    var y1 = parseFloat(l.getAttribute('y1'));
                    var x2 = parseFloat(l.getAttribute('x2'));
                    var y2 = parseFloat(l.getAttribute('y2'));
                    next.setAttribute('x', (x1 + x2) / 2);
                    next.setAttribute('y', (y1 + y2) / 2 - 4);
                }
            });
        });

        function endDrag(ev) {
            if (drag.pointerId != null && ev && ev.pointerId !== drag.pointerId) return;
            drag.active = false;
            drag.nodeId = null;
            drag.pointerId = null;
        }
        svg.addEventListener('pointerup', endDrag);
        svg.addEventListener('pointercancel', endDrag);
        svg.addEventListener('pointerleave', endDrag);
    }

    function createTitle(svgNS, text) {
        var title = document.createElementNS(svgNS, 'title');
        title.textContent = text;
        return title;
    }

    function highlightNode(svg, nodeId) {
        if (!svg) return;
        // Quitar destacados previos
        svg.querySelectorAll('.rel-node').forEach(function (g) {
            var circle = g.querySelector('circle');
            if (!circle) return;
            var hasImg = !!g.querySelector('image');
            if (hasImg) {
                circle.setAttribute('fill', '#fff');
                circle.setAttribute('fill-opacity', '0.001');
                circle.setAttribute('stroke', '#ffffff');
                circle.setAttribute('stroke-width', '2');
            } else {
                // Nodo sin avatar: círculo azul sólido
                circle.setAttribute('fill', '#0d6efd');
                circle.setAttribute('stroke', '#ffffff');
                circle.setAttribute('stroke-width', '2');
            }
            circle.setAttribute('opacity', '1');
        });
        var showAllLines = document.getElementById('relaciones-toggle-all-lines') && document.getElementById('relaciones-toggle-all-lines').checked;
        svg.querySelectorAll('line').forEach(function (l) {
            l.setAttribute('stroke', '#ced4da');
            l.setAttribute('opacity', showAllLines ? '1' : '0.7');
        });

        // Destacar el seleccionado
        svg.querySelectorAll('.rel-node').forEach(function (g) {
            var id = g.getAttribute('data-id');
            var circle = g.querySelector('circle');
            if (!circle) return;
            var hasImg = !!g.querySelector('image');
            if (id === nodeId) {
                if (hasImg) {
                    circle.setAttribute('stroke', '#dc3545');
                    circle.setAttribute('stroke-width', '4');
                    circle.setAttribute('fill', '#fff');
                    circle.setAttribute('fill-opacity', '0.001');
                } else {
                    circle.setAttribute('fill', '#dc3545');
                    circle.setAttribute('stroke', '#ffffff');
                    circle.setAttribute('stroke-width', '2');
                }
                circle.setAttribute('opacity', '1');
            } else {
                circle.setAttribute('opacity', nodeId ? '0.4' : '1');
            }
        });

        svg.querySelectorAll('line').forEach(function (l) {
            var a = l.getAttribute('data-source');
            var b = l.getAttribute('data-target');
            if (showAllLines) {
                // Ver todas las líneas: todas visibles y del mismo color
                l.setAttribute('stroke', '#0d6efd');
                l.setAttribute('opacity', '1');
            } else {
                if (!nodeId) {
                    l.setAttribute('stroke', '#ced4da');
                    l.setAttribute('opacity', '0.7');
                    return;
                }
                if (a === nodeId || b === nodeId) {
                    l.setAttribute('stroke', '#0d6efd');
                    l.setAttribute('opacity', '1');
                } else {
                    l.setAttribute('opacity', '0.2');
                }
            }
        });
    }

    function highlightRowsForNode(nodeId) {
        var table = document.getElementById('relaciones-table');
        if (!table) return;
        var rows = table.querySelectorAll('tbody tr');
        rows.forEach(function (row) {
            row.classList.remove('rel-row-highlight');
            var aCell = row.querySelector('td[data-role="num-a"]');
            var bCell = row.querySelector('td[data-role="num-b"]');
            var a = (aCell && aCell.getAttribute('data-numero')) || (aCell ? (aCell.textContent || '').trim() : '');
            var b = (bCell && bCell.getAttribute('data-numero')) || (bCell ? (bCell.textContent || '').trim() : '');
            if (String(a) === String(nodeId) || String(b) === String(nodeId)) {
                row.classList.add('rel-row-highlight');
            }
        });
    }

    function initTableSearch() {
        var input = document.getElementById('relaciones-table-search');
        if (!input) return;
        var table = document.getElementById('relaciones-table');
        if (!table) return;
        input.addEventListener('input', function () {
            var q = (this.value || '').toLowerCase().trim();
            var rows = table.querySelectorAll('tbody tr');
            rows.forEach(function (row) {
                var txt = (row.textContent || '').toLowerCase();
                row.style.display = (!q || txt.indexOf(q) !== -1) ? '' : 'none';
            });
        });
    }

    function initFullscreenToggle() {
        var btn = document.getElementById('btn-relaciones-fullscreen');
        var wrap = document.getElementById('relaciones-graph-wrap');
        if (!btn || !wrap) return;
        btn.addEventListener('click', function () {
            var isFs = wrap.classList.toggle('relaciones-graph-fullscreen');
            if (isFs) {
                btn.innerHTML = '<i class="bi bi-fullscreen-exit"></i> Salir de pantalla completa';
            } else {
                btn.innerHTML = '<i class="bi bi-arrows-fullscreen"></i> Pantalla completa';
            }
        });

        // Permitir salir con ESC
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && wrap.classList.contains('relaciones-graph-fullscreen')) {
                wrap.classList.remove('relaciones-graph-fullscreen');
                btn.innerHTML = '<i class="bi bi-arrows-fullscreen"></i> Pantalla completa';
            }
        });
    }

    function getGraphOpts() {
        var scaleEl = document.getElementById('relaciones-node-scale');
        var avatarEl = document.getElementById('relaciones-avatar-size');
        var edgeLabelEl = document.getElementById('relaciones-edge-label-size');
        var edgeMinEl = document.getElementById('relaciones-edge-min');
        var nodeScale = 1;
        if (scaleEl) {
            var pct = parseInt(scaleEl.value, 10) || 100;
            nodeScale = Math.max(0.5, Math.min(2, pct / 100));
        }
        var avatarSizeBonus = (avatarEl && parseInt(avatarEl.value, 10)) || 6;
        var edgeLabelFontSize = (edgeLabelEl && parseInt(edgeLabelEl.value, 10)) || 10;
        var edgeMin = (edgeMinEl && parseInt(edgeMinEl.value, 10)) || 1;
        return { nodeScale: nodeScale, avatarSizeBonus: avatarSizeBonus, edgeLabelFontSize: edgeLabelFontSize, edgeMin: edgeMin };
    }

    function initGraphTitle() {
        var input = document.getElementById('relaciones-graph-title');
        var overlay = document.getElementById('relaciones-graph-title-overlay');
        var wrap = document.getElementById('relaciones-graph-wrap');
        if (!input || !overlay || !wrap) return;

        function sync() {
            var txt = (input.value || '').trim();
            overlay.textContent = txt;
            overlay.style.display = txt ? 'inline-block' : 'none';
        }

        // Permitir arrastrar el título dentro del área del grafo
        (function enableDrag() {
            var dragging = false;
            var startX = 0, startY = 0;
            var startLeft = 0, startTop = 0;

            function onMouseMove(ev) {
                if (!dragging) return;
                ev.preventDefault();
                var dx = ev.clientX - startX;
                var dy = ev.clientY - startY;
                overlay.style.left = (startLeft + dx) + 'px';
                overlay.style.top = (startTop + dy) + 'px';
            }

            function onMouseUp() {
                if (!dragging) return;
                dragging = false;
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            }

            overlay.addEventListener('mousedown', function (ev) {
                if (!overlay.textContent) return;
                dragging = true;
                ev.preventDefault();
                startX = ev.clientX;
                startY = ev.clientY;
                var rect = overlay.getBoundingClientRect();
                var wrapRect = wrap.getBoundingClientRect();
                startLeft = rect.left - wrapRect.left;
                startTop = rect.top - wrapRect.top;
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });
        })();

        input.addEventListener('input', sync);
        sync();
    }

    function initGraphSliders() {
        var scaleSlider = document.getElementById('relaciones-node-scale');
        var scaleVal = document.getElementById('relaciones-node-scale-val');
        var avatarSlider = document.getElementById('relaciones-avatar-size');
        var avatarVal = document.getElementById('relaciones-avatar-size-val');

        function updateScaleVal() {
            if (scaleSlider && scaleVal) {
                var v = parseInt(scaleSlider.value, 10) || 100;
                scaleVal.textContent = v + '%';
            }
        }
        function updateAvatarVal() {
            if (avatarSlider && avatarVal) {
                var v = parseInt(avatarSlider.value, 10) || 6;
                avatarVal.textContent = v;
            }
        }

        function rebuild() {
            var relaciones = parseRelacionesFromDom();
            if (relaciones && relaciones.length) {
                buildGraph(relaciones, getGraphOpts());
            }
        }

        if (scaleSlider) {
            scaleSlider.addEventListener('input', updateScaleVal);
            scaleSlider.addEventListener('change', rebuild);
            updateScaleVal();
        }
        if (avatarSlider) {
            avatarSlider.addEventListener('input', updateAvatarVal);
            avatarSlider.addEventListener('change', rebuild);
            updateAvatarVal();
        }

        var edgeLabelSlider = document.getElementById('relaciones-edge-label-size');
        var edgeLabelVal = document.getElementById('relaciones-edge-label-size-val');
        var edgeMinSlider = document.getElementById('relaciones-edge-min');
        var edgeMinVal = document.getElementById('relaciones-edge-min-val');
        if (edgeLabelSlider) {
            function updateEdgeLabelVal() {
                if (edgeLabelVal) edgeLabelVal.textContent = edgeLabelSlider.value;
            }
            edgeLabelSlider.addEventListener('input', function () {
                updateEdgeLabelVal();
                var size = parseInt(edgeLabelSlider.value, 10) || 10;
                var svgEl = document.querySelector('#relaciones-graph svg');
                if (svgEl) {
                    svgEl.querySelectorAll('text[data-edge-label="1"]').forEach(function (t) {
                        t.setAttribute('font-size', size);
                    });
                }
            });
            updateEdgeLabelVal();
        }
        if (edgeMinSlider) {
            function updateEdgeMinVal() {
                var v = parseInt(edgeMinSlider.value, 10) || 1;
                if (edgeMinVal) edgeMinVal.textContent = '>= ' + v;
            }
            edgeMinSlider.addEventListener('input', updateEdgeMinVal);
            edgeMinSlider.addEventListener('change', rebuild);
            updateEdgeMinVal();
        }

        var toggleAllLines = document.getElementById('relaciones-toggle-all-lines');
        if (toggleAllLines) {
            toggleAllLines.addEventListener('change', function () {
                if (graphState && graphState.svg) {
                    highlightNode(graphState.svg, graphState.selectedNodeId || null);
                }
            });
        }
    }

    var lastInformeData = null;

    function getTopN() {
        var sel = document.getElementById('analisis-topN');
        if (!sel) return 10;
        var v = parseInt(sel.value, 10);
        if (!isFinite(v) || v < 0) return 10;
        return v;
    }

    function initRelContext() {
        var ac = document.getElementById('analisis-content');
        if (ac) {
            var tipo = ac.getAttribute('data-relaciones-tipo') || 'VOZ';
            relContext.tipo = tipo;
            relContext.label = String(tipo).toUpperCase();
            relContext.apiInforme = ac.getAttribute('data-api-informe') || null;
            relContext.informeSabana = ac.getAttribute('data-informe-sabana') === '1';
        }
    }

    function pushCtxItem(items, label, value) {
        if (value == null) return;
        var txt = String(value).trim();
        if (!txt) return;
        items.push('<li><strong>' + escapeHtml(label) + ':</strong> ' + escapeHtml(txt) + '</li>');
    }

    function renderAnalisisContexto(relaciones) {
        var box = document.getElementById('analisis-contexto');
        if (!box) return;
        var meta = parseMetaFromDom();
        var f = (meta && meta.filtros) ? meta.filtros : {};
        var list = Array.isArray(relaciones) ? relaciones : [];
        var items = [];
        pushCtxItem(items, 'Origen', f.origen || '');
        pushCtxItem(items, 'Tipo de tráfico', f.tipo || relContext.label);
        pushCtxItem(items, 'Caso', f.caso || '');
        pushCtxItem(items, 'Sujetos', f.sujetos || f.sujeto || '');
        pushCtxItem(items, 'Cargas', f.cargas || f.carga_voz || f.carga_gprs || '');
        pushCtxItem(items, 'Archivos Record', f.fuentes_record || '');
        pushCtxItem(items, 'Números (múltiple)', f.numeros || '');
        pushCtxItem(items, 'IMEIs', f.imeis || '');
        pushCtxItem(items, 'Provincias', f.provincias || '');
        pushCtxItem(items, 'Localidades', f.localidades || '');
        pushCtxItem(items, 'Número puntual', f.numero || '');
        if (f.fecha_desde || f.fecha_hasta) {
            pushCtxItem(items, 'Rango de fechas', (f.fecha_desde || '-') + ' a ' + (f.fecha_hasta || '-'));
        }
        if (f.hora_desde || f.hora_hasta) {
            pushCtxItem(items, 'Rango horario', (f.hora_desde || '-') + ' a ' + (f.hora_hasta || '-'));
        }
        if (typeof f.limit !== 'undefined') {
            pushCtxItem(items, 'Límite de pares', String(f.limit));
        }
        pushCtxItem(items, 'Pares analizados', String(list.length || 0));
        if (!items.length) {
            box.innerHTML = '';
            return;
        }
        box.innerHTML = '<h6 class="text-secondary">Contexto del análisis</h6><ul class="small mb-0">' + items.join('') + '</ul>';
    }

    function renderNarrativaAutomatica(relaciones) {
        var narrativoEl = document.getElementById('analisis-informe-narrativo');
        if (!narrativoEl) return;
        var list = Array.isArray(relaciones) ? relaciones : [];
        if (!list.length) {
            narrativoEl.innerHTML = '';
            return;
        }
        var texto = buildNarrativaText(list);
        narrativoEl.innerHTML =
            '<h6 class="text-secondary border-bottom pb-2">Síntesis automática</h6>' +
            '<div class="informe-parrafo bg-light border-start border-4 border-secondary px-3 py-2 small lh-base">' +
            escapeHtml(texto) +
            '</div>';
    }

    function buildNarrativaText(relaciones) {
        var list = Array.isArray(relaciones) ? relaciones : [];
        if (!list.length) return '';
        var ordenado = list.slice().sort(function (a, b) {
            return (parseInt(b.cantidad || 0, 10) || 0) - (parseInt(a.cantidad || 0, 10) || 0);
        });
        var top = ordenado[0] || {};
        var total = ordenado.reduce(function (sum, r) { return sum + (parseInt(r.cantidad || 0, 10) || 0); }, 0);
        var nums = Object.create(null);
        ordenado.forEach(function (r) {
            if (r && r.numero_a) nums[String(r.numero_a).trim()] = true;
            if (r && r.numero_b) nums[String(r.numero_b).trim()] = true;
        });
        var texto = 'Con los filtros aplicados se observan ' + ordenado.length + ' pares y un volumen total de ' + total +
            (relContext.tipo === 'GPRS' ? ' accesos de datos' : ' comunicaciones') + '. ';
        if (top && top.numero_a && top.numero_b) {
            texto += 'El vínculo de mayor intensidad corresponde a ' + top.numero_a + ' y ' + top.numero_b +
                ' con ' + (top.cantidad || 0) + '. ';
        }
        texto += 'Se identifican ' + Object.keys(nums).length + ' nodos únicos involucrados en el período analizado.';
        return texto;
    }

    function buildLocalInformeData() {
        var relaciones = parseRelacionesFromDom();
        var totalCom = 0;
        var nums = Object.create(null);
        var apiLike = [];
        relaciones.forEach(function (r) {
            var cant = parseInt(r.cantidad || 0, 10) || 0;
            totalCom += cant;
            if (r.numero_a) nums[String(r.numero_a).trim()] = true;
            if (r.numero_b) nums[String(r.numero_b).trim()] = true;
            apiLike.push({
                numero_a: r.numero_a || null,
                numero_b: r.numero_b || null,
                cantidad: cant,
                sujeto_a: (r.sujeto_a && r.sujeto_a.display) ? r.sujeto_a.display : null,
                sujeto_b: (r.sujeto_b && r.sujeto_b.display) ? r.sujeto_b.display : null,
            });
        });
        return {
            relaciones: apiLike,
            resumen: {
                total_pares: relaciones.length,
                total_comunicaciones: totalCom,
                numeros_unicos: Object.keys(nums).length,
            },
            sujetos_por_numero: {},
            impactos_por_numero: {},
            parrafo_informe: buildNarrativaText(relaciones),
            metadatos: {
                origen_local: true,
            },
        };
    }

    function parseIsoLike(fecha, hora) {
        var f = (fecha || '').trim();
        var h = (hora || '').trim();
        if (!f) return null;
        if (!h) h = '00:00:00';
        if (h.length === 5) h += ':00';
        return f + 'T' + h;
    }

    function buildRecordImpactosPorNumero(items) {
        var byNumero = Object.create(null);
        (Array.isArray(items) ? items : []).forEach(function (cell) {
            if (!cell || !Array.isArray(cell.impactos)) return;
            var celdaId = cell.celda_id || cell.id || '—';
            cell.impactos.forEach(function (imp) {
                var num = imp && imp.numero ? String(imp.numero).trim() : '';
                if (!num) return;
                if (!byNumero[num]) byNumero[num] = Object.create(null);
                var key = String(celdaId);
                if (!byNumero[num][key]) {
                    byNumero[num][key] = {
                        celda_id: celdaId,
                        lat: (cell.lat != null) ? Number(cell.lat) : null,
                        long: (cell.lng != null) ? Number(cell.lng) : null,
                        direccion: cell.celda_direccion || null,
                        localidad: cell.locality_cell || null,
                        provincia: cell.province_cell || null,
                        cantidad: 0,
                        primera_fecha: null,
                        ultima_fecha: null,
                    };
                }
                var rec = byNumero[num][key];
                rec.cantidad += 1;
                var when = parseIsoLike(imp.fecha, imp.hora);
                if (when) {
                    if (!rec.primera_fecha || when < rec.primera_fecha) rec.primera_fecha = when;
                    if (!rec.ultima_fecha || when > rec.ultima_fecha) rec.ultima_fecha = when;
                }
            });
        });
        var out = {};
        Object.keys(byNumero).forEach(function (num) {
            out[num] = Object.keys(byNumero[num]).map(function (k) {
                return byNumero[num][k];
            }).sort(function (a, b) {
                return (b.cantidad || 0) - (a.cantidad || 0);
            });
        });
        return out;
    }

    function fetchRecordGeoResumenForInforme() {
        var casoId = '';
        try {
            var qs = new URLSearchParams(window.location.search || '');
            casoId = (qs.get('caso_id') || '').trim();
        } catch (e) { casoId = ''; }
        if (!casoId) {
            return Promise.resolve({
                total_filtrados: 0,
                con_cell_id: 0,
                con_celda_geo: 0,
                sin_cell_id: 0,
                sin_celda_geo: 0,
            });
        }
        var q = new URLSearchParams(window.location.search || '');
        q.set('source_type', relContext.tipo === 'GPRS' ? 'GPRS' : 'VOZ');
        return fetch((document.body.getAttribute('data-sabana-base') || '') + '/sabana-llamadas/api/relaciones/record-geo-resumen?' + q.toString(), {
            headers: { 'Accept': 'application/json' }
        }).then(function (res) {
            return res.ok ? res.json() : {};
        }).catch(function () {
            return {};
        });
    }

    function fetchRecordImpactosForInforme() {
        var casoId = '';
        try {
            var qs = new URLSearchParams(window.location.search || '');
            casoId = (qs.get('caso_id') || '').trim();
        } catch (e) { casoId = ''; }
        if (!casoId) return Promise.resolve({ impactos_por_numero: {}, geo_resumen: {} });
        var q = new URLSearchParams(window.location.search || '');
        q.set('source_type', relContext.tipo === 'GPRS' ? 'GPRS' : 'VOZ');
        return fetch((document.body.getAttribute('data-sabana-base') || '') + '/sabana-llamadas/api/mapa/record-impactos?' + q.toString(), {
            headers: { 'Accept': 'application/json' }
        }).then(function (res) {
            return res.ok ? res.json() : [];
        }).then(function (items) {
            return fetchRecordGeoResumenForInforme().then(function (geo) {
                return {
                    impactos_por_numero: buildRecordImpactosPorNumero(items),
                    geo_resumen: geo || {},
                };
            });
        }).catch(function () {
            return { impactos_por_numero: {}, geo_resumen: {} };
        });
    }

    function computeHallazgos(relaciones) {
        var list = Array.isArray(relaciones) ? relaciones : [];
        if (!list.length) return [];
        var ordenado = list.slice().sort(function (a, b) {
            return (parseInt(b.cantidad || 0, 10) || 0) - (parseInt(a.cantidad || 0, 10) || 0);
        });
        var topPar = ordenado[0] || null;
        var nodoStats = Object.create(null);
        list.forEach(function (r) {
            if (!r) return;
            var cant = parseInt(r.cantidad || 0, 10) || 0;
            ['a', 'b'].forEach(function (side) {
                var numKey = side === 'a' ? 'numero_a' : 'numero_b';
                var sjKey = side === 'a' ? 'sujeto_a' : 'sujeto_b';
                var n = r[numKey] ? String(r[numKey]).trim() : '';
                if (!n) return;
                if (!nodoStats[n]) {
                    nodoStats[n] = { numero: n, conexiones: 0, volumen: 0, sujeto: r[sjKey] || null };
                }
                nodoStats[n].conexiones += 1;
                nodoStats[n].volumen += cant;
                if (!nodoStats[n].sujeto && r[sjKey]) nodoStats[n].sujeto = r[sjKey];
            });
        });
        var nodos = Object.keys(nodoStats).map(function (k) { return nodoStats[k]; });
        nodos.sort(function (a, b) {
            if (b.conexiones !== a.conexiones) return b.conexiones - a.conexiones;
            return b.volumen - a.volumen;
        });
        var nodoClave = nodos[0] || null;
        var volTotal = list.reduce(function (sum, r) { return sum + (parseInt(r.cantidad || 0, 10) || 0); }, 0);
        var conectividadProm = nodos.length ? (list.length * 2 / nodos.length) : 0;
        var hallazgos = [];
        if (topPar) {
            hallazgos.push('Par más intenso: ' + (topPar.numero_a || '—') + ' ↔ ' + (topPar.numero_b || '—') + ' (' + (topPar.cantidad || 0) + ').');
        }
        if (nodoClave) {
            var sujetoNombre = '';
            if (typeof nodoClave.sujeto === 'string') sujetoNombre = nodoClave.sujeto;
            else if (nodoClave.sujeto && nodoClave.sujeto.display) sujetoNombre = nodoClave.sujeto.display;
            var sujetoTxt = sujetoNombre ? (' — ' + sujetoNombre) : '';
            hallazgos.push('Nodo con mayor centralidad: ' + nodoClave.numero + sujetoTxt + ' (conexiones: ' + nodoClave.conexiones + ', volumen: ' + nodoClave.volumen + ').');
        }
        hallazgos.push('Densidad observada: ' + list.length + ' enlaces, ' + nodos.length + ' nodos, conectividad media ' + conectividadProm.toFixed(2) + '.');
        if (volTotal > 0 && topPar) {
            var topShare = ((parseInt(topPar.cantidad || 0, 10) || 0) * 100 / volTotal);
            hallazgos.push('Concentración del par líder: ' + topShare.toFixed(1) + '% del volumen total.');
        }
        return hallazgos;
    }

    function renderHallazgos(relaciones) {
        var box = document.getElementById('analisis-hallazgos');
        if (!box) return;
        var hallazgos = computeHallazgos(relaciones);
        if (!hallazgos.length) {
            box.innerHTML = '';
            return;
        }
        box.innerHTML = '<h6 class="text-secondary">Hallazgos automáticos</h6><ul class="mb-0 small">' +
            hallazgos.map(function (h) { return '<li>' + escapeHtml(h) + '</li>'; }).join('') +
            '</ul>';
    }

    function renderRecomendaciones(relaciones) {
        var box = document.getElementById('analisis-recomendaciones');
        if (!box) return;
        var list = Array.isArray(relaciones) ? relaciones : [];
        if (!list.length) {
            box.innerHTML = '';
            return;
        }
        var ordenado = list.slice().sort(function (a, b) {
            return (parseInt(b.cantidad || 0, 10) || 0) - (parseInt(a.cantidad || 0, 10) || 0);
        });
        var top = ordenado[0] || null;
        var recomendaciones = [];
        if (top && top.numero_a && top.numero_b) {
            recomendaciones.push('Priorizar trazado geográfico del par ' + top.numero_a + ' ↔ ' + top.numero_b + ' por concentrar mayor intensidad.');
        }
        recomendaciones.push('Cruzar nodos de mayor centralidad con líneas/sujetos ya judicializados y validar continuidad temporal en pestaña Patrones.');
        recomendaciones.push('Repetir análisis por ventanas horarias acotadas (mañana/tarde/noche) para detectar cambios de comportamiento.');
        box.innerHTML = '<h6 class="text-secondary">Conclusiones y recomendaciones</h6><ul class="mb-0 small">' +
            recomendaciones.map(function (r) { return '<li>' + escapeHtml(r) + '</li>'; }).join('') +
            '</ul>';
    }

    function buildAnalisisSummary() {
        var relaciones = parseRelacionesFromDom();
        var resumenEl = document.getElementById('analisis-resumen');
        var topParesEl = document.getElementById('analisis-top-pares');
        if (!resumenEl || !topParesEl) return;
        renderAnalisisContexto(relaciones);

        if (!relaciones || relaciones.length === 0) {
            resumenEl.innerHTML = '<p class="text-muted mb-0">No hay datos para analizar. Aplique filtros y recargue.</p>';
            topParesEl.innerHTML = '';
            renderHallazgos([]);
            renderRecomendaciones([]);
            renderNarrativaAutomatica([]);
            return;
        }

        var totalPares = relaciones.length;
        var totalComunicaciones = relaciones.reduce(function (sum, r) { return sum + (parseInt(r.cantidad, 10) || 0); }, 0);
        var commLabel = relContext.tipo === 'GPRS' ? 'accesos de datos' : 'llamadas';
        var numerosSet = Object.create(null);
        var conSujeto = 0;
        relaciones.forEach(function (r) {
            if (r.numero_a) numerosSet[String(r.numero_a).trim()] = true;
            if (r.numero_b) numerosSet[String(r.numero_b).trim()] = true;
            if (r.sujeto_a) conSujeto += 1;
            if (r.sujeto_b) conSujeto += 1;
        });
        var numUnicos = Object.keys(numerosSet).length;

        resumenEl.innerHTML =
            '<h6 class="text-secondary">Resumen (' + relContext.label + ')</h6>' +
            '<ul class="list-unstyled mb-0">' +
            '<li><strong>Pares de números en relación:</strong> ' + totalPares + '</li>' +
            '<li><strong>Total comunicaciones (' + commLabel + '):</strong> ' + totalComunicaciones + '</li>' +
            '<li><strong>Números únicos involucrados:</strong> ' + numUnicos + '</li>' +
            '<li><strong>Relaciones con sujeto identificado:</strong> ' + conSujeto + ' extremos</li>' +
            '</ul>';

        var ordenado = relaciones.slice().sort(function (a, b) {
            return (parseInt(b.cantidad, 10) || 0) - (parseInt(a.cantidad, 10) || 0);
        });
        var topN = getTopN();
        var subset = (topN && topN > 0) ? ordenado.slice(0, topN) : ordenado;
        var rows = subset.map(function (r) {
            var labelA = (r.sujeto_a && r.sujeto_a.display) ? r.sujeto_a.display + ' (' + r.numero_a + ')' : r.numero_a;
            var labelB = (r.sujeto_b && r.sujeto_b.display) ? r.sujeto_b.display + ' (' + r.numero_b + ')' : r.numero_b;
            return '<tr><td>' + escapeHtml(labelA) + '</td><td>' + escapeHtml(labelB) + '</td><td class="text-end">' + (r.cantidad || 0) + '</td></tr>';
        }).join('');
        var thB = relContext.tipo === 'GPRS' ? 'IP / destino' : 'Número B';
        var thCount = relContext.tipo === 'GPRS' ? '# Accesos' : '# Llamadas';
        topParesEl.innerHTML =
            '<h6 class="text-secondary">Top pares por cantidad de comunicaciones</h6>' +
            '<div class="table-responsive"><table class="table table-sm table-bordered"><thead><tr><th>Número A</th><th>' + thB + '</th><th class="text-end">' + thCount + '</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
        renderHallazgos(relaciones);
        renderRecomendaciones(relaciones);
        if (!lastInformeData || !lastInformeData.parrafo_informe) {
            renderNarrativaAutomatica(relaciones);
        }
    }

    function renderInformeCompleto(data) {
        lastInformeData = data;
        var narrativoEl = document.getElementById('analisis-informe-narrativo');
        var resumenEl = document.getElementById('analisis-resumen');
        var impactosEl = document.getElementById('analisis-impactos-celdas');
        if (!data) return;
        var rels = Array.isArray(data.relaciones) ? data.relaciones : parseRelacionesFromDom();
        renderAnalisisContexto(rels);
        renderHallazgos(rels);
        renderRecomendaciones(rels);

        if (narrativoEl && data.parrafo_informe) {
            narrativoEl.innerHTML =
                '<h6 class="text-secondary border-bottom pb-2">Informe redactado (para presentación)</h6>' +
                '<div class="informe-parrafo bg-light border-start border-4 border-primary px-3 py-2 small lh-base">' +
                escapeHtml(data.parrafo_informe).replace(/\n/g, '<br>') +
                '</div>';
        } else {
            renderNarrativaAutomatica(rels);
        }

        if (resumenEl && data.resumen) {
            var r = data.resumen;
            resumenEl.innerHTML =
                '<h6 class="text-secondary">Resumen (' + relContext.label + ')</h6>' +
                '<ul class="list-unstyled mb-0">' +
                '<li><strong>Pares de números en relación:</strong> ' + (r.total_pares || 0) + '</li>' +
                '<li><strong>Total comunicaciones (llamadas):</strong> ' + (r.total_comunicaciones || 0) + '</li>' +
                '<li><strong>Números únicos involucrados:</strong> ' + (r.numeros_unicos || 0) + '</li>' +
                '</ul>';
        }

        if (impactosEl && data.impactos_por_numero && Object.keys(data.impactos_por_numero).length > 0) {
            var sujetos = data.sujetos_por_numero || {};
            var html = '<h6 class="text-secondary">Impactos en celdas por línea (lat/long y ubicación)</h6>';
            Object.keys(data.impactos_por_numero).sort().forEach(function (num) {
                var sujeto = sujetos[num] || 'sin identificar';
                var celdas = data.impactos_por_numero[num];
                var totalImp = celdas.reduce(function (s, c) { return s + (c.cantidad || 0); }, 0);
                html += '<p class="mb-1"><strong>Número ' + escapeHtml(num) + '</strong> (sujeto: ' + escapeHtml(sujeto) + ') — ' + totalImp + ' impactos en ' + celdas.length + ' celda(s).</p>';
                html += '<div class="table-responsive mb-3"><table class="table table-sm table-bordered"><thead><tr><th>Celda</th><th>Latitud</th><th>Longitud</th><th>Ubicación</th><th class="text-end">#</th></tr></thead><tbody>';
                celdas.forEach(function (c) {
                    var ub = [c.direccion, c.localidad, c.provincia].filter(Boolean).join(', ') || '—';
                    html += '<tr><td>' + escapeHtml(c.celda_id || '—') + '</td><td>' + (c.lat != null ? c.lat.toFixed(5) : '—') + '</td><td>' + (c.long != null ? c.long.toFixed(5) : '—') + '</td><td>' + escapeHtml(ub) + '</td><td class="text-end">' + (c.cantidad || 0) + '</td></tr>';
                });
                html += '</tbody></table></div>';
            });
            impactosEl.innerHTML = html;
        } else if (impactosEl) {
            var extra = '';
            try {
                var geo = data && data.metadatos ? (data.metadatos.record_geo || {}) : {};
                if (geo && (geo.total_filtrados || geo.con_cell_id || geo.con_celda_geo || geo.sin_cell_id || geo.sin_celda_geo)) {
                    extra = '<div class="mt-2"><span class="badge text-bg-secondary me-1">Total filtrados: ' + String(geo.total_filtrados || 0) + '</span>' +
                        '<span class="badge text-bg-secondary me-1">Con cell_id: ' + String(geo.con_cell_id || 0) + '</span>' +
                        '<span class="badge text-bg-secondary me-1">Georreferenciables: ' + String(geo.con_celda_geo || 0) + '</span>' +
                        '<span class="badge text-bg-warning text-dark me-1">Sin cell_id: ' + String(geo.sin_cell_id || 0) + '</span>' +
                        '<span class="badge text-bg-warning text-dark">Sin coordenadas: ' + String(geo.sin_celda_geo || 0) + '</span></div>';
                }
            } catch (eGeo) {}
            impactosEl.innerHTML = '<p class="text-muted small mb-0">No hay impactos en celdas con coordenadas para los números del informe.</p>' + extra;
        }
    }

    function fetchInformeCompleto() {
        var btn = document.getElementById('btn-generar-informe');
        if (btn) btn.disabled = true;
        if (!relContext.informeSabana) {
            var localData = buildLocalInformeData();
            fetchRecordImpactosForInforme().then(function (payload) {
                payload = payload || {};
                localData.impactos_por_numero = payload.impactos_por_numero || {};
                if (!localData.metadatos) localData.metadatos = {};
                localData.metadatos.record_geo = payload.geo_resumen || {};
                renderInformeCompleto(localData);
                updateAnalisisBadgeWithTime();
            }).finally(function () {
                if (btn) btn.disabled = false;
            });
            return;
        }
        var qs = window.location.search || '';
        var api = relContext.apiInforme || (window.location.pathname.replace(/\/relaciones\/?$/, '') + '/api/informe-voz');
        var url = api + (qs ? qs : '?limit=200');
        fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.error) throw new Error(data.error);
                renderInformeCompleto(data);
                updateAnalisisBadgeWithTime();
                var topParesEl = document.getElementById('analisis-top-pares');
                if (topParesEl && data.relaciones && data.relaciones.length) {
                    var ordenado = data.relaciones.slice().sort(function (a, b) { return (b.cantidad || 0) - (a.cantidad || 0); });
                    var topN = getTopN();
                    var subset = (topN && topN > 0) ? ordenado.slice(0, topN) : ordenado;
                    var rows = subset.map(function (r) {
                        var labelA = (r.sujeto_a ? r.sujeto_a + ' (' + r.numero_a + ')' : r.numero_a);
                        var labelB = (r.sujeto_b ? r.sujeto_b + ' (' + r.numero_b + ')' : r.numero_b);
                        return '<tr><td>' + escapeHtml(labelA) + '</td><td>' + escapeHtml(labelB) + '</td><td class="text-end">' + (r.cantidad || 0) + '</td></tr>';
                    }).join('');
                    topParesEl.innerHTML = '<h6 class="text-secondary">Top pares por cantidad de comunicaciones</h6><div class="table-responsive"><table class="table table-sm table-bordered"><thead><tr><th>Número A</th><th>Número B</th><th class="text-end"># Llamadas</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
                }
            })
            .catch(function (err) {
                console.error('Informe:', err);
                alert('No se pudo generar el informe. Verifique los filtros y vuelva a intentar.');
            })
            .finally(function () {
                if (btn) btn.disabled = false;
            });
    }

    function fetchPatronesData() {
        var qs = window.location.search || '';
        var url = (document.body.getAttribute('data-sabana-base') || '') + '/sabana-llamadas/api/relaciones/patrones' + (qs ? qs : '');
        if (!qs) {
            url += '?origen=sabana&tipo_trafico=voz';
        }
        return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (res) {
            return res.ok ? res.json() : {};
        }).catch(function () {
            return {};
        });
    }

    function renderPatronesCharts(data) {
        var wdEl = document.getElementById('patrones-weekday-chart');
        var hrEl = document.getElementById('patrones-hour-chart');
        var sumEl = document.getElementById('patrones-resumen');
        var extraEl = document.getElementById('patrones-extra');
        if (!wdEl || !hrEl) return;

        var byW = Array.isArray(data.by_weekday) ? data.by_weekday : [];
        var byH = Array.isArray(data.by_hour) ? data.by_hour : [];
        var wdLabels = byW.map(function (x) { return x.label || ''; });
        var wdVals = byW.map(function (x) { return parseInt(x.count || 0, 10) || 0; });
        var hLabels = byH.map(function (x) { return String(x.hour || '00') + ':00'; });
        var hVals = byH.map(function (x) { return parseInt(x.count || 0, 10) || 0; });

        var total = parseInt(data.total_eventos || 0, 10) || 0;
        if (sumEl) {
            if (total > 0) {
                var tw = data.top_weekday ? (data.top_weekday.label + ' (' + (data.top_weekday.count || 0) + ')') : '—';
                var th = data.top_hour ? ((data.top_hour.hour || '00') + ':00 (' + (data.top_hour.count || 0) + ')') : '—';
                sumEl.classList.remove('d-none');
                sumEl.textContent = 'Total eventos analizados: ' + total + ' | Pico semanal: ' + tw + ' | Pico horario: ' + th;
            } else {
                sumEl.classList.remove('d-none');
                sumEl.textContent = 'Sin eventos con fecha/hora para los filtros actuales.';
            }
        }

        if (typeof window.Plotly !== 'undefined') {
            window.Plotly.react(wdEl, [{
                x: wdLabels, y: wdVals, type: 'bar', marker: { color: '#0d6efd' }, hovertemplate: '%{x}: %{y}<extra></extra>'
            }], {
                margin: { l: 36, r: 10, t: 8, b: 36 },
                yaxis: { title: 'Eventos' },
                xaxis: { title: 'Dia' },
            }, { displayModeBar: false, responsive: true });
            window.Plotly.react(hrEl, [{
                x: hLabels, y: hVals, type: 'bar', marker: { color: '#20c997' }, hovertemplate: '%{x}: %{y}<extra></extra>'
            }], {
                margin: { l: 36, r: 10, t: 8, b: 36 },
                yaxis: { title: 'Eventos' },
                xaxis: { title: 'Hora' },
            }, { displayModeBar: false, responsive: true });
        } else {
            wdEl.innerHTML = '<p class="text-muted small mb-0">Plotly no disponible.</p>';
            hrEl.innerHTML = '<p class="text-muted small mb-0">Plotly no disponible.</p>';
        }

        if (extraEl) {
            var topHours = byH.slice().sort(function (a, b) { return (b.count || 0) - (a.count || 0); }).slice(0, 3);
            if (topHours.length && (topHours[0].count || 0) > 0) {
                extraEl.innerHTML = '<h6 class="text-secondary mb-1">Patrones sugeridos</h6><ul class="small mb-0">' +
                    '<li>Las franjas con mayor actividad son: ' + topHours.map(function (h) { return (h.hour || '00') + ':00'; }).join(', ') + '.</li>' +
                    '<li>Contrastar estos picos con desplazamientos geográficos en mapa para inferir rutinas.</li>' +
                    '<li>Comparar días pico vs días valle para detectar comportamiento anómalo.</li>' +
                    '</ul>';
            } else {
                extraEl.innerHTML = '';
            }
        }
    }

    function loadPatrones(force) {
        if (!force && patronesState.loaded && patronesState.data) {
            renderPatronesCharts(patronesState.data);
            return Promise.resolve(patronesState.data);
        }
        return fetchPatronesData().then(function (data) {
            patronesState.loaded = true;
            patronesState.data = data || {};
            renderPatronesCharts(patronesState.data);
            setBadgeText('tab-badge-patrones', String((patronesState.data && patronesState.data.total_eventos) || 0));
            return patronesState.data;
        });
    }

    function initPatronesTab() {
        var tab = document.getElementById('tab-patrones');
        if (tab) {
            tab.addEventListener('shown.bs.tab', function () {
                loadPatrones(false);
            });
        }
        var btn = document.getElementById('btn-refrescar-patrones');
        if (btn) {
            btn.addEventListener('click', function () {
                loadPatrones(true);
            });
        }
    }

    function setBadgeText(id, txt) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = txt || '';
    }

    function updateAnalisisBadgeWithTime() {
        try {
            var hhmm = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            setBadgeText('tab-badge-analisis', hhmm);
        } catch (e) {
            setBadgeText('tab-badge-analisis', 'Generado');
        }
    }

    function updateTabBadges(relaciones) {
        var list = Array.isArray(relaciones) ? relaciones : [];
        setBadgeText('tab-badge-tabla', String(list.length || 0));
        var nodes = Object.create(null);
        var edges = 0;
        list.forEach(function (r) {
            if (!r) return;
            var a = r.numero_a ? String(r.numero_a).trim() : '';
            var b = r.numero_b ? String(r.numero_b).trim() : '';
            if (a) nodes[a] = true;
            if (b) nodes[b] = true;
            if (a && b) edges += 1;
        });
        setBadgeText('tab-badge-grafo', Object.keys(nodes).length + '/' + edges);
        if (!lastInformeData) setBadgeText('tab-badge-analisis', 'Sin generar');
    }

    function initTabPersistence() {
        var tabs = document.querySelectorAll('.nav-link[data-bs-toggle="tab"]');
        tabs.forEach(function (tabBtn) {
            tabBtn.addEventListener('shown.bs.tab', function (ev) {
                var target = ev && ev.target ? ev.target.getAttribute('data-bs-target') : null;
                if (!target) return;
                try { localStorage.setItem(TAB_STORAGE_KEY, target); } catch (e) {}
            });
        });
        try {
            var savedTarget = localStorage.getItem(TAB_STORAGE_KEY);
            if (!savedTarget) return;
            var savedTab = document.querySelector('.nav-link[data-bs-target="' + savedTarget + '"]');
            if (!savedTab || !window.bootstrap || !window.bootstrap.Tab) return;
            var instance = window.bootstrap.Tab.getOrCreateInstance(savedTab);
            if (instance) instance.show();
        } catch (e2) {}
    }

    function escapeHtml(s) {
        if (s == null) return '';
        var div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    function exportToPdf() {
        var titleInput = document.getElementById('relaciones-graph-title');
        var defaultTitulo = 'Informe de relaciones ' + relContext.label;
        var titulo = (titleInput && titleInput.value) ? titleInput.value.trim() : defaultTitulo;
        var resumenEl = document.getElementById('analisis-resumen');
        var topParesEl = document.getElementById('analisis-top-pares');
        var narrativoEl = document.getElementById('analisis-informe-narrativo');
        var impactosEl = document.getElementById('analisis-impactos-celdas');
        var meta = parseMetaFromDom();

        var filtrosHtml = '';
        var filtrosItems = [];
        if (meta.filtros) {
            if (meta.filtros.sujeto) filtrosItems.push('<li><strong>Sujeto:</strong> ' + escapeHtml(meta.filtros.sujeto) + '</li>');
            if (meta.filtros.sujetos) filtrosItems.push('<li><strong>Sujetos:</strong> ' + escapeHtml(meta.filtros.sujetos) + '</li>');
            if (meta.filtros.carga_voz) filtrosItems.push('<li><strong>Carga VOZ:</strong> ' + escapeHtml(meta.filtros.carga_voz) + '</li>');
            if (meta.filtros.carga_gprs) filtrosItems.push('<li><strong>Carga GPRS:</strong> ' + escapeHtml(meta.filtros.carga_gprs) + '</li>');
            if (meta.filtros.cargas) filtrosItems.push('<li><strong>Cargas (múltiple):</strong> ' + escapeHtml(meta.filtros.cargas) + '</li>');
            if (meta.filtros.fuentes_record) filtrosItems.push('<li><strong>Archivos Record:</strong> ' + escapeHtml(meta.filtros.fuentes_record) + '</li>');
            if (meta.filtros.numero) filtrosItems.push('<li><strong>Número (A/B):</strong> ' + escapeHtml(meta.filtros.numero) + '</li>');
            if (meta.filtros.numeros) filtrosItems.push('<li><strong>Números (múltiple):</strong> ' + escapeHtml(meta.filtros.numeros) + '</li>');
            if (meta.filtros.imeis) filtrosItems.push('<li><strong>IMEIs:</strong> ' + escapeHtml(meta.filtros.imeis) + '</li>');
            if (meta.filtros.provincias) filtrosItems.push('<li><strong>Provincias:</strong> ' + escapeHtml(meta.filtros.provincias) + '</li>');
            if (meta.filtros.localidades) filtrosItems.push('<li><strong>Localidades:</strong> ' + escapeHtml(meta.filtros.localidades) + '</li>');
            if (meta.filtros.fecha_desde || meta.filtros.fecha_hasta) {
                filtrosItems.push('<li><strong>Fechas:</strong> ' + escapeHtml(meta.filtros.fecha_desde || '-') + ' a ' + escapeHtml(meta.filtros.fecha_hasta || '-') + '</li>');
            }
            if (meta.filtros.hora_desde || meta.filtros.hora_hasta) {
                filtrosItems.push('<li><strong>Franjas horarias:</strong> ' + escapeHtml(meta.filtros.hora_desde || '-') + ' a ' + escapeHtml(meta.filtros.hora_hasta || '-') + '</li>');
            }
            if (typeof meta.filtros.limit !== 'undefined') {
                filtrosItems.push('<li><strong>Límite de pares:</strong> ' + String(meta.filtros.limit) + '</li>');
            }
        } else {
            var sujetoSel = document.getElementById('sujeto_id');
            if (sujetoSel && sujetoSel.value) {
                filtrosItems.push('<li><strong>Sujeto:</strong> ' + escapeHtml(sujetoSel.options[sujetoSel.selectedIndex].text) + '</li>');
            }
            var cargaSel = document.getElementById('carga_id');
            if (cargaSel && cargaSel.value) {
                filtrosItems.push('<li><strong>Carga VOZ:</strong> ' + escapeHtml(cargaSel.options[cargaSel.selectedIndex].text) + '</li>');
            }
            var numInput = document.getElementById('numero');
            if (numInput && numInput.value) {
                filtrosItems.push('<li><strong>Número filtro:</strong> ' + escapeHtml(numInput.value) + '</li>');
            }
            var fd = document.getElementById('fecha_desde');
            var fh = document.getElementById('fecha_hasta');
            if (fd && fd.value) filtrosItems.push('<li><strong>Fecha desde:</strong> ' + escapeHtml(fd.value) + '</li>');
            if (fh && fh.value) filtrosItems.push('<li><strong>Fecha hasta:</strong> ' + escapeHtml(fh.value) + '</li>');
            var hd = document.getElementById('hora_desde');
            var hh = document.getElementById('hora_hasta');
            if (hd && hd.value) filtrosItems.push('<li><strong>Hora desde:</strong> ' + escapeHtml(hd.value) + '</li>');
            if (hh && hh.value) filtrosItems.push('<li><strong>Hora hasta:</strong> ' + escapeHtml(hh.value) + '</li>');
        }
        if (!filtrosItems.length) {
            filtrosItems.push('<li>Sin filtros específicos: se analizaron todas las comunicaciones VOZ accesibles al usuario.</li>');
        }
        filtrosHtml = '<h3>Parámetros del análisis</h3><ul>' + filtrosItems.join('') + '</ul>';

        var generadoLocal = '';
        if (meta.generado_en_utc) {
            try {
                generadoLocal = new Date(meta.generado_en_utc).toLocaleString();
            } catch (e) {
                generadoLocal = meta.generado_en_utc;
            }
        }

        var encabezadoHtml = '<h2>Datos del informe</h2><ul>' +
            '<li><strong>Unidad:</strong> ' + escapeHtml((meta.unidad || '')) + '</li>' +
            '<li><strong>Usuario:</strong> ' + escapeHtml((meta.usuario || '')) + '</li>' +
            (generadoLocal ? '<li><strong>Generado:</strong> ' + escapeHtml(generadoLocal) + '</li>' : '') +
            '</ul>';

        var bodyParts = [encabezadoHtml, filtrosHtml];
        if (lastInformeData && lastInformeData.parrafo_informe) {
            bodyParts.push('<h2>Informe redactado</h2><div class="informe-parrafo" style="background:#f8f9fa;border-left:4px solid #0d6efd;padding:12px 16px;margin:12px 0;">' + escapeHtml(lastInformeData.parrafo_informe).replace(/\n/g, '<br>') + '</div>');
        }
        bodyParts.push('<div class="resumen-pdf">' + (resumenEl ? resumenEl.innerHTML : '') + (topParesEl ? topParesEl.outerHTML : '') + '</div>');
        if (impactosEl && impactosEl.innerHTML) {
            bodyParts.push('<h3>Impactos en celdas</h3>' + impactosEl.innerHTML);
        }

        var mapaImg = localStorage.getItem('sabana_mapa_ultima_captura');
        if (mapaImg) {
            bodyParts.push('<h3>Mapa de impactos</h3><div class="mapa-pdf"><img src="' + mapaImg + '" style="max-width:100%;border:1px solid #ccc;"></div>');
        }

        var svgEl = document.querySelector('#relaciones-graph svg');
        var svgHtml = '';
        if (svgEl) {
            var clone = svgEl.cloneNode(true);
            clone.setAttribute('width', '700');
            clone.setAttribute('height', '400');
            clone.style.maxWidth = '100%';
            clone.style.height = 'auto';
            svgHtml = '<div class="page-grafo"><div class="grafo-pdf">' + new XMLSerializer().serializeToString(clone) + '</div></div>';
        }

        var win = window.open('', '_blank');
        if (!win) {
            alert('Permita ventanas emergentes para exportar a PDF.');
            return;
        }
        win.document.write(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + escapeHtml(titulo) + '</title>' +
            '<style>@page { margin: 2.5cm; } body{font-family:Arial,Segoe UI,sans-serif;padding:20px;max-width:900px;margin:0 auto;font-size:12pt;line-height:1.5;text-align:justify;} h1,h2,h3,h4{font-weight:bold;text-align:left;} h1{font-size:18pt;margin-bottom:8px;} h2{font-size:16pt;margin-top:14px;margin-bottom:6px;} h3{font-size:14pt;margin-top:12px;margin-bottom:6px;} .grafo-pdf svg{max-width:100%;height:auto;} table{border-collapse:collapse;width:100%;margin:8px 0;font-size:11pt;} th,td{border:1px solid #ddd;padding:6px;text-align:left;} th{background:#f5f5f5;font-weight:bold;} .informe-parrafo{line-height:1.5;} .grafo-seccion{page-break-before:always;} @media print{body{padding:0;} .no-print{display:none;}}</style></head><body>' +
            '<h1>' + escapeHtml(titulo) + '</h1>' +
            '<p style="color:#6c757d;font-size:10pt;">Generado desde Relaciones (' + relContext.label + ') – ' + new Date().toLocaleString() + '</p>' +
            encabezadoHtml +
            filtrosHtml +
            '<hr>' +
            bodyParts.join('<hr>') +
            (svgHtml ? '<div class="grafo-seccion"><h3>Grafo de relaciones</h3>' + svgHtml + '</div>' : '') +
            '<hr><p style="font-size:10pt;color:#6c757d;">Para guardar como PDF: Archivo → Imprimir → Guardar como PDF.</p>' +
            '</body></html>'
        );
        win.document.close();
        setTimeout(function () { win.print(); }, 250);
    }

    function exportToWord() {
        var titleInput = document.getElementById('relaciones-graph-title');
        var defaultTitulo = 'Informe de relaciones ' + relContext.label;
        var titulo = (titleInput && titleInput.value) ? titleInput.value.trim() : defaultTitulo;
        var resumenEl = document.getElementById('analisis-resumen');
        var topParesEl = document.getElementById('analisis-top-pares');
        var impactosEl = document.getElementById('analisis-impactos-celdas');
        var meta = parseMetaFromDom();

        var filtrosItems = [];
        if (meta.filtros) {
            if (meta.filtros.sujeto) filtrosItems.push('<li><strong>Sujeto:</strong> ' + escapeHtml(meta.filtros.sujeto) + '</li>');
            if (meta.filtros.sujetos) filtrosItems.push('<li><strong>Sujetos:</strong> ' + escapeHtml(meta.filtros.sujetos) + '</li>');
            if (meta.filtros.carga_voz) filtrosItems.push('<li><strong>Carga VOZ:</strong> ' + escapeHtml(meta.filtros.carga_voz) + '</li>');
            if (meta.filtros.carga_gprs) filtrosItems.push('<li><strong>Carga GPRS:</strong> ' + escapeHtml(meta.filtros.carga_gprs) + '</li>');
            if (meta.filtros.cargas) filtrosItems.push('<li><strong>Cargas (múltiple):</strong> ' + escapeHtml(meta.filtros.cargas) + '</li>');
            if (meta.filtros.fuentes_record) filtrosItems.push('<li><strong>Archivos Record:</strong> ' + escapeHtml(meta.filtros.fuentes_record) + '</li>');
            if (meta.filtros.numero) filtrosItems.push('<li><strong>Número:</strong> ' + escapeHtml(meta.filtros.numero) + '</li>');
            if (meta.filtros.numeros) filtrosItems.push('<li><strong>Números (múltiple):</strong> ' + escapeHtml(meta.filtros.numeros) + '</li>');
            if (meta.filtros.imeis) filtrosItems.push('<li><strong>IMEIs:</strong> ' + escapeHtml(meta.filtros.imeis) + '</li>');
            if (meta.filtros.provincias) filtrosItems.push('<li><strong>Provincias:</strong> ' + escapeHtml(meta.filtros.provincias) + '</li>');
            if (meta.filtros.localidades) filtrosItems.push('<li><strong>Localidades:</strong> ' + escapeHtml(meta.filtros.localidades) + '</li>');
            if (meta.filtros.fecha_desde || meta.filtros.fecha_hasta) {
                filtrosItems.push('<li><strong>Fechas:</strong> ' + escapeHtml(meta.filtros.fecha_desde || '-') + ' a ' + escapeHtml(meta.filtros.fecha_hasta || '-') + '</li>');
            }
            if (meta.filtros.hora_desde || meta.filtros.hora_hasta) {
                filtrosItems.push('<li><strong>Franjas horarias:</strong> ' + escapeHtml(meta.filtros.hora_desde || '-') + ' a ' + escapeHtml(meta.filtros.hora_hasta || '-') + '</li>');
            }
            if (typeof meta.filtros.limit !== 'undefined') {
                filtrosItems.push('<li><strong>Límite de pares:</strong> ' + String(meta.filtros.limit) + '</li>');
            }
        }
        if (!filtrosItems.length) {
            filtrosItems.push('<li>Sin filtros específicos: se analizaron todas las comunicaciones VOZ accesibles al usuario.</li>');
        }
        var filtrosHtml = '<h3>Parámetros del análisis</h3><ul>' + filtrosItems.join('') + '</ul>';

        var encabezadoHtml = '<h2>Datos del informe</h2><ul>' +
            '<li><strong>Unidad:</strong> ' + escapeHtml((meta.unidad || '')) + '</li>' +
            '<li><strong>Usuario:</strong> ' + escapeHtml((meta.usuario || '')) + '</li>' +
            '</ul>';

        var bodyParts = [];
        if (lastInformeData && lastInformeData.parrafo_informe) {
            bodyParts.push('<h2>Informe redactado</h2><div class="informe-parrafo" style="background:#f8f9fa;border-left:4px solid #0d6efd;padding:12px 16px;margin:12px 0;">' + escapeHtml(lastInformeData.parrafo_informe).replace(/\n/g, '<br>') + '</div>');
        }
        bodyParts.push('<div class="resumen-pdf">' + (resumenEl ? resumenEl.innerHTML : '') + (topParesEl ? topParesEl.outerHTML : '') + '</div>');
        if (impactosEl && impactosEl.innerHTML) {
            bodyParts.push('<h3>Impactos en celdas</h3>' + impactosEl.innerHTML);
        }

        var mapaImg = localStorage.getItem('sabana_mapa_ultima_captura');
        if (mapaImg) {
            bodyParts.push('<h3>Mapa de impactos</h3><div class="mapa-pdf"><img src="' + mapaImg + '" style="max-width:100%;border:1px solid #ccc;"></div>');
        }

        var svgEl = document.querySelector('#relaciones-graph svg');
        var svgHtml = '';
        if (svgEl) {
            var clone = svgEl.cloneNode(true);
            clone.setAttribute('width', '700');
            clone.setAttribute('height', '400');
            clone.style.maxWidth = '100%';
            clone.style.height = 'auto';
            svgHtml = '<div class="page-grafo"><div class="grafo-pdf">' + new XMLSerializer().serializeToString(clone) + '</div></div>';
        }

        var content =
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + escapeHtml(titulo) + '</title>' +
            '<style>@page { margin: 2.5cm; } body{font-family:Arial,Segoe UI,sans-serif;font-size:12pt;line-height:1.5;text-align:justify;} h1,h2,h3,h4{font-weight:bold;text-align:left;} h1{font-size:18pt;margin-bottom:8px;} h2{font-size:16pt;margin-top:14px;margin-bottom:6px;} h3{font-size:14pt;margin-top:12px;margin-bottom:6px;} table{border-collapse:collapse;width:100%;margin:8px 0;font-size:11pt;} th,td{border:1px solid #ddd;padding:6px;text-align:left;} th{background:#f5f5f5;font-weight:bold;} .informe-parrafo{line-height:1.5;}</style></head><body>' +
            '<h1>' + escapeHtml(titulo) + '</h1>' +
            '<p style="color:#6c757d;font-size:10pt;">Generado desde Relaciones (' + relContext.label + ').</p>' +
            encabezadoHtml +
            filtrosHtml +
            '<hr>' +
            bodyParts.join('<hr>') +
            (svgHtml ? '<hr><h3>Grafo de relaciones</h3>' + svgHtml : '') +
            '</body></html>';

        var blob = new Blob([content], { type: 'application/msword' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = (titulo || 'informe_relaciones_voz') + '.doc';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function initAnalisisTab() {
        buildAnalisisSummary();
        var tab = document.getElementById('tab-analisis');
        if (tab) {
            tab.addEventListener('shown.bs.tab', function () {
                buildAnalisisSummary();
                if (window.location.search) fetchInformeCompleto();
            });
        }
        var btnInforme = document.getElementById('btn-generar-informe');
        if (btnInforme) {
            btnInforme.addEventListener('click', fetchInformeCompleto);
        }
        var btnPdf = document.getElementById('btn-exportar-pdf');
        if (btnPdf) {
            btnPdf.addEventListener('click', exportToPdf);
        }
        var btnWord = document.getElementById('btn-exportar-word');
        if (btnWord) {
            btnWord.addEventListener('click', exportToWord);
        }
        var selTopN = document.getElementById('analisis-topN');
        if (selTopN) {
            selTopN.addEventListener('change', function () {
                if (lastInformeData) {
                    // Re-render solo la parte de top pares usando datos del informe
                    var topParesEl = document.getElementById('analisis-top-pares');
                    if (topParesEl && lastInformeData.relaciones && lastInformeData.relaciones.length) {
                        var ordenado = lastInformeData.relaciones.slice().sort(function (a, b) {
                            return (b.cantidad || 0) - (a.cantidad || 0);
                        });
                        var topN = getTopN();
                        var subset = (topN && topN > 0) ? ordenado.slice(0, topN) : ordenado;
                        var rows = subset.map(function (r) {
                            var labelA = (r.sujeto_a ? r.sujeto_a + ' (' + r.numero_a + ')' : r.numero_a);
                            var labelB = (r.sujeto_b ? r.sujeto_b + ' (' + r.numero_b + ')' : r.numero_b);
                            return '<tr><td>' + escapeHtml(labelA) + '</td><td>' + escapeHtml(labelB) + '</td><td class=\"text-end\">' + (r.cantidad || 0) + '</td></tr>';
                        }).join('');
                        topParesEl.innerHTML = '<h6 class=\"text-secondary\">Top pares por cantidad de comunicaciones</h6><div class=\"table-responsive\"><table class=\"table table-sm table-bordered\"><thead><tr><th>Número A</th><th>Número B</th><th class=\"text-end\"># Llamadas</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
                    }
                } else {
                    buildAnalisisSummary();
                }
            });
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        initTableSearch();
        initFullscreenToggle();
        initRelContext();
        initGraphTitle();
        initGraphSliders();
        initAnalisisTab();
        initPatronesTab();
        var relaciones = parseRelacionesFromDom();
        updateTabBadges(relaciones);
        initTabPersistence();
        if (relaciones && relaciones.length) {
            buildGraph(relaciones, getGraphOpts());
        }

        var resizeTimer = null;
        window.addEventListener('resize', function () {
            if (!relaciones || !relaciones.length) return;
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                buildGraph(relaciones, getGraphOpts());
            }, 180);
        });
    });
})();


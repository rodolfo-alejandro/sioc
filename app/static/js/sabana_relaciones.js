(function () {
    'use strict';

    var graphState = null;
    var lastInformeData = null;
    var relContext = {
        tipo: 'VOZ',
        label: 'VOZ',
        apiInforme: null,
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
        var container = document.getElementById('relaciones-graph');
        if (!container) return;

        var width = container.clientWidth || 800;
        // Altura responsive: evita SVG demasiado alto en móvil y demasiado bajo en desktop.
        var height = Math.max(260, Math.min(480, Math.round(width * 0.62)));
        var padding = 40;

        // Construir nodos y links a partir de relaciones
        var nodesMap = Object.create(null);
        var links = [];
        var maxCantidad = 0;

        relaciones.forEach(function (r) {
            if (!r || !r.numero_a || !r.numero_b) return;
            var a = String(r.numero_a);
            var b = String(r.numero_b);
            if (!nodesMap[a]) nodesMap[a] = { id: a, label: a, degree: 0, sujeto: r.sujeto_a || null };
            else if (!nodesMap[a].sujeto && r.sujeto_a) nodesMap[a].sujeto = r.sujeto_a;
            if (!nodesMap[b]) nodesMap[b] = { id: b, label: b, degree: 0, sujeto: r.sujeto_b || null };
            else if (!nodesMap[b].sujeto && r.sujeto_b) nodesMap[b].sujeto = r.sujeto_b;
            nodesMap[a].degree += 1;
            nodesMap[b].degree += 1;
            var cant = parseInt(r.cantidad || 0, 10) || 0;
            if (cant > maxCantidad) maxCantidad = cant;
            links.push({ source: a, target: b, cantidad: cant });
        });

        var nodes = Object.keys(nodesMap).map(function (k) { return nodesMap[k]; });
        if (!nodes.length) {
            container.innerHTML = '<p class="text-muted mb-0">No hay datos suficientes para dibujar el grafo.</p>';
            return;
        }

        // Disposición simple en círculo
        var cx = width / 2;
        var cy = height / 2;
        var radius = Math.max(120, Math.min(width, height) / 2 - padding);
        nodes.forEach(function (n, idx) {
            var angle = (2 * Math.PI * idx) / nodes.length;
            n.x = cx + radius * Math.cos(angle);
            n.y = cy + radius * Math.sin(angle);
        });

        // Calcular radios de nodos según grado
        var maxDegree = nodes.reduce(function (m, n) { return Math.max(m, n.degree || 0); }, 0);

        function nodeRadius(deg) {
            if (maxDegree <= 0) return 8;
            return 8 + (deg / maxDegree) * 10;
        }

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
            line.appendChild(createTitle(svgNS, a.id + ' ↔ ' + b.id + ' (' + l.cantidad + ' llamadas)'));
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
            if (!g) return;
            ev.preventDefault();

            var id = g.getAttribute('data-id');
            if (!id || !graphState || !graphState.nodesMap[id]) return;

            drag.active = true;
            drag.nodeId = id;
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
        var nodeScale = 1;
        if (scaleEl) {
            var pct = parseInt(scaleEl.value, 10) || 100;
            nodeScale = Math.max(0.5, Math.min(2, pct / 100));
        }
        var avatarSizeBonus = (avatarEl && parseInt(avatarEl.value, 10)) || 6;
        var edgeLabelFontSize = (edgeLabelEl && parseInt(edgeLabelEl.value, 10)) || 10;
        return { nodeScale: nodeScale, avatarSizeBonus: avatarSizeBonus, edgeLabelFontSize: edgeLabelFontSize };
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
        }
    }

    function buildAnalisisSummary() {
        var relaciones = parseRelacionesFromDom();
        var resumenEl = document.getElementById('analisis-resumen');
        var topParesEl = document.getElementById('analisis-top-pares');
        if (!resumenEl || !topParesEl) return;

        if (!relaciones || relaciones.length === 0) {
            resumenEl.innerHTML = '<p class="text-muted mb-0">No hay datos para analizar. Aplique filtros y recargue.</p>';
            topParesEl.innerHTML = '';
            return;
        }

        var totalPares = relaciones.length;
        var totalComunicaciones = relaciones.reduce(function (sum, r) { return sum + (parseInt(r.cantidad, 10) || 0); }, 0);
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
            '<li><strong>Total comunicaciones (llamadas):</strong> ' + totalComunicaciones + '</li>' +
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
        topParesEl.innerHTML =
            '<h6 class="text-secondary">Top pares por cantidad de comunicaciones</h6>' +
            '<div class="table-responsive"><table class="table table-sm table-bordered"><thead><tr><th>Número A</th><th>Número B</th><th class="text-end"># Llamadas</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    }

    function renderInformeCompleto(data) {
        lastInformeData = data;
        var narrativoEl = document.getElementById('analisis-informe-narrativo');
        var resumenEl = document.getElementById('analisis-resumen');
        var impactosEl = document.getElementById('analisis-impactos-celdas');
        if (!data) return;

        if (narrativoEl && data.parrafo_informe) {
            narrativoEl.innerHTML =
                '<h6 class="text-secondary border-bottom pb-2">Informe redactado (para presentación)</h6>' +
                '<div class="informe-parrafo bg-light border-start border-4 border-primary px-3 py-2 small lh-base">' +
                escapeHtml(data.parrafo_informe).replace(/\n/g, '<br>') +
                '</div>';
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
            impactosEl.innerHTML = '<p class="text-muted small mb-0">No hay impactos en celdas con coordenadas para los números del informe, o genere el informe completo.</p>';
        }
    }

    function fetchInformeCompleto() {
        var btn = document.getElementById('btn-generar-informe');
        var qs = window.location.search || '';
        var api = relContext.apiInforme || (window.location.pathname.replace(/\/relaciones\/?$/, '') + '/api/informe-voz');
        var url = api + (qs ? qs : '?limit=200');
        if (btn) btn.disabled = true;
        fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.error) throw new Error(data.error);
                renderInformeCompleto(data);
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
            if (meta.filtros.carga_voz) filtrosItems.push('<li><strong>Carga VOZ:</strong> ' + escapeHtml(meta.filtros.carga_voz) + '</li>');
            if (meta.filtros.numero) filtrosItems.push('<li><strong>Número (A/B):</strong> ' + escapeHtml(meta.filtros.numero) + '</li>');
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
            if (meta.filtros.carga_voz) filtrosItems.push('<li><strong>Carga:</strong> ' + escapeHtml(meta.filtros.carga_voz) + '</li>');
            if (meta.filtros.numero) filtrosItems.push('<li><strong>Número:</strong> ' + escapeHtml(meta.filtros.numero) + '</li>');
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
            '<p style="color:#6c757d;font-size:10pt;">Generado desde Relaciones (VOZ).</p>' +
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
        var relaciones = parseRelacionesFromDom();
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


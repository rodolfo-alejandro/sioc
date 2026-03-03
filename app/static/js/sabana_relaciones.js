(function () {
    'use strict';

    var graphState = null;

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

    function buildGraph(relaciones) {
        var container = document.getElementById('relaciones-graph');
        if (!container) return;

        var width = container.clientWidth || 800;
        var height = 480;
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
        });

        // Dibujar nodos
        nodes.forEach(function (n) {
            var group = document.createElementNS(svgNS, 'g');
            group.setAttribute('class', 'rel-node');
            group.setAttribute('data-id', n.id);

            var rNode = nodeRadius(n.degree);

            // Imagen dentro del nodo (clip circle) si hay sujeto con imagen
            if (n.sujeto && n.sujeto.imagen_url) {
                var clipId = 'rel-clip-' + n.id.replace(/[^a-zA-Z0-9_-]/g, '_');
                var clip = document.createElementNS(svgNS, 'clipPath');
                clip.setAttribute('id', clipId);
                var clipCircle = document.createElementNS(svgNS, 'circle');
                clipCircle.setAttribute('cx', n.x);
                clipCircle.setAttribute('cy', n.y);
                clipCircle.setAttribute('r', rNode);
                clip.appendChild(clipCircle);
                svg.querySelector('defs').appendChild(clip);

                var img = document.createElementNS(svgNS, 'image');
                img.setAttributeNS('http://www.w3.org/1999/xlink', 'href', n.sujeto.imagen_url);
                img.setAttribute('x', n.x - rNode);
                img.setAttribute('y', n.y - rNode);
                img.setAttribute('width', rNode * 2);
                img.setAttribute('height', rNode * 2);
                img.setAttribute('preserveAspectRatio', 'xMidYMid slice');
                img.setAttribute('clip-path', 'url(#' + clipId + ')');
                group.appendChild(img);
                group.setAttribute('data-clip-id', clipId);
            }

            var circle = document.createElementNS(svgNS, 'circle');
            circle.setAttribute('cx', n.x);
            circle.setAttribute('cy', n.y);
            circle.setAttribute('r', rNode);
            circle.setAttribute('fill', n.sujeto && n.sujeto.imagen_url ? 'none' : '#0d6efd');
            circle.setAttribute('stroke', '#ffffff');
            circle.setAttribute('stroke-width', '2');
            group.appendChild(circle);

            var titleLabel = n.id;
            if (n.sujeto && n.sujeto.display) {
                titleLabel = n.id + ' - ' + n.sujeto.display;
            }
            group.appendChild(createTitle(svgNS, titleLabel + ' (' + n.degree + ' relaciones)'));

            var text = document.createElementNS(svgNS, 'text');
            text.setAttribute('x', n.x);
            text.setAttribute('y', n.y + rNode + 16);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('font-size', '11');
            text.setAttribute('fill', '#212529');
            text.textContent = (n.sujeto && n.sujeto.display) ? n.sujeto.display : n.label;
            group.appendChild(text);

            svg.appendChild(group);
        });

        container.innerHTML = '';
        container.appendChild(svg);

        // Guardar estado global para drag y otros usos
        graphState = {
            svg: svg,
            nodesMap: nodesMap
        };

        // Resaltar al hacer click en un nodo
        container.addEventListener('click', function (ev) {
            var g = ev.target.closest('.rel-node');
            if (!g) return;
            var id = g.getAttribute('data-id');
            if (!id) return;
            highlightNode(svg, id);
            highlightRowsForNode(id);
        });

        // Soporte de arrastre simple de nodos
        var drag = { active: false, nodeId: null, offsetX: 0, offsetY: 0 };

        svg.addEventListener('mousedown', function (ev) {
            var g = ev.target.closest('.rel-node');
            if (!g) return;
            ev.preventDefault();
            var id = g.getAttribute('data-id');
            if (!id || !graphState || !graphState.nodesMap[id]) return;
            drag.active = true;
            drag.nodeId = id;
            drag.startX = ev.clientX;
            drag.startY = ev.clientY;
        });

        svg.addEventListener('mousemove', function (ev) {
            if (!drag.active || !graphState || !graphState.nodesMap[drag.nodeId]) return;
            ev.preventDefault();
            var n = graphState.nodesMap[drag.nodeId];
            var dx = ev.clientX - drag.startX;
            var dy = ev.clientY - drag.startY;
            var newX = n.x + dx;
            var newY = n.y + dy;
            n.x = newX;
            n.y = newY;
            drag.startX = ev.clientX;
            drag.startY = ev.clientY;
            // actualizar nodo (circle + text + imagen/clip)
            svg.querySelectorAll('.rel-node').forEach(function (g) {
                var id = g.getAttribute('data-id');
                if (id !== drag.nodeId) return;
                var circle = g.querySelector('circle');
                var text = g.querySelector('text');
                var img = g.querySelector('image');
                if (circle) {
                    circle.setAttribute('cx', n.x);
                    circle.setAttribute('cy', n.y);
                }
                if (text) {
                    var r = parseFloat(circle ? circle.getAttribute('r') : '10') || 10;
                    text.setAttribute('x', n.x);
                    text.setAttribute('y', n.y + r + 16);
                }
                if (img) {
                    var r2 = parseFloat(circle ? circle.getAttribute('r') : '10') || 10;
                    img.setAttribute('x', n.x - r2);
                    img.setAttribute('y', n.y - r2);
                    img.setAttribute('width', r2 * 2);
                    img.setAttribute('height', r2 * 2);
                }
                var clipId = g.getAttribute('data-clip-id');
                if (clipId) {
                    var clipCircle = svg.querySelector('#' + clipId + ' circle');
                    if (clipCircle) {
                        clipCircle.setAttribute('cx', n.x);
                        clipCircle.setAttribute('cy', n.y);
                    }
                }
            });
            // actualizar líneas que tocan el nodo
            svg.querySelectorAll('line').forEach(function (l) {
                var a = l.getAttribute('data-source');
                var b = l.getAttribute('data-target');
                if (a === drag.nodeId) {
                    l.setAttribute('x1', n.x);
                    l.setAttribute('y1', n.y);
                }
                if (b === drag.nodeId) {
                    l.setAttribute('x2', n.x);
                    l.setAttribute('y2', n.y);
                }
            });
        });

        svg.addEventListener('mouseup', function () {
            drag.active = false;
            drag.nodeId = null;
        });
        svg.addEventListener('mouseleave', function () {
            drag.active = false;
            drag.nodeId = null;
        });
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
                // Nodo con avatar: fondo transparente, borde blanco normal
                circle.setAttribute('fill', 'none');
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
        svg.querySelectorAll('line').forEach(function (l) {
            l.setAttribute('stroke', '#ced4da');
            l.setAttribute('opacity', '0.7');
        });

        // Destacar el seleccionado
        svg.querySelectorAll('.rel-node').forEach(function (g) {
            var id = g.getAttribute('data-id');
            var circle = g.querySelector('circle');
            if (!circle) return;
            var hasImg = !!g.querySelector('image');
            if (id === nodeId) {
                if (hasImg) {
                    // Resaltar borde del avatar
                    circle.setAttribute('stroke', '#dc3545');
                    circle.setAttribute('stroke-width', '4');
                    circle.setAttribute('fill', 'none');
                } else {
                    circle.setAttribute('fill', '#dc3545');
                    circle.setAttribute('stroke', '#ffffff');
                    circle.setAttribute('stroke-width', '2');
                }
                circle.setAttribute('opacity', '1');
            } else {
                circle.setAttribute('opacity', '0.4');
            }
        });

        svg.querySelectorAll('line').forEach(function (l) {
            var a = l.getAttribute('data-source');
            var b = l.getAttribute('data-target');
            if (a === nodeId || b === nodeId) {
                l.setAttribute('stroke', '#0d6efd');
                l.setAttribute('opacity', '1');
            } else {
                l.setAttribute('opacity', '0.2');
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
            var a = aCell ? (aCell.textContent || '').trim() : '';
            var b = bCell ? (bCell.textContent || '').trim() : '';
            if (a === nodeId || b === nodeId) {
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
            var icon = btn.querySelector('i');
            if (icon) icon.className = isFs ? 'bi bi-fullscreen-exit' : 'bi bi-arrows-fullscreen';
            btn.textContent = isFs ? ' Salir de pantalla completa' : ' Pantalla completa';
            btn.prepend(icon);
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initTableSearch();
        initFullscreenToggle();
        var relaciones = parseRelacionesFromDom();
        if (relaciones && relaciones.length) {
            buildGraph(relaciones);
        }
    });
})();


"""
Generación de informe PDF para Llamadas SE (servidor).
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from app.models.analisis_llamadas_se import LlamadaSE

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except Exception:
    SimpleDocTemplate = None


INFORME_COLUMN_DEFS: dict[str, tuple[str, Callable[[LlamadaSE], str]]] = {
    "fecha": ("Fecha", lambda r: r.llamada_fecha.strftime("%d/%m/%Y") if r.llamada_fecha else "—"),
    "hora": ("Hora", lambda r: r.llamada_fecha.strftime("%H:%M") if r.llamada_fecha else "—"),
    "alerta": ("Alerta", lambda r: (r.llamada_alerta_desc or "—")[:120]),
    "barrio": ("Barrio", lambda r: (r.llamada_barrio_nombre or "—")[:80]),
    "localidad": ("Localidad", lambda r: (r.llamada_local_nombre or "—")[:80]),
    "lugar": ("Lugar", lambda r: (r.llamada_detalle or "—")[:350]),
    "dependencia": ("Dependencia", lambda r: (r.llamada_dep_nombre or "—")[:100]),
    "dinar": ("División (DINAR)", lambda r: (r.llamada_jurisdiccion or "—")[:80]),
    "semana": ("Semana", lambda r: (r.llamada_semana or "—")[:20]),
    "dia_semana": ("Día", lambda r: (r.llamada_dia_semana or "—")[:20]),
    "coords": ("Coordenadas", lambda r: (
        f"{r.llamada_coordx:.6f}, {r.llamada_coordy:.6f}"
        if r.llamada_coordx is not None and r.llamada_coordy is not None
        else "—"
    )),
}

DEFAULT_COLUMNS = ["fecha", "hora", "alerta", "barrio", "localidad", "lugar", "dependencia", "dinar"]


def _now_local_str(fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Misma lógica que el filtro Jinja localtime (TIMEZONE_OFFSET_HOURS, ej. -3 Salta)."""
    try:
        offset = int(os.environ.get("TIMEZONE_OFFSET_HOURS", "-3"))
    except (TypeError, ValueError):
        offset = -3
    return (datetime.utcnow() + timedelta(hours=offset)).strftime(fmt)


def _color_alerta_hex(desc: str | None) -> str:
    s = (desc or "").lower()
    if "venta" in s:
        return "#dc3545"
    if "consumo" in s:
        return "#198754"
    if "sospecha" in s:
        return "#ffc107"
    return "#0d6efd"


def _escape_pdf_text(val: str) -> str:
    return (
        str(val or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _auto_zoom(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> int:
    span = max(max_lat - min_lat, max_lon - min_lon)
    if span < 0.015:
        return 14
    if span < 0.04:
        return 13
    if span < 0.12:
        return 12
    if span < 0.35:
        return 11
    return 10


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    import math
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_bounds(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    import math
    n = 2 ** zoom
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def _add_osm_basemap(ax, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> bool:
    """Descarga tiles OSM (como Leaflet en la web) y los usa de fondo."""
    import urllib.request
    from PIL import Image as PILImage

    pad_lat = max((max_lat - min_lat) * 0.12, 0.004)
    pad_lon = max((max_lon - min_lon) * 0.12, 0.004)
    min_lat -= pad_lat
    max_lat += pad_lat
    min_lon -= pad_lon
    max_lon += pad_lon

    zoom = _auto_zoom(min_lat, max_lat, min_lon, max_lon)
    x0, y0 = _latlon_to_tile(max_lat, min_lon, zoom)
    x1, y1 = _latlon_to_tile(min_lat, max_lon, zoom)

    tw, th = 256, 256
    cols = x1 - x0 + 1
    rows_n = y1 - y0 + 1
    if cols * rows_n > 80:
        return False

    mosaic = PILImage.new("RGB", (cols * tw, rows_n * th))
    headers = {"User-Agent": "SIOC-LlamadasSE/1.0 (informe PDF)"}
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                tile = PILImage.open(io.BytesIO(resp.read())).convert("RGB")
            mosaic.paste(tile, ((x - x0) * tw, (y - y0) * th))

    lon_min, _, _, lat_max = _tile_bounds(x0, y0, zoom)
    _, lat_min, lon_max, _ = _tile_bounds(x1, y1, zoom)
    ax.imshow(mosaic, extent=[lon_min, lon_max, lat_min, lat_max], aspect="auto", zorder=0)
    ax.set_xlim(min_lon, max_lon)
    ax.set_ylim(min_lat, max_lat)
    return True


def _legend_label(hex_color: str) -> str:
    return {
        "#dc3545": "Venta",
        "#198754": "Consumo",
        "#ffc107": "Sospecha",
        "#0d6efd": "Otras alertas",
    }.get(hex_color.lower(), "Otros")


def build_map_png(rows: Iterable[LlamadaSE]) -> io.BytesIO | None:
    if plt is None:
        return None
    points: list[tuple[float, float, str]] = []
    for r in rows:
        if r.llamada_coordx is None or r.llamada_coordy is None:
            continue
        points.append((r.llamada_coordx, r.llamada_coordy, _color_alerta_hex(r.llamada_alerta_desc)))
    if not points:
        return None

    fig, ax = plt.subplots(figsize=(12, 8), dpi=120)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)

    by_color: dict[str, list[tuple[float, float]]] = {}
    for lat, lon, col in points:
        by_color.setdefault(col, []).append((lon, lat))

    try:
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        if _add_osm_basemap(ax, min(lats), max(lats), min(lons), max(lons)):
            for col, pts in by_color.items():
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                ax.scatter(
                    xs, ys, c=col, s=32, alpha=0.92, linewidths=0.6,
                    edgecolors="white", label=_legend_label(col), zorder=5,
                )
        else:
            raise RuntimeError("demasiados tiles")
    except Exception:
        for col, pts in by_color.items():
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.scatter(
                xs, ys, c=col, s=14, alpha=0.85, linewidths=0.4,
                edgecolors="white", label=_legend_label(col), zorder=5,
            )
        ax.set_facecolor("#eef2f7")
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        pad_lat = max((max(lats) - min(lats)) * 0.1, 0.005)
        pad_lon = max((max(lons) - min(lons)) * 0.1, 0.005)
        ax.set_xlim(min(lons) - pad_lon, max(lons) + pad_lon)
        ax.set_ylim(min(lats) - pad_lat, max(lats) + pad_lat)

    ax.set_axis_off()
    if len(by_color) <= 6:
        ax.legend(loc="upper right", fontsize=7, framealpha=0.92, markerscale=1.2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.04, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _kpis(rows: list[LlamadaSE]) -> dict[str, int]:
    total = len(rows)
    con_coords = sum(
        1 for r in rows if r.llamada_coordx is not None and r.llamada_coordy is not None
    )
    venta = sum(1 for r in rows if "venta" in (r.llamada_alerta_desc or "").lower())
    consumo = sum(1 for r in rows if "consumo" in (r.llamada_alerta_desc or "").lower())
    return {"total": total, "con_coords": con_coords, "venta": venta, "consumo": consumo}


def build_informe_pdf(
    rows: list[LlamadaSE],
    *,
    filters_lines: list[str],
    columns: list[str],
    include_cover: bool = True,
    include_map: bool = True,
    include_table: bool = True,
    unidad_nombre: str = "",
    usuario_nombre: str = "",
) -> bytes:
    if SimpleDocTemplate is None:
        raise RuntimeError("Falta dependencia reportlab en el servidor.")

    valid_cols = [c for c in columns if c in INFORME_COLUMN_DEFS]
    if include_table and not valid_cols:
        valid_cols = DEFAULT_COLUMNS.copy()

    buf = io.BytesIO()
    page_size = landscape(A4) if include_table else A4
    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Informe Llamadas SE",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AlsTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=10,
        alignment=TA_CENTER,
    )
    sub_style = ParagraphStyle(
        "AlsSub",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
    )
    center_style = ParagraphStyle(
        "AlsCenter",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        alignment=TA_CENTER,
    )
    cell_style = ParagraphStyle(
        "AlsCell",
        parent=styles["Normal"],
        fontSize=6.5,
        leading=8,
        alignment=TA_LEFT,
    )
    header_cell = ParagraphStyle(
        "AlsHeader",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.white,
    )

    story: list[Any] = []
    stats = _kpis(rows)
    now_txt = _now_local_str()

    if include_cover:
        story.append(Paragraph("Informe - Llamadas SE", title_style))
        story.append(Spacer(1, 0.2 * cm))
        meta = [
            f"<b>Generado:</b> {_escape_pdf_text(now_txt)}",
            f"<b>Unidad:</b> {_escape_pdf_text(unidad_nombre or '—')}",
            f"<b>Usuario:</b> {_escape_pdf_text(usuario_nombre or '—')}",
        ]
        for line in meta:
            story.append(Paragraph(line, sub_style))
        story.append(Spacer(1, 0.35 * cm))
        if filters_lines:
            for fl in filters_lines:
                story.append(Paragraph(_escape_pdf_text(fl), center_style))
        else:
            story.append(Paragraph("Sin filtros adicionales (dataset completo de la unidad)", center_style))
        story.append(Spacer(1, 0.4 * cm))
        kpi_data = [
            ["Total llamadas", "Alerta venta", "Alerta consumo"],
            [
                str(stats["total"]),
                str(stats["venta"]),
                str(stats["consumo"]),
            ],
        ]
        kpi_table = Table(kpi_data, colWidths=[5 * cm, 5 * cm, 5 * cm])
        kpi_table.hAlign = "CENTER"
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#198754")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8f9fa")),
        ]))
        story.append(kpi_table)
        story.append(PageBreak())

    if include_map:
        map_buf = build_map_png(rows)
        if map_buf:
            img_w = 25 * cm if include_table else 18 * cm
            img_h = 14 * cm if include_table else 11.5 * cm
            img = Image(map_buf, width=img_w, height=img_h)
            story.append(Paragraph("MAPA", title_style))
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(
                f"Puntos en mapa: <b>{stats['con_coords']}</b> "
                f"(llamadas sin coordenadas: {stats['total'] - stats['con_coords']})",
                center_style,
            ))
            story.append(Spacer(1, 0.1 * cm))
            story.append(img)
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(
                "<font size='7'>Leyenda: rojo = venta, verde = consumo, amarillo = sospecha, azul = otras alertas.</font>",
                center_style,
            ))
        else:
            story.append(Paragraph("MAPA", title_style))
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph("No hay puntos con coordenadas en el conjunto filtrado.", sub_style))
        story.append(PageBreak())

    if include_table and valid_cols:
        story.append(Paragraph(f"Detalle de llamadas ({stats['total']} registros)", title_style))
        story.append(Spacer(1, 0.15 * cm))

        headers = [Paragraph(_escape_pdf_text(INFORME_COLUMN_DEFS[c][0]), header_cell) for c in valid_cols]
        table_data: list[list[Any]] = [headers]
        getters = [INFORME_COLUMN_DEFS[c][1] for c in valid_cols]

        for r in rows:
            row_cells = []
            for fn in getters:
                txt = _escape_pdf_text(fn(r))
                row_cells.append(Paragraph(txt, cell_style))
            table_data.append(row_cells)

        col_count = len(valid_cols)
        page_w = landscape(A4)[0] - 2 * cm
        col_w = page_w / max(col_count, 1)
        if "lugar" in valid_cols:
            idx = valid_cols.index("lugar")
            extra = col_w * 0.6
            widths = [col_w] * col_count
            widths[idx] = col_w + extra
            total = sum(widths)
            widths = [w * page_w / total for w in widths]
        else:
            widths = [col_w] * col_count

        tbl = Table(table_data, colWidths=widths, repeatRows=1, splitByRow=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(tbl)

    if not story:
        story.append(Paragraph("Informe vacío: no se seleccionó ninguna sección.", sub_style))

    doc.build(story)
    buf.seek(0)
    return buf.read()

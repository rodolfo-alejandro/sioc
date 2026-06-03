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


def build_map_png(rows: Iterable[LlamadaSE]) -> io.BytesIO | None:
    if plt is None:
        return None
    points = []
    for r in rows:
        if r.llamada_coordx is None or r.llamada_coordy is None:
            continue
        points.append((r.llamada_coordx, r.llamada_coordy, _color_alerta_hex(r.llamada_alerta_desc)))
    if not points:
        return None

    fig, ax = plt.subplots(figsize=(11.5, 7.5), dpi=110)
    by_color: dict[str, list[tuple[float, float]]] = {}
    for lat, lon, col in points:
        by_color.setdefault(col, []).append((lon, lat))
    for col, pts in by_color.items():
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.scatter(xs, ys, c=col, s=10, alpha=0.75, linewidths=0, label=col)

    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    ax.set_title(f"Llamadas SE — {len(points)} puntos georreferenciados")
    ax.grid(True, alpha=0.25, linestyle="--")
    if len(by_color) <= 6:
        ax.legend(loc="upper right", fontsize=7, markerscale=2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
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
            story.append(Paragraph("Mapa de puntos (según filtros)", title_style))
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(
                f"Puntos en mapa: <b>{stats['con_coords']}</b> "
                f"(llamadas sin coordenadas: {stats['total'] - stats['con_coords']})",
                sub_style,
            ))
            story.append(Spacer(1, 0.15 * cm))
            story.append(img)
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(
                "<font size='7'>Leyenda: rojo = venta, verde = consumo, amarillo = sospecha, azul = otras alertas.</font>",
                sub_style,
            ))
        else:
            story.append(Paragraph("Mapa de puntos", title_style))
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

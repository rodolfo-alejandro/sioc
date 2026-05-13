from __future__ import annotations

import csv
import json
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, inspect

from app.blueprints.analisis_llamadas_se import bp
from app.extensions import db
from app.models.analisis_llamadas_se import LlamadaSE


_schema_checked = False


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("LLAMADAS_SE_VIEW")


def _can_import() -> bool:
    return _is_superadmin() or current_user.has_permission("LLAMADAS_SE_IMPORT")


def _can_export() -> bool:
    return _is_superadmin() or current_user.has_permission("LLAMADAS_SE_EXPORT")


def _can_dashboard() -> bool:
    return _is_superadmin() or current_user.has_permission("LLAMADAS_SE_DASHBOARD")


def _can_map() -> bool:
    return _is_superadmin() or current_user.has_permission("LLAMADAS_SE_MAPA")


def _ensure_schema():
    global _schema_checked
    if _schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    if LlamadaSE.__tablename__ not in existing:
        LlamadaSE.__table__.create(bind=db.engine)
    _schema_checked = True


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _parse_int(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return int(float(v))
    except Exception:
        return None


def _parse_dt(v):
    """Fechas como en Argentina: día/mes/año (no mes/día como pandas por defecto)."""
    try:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        d = pd.to_datetime(v, errors="coerce", dayfirst=True, format="mixed")
        if pd.isna(d):
            return None
        return d.to_pydatetime()
    except Exception:
        return None


def _parse_float(v):
    try:
        if v is None:
            return None
        s = str(v).strip().replace(",", ".")
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _base_q():
    return LlamadaSE.query.filter(LlamadaSE.unidad_id == current_user.unidad_id, LlamadaSE.activo.is_(True))


def _get_list_arg(name: str) -> list[str]:
    vals: list[str] = []
    for raw in request.args.getlist(name):
        s = _clean(raw)
        if s:
            vals.append(s)
    return sorted(set(vals))


def _selected():
    return {
        "q": _clean(request.args.get("q")) or "",
        "fecha_desde": _clean(request.args.get("fecha_desde")) or "",
        "fecha_hasta": _clean(request.args.get("fecha_hasta")) or "",
        "semana": _clean(request.args.get("semana")) or "",
        "dia_semana": _clean(request.args.get("dia_semana")) or "",
        "alertas": _get_list_arg("alerta[]"),
        "jurisdicciones": _get_list_arg("jurisdiccion[]"),
        "deps": _get_list_arg("dep[]"),
        "localidades": _get_list_arg("localidad[]"),
        "barrios": _get_list_arg("barrio[]"),
    }


def _apply_filters(q):
    s = _selected()
    if s["q"]:
        p = f"%{s['q']}%"
        q = q.filter(
            (LlamadaSE.llamada_detalle.ilike(p))
            | (LlamadaSE.llamada_alerta_desc.ilike(p))
            | (LlamadaSE.llamada_dep_nombre.ilike(p))
            | (LlamadaSE.llamada_barrio_nombre.ilike(p))
            | (LlamadaSE.llamada_local_nombre.ilike(p))
            | (LlamadaSE.llamada_jurisdiccion.ilike(p))
        )
    if s["fecha_desde"]:
        fd = _parse_dt(s["fecha_desde"])
        if fd:
            q = q.filter(LlamadaSE.llamada_fecha >= fd)
    if s["fecha_hasta"]:
        fh = _parse_dt(s["fecha_hasta"])
        if fh:
            fh = fh.replace(hour=23, minute=59, second=59, microsecond=999999)
            q = q.filter(LlamadaSE.llamada_fecha <= fh)
    if s["semana"]:
        q = q.filter(LlamadaSE.llamada_semana == s["semana"])
    if s["dia_semana"]:
        q = q.filter(LlamadaSE.llamada_dia_semana == s["dia_semana"])
    if s["alertas"]:
        q = q.filter(LlamadaSE.llamada_alerta_desc.in_(s["alertas"]))
    if s["jurisdicciones"]:
        q = q.filter(LlamadaSE.llamada_jurisdiccion.in_(s["jurisdicciones"]))
    if s["deps"]:
        q = q.filter(LlamadaSE.llamada_dep_nombre.in_(s["deps"]))
    if s["localidades"]:
        q = q.filter(LlamadaSE.llamada_local_nombre.in_(s["localidades"]))
    if s["barrios"]:
        q = q.filter(LlamadaSE.llamada_barrio_nombre.in_(s["barrios"]))
    return q


def _filter_options():
    q = _apply_filters(_base_q())
    return {
        "alertas": [r[0] for r in q.with_entities(LlamadaSE.llamada_alerta_desc).distinct().order_by(LlamadaSE.llamada_alerta_desc.asc()).all() if r[0]],
        "jurisdicciones": [r[0] for r in q.with_entities(LlamadaSE.llamada_jurisdiccion).distinct().order_by(LlamadaSE.llamada_jurisdiccion.asc()).all() if r[0]],
        "deps": [r[0] for r in q.with_entities(LlamadaSE.llamada_dep_nombre).distinct().order_by(LlamadaSE.llamada_dep_nombre.asc()).all() if r[0]],
        "localidades": [r[0] for r in q.with_entities(LlamadaSE.llamada_local_nombre).distinct().order_by(LlamadaSE.llamada_local_nombre.asc()).all() if r[0]],
        "barrios": [r[0] for r in q.with_entities(LlamadaSE.llamada_barrio_nombre).distinct().order_by(LlamadaSE.llamada_barrio_nombre.asc()).all() if r[0]],
        "semanas": [r[0] for r in q.with_entities(LlamadaSE.llamada_semana).distinct().order_by(LlamadaSE.llamada_semana.asc()).all() if r[0]],
        "dias_semana": [r[0] for r in q.with_entities(LlamadaSE.llamada_dia_semana).distinct().order_by(LlamadaSE.llamada_dia_semana.asc()).all() if r[0]],
    }


def _import_from_text(text: str, replace_all: bool = False):
    if not text.strip():
        return {"error": "Archivo vacío."}
    reader = csv.DictReader(StringIO(text), delimiter=";")
    expected = {
        "llamada_fecha", "llamada_alerta_id", "llamada_alerta_desc", "llamada_CoordX", "llamada_coordY",
        "llamada_detalle", "llamada_dep_id", "llamada_dep_nombre", "llamada_barrio_id", "llamada_barrio_nombre",
        "llamada_local_id", "llamada_local_nombre", "llamada_jurisdiccion", "llamada_mes", "llamada_semana", "llamada_dia_semana",
    }
    fields = set(reader.fieldnames or [])
    miss = sorted([x for x in expected if x not in fields])
    if miss:
        return {"error": f"Faltan columnas: {', '.join(miss)}"}

    deleted = 0
    if replace_all:
        deleted = LlamadaSE.query.filter(LlamadaSE.unidad_id == current_user.unidad_id).delete()
        db.session.commit()

    imported = 0
    skipped = 0
    now = datetime.utcnow()
    for row in reader:
        fecha = _parse_dt(row.get("llamada_fecha"))
        detalle = _clean(row.get("llamada_detalle"))
        if not fecha and not detalle:
            skipped += 1
            continue
        obj = LlamadaSE(
            unidad_id=current_user.unidad_id,
            creado_por=current_user.id,
            fecha_importacion=now,
            llamada_fecha=fecha,
            llamada_alerta_id=_parse_int(row.get("llamada_alerta_id")),
            llamada_alerta_desc=_clean(row.get("llamada_alerta_desc")),
            llamada_coordx=_parse_float(row.get("llamada_CoordX")),
            llamada_coordy=_parse_float(row.get("llamada_coordY")),
            llamada_detalle=detalle,
            llamada_dep_id=_parse_int(row.get("llamada_dep_id")),
            llamada_dep_nombre=_clean(row.get("llamada_dep_nombre")),
            llamada_barrio_id=_parse_int(row.get("llamada_barrio_id")),
            llamada_barrio_nombre=_clean(row.get("llamada_barrio_nombre")),
            llamada_local_id=_parse_int(row.get("llamada_local_id")),
            llamada_local_nombre=_clean(row.get("llamada_local_nombre")),
            llamada_jurisdiccion=_clean(row.get("llamada_jurisdiccion")),
            llamada_mes=_clean(row.get("llamada_mes")),
            llamada_semana=_clean(row.get("llamada_semana")),
            llamada_dia_semana=_clean(row.get("llamada_dia_semana")),
            activo=True,
        )
        db.session.add(obj)
        imported += 1
    db.session.commit()
    return {"importados": imported, "omitidos": skipped, "eliminados_previos": deleted}


def _dashboard_data(q):
    total = q.count()
    con_coords = q.filter(LlamadaSE.llamada_coordx.isnot(None), LlamadaSE.llamada_coordy.isnot(None)).count()
    venta = q.filter(LlamadaSE.llamada_alerta_desc.ilike("%venta%")).count()
    consumo = q.filter(LlamadaSE.llamada_alerta_desc.ilike("%consumo%")).count()

    alertas = (
        q.with_entities(LlamadaSE.llamada_alerta_desc, func.count(LlamadaSE.id))
        .group_by(LlamadaSE.llamada_alerta_desc)
        .order_by(func.count(LlamadaSE.id).desc())
        .all()
    )
    top_barrios = (
        q.with_entities(LlamadaSE.llamada_barrio_nombre, func.count(LlamadaSE.id))
        .group_by(LlamadaSE.llamada_barrio_nombre)
        .order_by(func.count(LlamadaSE.id).desc())
        .limit(10)
        .all()
    )
    top_deps = (
        q.with_entities(LlamadaSE.llamada_dep_nombre, func.count(LlamadaSE.id))
        .group_by(LlamadaSE.llamada_dep_nombre)
        .order_by(func.count(LlamadaSE.id).desc())
        .limit(10)
        .all()
    )
    diarios = (
        q.with_entities(func.date(LlamadaSE.llamada_fecha), func.count(LlamadaSE.id))
        .group_by(func.date(LlamadaSE.llamada_fecha))
        .order_by(func.date(LlamadaSE.llamada_fecha))
        .all()
    )
    return {
        "kpis": {"total": total, "con_coords": con_coords, "venta": venta, "consumo": consumo},
        "alertas": [{"label": r[0] or "Sin dato", "value": int(r[1] or 0)} for r in alertas],
        "barrios": [{"label": r[0] or "Sin dato", "value": int(r[1] or 0)} for r in top_barrios],
        "deps": [{"label": r[0] or "Sin dato", "value": int(r[1] or 0)} for r in top_deps],
        "diario": [{"label": str(r[0]), "value": int(r[1] or 0)} for r in diarios if r[0]],
    }


def _serialize_dashboard_row(r: LlamadaSE) -> dict:
    return {
        "id": r.id,
        "llamada_fecha": r.llamada_fecha.isoformat() if r.llamada_fecha else "",
        "llamada_alerta_desc": r.llamada_alerta_desc or "",
        "llamada_detalle": r.llamada_detalle or "",
        "llamada_dep_nombre": r.llamada_dep_nombre or "",
        "llamada_barrio_nombre": r.llamada_barrio_nombre or "",
        "llamada_local_nombre": r.llamada_local_nombre or "",
        "llamada_jurisdiccion": r.llamada_jurisdiccion or "",
        "llamada_mes": r.llamada_mes or "",
        "llamada_semana": r.llamada_semana or "",
        "llamada_dia_semana": r.llamada_dia_semana or "",
        "llamada_coordx": r.llamada_coordx,
        "llamada_coordy": r.llamada_coordy,
    }


@bp.before_request
@login_required
def _before():
    _ensure_schema()


@bp.route("/")
def index():
    if not _can_view():
        abort(403)
    return redirect(url_for("analisis_llamadas_se.listado"))


@bp.route("/importar", methods=["GET", "POST"])
def importar():
    if not _can_import():
        abort(403)
    if request.method == "POST":
        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccione un CSV.", "warning")
            return redirect(url_for("analisis_llamadas_se.importar"))
        if not f.filename.lower().endswith(".csv"):
            flash("Formato inválido.", "danger")
            return redirect(url_for("analisis_llamadas_se.importar"))
        replace_all = bool(request.form.get("replace_all"))
        raw = f.read()
        res = _import_from_text(raw.decode("utf-8-sig", errors="replace"), replace_all=replace_all)
        if res.get("error"):
            flash(res["error"], "danger")
        else:
            msg = (
                f"Importación OK. Importados: {res['importados']}, omitidos: {res['omitidos']}. "
                "La carga quedó compartida para toda la dependencia."
            )
            if int(res.get("eliminados_previos") or 0) > 0:
                msg = f"Se eliminaron {res['eliminados_previos']} previos. " + msg
            flash(msg, "success")
        return redirect(url_for("analisis_llamadas_se.importar"))
    total = _base_q().count()
    ultima = _base_q().order_by(LlamadaSE.fecha_importacion.desc(), LlamadaSE.id.desc()).first()
    return render_template("analisis_llamadas_se/importar.html", total=total, ultima=ultima)


@bp.route("/importar/base", methods=["POST"])
def importar_base():
    if not _can_import():
        abort(403)
    base_file = Path(__file__).resolve().parents[3] / "llamadas_se_2026.csv"
    if not base_file.exists():
        flash("No se encontró llamadas_se_2026.csv", "danger")
        return redirect(url_for("analisis_llamadas_se.importar"))
    text = base_file.read_text(encoding="utf-8-sig", errors="replace")
    replace_all = bool(request.form.get("replace_all"))
    res = _import_from_text(text, replace_all=replace_all)
    if res.get("error"):
        flash(res["error"], "danger")
    else:
        flash(
            (
                f"Base importada. Importados: {res['importados']}, omitidos: {res['omitidos']}. "
                "La carga quedó compartida para toda la dependencia."
            ),
            "success",
        )
    return redirect(url_for("analisis_llamadas_se.importar"))


@bp.route("/importar/limpiar", methods=["POST"])
def limpiar():
    if not _can_import():
        abort(403)
    n = LlamadaSE.query.filter(LlamadaSE.unidad_id == current_user.unidad_id).delete()
    db.session.commit()
    flash(f"Se eliminaron {n} registros.", "success")
    return redirect(url_for("analisis_llamadas_se.importar"))


@bp.route("/listado")
def listado():
    if not _can_view():
        abort(403)
    q = _apply_filters(_base_q())
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(200, max(20, request.args.get("per_page", type=int) or 50))
    total = q.count()
    rows = q.order_by(LlamadaSE.llamada_fecha.desc(), LlamadaSE.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    pages = max(1, (total + per_page - 1) // per_page)
    args_no_page = request.args.to_dict(flat=False)
    args_no_page.pop("page", None)
    qs_no_page = urlencode(args_no_page, doseq=True)
    return render_template(
        "analisis_llamadas_se/listado.html",
        rows=rows,
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        qs_no_page=qs_no_page,
        filtros=_filter_options(),
        selected=_selected(),
        can_import=_can_import(),
        can_export=_can_export(),
        can_dashboard=_can_dashboard(),
        can_map=_can_map(),
    )


@bp.route("/dashboard")
def dashboard():
    if not _can_dashboard():
        abort(403)
    q = _apply_filters(_base_q())
    datos = _dashboard_data(q)
    rows_plot = [_serialize_dashboard_row(r) for r in q.all()]
    return render_template(
        "analisis_llamadas_se/dashboard.html",
        datos_json=json.dumps(datos),
        rows_plot_json=json.dumps(rows_plot),
        kpis=datos["kpis"],
        filtros=_filter_options(),
        selected=_selected(),
        can_map=_can_map(),
        can_view=_can_view(),
    )


@bp.route("/mapa")
def mapa():
    if not _can_map():
        abort(403)
    q = _apply_filters(_base_q()).filter(LlamadaSE.llamada_coordx.isnot(None), LlamadaSE.llamada_coordy.isnot(None))
    rows = q.order_by(LlamadaSE.llamada_fecha.desc()).limit(8000).all()
    markers = []
    for r in rows:
        markers.append(
            {
                "id": r.id,
                "fecha": r.llamada_fecha.strftime("%d/%m/%Y %H:%M") if r.llamada_fecha else "",
                "alerta": r.llamada_alerta_desc or "",
                "detalle": (r.llamada_detalle or "")[:250],
                "dep": r.llamada_dep_nombre or "",
                "barrio": r.llamada_barrio_nombre or "",
                "localidad": r.llamada_local_nombre or "",
                "jurisdiccion": r.llamada_jurisdiccion or "",
                "latitud": r.llamada_coordx,
                "longitud": r.llamada_coordy,
                "detalle_url": url_for("analisis_llamadas_se.detalle", llamada_id=r.id),
            }
        )
    return render_template(
        "analisis_llamadas_se/mapa.html",
        markers_json=json.dumps(markers),
        total_filtrado=q.count(),
        filtros=_filter_options(),
        selected=_selected(),
        can_dashboard=_can_dashboard(),
        can_view=_can_view(),
    )


@bp.route("/detalle/<int:llamada_id>")
def detalle(llamada_id: int):
    if not _can_view():
        abort(403)
    row = _base_q().filter(LlamadaSE.id == llamada_id).first_or_404()
    return render_template("analisis_llamadas_se/detalle.html", row=row, can_map=_can_map())


@bp.route("/export.csv")
def export_csv():
    if not _can_export():
        abort(403)
    q = _apply_filters(_base_q()).order_by(LlamadaSE.llamada_fecha.desc())
    out = StringIO()
    w = csv.writer(out)
    w.writerow([
        "llamada_fecha", "llamada_alerta_desc", "llamada_detalle", "llamada_dep_nombre", "llamada_barrio_nombre",
        "llamada_local_nombre", "llamada_jurisdiccion", "llamada_mes", "llamada_semana", "llamada_dia_semana", "latitud", "longitud",
    ])
    for r in q.yield_per(500):
        w.writerow([
            r.llamada_fecha.isoformat() if r.llamada_fecha else "",
            r.llamada_alerta_desc or "",
            r.llamada_detalle or "",
            r.llamada_dep_nombre or "",
            r.llamada_barrio_nombre or "",
            r.llamada_local_nombre or "",
            r.llamada_jurisdiccion or "",
            r.llamada_mes or "",
            r.llamada_semana or "",
            r.llamada_dia_semana or "",
            r.llamada_coordx if r.llamada_coordx is not None else "",
            r.llamada_coordy if r.llamada_coordy is not None else "",
        ])
    return Response(
        out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=llamadas_se_filtrado.csv"},
    )


@bp.route("/export.xlsx")
def export_xlsx():
    if not _can_export():
        abort(403)
    q = _apply_filters(_base_q()).order_by(LlamadaSE.llamada_fecha.desc())
    data = []
    for r in q.yield_per(500):
        data.append(
            {
                "llamada_fecha": r.llamada_fecha.strftime("%Y-%m-%d %H:%M:%S") if r.llamada_fecha else "",
                "llamada_alerta_desc": r.llamada_alerta_desc,
                "llamada_detalle": r.llamada_detalle,
                "llamada_dep_nombre": r.llamada_dep_nombre,
                "llamada_barrio_nombre": r.llamada_barrio_nombre,
                "llamada_local_nombre": r.llamada_local_nombre,
                "llamada_jurisdiccion": r.llamada_jurisdiccion,
                "llamada_mes": r.llamada_mes,
                "llamada_semana": r.llamada_semana,
                "llamada_dia_semana": r.llamada_dia_semana,
                "latitud": r.llamada_coordx,
                "longitud": r.llamada_coordy,
            }
        )
    bio = BytesIO()
    pd.DataFrame(data).to_excel(bio, index=False)
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=llamadas_se_filtrado.xlsx"},
    )


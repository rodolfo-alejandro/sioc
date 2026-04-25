from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, inspect, or_, text

from app.blueprints.analisis_denuncias import bp
from app.extensions import db
from app.models.analisis_denuncias import DenunciaWeb


_ad_schema_checked = False
_DATE_COLUMNS = {
    "fecha_denuncia",
    "fecha_recepcion",
    "fecha_apertura",
    "fecha_desestimada",
    "fecha_sol_allanamiento",
}


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("DENUNCIAS_WEB_VIEW")


def _can_import() -> bool:
    return _is_superadmin() or current_user.has_permission("DENUNCIAS_WEB_IMPORT")


def _can_export() -> bool:
    return _is_superadmin() or current_user.has_permission("DENUNCIAS_WEB_EXPORT")


def _can_dashboard() -> bool:
    return _is_superadmin() or current_user.has_permission("DENUNCIAS_WEB_DASHBOARD")


def _can_map() -> bool:
    return _is_superadmin() or current_user.has_permission("DENUNCIAS_WEB_MAPA")


def _ensure_schema():
    global _ad_schema_checked
    if _ad_schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    if DenunciaWeb.__tablename__ not in existing:
        DenunciaWeb.__table__.create(bind=db.engine)
    else:
        cols = {c.get("name") for c in insp.get_columns(DenunciaWeb.__tablename__)}
        if "observacion_interna" not in cols:
            db.session.execute(text(f"ALTER TABLE {DenunciaWeb.__tablename__} ADD COLUMN observacion_interna TEXT NULL"))
        if "relato_original" not in cols:
            db.session.execute(text(f"ALTER TABLE {DenunciaWeb.__tablename__} ADD COLUMN relato_original TEXT NULL"))
        db.session.commit()
    _ad_schema_checked = True


def _clean(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _parse_int(v: object) -> int | None:
    try:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return int(float(v))
    except Exception:
        return None


def _parse_dt(v: object) -> datetime | None:
    try:
        if v is None:
            return None
        d = pd.to_datetime(v, errors="coerce", dayfirst=True)
        if pd.isna(d):
            return None
        return d.to_pydatetime()
    except Exception:
        return None


def _parse_coord(coord_raw: str | None) -> tuple[float | None, float | None]:
    if not coord_raw:
        return None, None
    s = coord_raw.replace(";", ",").replace("|", ",").strip()
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", s)
    if len(nums) < 2:
        return None, None
    try:
        lat = float(nums[0].replace(",", "."))
        lon = float(nums[1].replace(",", "."))
        if abs(lat) > 90 or abs(lon) > 180:
            return None, None
        return lat, lon
    except Exception:
        return None, None


def _base_q():
    return DenunciaWeb.query.filter(DenunciaWeb.unidad_id == current_user.unidad_id, DenunciaWeb.activo.is_(True))


def _apply_filters(q):
    search = _clean(request.args.get("q"))
    causas_id = _clean(request.args.get("causas_id"))
    anio = request.args.get("anio", type=int)
    fd = _parse_dt(request.args.get("fecha_desde"))
    fh = _parse_dt(request.args.get("fecha_hasta"))
    dep_reg = _clean(request.args.get("dep_registro"))
    dep_act = _clean(request.args.get("dep_actuario"))
    estado = _clean(request.args.get("causa_estado"))
    localidad = _clean(request.args.get("localidad"))
    barrio = _clean(request.args.get("barrio"))
    actuario = _clean(request.args.get("actuario"))
    coord_mode = _clean(request.args.get("coords"))
    inv_mode = _clean(request.args.get("investigados_mode"))
    all_mode = _clean(request.args.get("allanamiento_mode"))
    des_mode = _clean(request.args.get("desestimada_mode"))

    if search:
        pat = f"%{search}%"
        q = q.filter(
            or_(
                DenunciaWeb.relato.ilike(pat),
                DenunciaWeb.barrio.ilike(pat),
                DenunciaWeb.localidad.ilike(pat),
                DenunciaWeb.investigados.ilike(pat),
                DenunciaWeb.actuario_apenom.ilike(pat),
                DenunciaWeb.desc_dep_registro.ilike(pat),
                DenunciaWeb.desc_dep_actuario.ilike(pat),
                DenunciaWeb.causa_estado.ilike(pat),
                DenunciaWeb.nro_actuacion.ilike(pat),
                DenunciaWeb.causas_id.ilike(pat),
            )
        )
    if causas_id:
        q = q.filter(DenunciaWeb.causas_id == causas_id)
    if anio:
        q = q.filter(DenunciaWeb.anio_actuacion == anio)
    if fd:
        q = q.filter(DenunciaWeb.fecha_denuncia >= fd)
    if fh:
        try:
            fh = fh.replace(hour=23, minute=59, second=59, microsecond=999999)
        except Exception:
            pass
        q = q.filter(DenunciaWeb.fecha_denuncia <= fh)
    if dep_reg:
        q = q.filter(DenunciaWeb.desc_dep_registro == dep_reg)
    if dep_act:
        q = q.filter(DenunciaWeb.desc_dep_actuario == dep_act)
    if estado:
        q = q.filter(DenunciaWeb.causa_estado == estado)
    if localidad:
        q = q.filter(DenunciaWeb.localidad == localidad)
    if barrio:
        q = q.filter(DenunciaWeb.barrio == barrio)
    if actuario:
        q = q.filter(DenunciaWeb.actuario_apenom == actuario)
    if coord_mode == "con":
        q = q.filter(DenunciaWeb.latitud.isnot(None), DenunciaWeb.longitud.isnot(None))
    elif coord_mode == "sin":
        q = q.filter(or_(DenunciaWeb.latitud.is_(None), DenunciaWeb.longitud.is_(None)))
    if inv_mode == "con":
        q = q.filter(DenunciaWeb.investigados.isnot(None), DenunciaWeb.investigados != "")
    elif inv_mode == "sin":
        q = q.filter(or_(DenunciaWeb.investigados.is_(None), DenunciaWeb.investigados == ""))
    if all_mode == "con":
        q = q.filter(DenunciaWeb.fecha_sol_allanamiento.isnot(None))
    elif all_mode == "sin":
        q = q.filter(DenunciaWeb.fecha_sol_allanamiento.is_(None))
    if des_mode == "con":
        q = q.filter(DenunciaWeb.fecha_desestimada.isnot(None))
    elif des_mode == "sin":
        q = q.filter(DenunciaWeb.fecha_desestimada.is_(None))
    return q


def _filter_options():
    bq = _base_q()
    return {
        "anios": [r[0] for r in bq.with_entities(DenunciaWeb.anio_actuacion).distinct().order_by(DenunciaWeb.anio_actuacion.desc()).all() if r[0]],
        "deps_registro": [r[0] for r in bq.with_entities(DenunciaWeb.desc_dep_registro).distinct().order_by(DenunciaWeb.desc_dep_registro.asc()).all() if r[0]],
        "deps_actuario": [r[0] for r in bq.with_entities(DenunciaWeb.desc_dep_actuario).distinct().order_by(DenunciaWeb.desc_dep_actuario.asc()).all() if r[0]],
        "estados": [r[0] for r in bq.with_entities(DenunciaWeb.causa_estado).distinct().order_by(DenunciaWeb.causa_estado.asc()).all() if r[0]],
        "localidades": [r[0] for r in bq.with_entities(DenunciaWeb.localidad).distinct().order_by(DenunciaWeb.localidad.asc()).all() if r[0]],
        "barrios": [r[0] for r in bq.with_entities(DenunciaWeb.barrio).distinct().order_by(DenunciaWeb.barrio.asc()).all() if r[0]],
        "actuarios": [r[0] for r in bq.with_entities(DenunciaWeb.actuario_apenom).distinct().order_by(DenunciaWeb.actuario_apenom.asc()).all() if r[0]],
    }


def _serialize_marker(row: DenunciaWeb) -> dict:
    return {
        "id": row.id,
        "nro_actuacion": row.nro_actuacion or "",
        "fecha_denuncia": row.fecha_denuncia.strftime("%d/%m/%Y") if row.fecha_denuncia else "",
        "barrio": row.barrio or "",
        "localidad": row.localidad or "",
        "causa_estado": row.causa_estado or "",
        "dependencia": row.desc_dep_registro or "",
        "relato_corto": (row.relato or "")[:200],
        "latitud": row.latitud,
        "longitud": row.longitud,
        "detalle_url": url_for("analisis_denuncias.detalle", denuncia_id=row.id),
    }


def _calc_dashboard(q):
    total = q.count()
    con_coords = q.filter(DenunciaWeb.latitud.isnot(None), DenunciaWeb.longitud.isnot(None)).count()
    sin_coords = max(0, total - con_coords)
    con_alla = q.filter(DenunciaWeb.fecha_sol_allanamiento.isnot(None)).count()
    desestimadas = q.filter(DenunciaWeb.fecha_desestimada.isnot(None)).count()
    con_invest = q.filter(DenunciaWeb.investigados.isnot(None), DenunciaWeb.investigados != "").count()

    top_barrios = (
        q.with_entities(DenunciaWeb.barrio, func.count(DenunciaWeb.id).label("n"))
        .filter(DenunciaWeb.barrio.isnot(None), DenunciaWeb.barrio != "")
        .group_by(DenunciaWeb.barrio)
        .order_by(func.count(DenunciaWeb.id).desc())
        .limit(10)
        .all()
    )
    top_dep = (
        q.with_entities(DenunciaWeb.desc_dep_registro, func.count(DenunciaWeb.id).label("n"))
        .filter(DenunciaWeb.desc_dep_registro.isnot(None), DenunciaWeb.desc_dep_registro != "")
        .group_by(DenunciaWeb.desc_dep_registro)
        .order_by(func.count(DenunciaWeb.id).desc())
        .limit(10)
        .all()
    )
    estados = (
        q.with_entities(DenunciaWeb.causa_estado, func.count(DenunciaWeb.id).label("n"))
        .filter(DenunciaWeb.causa_estado.isnot(None), DenunciaWeb.causa_estado != "")
        .group_by(DenunciaWeb.causa_estado)
        .order_by(func.count(DenunciaWeb.id).desc())
        .all()
    )
    mensual = (
        q.with_entities(func.date_format(DenunciaWeb.fecha_denuncia, "%Y-%m").label("m"), func.count(DenunciaWeb.id).label("n"))
        .filter(DenunciaWeb.fecha_denuncia.isnot(None))
        .group_by(func.date_format(DenunciaWeb.fecha_denuncia, "%Y-%m"))
        .order_by(func.date_format(DenunciaWeb.fecha_denuncia, "%Y-%m"))
        .all()
    )

    return {
        "kpis": {
            "total": total,
            "con_coords": con_coords,
            "sin_coords": sin_coords,
            "con_allanamiento": con_alla,
            "desestimadas": desestimadas,
            "con_investigados": con_invest,
        },
        "top_barrios": [{"label": r[0], "value": int(r[1])} for r in top_barrios],
        "top_dependencias": [{"label": r[0], "value": int(r[1])} for r in top_dep],
        "estados": [{"label": r[0], "value": int(r[1])} for r in estados],
        "mensual": [{"label": r[0], "value": int(r[1])} for r in mensual if r[0]],
        "coords": [
            {"label": "Con coordenadas", "value": con_coords},
            {"label": "Sin coordenadas", "value": sin_coords},
        ],
    }


def _import_from_text(text: str) -> dict:
    if not text.strip():
        return {"error": "El archivo está vacío."}
    reader = csv.DictReader(StringIO(text), delimiter=";")
    expected = {
        "causas_id", "nro_actuacion", "anio_actuacion", "fecha_denuncia", "id_dep_registro", "desc_dep_registro",
        "id_dep_padre", "desc_dep_padre", "id_dep_actuario", "desc_dep_actuario", "actuario_grado", "actuario_apenom",
        "fecha_recepcion", "causa_estado", "fecha_apertura", "fecha_desestimada", "fecha_sol_allanamiento",
        "relato", "localidad", "barrio", "coord", "investigados",
    }
    fields = {(_clean(c) or "").lower() for c in (reader.fieldnames or [])}
    missing = sorted([c for c in expected if c not in fields])
    if missing:
        return {"error": f"Columnas faltantes: {', '.join(missing)}"}

    imported = 0
    updated = 0
    skipped = 0
    now = datetime.utcnow()
    for row in reader:
        causas_id = _clean(row.get("causas_id"))
        if not causas_id:
            skipped += 1
            continue
        obj = _base_q().filter(DenunciaWeb.causas_id == causas_id).first()
        is_new = obj is None
        if is_new:
            obj = DenunciaWeb(
                unidad_id=current_user.unidad_id,
                creado_por=current_user.id,
                fecha_importacion=now,
                causas_id=causas_id,
            )
            db.session.add(obj)

        coord_raw = _clean(row.get("coord"))
        lat, lon = _parse_coord(coord_raw)
        relato = _clean(row.get("relato"))
        obj.nro_actuacion = _clean(row.get("nro_actuacion"))
        obj.anio_actuacion = _parse_int(row.get("anio_actuacion"))
        obj.fecha_denuncia = _parse_dt(row.get("fecha_denuncia"))
        obj.id_dep_registro = _clean(row.get("id_dep_registro"))
        obj.desc_dep_registro = _clean(row.get("desc_dep_registro"))
        obj.id_dep_padre = _clean(row.get("id_dep_padre"))
        obj.desc_dep_padre = _clean(row.get("desc_dep_padre"))
        obj.id_dep_actuario = _clean(row.get("id_dep_actuario"))
        obj.desc_dep_actuario = _clean(row.get("desc_dep_actuario"))
        obj.actuario_grado = _clean(row.get("actuario_grado"))
        obj.actuario_apenom = _clean(row.get("actuario_apenom"))
        obj.fecha_recepcion = _parse_dt(row.get("fecha_recepcion"))
        obj.causa_estado = _clean(row.get("causa_estado"))
        obj.fecha_apertura = _parse_dt(row.get("fecha_apertura"))
        obj.fecha_desestimada = _parse_dt(row.get("fecha_desestimada"))
        obj.fecha_sol_allanamiento = _parse_dt(row.get("fecha_sol_allanamiento"))
        obj.relato = relato
        obj.relato_original = relato
        obj.localidad = _clean(row.get("localidad"))
        obj.barrio = _clean(row.get("barrio"))
        obj.coord = coord_raw
        obj.latitud = lat
        obj.longitud = lon
        obj.investigados = _clean(row.get("investigados"))
        obj.fecha_importacion = now
        obj.activo = True
        if is_new:
            imported += 1
        else:
            updated += 1

    db.session.commit()
    return {"importados": imported, "actualizados": updated, "omitidos": skipped}


def _import_from_csv(file_storage) -> dict:
    raw = file_storage.read()
    if not raw:
        return {"error": "El archivo está vacío."}
    return _import_from_text(raw.decode("utf-8-sig", errors="replace"))


@bp.before_request
@login_required
def _before():
    _ensure_schema()


@bp.route("/")
def index():
    if not _can_view():
        flash("No tiene permisos para ver denuncias web.", "warning")
        return redirect(url_for("core.dashboard"))
    return redirect(url_for("analisis_denuncias.listado"))


@bp.route("/importar", methods=["GET", "POST"])
def importar():
    if not _can_import():
        abort(403)
    if request.method == "POST":
        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccione un archivo CSV.", "warning")
            return redirect(url_for("analisis_denuncias.importar"))
        if not f.filename.lower().endswith(".csv"):
            flash("Formato inválido. Debe ser CSV.", "danger")
            return redirect(url_for("analisis_denuncias.importar"))
        res = _import_from_csv(f)
        if res.get("error"):
            flash(res["error"], "danger")
        else:
            flash(
                f"Importación finalizada. Importados: {res['importados']}, actualizados: {res['actualizados']}, omitidos: {res['omitidos']}.",
                "success",
            )
        return redirect(url_for("analisis_denuncias.importar"))

    total = _base_q().count()
    ultima = _base_q().order_by(DenunciaWeb.fecha_importacion.desc()).first()
    return render_template("analisis_denuncias/importar.html", total=total, ultima=ultima)


@bp.route("/importar/base", methods=["POST"])
def importar_base():
    if not _can_import():
        abort(403)
    base_file = Path(__file__).resolve().parents[3] / "analisis_denuncias_2026.csv"
    if not base_file.exists():
        flash(f"No se encontró el archivo base: {base_file}", "danger")
        return redirect(url_for("analisis_denuncias.importar"))
    try:
        text = base_file.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as exc:
        flash(f"No se pudo leer el archivo base: {exc}", "danger")
        return redirect(url_for("analisis_denuncias.importar"))
    res = _import_from_text(text)
    if res.get("error"):
        flash(res["error"], "danger")
    else:
        flash(
            f"Archivo base importado. Importados: {res['importados']}, actualizados: {res['actualizados']}, omitidos: {res['omitidos']}.",
            "success",
        )
    return redirect(url_for("analisis_denuncias.importar"))


@bp.route("/listado")
def listado():
    if not _can_view():
        abort(403)
    q = _apply_filters(_base_q())
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(200, max(20, request.args.get("per_page", type=int) or 50))
    total = q.count()
    rows = q.order_by(DenunciaWeb.fecha_denuncia.desc(), DenunciaWeb.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    pages = max(1, (total + per_page - 1) // per_page)
    args_no_page = request.args.to_dict(flat=True)
    args_no_page.pop("page", None)
    return render_template(
        "analisis_denuncias/listado.html",
        rows=rows,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        filtros=_filter_options(),
        args_no_page=args_no_page,
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
    datos = _calc_dashboard(q)
    return render_template(
        "analisis_denuncias/dashboard.html",
        datos_json=json.dumps(datos),
        kpis=datos["kpis"],
        filtros=_filter_options(),
        can_map=_can_map(),
        can_view=_can_view(),
    )


@bp.route("/mapa")
def mapa():
    if not _can_map():
        abort(403)
    q = _apply_filters(_base_q()).filter(DenunciaWeb.latitud.isnot(None), DenunciaWeb.longitud.isnot(None))
    markers = [_serialize_marker(r) for r in q.order_by(DenunciaWeb.fecha_denuncia.desc()).limit(5000).all()]
    return render_template(
        "analisis_denuncias/mapa.html",
        markers_json=json.dumps(markers),
        total_filtrado=q.count(),
        filtros=_filter_options(),
        can_dashboard=_can_dashboard(),
        can_view=_can_view(),
    )


@bp.route("/detalle/<int:denuncia_id>")
def detalle(denuncia_id: int):
    if not _can_view():
        abort(403)
    row = _base_q().filter(DenunciaWeb.id == denuncia_id).first_or_404()
    return render_template("analisis_denuncias/detalle.html", row=row, can_map=_can_map())


@bp.route("/observacion/<int:denuncia_id>", methods=["POST"])
def guardar_observacion(denuncia_id: int):
    if not _can_view():
        abort(403)
    row = _base_q().filter(DenunciaWeb.id == denuncia_id).first_or_404()
    row.observacion_interna = _clean(request.form.get("observacion_interna"))
    db.session.commit()
    flash("Observación interna guardada.", "success")
    return redirect(url_for("analisis_denuncias.detalle", denuncia_id=row.id))


@bp.route("/export.csv")
def export_csv():
    if not _can_export():
        abort(403)
    q = _apply_filters(_base_q()).order_by(DenunciaWeb.fecha_denuncia.desc())
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "causas_id", "nro_actuacion", "anio_actuacion", "fecha_denuncia", "desc_dep_registro", "desc_dep_actuario",
            "causa_estado", "localidad", "barrio", "latitud", "longitud", "investigados", "relato",
        ]
    )
    for r in q.yield_per(500):
        writer.writerow(
            [
                r.causas_id or "",
                r.nro_actuacion or "",
                r.anio_actuacion or "",
                r.fecha_denuncia.isoformat() if r.fecha_denuncia else "",
                r.desc_dep_registro or "",
                r.desc_dep_actuario or "",
                r.causa_estado or "",
                r.localidad or "",
                r.barrio or "",
                r.latitud if r.latitud is not None else "",
                r.longitud if r.longitud is not None else "",
                r.investigados or "",
                r.relato or "",
            ]
        )
    return Response(
        out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=analisis_denuncias_filtrado.csv"},
    )


@bp.route("/export.xlsx")
def export_xlsx():
    if not _can_export():
        abort(403)
    q = _apply_filters(_base_q()).order_by(DenunciaWeb.fecha_denuncia.desc())
    data = []
    for r in q.yield_per(500):
        data.append(
            {
                "causas_id": r.causas_id,
                "nro_actuacion": r.nro_actuacion,
                "anio_actuacion": r.anio_actuacion,
                "fecha_denuncia": r.fecha_denuncia.strftime("%Y-%m-%d") if r.fecha_denuncia else "",
                "dep_registro": r.desc_dep_registro,
                "dep_actuario": r.desc_dep_actuario,
                "causa_estado": r.causa_estado,
                "localidad": r.localidad,
                "barrio": r.barrio,
                "latitud": r.latitud,
                "longitud": r.longitud,
                "investigados": r.investigados,
                "relato": r.relato,
            }
        )
    bio = BytesIO()
    pd.DataFrame(data).to_excel(bio, index=False)
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=analisis_denuncias_filtrado.xlsx"},
    )


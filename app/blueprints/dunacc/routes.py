"""
Módulo DUNACC: subir planillas Excel, listar/geo­rreferenciar registros y verlos en mapa.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from io import BytesIO

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import inspect, or_
from werkzeug.utils import secure_filename

from app.blueprints.dunacc import bp
from app.blueprints.dunacc import services
from app.extensions import db
from app.models.dunacc import DunaccLote, DunaccLoteCompartido, DunaccRegistro
from app.models.unidad import Unidad

_schema_checked = False

_ALLOWED_EXT = {".xlsx", ".xlsm"}


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("DUNACC_VIEW")


def _can_manage() -> bool:
    return _is_superadmin() or current_user.has_permission("DUNACC_MANAGE")


def _can_export() -> bool:
    return _is_superadmin() or current_user.has_permission("DUNACC_EXPORT")


def _clean(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _parse_date(s: str):
    s = _clean(s)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _ensure_schema():
    global _schema_checked
    if _schema_checked:
        return
    try:
        insp = inspect(db.engine)
        existing = set(insp.get_table_names())
        for model in (DunaccLote, DunaccRegistro, DunaccLoteCompartido):
            if model.__tablename__ not in existing:
                model.__table__.create(bind=db.engine)
        _schema_checked = True
    except Exception:
        db.session.rollback()


@bp.before_request
@login_required
def _gate():
    if not _can_view():
        abort(403)
    _ensure_schema()


def _shared_lote_ids():
    """IDs de planillas (lotes) compartidas con el área del usuario actual."""
    rows = (
        db.session.query(DunaccLoteCompartido.lote_id)
        .filter(DunaccLoteCompartido.unidad_destino_id == current_user.unidad_id)
        .all()
    )
    return [r[0] for r in rows]


def _base_registros():
    """Registros de mi área + los de planillas compartidas conmigo."""
    shared = _shared_lote_ids()
    cond = DunaccRegistro.unidad_id == current_user.unidad_id
    if shared:
        cond = or_(cond, DunaccRegistro.lote_id.in_(shared))
    return DunaccRegistro.query.filter(cond)


def _upload_dir(unidad_id=None) -> str:
    base_dir = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(current_app.root_path, base_dir)
    target = os.path.join(base_dir, "dunacc", str(unidad_id or current_user.unidad_id))
    os.makedirs(target, exist_ok=True)
    return target


# ---------------------- Listado ----------------------

@bp.route("/")
def listado():
    q = _base_registros()

    texto = _clean(request.args.get("q"))
    dependencia = _clean(request.args.get("dependencia"))
    caratula = _clean(request.args.get("caratula"))
    anio = _clean(request.args.get("anio"))
    geo = _clean(request.args.get("geo"))  # con | sin
    lote = _clean(request.args.get("lote"))
    fecha_desde = _clean(request.args.get("fecha_desde"))
    fecha_hasta = _clean(request.args.get("fecha_hasta"))

    if lote.isdigit():
        q = q.filter(DunaccRegistro.lote_id == int(lote))
    if texto:
        like = f"%{texto}%"
        q = q.filter(or_(
            DunaccRegistro.caratula.ilike(like),
            DunaccRegistro.lugar.ilike(like),
            DunaccRegistro.dependencia.ilike(like),
            DunaccRegistro.informante.ilike(like),
            DunaccRegistro.acusado.ilike(like),
            DunaccRegistro.numero_ap.ilike(like),
            DunaccRegistro.relato.ilike(like),
        ))
    if dependencia:
        q = q.filter(DunaccRegistro.dependencia.ilike(f"%{dependencia}%"))
    if caratula:
        q = q.filter(DunaccRegistro.caratula.ilike(f"%{caratula}%"))
    if anio.isdigit():
        q = q.filter(DunaccRegistro.anio == int(anio))
    if geo == "con":
        q = q.filter(DunaccRegistro.lat.isnot(None), DunaccRegistro.lon.isnot(None))
    elif geo == "sin":
        q = q.filter(or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None)))
    d1 = _parse_date(fecha_desde)
    d2 = _parse_date(fecha_hasta)
    if d1:
        q = q.filter(DunaccRegistro.fecha >= d1)
    if d2:
        q = q.filter(DunaccRegistro.fecha <= d2)

    registros = q.order_by(
        DunaccRegistro.fecha.desc(),
        DunaccRegistro.created_at.desc(),
    ).limit(1000).all()

    total = _base_registros().count()
    sin_coords = _base_registros().filter(
        or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None))
    ).count()
    anios = [
        r[0]
        for r in db.session.query(DunaccRegistro.anio)
        .filter(DunaccRegistro.unidad_id == current_user.unidad_id, DunaccRegistro.anio.isnot(None))
        .distinct()
        .order_by(DunaccRegistro.anio.desc())
        .all()
        if r[0]
    ]
    own_lotes = (
        DunaccLote.query.filter_by(unidad_id=current_user.unidad_id)
        .order_by(DunaccLote.created_at.desc())
        .all()
    )
    shared_ids = _shared_lote_ids()
    shared_lotes = []
    if shared_ids:
        shared_lotes = (
            DunaccLote.query.filter(DunaccLote.id.in_(shared_ids))
            .order_by(DunaccLote.created_at.desc())
            .all()
        )
    share_counts = {}
    if own_lotes:
        for lid, cnt in (
            db.session.query(DunaccLoteCompartido.lote_id, db.func.count())
            .filter(DunaccLoteCompartido.lote_id.in_([l.id for l in own_lotes]))
            .group_by(DunaccLoteCompartido.lote_id)
            .all()
        ):
            share_counts[lid] = cnt
    lotes_info = [
        {"lote": l, "propio": True, "owner": None, "shares": share_counts.get(l.id, 0)}
        for l in own_lotes
    ] + [
        {"lote": l, "propio": False, "owner": (l.unidad.nombre if l.unidad else "Otra área"), "shares": 0}
        for l in shared_lotes
    ]

    return render_template(
        "dunacc/listado.html",
        registros=registros,
        total=total,
        sin_coords=sin_coords,
        con_coords=total - sin_coords,
        anios=anios,
        lotes_info=lotes_info,
        lotes=own_lotes + shared_lotes,
        selected={
            "q": texto,
            "dependencia": dependencia,
            "caratula": caratula,
            "anio": anio,
            "geo": geo,
            "lote": lote,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
        },
        can_manage=_can_manage(),
        can_export=_can_export(),
        dep_faltantes=services.dependencias_faltantes(),
    )


# ---------------------- Subir / importar ----------------------

@bp.route("/subir", methods=["GET", "POST"])
def subir():
    if not _can_manage():
        abort(403)

    if request.method == "GET":
        return render_template(
            "dunacc/subir.html",
            dep_faltantes=services.dependencias_faltantes(),
        )

    faltan = services.dependencias_faltantes()
    if faltan:
        flash(f"Faltan dependencias en el servidor: {', '.join(faltan)}.", "danger")
        return redirect(url_for("dunacc.subir"))

    f = request.files.get("archivo")
    if not f or not f.filename:
        flash("Seleccioná un archivo Excel.", "warning")
        return redirect(url_for("dunacc.subir"))

    nombre_original = f.filename
    ext = os.path.splitext(secure_filename(nombre_original) or "x")[1].lower()
    if ext not in _ALLOWED_EXT:
        flash("Formato no permitido. Subí un archivo .xlsx.", "warning")
        return redirect(url_for("dunacc.subir"))

    omitir_dup = request.form.get("omitir_duplicados") == "1"

    # Guardar archivo en disco.
    safe = secure_filename(nombre_original) or "planilla.xlsx"
    stored = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe}"
    path = os.path.join(_upload_dir(), stored)
    f.save(path)

    sha1 = hashlib.sha1()
    with open(path, "rb") as rf:
        for chunk in iter(lambda: rf.read(8192), b""):
            sha1.update(chunk)

    try:
        registros, advertencias = services.importar_excel(path)
    except Exception as e:
        try:
            os.remove(path)
        except Exception:
            pass
        flash(f"No se pudo leer el Excel: {e}", "danger")
        return redirect(url_for("dunacc.subir"))

    if not registros:
        try:
            os.remove(path)
        except Exception:
            pass
        msg = "No se detectaron filas para importar."
        if advertencias:
            msg += " " + " ".join(advertencias)
        flash(msg, "warning")
        return redirect(url_for("dunacc.subir"))

    lote = DunaccLote(
        unidad_id=current_user.unidad_id,
        user_id=current_user.id,
        nombre_archivo=stored,
        nombre_original=nombre_original[:255],
        sha1=sha1.hexdigest(),
        size_bytes=os.path.getsize(path),
        total_registros=0,
    )
    db.session.add(lote)
    db.session.flush()

    nuevos = 0
    duplicados = 0
    existentes = set()
    if omitir_dup:
        existentes = {
            h[0]
            for h in db.session.query(DunaccRegistro.dedupe_hash)
            .filter(DunaccRegistro.unidad_id == current_user.unidad_id)
            .all()
            if h[0]
        }

    vistos_en_lote = set()
    for reg in registros:
        h = reg.get("dedupe_hash")
        if omitir_dup and h and (h in existentes or h in vistos_en_lote):
            duplicados += 1
            continue
        if h:
            vistos_en_lote.add(h)
        db.session.add(DunaccRegistro(
            unidad_id=current_user.unidad_id,
            lote_id=lote.id,
            user_id=current_user.id,
            numero=reg.get("numero"),
            numero_ap=reg.get("numero_ap"),
            dependencia=reg.get("dependencia"),
            caratula=reg.get("caratula"),
            fecha=reg.get("fecha"),
            hora=reg.get("hora"),
            lugar=reg.get("lugar"),
            informante=reg.get("informante"),
            acusado=reg.get("acusado"),
            relato=reg.get("relato"),
            anio=reg.get("anio"),
            lat=reg.get("lat"),
            lon=reg.get("lon"),
            geo_origen=reg.get("geo_origen"),
            dedupe_hash=h,
        ))
        nuevos += 1

    lote.total_registros = nuevos
    db.session.commit()

    sin_coords = sum(1 for reg in registros if reg.get("lat") is None or reg.get("lon") is None)
    partes = [f"{nuevos} registro(s) importado(s)"]
    if duplicados:
        partes.append(f"{duplicados} duplicado(s) omitido(s)")
    if sin_coords:
        partes.append(f"{sin_coords} sin coordenadas (cargalas desde el listado)")
    flash(". ".join(partes) + ".", "success")
    for adv in advertencias:
        flash(adv, "info")
    return redirect(url_for("dunacc.listado", geo="sin" if sin_coords else None))


# ---------------------- Coordenadas ----------------------

@bp.route("/registro/<int:registro_id>")
def registro_detalle(registro_id: int):
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()
    return render_template("dunacc/detalle.html", reg=reg, can_manage=_can_manage())


@bp.route("/registro/<int:registro_id>/coords", methods=["GET", "POST"])
def registro_coords(registro_id: int):
    if not _can_manage():
        abort(403)
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()

    if request.method == "GET":
        # Sugerencia inicial para el mapa: registros vecinos ya geolocalizados.
        ref = _base_registros().filter(
            DunaccRegistro.lat.isnot(None), DunaccRegistro.lon.isnot(None)
        ).first()
        centro = {"lat": ref.lat, "lon": ref.lon} if ref else {"lat": -24.7859, "lon": -65.4114}
        return render_template("dunacc/coords.html", reg=reg, centro=centro)

    lat = services._parse_float(request.form.get("lat"))
    lon = services._parse_float(request.form.get("lon"))
    if lat is None or lon is None:
        # Permite pegar "lat, lon" en un solo campo.
        lat, lon = services._parse_coords(request.form.get("coords"))
    if not services._coords_validas(lat, lon):
        flash("Coordenadas inválidas. Revisá latitud y longitud.", "warning")
        return redirect(url_for("dunacc.registro_coords", registro_id=reg.id))

    reg.lat = lat
    reg.lon = lon
    reg.geo_origen = _clean(request.form.get("origen")) or "manual"
    db.session.commit()
    flash("Coordenadas guardadas.", "success")
    siguiente = request.form.get("siguiente") == "1"
    if siguiente:
        prox = _base_registros().filter(
            or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None))
        ).order_by(DunaccRegistro.fecha.desc()).first()
        if prox:
            return redirect(url_for("dunacc.registro_coords", registro_id=prox.id))
        flash("¡No quedan registros sin coordenadas!", "info")
    return redirect(url_for("dunacc.listado"))


@bp.route("/registro/<int:registro_id>/quitar-coords", methods=["POST"])
def registro_quitar_coords(registro_id: int):
    if not _can_manage():
        abort(403)
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()
    reg.lat = None
    reg.lon = None
    reg.geo_origen = None
    db.session.commit()
    flash("Coordenadas quitadas.", "success")
    return redirect(request.referrer or url_for("dunacc.listado"))


@bp.route("/registro/<int:registro_id>/eliminar", methods=["POST"])
def registro_eliminar(registro_id: int):
    if not _can_manage():
        abort(403)
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()
    if reg.unidad_id != current_user.unidad_id:
        flash("Solo el área dueña de la planilla puede eliminar registros.", "warning")
        return redirect(request.referrer or url_for("dunacc.listado"))
    db.session.delete(reg)
    db.session.commit()
    flash("Registro eliminado.", "success")
    return redirect(request.referrer or url_for("dunacc.listado"))


@bp.route("/api/geocodificar")
def api_geocodificar():
    if not _can_manage():
        return jsonify({"ok": False, "error": "sin_permiso"}), 403
    consulta = _clean(request.args.get("q"))
    if not consulta:
        return jsonify({"ok": False, "error": "consulta_vacia"}), 400
    res = services.geocodificar(consulta)
    if not res:
        return jsonify({"ok": False, "error": "sin_resultados"}), 404
    return jsonify({"ok": True, **res})


# ---------------------- Mapa ----------------------

@bp.route("/mapa")
def mapa():
    q = _base_registros().filter(
        DunaccRegistro.lat.isnot(None), DunaccRegistro.lon.isnot(None)
    )
    anio = _clean(request.args.get("anio"))
    if anio.isdigit():
        q = q.filter(DunaccRegistro.anio == int(anio))
    dependencia = _clean(request.args.get("dependencia"))
    if dependencia:
        q = q.filter(DunaccRegistro.dependencia.ilike(f"%{dependencia}%"))
    caratula = _clean(request.args.get("caratula"))
    if caratula:
        q = q.filter(DunaccRegistro.caratula.ilike(f"%{caratula}%"))
    lote = _clean(request.args.get("lote"))
    if lote.isdigit():
        q = q.filter(DunaccRegistro.lote_id == int(lote))

    puntos = []
    for r in q.limit(3000).all():
        puntos.append({
            "id": r.id,
            "lat": r.lat,
            "lng": r.lon,
            "caratula": r.caratula or "-",
            "fecha": r.fecha.strftime("%d/%m/%Y") if r.fecha else "-",
            "dependencia": r.dependencia or "-",
            "lugar": (r.lugar or "-")[:200],
            "numero_ap": r.numero_ap or "-",
        })

    anios = [
        r[0]
        for r in db.session.query(DunaccRegistro.anio)
        .filter(DunaccRegistro.unidad_id == current_user.unidad_id, DunaccRegistro.anio.isnot(None))
        .distinct()
        .order_by(DunaccRegistro.anio.desc())
        .all()
        if r[0]
    ]
    sin_coords = _base_registros().filter(
        or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None))
    ).count()
    shared_ids = _shared_lote_ids()
    lote_cond = DunaccLote.unidad_id == current_user.unidad_id
    if shared_ids:
        lote_cond = or_(lote_cond, DunaccLote.id.in_(shared_ids))
    lotes = DunaccLote.query.filter(lote_cond).order_by(DunaccLote.created_at.desc()).all()

    return render_template(
        "dunacc/mapa.html",
        puntos=puntos,
        anios=anios,
        lotes=lotes,
        sin_coords=sin_coords,
        selected={"anio": anio, "dependencia": dependencia, "caratula": caratula, "lote": lote},
    )


# ---------------------- Lotes (archivos) ----------------------

def _lote_accesible(lote_id: int):
    """Devuelve el lote si es de mi área o está compartido conmigo; si no, 404."""
    lote = DunaccLote.query.filter_by(id=lote_id).first_or_404()
    if lote.unidad_id == current_user.unidad_id:
        return lote
    if lote.id in _shared_lote_ids():
        return lote
    abort(404)


@bp.route("/lote/<int:lote_id>/descargar")
def lote_descargar(lote_id: int):
    lote = _lote_accesible(lote_id)
    path = os.path.join(_upload_dir(lote.unidad_id), lote.nombre_archivo)
    if not os.path.exists(path):
        flash("El archivo original ya no está disponible en el servidor.", "warning")
        return redirect(url_for("dunacc.listado"))
    return send_file(path, as_attachment=True, download_name=lote.nombre_original or lote.nombre_archivo)


@bp.route("/lote/<int:lote_id>/compartir", methods=["GET", "POST"])
def lote_compartir(lote_id: int):
    if not _can_manage():
        abort(403)
    lote = DunaccLote.query.filter_by(id=lote_id, unidad_id=current_user.unidad_id).first_or_404()

    if request.method == "POST":
        seleccionadas = {
            int(x) for x in request.form.getlist("unidades") if str(x).isdigit()
        }
        seleccionadas.discard(current_user.unidad_id)
        actuales = {
            c.unidad_destino_id: c
            for c in DunaccLoteCompartido.query.filter_by(lote_id=lote.id).all()
        }
        # Agregar nuevas
        for uid in seleccionadas - set(actuales):
            db.session.add(DunaccLoteCompartido(
                lote_id=lote.id,
                unidad_destino_id=uid,
                compartido_por=current_user.id,
            ))
        # Quitar las que ya no están
        for uid in set(actuales) - seleccionadas:
            db.session.delete(actuales[uid])
        db.session.commit()
        flash("Compartición actualizada.", "success")
        return redirect(url_for("dunacc.listado"))

    unidades = (
        Unidad.query.filter(Unidad.activo.is_(True), Unidad.id != current_user.unidad_id)
        .order_by(Unidad.nombre)
        .all()
    )
    compartidas = {
        c.unidad_destino_id for c in DunaccLoteCompartido.query.filter_by(lote_id=lote.id).all()
    }
    return render_template(
        "dunacc/compartir.html",
        lote=lote,
        unidades=unidades,
        compartidas=compartidas,
    )


@bp.route("/lote/<int:lote_id>/eliminar", methods=["POST"])
def lote_eliminar(lote_id: int):
    if not _can_manage():
        abort(403)
    lote = DunaccLote.query.filter_by(id=lote_id, unidad_id=current_user.unidad_id).first_or_404()
    borrar_registros = request.form.get("borrar_registros") == "1"
    if borrar_registros:
        DunaccRegistro.query.filter_by(lote_id=lote.id, unidad_id=current_user.unidad_id).delete(
            synchronize_session=False
        )
    else:
        DunaccRegistro.query.filter_by(lote_id=lote.id, unidad_id=current_user.unidad_id).update(
            {DunaccRegistro.lote_id: None}, synchronize_session=False
        )
    try:
        path = os.path.join(_upload_dir(), lote.nombre_archivo)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    db.session.delete(lote)
    db.session.commit()
    flash("Lote eliminado." + (" Sus registros también se eliminaron." if borrar_registros else " Los registros se conservaron."), "success")
    return redirect(url_for("dunacc.listado"))


# ---------------------- Export ----------------------

@bp.route("/export.xlsx")
def export_xlsx():
    if not _can_export():
        abort(403)
    import openpyxl

    q = _base_registros()
    texto = _clean(request.args.get("q"))
    if texto:
        like = f"%{texto}%"
        q = q.filter(or_(
            DunaccRegistro.caratula.ilike(like),
            DunaccRegistro.lugar.ilike(like),
            DunaccRegistro.dependencia.ilike(like),
            DunaccRegistro.informante.ilike(like),
            DunaccRegistro.acusado.ilike(like),
            DunaccRegistro.numero_ap.ilike(like),
            DunaccRegistro.relato.ilike(like),
        ))
    anio = _clean(request.args.get("anio"))
    if anio.isdigit():
        q = q.filter(DunaccRegistro.anio == int(anio))
    lote = _clean(request.args.get("lote"))
    if lote.isdigit():
        q = q.filter(DunaccRegistro.lote_id == int(lote))
    geo = _clean(request.args.get("geo"))
    if geo == "con":
        q = q.filter(DunaccRegistro.lat.isnot(None), DunaccRegistro.lon.isnot(None))
    elif geo == "sin":
        q = q.filter(or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None)))
    d1 = _parse_date(request.args.get("fecha_desde"))
    d2 = _parse_date(request.args.get("fecha_hasta"))
    if d1:
        q = q.filter(DunaccRegistro.fecha >= d1)
    if d2:
        q = q.filter(DunaccRegistro.fecha <= d2)

    rows = q.order_by(DunaccRegistro.fecha.desc(), DunaccRegistro.created_at.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DUNACC"
    ws.append([
        "N°", "N° AP", "Dependencia", "Carátula", "Fecha", "Hora", "Lugar",
        "Informante", "Acusado", "Breve relato", "Latitud", "Longitud", "Año",
    ])
    for r in rows:
        ws.append([
            r.numero or "",
            r.numero_ap or "",
            r.dependencia or "",
            r.caratula or "",
            r.fecha.strftime("%d/%m/%Y") if r.fecha else "",
            r.hora or "",
            r.lugar or "",
            r.informante or "",
            r.acusado or "",
            r.relato or "",
            r.lat if r.lat is not None else "",
            r.lon if r.lon is not None else "",
            r.anio or "",
        ])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    fname = f"dunacc_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

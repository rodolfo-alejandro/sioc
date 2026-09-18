"""
Rutas para el módulo de auditoría.
"""
from __future__ import annotations

import json
from datetime import datetime
from io import StringIO
from urllib.parse import urlencode

import pandas as pd
from flask import Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, inspect, or_, text

from app.blueprints.auditoria import bp
from app.extensions import db
from app.models.analisis_denuncias import DenunciaWeb
from app.models.analisis_intervenciones import Intervencion
from app.models.auditoria import AuditoriaObservacion, AuditoriaResumen


_auditoria_schema_checked = False


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view_auditoria() -> bool:
    """Verifica si el usuario puede ver auditorías"""
    return _is_superadmin() or current_user.has_permission("AUDITORIA_VIEW")


def _can_create_observacion() -> bool:
    """Verifica si el usuario puede crear observaciones de auditoría"""
    return _is_superadmin() or current_user.has_permission("AUDITORIA_CREATE")


def _can_resolve_observacion() -> bool:
    """Verifica si el usuario puede resolver observaciones"""
    return _is_superadmin() or current_user.has_permission("AUDITORIA_RESOLVE")


def _ensure_schema():
    """Asegura que las tablas de auditoría existan"""
    global _auditoria_schema_checked
    if _auditoria_schema_checked:
        return
    
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    
    if AuditoriaObservacion.__tablename__ not in existing:
        AuditoriaObservacion.__table__.create(bind=db.engine)
    
    if AuditoriaResumen.__tablename__ not in existing:
        AuditoriaResumen.__table__.create(bind=db.engine)
    
    db.session.commit()
    _auditoria_schema_checked = True


def _clean(v: object) -> str | None:
    """Limpia valores de entrada"""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


@bp.before_request
@login_required
def _before():
    _ensure_schema()


@bp.route("/")
def index():
    """Página principal de auditoría - redirige al selector de módulos"""
    if not _can_view_auditoria():
        flash("No tiene permisos para acceder a auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    
    return render_template(
        "auditoria/index.html",
        can_create=_can_create_observacion(),
        can_resolve=_can_resolve_observacion()
    )


@bp.route("/denuncias-web")
def denuncias_web():
    """Panel de auditoría para denuncias web"""
    if not _can_view_auditoria():
        abort(403)
    
    # Obtener filtros
    agrupacion = _clean(request.args.get("agrupacion")) or "dependencia"
    filtro_texto = _clean(request.args.get("q")) or ""
    
    # Query base de denuncias web
    base_q = DenunciaWeb.query.filter(
        DenunciaWeb.unidad_id == current_user.unidad_id,
        DenunciaWeb.activo.is_(True)
    )
    
    # Determinar agrupación
    if agrupacion == "dependencia":
        grupo_campo = DenunciaWeb.desc_dep_actuario
        grupo_nombre = "Dependencia Actuario"
    elif agrupacion == "actuario":
        grupo_campo = DenunciaWeb.actuario_apenom
        grupo_nombre = "Actuario"
    elif agrupacion == "estado":
        grupo_campo = DenunciaWeb.causa_estado
        grupo_nombre = "Estado"
    elif agrupacion == "localidad":
        grupo_campo = DenunciaWeb.localidad
        grupo_nombre = "Localidad"
    else:
        grupo_campo = DenunciaWeb.desc_dep_actuario
        grupo_nombre = "Dependencia Actuario"
        agrupacion = "dependencia"
    
    # Estadísticas por grupo
    stats_query = (
        base_q
        .filter(grupo_campo.isnot(None), grupo_campo != "")
        .with_entities(
            grupo_campo.label("grupo"),
            func.count(DenunciaWeb.id).label("total"),
            func.count(func.distinct(DenunciaWeb.id)).label("total_registros")
        )
        .group_by(grupo_campo)
        .order_by(func.count(DenunciaWeb.id).desc())
    )
    
    if filtro_texto:
        stats_query = stats_query.filter(grupo_campo.ilike(f"%{filtro_texto}%"))
    
    stats = stats_query.all()
    
    # Agregar conteo de observaciones por grupo
    grupos_con_stats = []
    for stat in stats:
        # Contar observaciones para este grupo
        obs_count = (
            db.session.query(func.count(AuditoriaObservacion.id))
            .join(
                DenunciaWeb,
                (AuditoriaObservacion.modulo == "denuncias_web") &
                (AuditoriaObservacion.registro_id == DenunciaWeb.id)
            )
            .filter(
                DenunciaWeb.unidad_id == current_user.unidad_id,
                DenunciaWeb.activo.is_(True),
                grupo_campo == stat.grupo
            )
            .scalar()
        ) or 0
        
        # Contar observaciones no resueltas
        obs_pendientes = (
            db.session.query(func.count(AuditoriaObservacion.id))
            .join(
                DenunciaWeb,
                (AuditoriaObservacion.modulo == "denuncias_web") &
                (AuditoriaObservacion.registro_id == DenunciaWeb.id)
            )
            .filter(
                DenunciaWeb.unidad_id == current_user.unidad_id,
                DenunciaWeb.activo.is_(True),
                grupo_campo == stat.grupo,
                AuditoriaObservacion.resuelta.is_(False)
            )
            .scalar()
        ) or 0
        
        grupos_con_stats.append({
            "grupo": stat.grupo,
            "total_registros": stat.total_registros,
            "total_observaciones": obs_count,
            "observaciones_pendientes": obs_pendientes
        })
    
    return render_template(
        "auditoria/denuncias_web.html",
        grupos=grupos_con_stats,
        agrupacion=agrupacion,
        grupo_nombre=grupo_nombre,
        filtro_texto=filtro_texto,
        can_create=_can_create_observacion(),
        can_resolve=_can_resolve_observacion()
    )


@bp.route("/denuncias-web/grupo/<grupo_valor>")
def denuncias_web_grupo(grupo_valor: str):
    """Vista detallada de un grupo específico de denuncias web"""
    if not _can_view_auditoria():
        abort(403)
    
    agrupacion = _clean(request.args.get("agrupacion")) or "dependencia"
    
    # Determinar campo de agrupación
    if agrupacion == "dependencia":
        grupo_campo = DenunciaWeb.desc_dep_actuario
    elif agrupacion == "actuario":
        grupo_campo = DenunciaWeb.actuario_apenom
    elif agrupacion == "estado":
        grupo_campo = DenunciaWeb.causa_estado
    elif agrupacion == "localidad":
        grupo_campo = DenunciaWeb.localidad
    else:
        grupo_campo = DenunciaWeb.desc_dep_actuario
    
    # Obtener denuncias del grupo
    denuncias_query = (
        DenunciaWeb.query
        .filter(
            DenunciaWeb.unidad_id == current_user.unidad_id,
            DenunciaWeb.activo.is_(True),
            grupo_campo == grupo_valor
        )
        .order_by(DenunciaWeb.fecha_denuncia.desc())
    )
    
    # Paginación
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(100, max(10, request.args.get("per_page", type=int) or 25))
    total = denuncias_query.count()
    denuncias = denuncias_query.offset((page - 1) * per_page).limit(per_page).all()
    pages = max(1, (total + per_page - 1) // per_page)
    
    # Obtener observaciones para estas denuncias
    denuncias_ids = [d.id for d in denuncias]
    observaciones_map = {}
    
    if denuncias_ids:
        observaciones = (
            AuditoriaObservacion.query
            .filter(
                AuditoriaObservacion.modulo == "denuncias_web",
                AuditoriaObservacion.registro_id.in_(denuncias_ids),
                AuditoriaObservacion.unidad_id == current_user.unidad_id
            )
            .order_by(AuditoriaObservacion.fecha_creacion.desc())
            .all()
        )
        
        for obs in observaciones:
            if obs.registro_id not in observaciones_map:
                observaciones_map[obs.registro_id] = []
            observaciones_map[obs.registro_id].append(obs)
    
    return render_template(
        "auditoria/denuncias_web_grupo.html",
        grupo_valor=grupo_valor,
        agrupacion=agrupacion,
        denuncias=denuncias,
        observaciones_map=observaciones_map,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        can_create=_can_create_observacion(),
        can_resolve=_can_resolve_observacion()
    )


@bp.route("/denuncias-web/detalle/<int:denuncia_id>")
def denuncias_web_detalle(denuncia_id: int):
    """Vista detallada de una denuncia con todas sus observaciones"""
    if not _can_view_auditoria():
        abort(403)
    
    denuncia = (
        DenunciaWeb.query
        .filter(
            DenunciaWeb.id == denuncia_id,
            DenunciaWeb.unidad_id == current_user.unidad_id,
            DenunciaWeb.activo.is_(True)
        )
        .first_or_404()
    )
    
    # Obtener todas las observaciones
    observaciones = (
        AuditoriaObservacion.query
        .filter(
            AuditoriaObservacion.modulo == "denuncias_web",
            AuditoriaObservacion.registro_id == denuncia_id,
            AuditoriaObservacion.unidad_id == current_user.unidad_id
        )
        .order_by(AuditoriaObservacion.fecha_creacion.desc())
        .all()
    )
    
    # Agrupar observaciones por campo
    observaciones_por_campo = {}
    observaciones_generales = []
    
    for obs in observaciones:
        if obs.campo:
            if obs.campo not in observaciones_por_campo:
                observaciones_por_campo[obs.campo] = []
            observaciones_por_campo[obs.campo].append(obs)
        else:
            observaciones_generales.append(obs)
    
    # Definir campos auditables
    campos_auditables = [
        {"nombre": "nro_actuacion", "etiqueta": "Nro. Actuación"},
        {"nombre": "fecha_denuncia", "etiqueta": "Fecha Denuncia"},
        {"nombre": "desc_dep_registro", "etiqueta": "Dependencia Registro"},
        {"nombre": "desc_dep_actuario", "etiqueta": "Dependencia Actuario"},
        {"nombre": "actuario_apenom", "etiqueta": "Actuario"},
        {"nombre": "causa_estado", "etiqueta": "Estado"},
        {"nombre": "localidad", "etiqueta": "Localidad"},
        {"nombre": "barrio", "etiqueta": "Barrio"},
        {"nombre": "investigados", "etiqueta": "Investigados"},
        {"nombre": "relato", "etiqueta": "Relato"},
        {"nombre": "fecha_sol_allanamiento", "etiqueta": "Fecha Sol. Allanamiento"},
        {"nombre": "fecha_desestimada", "etiqueta": "Fecha Desestimada"},
    ]
    
    return render_template(
        "auditoria/denuncias_web_detalle.html",
        denuncia=denuncia,
        observaciones_generales=observaciones_generales,
        observaciones_por_campo=observaciones_por_campo,
        campos_auditables=campos_auditables,
        can_create=_can_create_observacion(),
        can_resolve=_can_resolve_observacion()
    )


@bp.route("/observacion/crear", methods=["POST"])
def crear_observacion():
    """Crea una nueva observación de auditoría"""
    if not _can_create_observacion():
        abort(403)
    
    modulo = _clean(request.form.get("modulo"))
    registro_id = request.form.get("registro_id", type=int)
    campo = _clean(request.form.get("campo"))
    observacion_texto = _clean(request.form.get("observacion"))
    
    if not modulo or not registro_id or not observacion_texto:
        flash("Faltan datos obligatorios para crear la observación.", "danger")
        return redirect(request.referrer or url_for("auditoria.index"))
    
    # Validar que el registro existe y pertenece a la unidad del usuario
    if modulo == "denuncias_web":
        registro = (
            DenunciaWeb.query
            .filter(
                DenunciaWeb.id == registro_id,
                DenunciaWeb.unidad_id == current_user.unidad_id
            )
            .first()
        )
        if not registro:
            flash("No se encontró la denuncia o no tiene permisos.", "danger")
            return redirect(request.referrer or url_for("auditoria.index"))
    elif modulo == "intervenciones":
        registro = (
            Intervencion.query
            .filter(
                Intervencion.id == registro_id,
                Intervencion.unidad_id == current_user.unidad_id
            )
            .first()
        )
        if not registro:
            flash("No se encontró la intervención o no tiene permisos.", "danger")
            return redirect(request.referrer or url_for("auditoria.index"))
    else:
        flash("Módulo no válido.", "danger")
        return redirect(request.referrer or url_for("auditoria.index"))
    
    # Crear la observación
    nueva_obs = AuditoriaObservacion(
        modulo=modulo,
        registro_id=registro_id,
        campo=campo,
        observacion=observacion_texto,
        auditor_id=current_user.id,
        unidad_id=current_user.unidad_id,
        fecha_creacion=datetime.utcnow()
    )
    
    db.session.add(nueva_obs)
    db.session.commit()
    
    flash("Observación de auditoría creada exitosamente.", "success")
    return redirect(request.referrer or url_for("auditoria.index"))


@bp.route("/observacion/<int:obs_id>/resolver", methods=["POST"])
def resolver_observacion(obs_id: int):
    """Marca una observación como resuelta"""
    if not _can_resolve_observacion():
        abort(403)
    
    observacion = (
        AuditoriaObservacion.query
        .filter(
            AuditoriaObservacion.id == obs_id,
            AuditoriaObservacion.unidad_id == current_user.unidad_id
        )
        .first_or_404()
    )
    
    nota_resolucion = _clean(request.form.get("nota_resolucion"))
    
    observacion.resuelta = True
    observacion.fecha_resolucion = datetime.utcnow()
    observacion.resuelto_por_id = current_user.id
    observacion.nota_resolucion = nota_resolucion
    
    db.session.commit()
    
    flash("Observación marcada como resuelta.", "success")
    return redirect(request.referrer or url_for("auditoria.index"))


@bp.route("/observacion/<int:obs_id>/reabrir", methods=["POST"])
def reabrir_observacion(obs_id: int):
    """Reabre una observación resuelta"""
    if not _can_resolve_observacion():
        abort(403)
    
    observacion = (
        AuditoriaObservacion.query
        .filter(
            AuditoriaObservacion.id == obs_id,
            AuditoriaObservacion.unidad_id == current_user.unidad_id
        )
        .first_or_404()
    )
    
    observacion.resuelta = False
    observacion.fecha_resolucion = None
    observacion.resuelto_por_id = None
    observacion.nota_resolucion = None
    
    db.session.commit()
    
    flash("Observación reabierta.", "success")
    return redirect(request.referrer or url_for("auditoria.index"))


@bp.route("/observacion/<int:obs_id>/eliminar", methods=["POST"])
def eliminar_observacion(obs_id: int):
    """Elimina una observación (solo el creador o superadmin)"""
    observacion = (
        AuditoriaObservacion.query
        .filter(
            AuditoriaObservacion.id == obs_id,
            AuditoriaObservacion.unidad_id == current_user.unidad_id
        )
        .first_or_404()
    )
    
    # Solo el creador o superadmin pueden eliminar
    if not _is_superadmin() and observacion.auditor_id != current_user.id:
        abort(403)
    
    db.session.delete(observacion)
    db.session.commit()
    
    flash("Observación eliminada.", "success")
    return redirect(request.referrer or url_for("auditoria.index"))


@bp.route("/intervenciones")
def intervenciones():
    """Panel de auditoría para intervenciones"""
    if not _can_view_auditoria():
        abort(403)
    
    # Obtener filtros
    agrupacion = _clean(request.args.get("agrupacion")) or "dinar"
    filtro_texto = _clean(request.args.get("q")) or ""
    
    # Query base de intervenciones
    base_q = Intervencion.query.filter(
        Intervencion.unidad_id == current_user.unidad_id,
        Intervencion.activo.is_(True)
    )
    
    # Determinar agrupación
    if agrupacion == "dinar":
        grupo_campo = Intervencion.dinar
        grupo_nombre = "DINAR"
    elif agrupacion == "sinar":
        grupo_campo = Intervencion.sinar
        grupo_nombre = "SINAR"
    elif agrupacion == "dpto_operativo":
        grupo_campo = Intervencion.dpto_operativo
        grupo_nombre = "Departamento Operativo"
    else:
        grupo_campo = Intervencion.dinar
        grupo_nombre = "DINAR"
        agrupacion = "dinar"
    
    # Estadísticas por grupo
    stats_query = (
        base_q
        .filter(grupo_campo.isnot(None), grupo_campo != "")
        .with_entities(
            grupo_campo.label("grupo"),
            func.count(Intervencion.id).label("total"),
            func.count(func.distinct(Intervencion.id)).label("total_registros")
        )
        .group_by(grupo_campo)
        .order_by(func.count(Intervencion.id).desc())
    )
    
    if filtro_texto:
        stats_query = stats_query.filter(grupo_campo.ilike(f"%{filtro_texto}%"))
    
    stats = stats_query.all()
    
    # Agregar conteo de observaciones por grupo
    grupos_con_stats = []
    for stat in stats:
        obs_count = (
            db.session.query(func.count(AuditoriaObservacion.id))
            .join(
                Intervencion,
                (AuditoriaObservacion.modulo == "intervenciones") &
                (AuditoriaObservacion.registro_id == Intervencion.id)
            )
            .filter(
                Intervencion.unidad_id == current_user.unidad_id,
                Intervencion.activo.is_(True),
                grupo_campo == stat.grupo
            )
            .scalar()
        ) or 0
        
        obs_pendientes = (
            db.session.query(func.count(AuditoriaObservacion.id))
            .join(
                Intervencion,
                (AuditoriaObservacion.modulo == "intervenciones") &
                (AuditoriaObservacion.registro_id == Intervencion.id)
            )
            .filter(
                Intervencion.unidad_id == current_user.unidad_id,
                Intervencion.activo.is_(True),
                grupo_campo == stat.grupo,
                AuditoriaObservacion.resuelta.is_(False)
            )
            .scalar()
        ) or 0
        
        grupos_con_stats.append({
            "grupo": stat.grupo,
            "total_registros": stat.total_registros,
            "total_observaciones": obs_count,
            "observaciones_pendientes": obs_pendientes
        })
    
    return render_template(
        "auditoria/intervenciones.html",
        grupos=grupos_con_stats,
        agrupacion=agrupacion,
        grupo_nombre=grupo_nombre,
        filtro_texto=filtro_texto,
        can_create=_can_create_observacion(),
        can_resolve=_can_resolve_observacion()
    )


@bp.route("/estadisticas")
def estadisticas():
    """Dashboard de estadísticas de auditoría"""
    if not _can_view_auditoria():
        abort(403)
    
    # Estadísticas generales de denuncias web
    total_denuncias = (
        DenunciaWeb.query
        .filter(
            DenunciaWeb.unidad_id == current_user.unidad_id,
            DenunciaWeb.activo.is_(True)
        )
        .count()
    )
    
    obs_denuncias = (
        db.session.query(func.count(AuditoriaObservacion.id))
        .filter(
            AuditoriaObservacion.modulo == "denuncias_web",
            AuditoriaObservacion.unidad_id == current_user.unidad_id
        )
        .scalar()
    ) or 0
    
    obs_denuncias_pendientes = (
        db.session.query(func.count(AuditoriaObservacion.id))
        .filter(
            AuditoriaObservacion.modulo == "denuncias_web",
            AuditoriaObservacion.unidad_id == current_user.unidad_id,
            AuditoriaObservacion.resuelta.is_(False)
        )
        .scalar()
    ) or 0
    
    # Estadísticas generales de intervenciones
    total_intervenciones = (
        Intervencion.query
        .filter(
            Intervencion.unidad_id == current_user.unidad_id,
            Intervencion.activo.is_(True)
        )
        .count()
    )
    
    obs_intervenciones = (
        db.session.query(func.count(AuditoriaObservacion.id))
        .filter(
            AuditoriaObservacion.modulo == "intervenciones",
            AuditoriaObservacion.unidad_id == current_user.unidad_id
        )
        .scalar()
    ) or 0
    
    obs_intervenciones_pendientes = (
        db.session.query(func.count(AuditoriaObservacion.id))
        .filter(
            AuditoriaObservacion.modulo == "intervenciones",
            AuditoriaObservacion.unidad_id == current_user.unidad_id,
            AuditoriaObservacion.resuelta.is_(False)
        )
        .scalar()
    ) or 0
    
    # Top auditores
    top_auditores = (
        db.session.query(
            AuditoriaObservacion.auditor_id,
            func.count(AuditoriaObservacion.id).label("total")
        )
        .filter(AuditoriaObservacion.unidad_id == current_user.unidad_id)
        .group_by(AuditoriaObservacion.auditor_id)
        .order_by(func.count(AuditoriaObservacion.id).desc())
        .limit(10)
        .all()
    )
    
    return render_template(
        "auditoria/estadisticas.html",
        total_denuncias=total_denuncias,
        obs_denuncias=obs_denuncias,
        obs_denuncias_pendientes=obs_denuncias_pendientes,
        total_intervenciones=total_intervenciones,
        obs_intervenciones=obs_intervenciones,
        obs_intervenciones_pendientes=obs_intervenciones_pendientes,
        top_auditores=top_auditores
    )

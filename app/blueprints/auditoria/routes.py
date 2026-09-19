"""
Rutas del módulo Auditoría — control de calidad sobre Denuncias Web.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, inspect, text

from app.blueprints.analisis_denuncias import routes as ad_routes
from app.blueprints.auditoria import bp
from app.extensions import db
from app.models.analisis_denuncias import DenunciaWeb
from app.models.auditoria import (
    CAMPO_GENERAL,
    CAMPOS_AUDITABLES_MAP,
    CAMPOS_PRINCIPALES,
    CAMPOS_SECUNDARIOS,
    AuditoriaObs,
)

_schema_checked = False
_OLD_TABLES = ("auditoria_observaciones", "auditoria_resumenes")
_LONG_FIELDS = frozenset({"relato", "investigados", "observacion_interna"})


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("AUDITORIA_VIEW")


def _can_edit() -> bool:
    return _is_superadmin() or current_user.has_permission("AUDITORIA_EDIT")


def _ensure_schema():
    """Crea tabla limpia y elimina restos del módulo fallido."""
    global _schema_checked
    if _schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())

    for old in _OLD_TABLES:
        if old in existing:
            db.session.execute(text(f"DROP TABLE IF EXISTS `{old}`"))
            db.session.commit()

    if AuditoriaObs.__tablename__ not in existing:
        AuditoriaObs.__table__.create(bind=db.engine)

    _schema_checked = True


def _fmt_valor(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M") if (v.hour or v.minute or v.second) else v.strftime("%d/%m/%Y")
    return str(v).strip()


def _valor_campo(row: DenunciaWeb, campo: str) -> str:
    """Valor mostrado/guardado como snapshot. Relato unifica original + relato."""
    if campo == "relato":
        return _fmt_valor(row.relato_original or row.relato)
    return _fmt_valor(getattr(row, campo, None))


def _denuncia_or_404(denuncia_id: int) -> DenunciaWeb:
    row = (
        DenunciaWeb.query.filter(
            DenunciaWeb.id == denuncia_id,
            DenunciaWeb.unidad_id == current_user.unidad_id,
            DenunciaWeb.activo.is_(True),
        ).first()
    )
    if not row:
        abort(404)
    return row


def _obs_map(denuncia_id: int) -> dict[str, AuditoriaObs]:
    rows = (
        AuditoriaObs.query.filter_by(
            unidad_id=current_user.unidad_id,
            denuncia_id=denuncia_id,
        )
        .order_by(AuditoriaObs.updated_at.desc())
        .all()
    )
    return {o.campo: o for o in rows}


def _build_campos(row: DenunciaWeb, obs_by_campo: dict, spec: tuple) -> list[dict]:
    out = []
    for key, label in spec:
        obs = obs_by_campo.get(key)
        valor = _valor_campo(row, key)
        out.append(
            {
                "key": key,
                "label": label,
                "valor": valor,
                "obs": obs,
                "es_largo": key in _LONG_FIELDS or len(valor) > 180,
            }
        )
    return out


@bp.route("/")
@login_required
def index():
    return redirect(url_for("auditoria.listado"))


@bp.route("/denuncias")
@login_required
def listado():
    if not _can_view():
        flash("No tenés permiso para ver Auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()

    solo_obs = (request.args.get("solo_obs") or "").strip() == "1"
    estado_obs = (request.args.get("estado_obs") or "").strip()

    # Mismos filtros avanzados que Denuncias Web
    q = ad_routes._apply_filters(ad_routes._base_q())

    obs_count_sq = (
        db.session.query(
            AuditoriaObs.denuncia_id.label("denuncia_id"),
            func.count(AuditoriaObs.id).label("obs_total"),
            func.sum(case((AuditoriaObs.estado == "pendiente", 1), else_=0)).label("obs_pendientes"),
        )
        .filter(AuditoriaObs.unidad_id == current_user.unidad_id)
        .group_by(AuditoriaObs.denuncia_id)
        .subquery()
    )

    q = q.outerjoin(obs_count_sq, DenunciaWeb.id == obs_count_sq.c.denuncia_id)
    if solo_obs:
        q = q.filter(obs_count_sq.c.obs_total > 0)
    if estado_obs == "pendiente":
        q = q.filter(obs_count_sq.c.obs_pendientes > 0)
    elif estado_obs == "resuelta":
        q = q.filter(
            obs_count_sq.c.obs_total > 0,
            obs_count_sq.c.obs_pendientes == 0,
        )

    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(200, max(20, request.args.get("per_page", type=int) or 50))
    total = q.with_entities(func.count(DenunciaWeb.id)).scalar() or 0
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages

    rows = (
        q.with_entities(
            DenunciaWeb,
            func.coalesce(obs_count_sq.c.obs_total, 0).label("obs_total"),
            func.coalesce(obs_count_sq.c.obs_pendientes, 0).label("obs_pendientes"),
        )
        .order_by(DenunciaWeb.fecha_denuncia.desc(), DenunciaWeb.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    args_no_page = request.args.to_dict(flat=False)
    args_no_page.pop("page", None)
    qs_no_page = urlencode(args_no_page, doseq=True)

    selected = ad_routes._selected_filters()
    selected["solo_obs"] = solo_obs
    selected["estado_obs"] = estado_obs

    return render_template(
        "auditoria/listado.html",
        rows=rows,
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        qs_no_page=qs_no_page,
        filtros=ad_routes._filter_options(),
        selected=selected,
        can_edit=_can_edit(),
    )


@bp.route("/denuncias/<int:denuncia_id>")
@login_required
def detalle(denuncia_id: int):
    if not _can_view():
        flash("No tenés permiso para ver Auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()

    row = _denuncia_or_404(denuncia_id)
    obs_by_campo = _obs_map(denuncia_id)
    general = obs_by_campo.get(CAMPO_GENERAL)
    campos = _build_campos(row, obs_by_campo, CAMPOS_PRINCIPALES)
    campos_sec = _build_campos(row, obs_by_campo, CAMPOS_SECUNDARIOS)

    return render_template(
        "auditoria/detalle.html",
        row=row,
        campos=campos,
        campos_sec=campos_sec,
        general=general,
        campo_general=CAMPO_GENERAL,
        can_edit=_can_edit(),
    )


@bp.route("/denuncias/<int:denuncia_id>/obs", methods=["POST"])
@login_required
def guardar_obs(denuncia_id: int):
    if not _can_edit():
        flash("No tenés permiso para cargar observaciones de auditoría.", "warning")
        return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))
    _ensure_schema()

    row = _denuncia_or_404(denuncia_id)
    campo = (request.form.get("campo") or "").strip()
    if campo != CAMPO_GENERAL and campo not in CAMPOS_AUDITABLES_MAP:
        flash("Campo de auditoría inválido.", "danger")
        return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))

    valor_auditor = (request.form.get("valor_auditor") or "").strip() or None
    nota = (request.form.get("nota") or "").strip() or None
    if not valor_auditor and not nota:
        flash("Indicá al menos el valor según auditoría o una nota.", "warning")
        return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))

    valor_sistema = None if campo == CAMPO_GENERAL else (_valor_campo(row, campo) or None)

    obs = AuditoriaObs.query.filter_by(
        denuncia_id=row.id,
        campo=campo,
        unidad_id=current_user.unidad_id,
    ).first()
    if not obs:
        obs = AuditoriaObs(
            unidad_id=current_user.unidad_id,
            denuncia_id=row.id,
            campo=campo,
            auditor_id=current_user.id,
        )
        db.session.add(obs)

    obs.valor_sistema = valor_sistema
    obs.valor_auditor = valor_auditor
    obs.nota = nota
    obs.estado = "pendiente"
    obs.auditor_id = current_user.id
    obs.updated_at = datetime.utcnow()
    db.session.commit()

    flash("Observación de auditoría guardada (el dato original no se modificó).", "success")
    return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))


@bp.route("/denuncias/<int:denuncia_id>/obs/<int:obs_id>/estado", methods=["POST"])
@login_required
def cambiar_estado(denuncia_id: int, obs_id: int):
    if not _can_edit():
        flash("No tenés permiso para modificar observaciones.", "warning")
        return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))
    _ensure_schema()
    _denuncia_or_404(denuncia_id)

    obs = AuditoriaObs.query.filter_by(
        id=obs_id,
        denuncia_id=denuncia_id,
        unidad_id=current_user.unidad_id,
    ).first_or_404()

    nuevo = (request.form.get("estado") or "").strip()
    if nuevo not in ("pendiente", "resuelta"):
        flash("Estado inválido.", "danger")
        return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))

    obs.estado = nuevo
    obs.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"Observación marcada como {nuevo}.", "success")
    return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))


@bp.route("/denuncias/<int:denuncia_id>/obs/<int:obs_id>/borrar", methods=["POST"])
@login_required
def borrar_obs(denuncia_id: int, obs_id: int):
    if not _can_edit():
        flash("No tenés permiso para borrar observaciones.", "warning")
        return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))
    _ensure_schema()
    _denuncia_or_404(denuncia_id)

    obs = AuditoriaObs.query.filter_by(
        id=obs_id,
        denuncia_id=denuncia_id,
        unidad_id=current_user.unidad_id,
    ).first_or_404()
    db.session.delete(obs)
    db.session.commit()
    flash("Observación eliminada.", "info")
    return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))

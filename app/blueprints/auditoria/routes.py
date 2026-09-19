"""
Rutas del módulo Auditoría — control de calidad sobre Denuncias Web.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, inspect, or_, text

from app.blueprints.analisis_denuncias import routes as ad_routes
from app.blueprints.auditoria import bp
from app.extensions import db
from app.models.analisis_denuncias import DenunciaWeb
from app.models.auditoria import (
    CAMPO_GENERAL,
    CAMPOS_AUDITABLES_MAP,
    CAMPOS_INTERV_LISTADO,
    CAMPOS_INTERV_MAP,
    CAMPOS_INTERV_PRINCIPALES,
    CAMPOS_INTERV_SECUNDARIOS,
    CAMPOS_LISTADO,
    CAMPOS_PRINCIPALES,
    CAMPOS_SECUNDARIOS,
    COLUMNAS_OCULTABLES,
    COLUMNAS_OCULTABLES_INTERV,
    ESTADO_LABEL,
    MODULO_DENUNCIAS,
    MODULO_INTERVENCIONES,
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
    """Crea/migra tabla de observaciones (denuncias + intervenciones)."""
    global _schema_checked
    if _schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    tname = AuditoriaObs.__tablename__

    for old in _OLD_TABLES:
        if old in existing:
            db.session.execute(text(f"DROP TABLE IF EXISTS `{old}`"))
            db.session.commit()

    if tname not in existing:
        AuditoriaObs.__table__.create(bind=db.engine)
    else:
        cols = {c.get("name") for c in insp.get_columns(tname)}
        # Quitar FK de denuncia_id si existe (para poder dejarla nullable)
        try:
            rows = db.session.execute(
                text(
                    """
                    SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = :t
                      AND COLUMN_NAME = 'denuncia_id'
                      AND REFERENCED_TABLE_NAME IS NOT NULL
                    """
                ),
                {"t": tname},
            ).fetchall()
            for (cname,) in rows:
                db.session.execute(text(f"ALTER TABLE `{tname}` DROP FOREIGN KEY `{cname}`"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        alters = []
        if "modulo" not in cols:
            alters.append("ADD COLUMN modulo VARCHAR(40) NOT NULL DEFAULT 'denuncias_web'")
        if "registro_id" not in cols:
            alters.append("ADD COLUMN registro_id INT NULL")
        if "intervencion_id" not in cols:
            alters.append("ADD COLUMN intervencion_id INT NULL")
        if "causas_id" not in cols:
            alters.append("ADD COLUMN causas_id VARCHAR(80) NULL")
        if alters:
            db.session.execute(text(f"ALTER TABLE `{tname}` " + ", ".join(alters)))
            db.session.commit()

        try:
            db.session.execute(text(f"ALTER TABLE `{tname}` MODIFY denuncia_id INT NULL"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        for idx_sql in (
            f"CREATE INDEX ix_auditoria_obs_unidad_causas ON `{tname}` (unidad_id, causas_id)",
            f"CREATE INDEX ix_auditoria_obs_modulo_reg ON `{tname}` (unidad_id, modulo, registro_id)",
        ):
            try:
                db.session.execute(text(idx_sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Backfill
        db.session.execute(
            text(
                f"""
                UPDATE `{tname}`
                SET modulo = COALESCE(NULLIF(modulo, ''), 'denuncias_web'),
                    registro_id = COALESCE(registro_id, denuncia_id)
                WHERE registro_id IS NULL AND denuncia_id IS NOT NULL
                """
            )
        )
        db.session.execute(
            text(
                f"""
                UPDATE `{tname}` o
                INNER JOIN analisis_denuncias_web d ON d.id = COALESCE(o.registro_id, o.denuncia_id)
                SET o.causas_id = d.causas_id
                WHERE (o.causas_id IS NULL OR o.causas_id = '')
                  AND (o.modulo = 'denuncias_web' OR o.modulo IS NULL OR o.modulo = '')
                """
            )
        )
        db.session.commit()

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
    if campo == "actuario":
        grado = (row.actuario_grado or "").strip()
        nombre = (row.actuario_apenom or "").strip()
        return f"{grado} {nombre}".strip()
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
        AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_DENUNCIAS,
            or_(
                AuditoriaObs.registro_id == denuncia_id,
                AuditoriaObs.denuncia_id == denuncia_id,
            ),
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


def _safe_next() -> str:
    n = (request.form.get("next") or request.args.get("next") or "").strip()
    if n.startswith("/auditoria") and not n.startswith("//"):
        return n
    return ""


def _redirect_after(denuncia_id: int):
    nxt = _safe_next()
    if nxt:
        return redirect(nxt)
    return redirect(url_for("auditoria.detalle", denuncia_id=denuncia_id))


def _estado_ui(code: str | None) -> str:
    if not code:
        return "Pendiente a auditar"
    return ESTADO_LABEL.get(code, code)


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

    q = ad_routes._apply_filters(ad_routes._base_q())

    obs_count_sq = (
        db.session.query(
            func.coalesce(AuditoriaObs.registro_id, AuditoriaObs.denuncia_id).label("denuncia_id"),
            func.count(AuditoriaObs.id).label("obs_total"),
            func.sum(case((AuditoriaObs.estado == "pendiente", 1), else_=0)).label("obs_pendientes"),
        )
        .filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_DENUNCIAS,
        )
        .group_by(func.coalesce(AuditoriaObs.registro_id, AuditoriaObs.denuncia_id))
        .subquery()
    )

    q = q.outerjoin(obs_count_sq, DenunciaWeb.id == obs_count_sq.c.denuncia_id)
    if solo_obs:
        q = q.filter(obs_count_sq.c.obs_total > 0)
    if estado_obs == "pendiente":
        q = q.filter(
            or_(
                obs_count_sq.c.obs_total.is_(None),
                obs_count_sq.c.obs_total == 0,
                obs_count_sq.c.obs_pendientes > 0,
            )
        )
    elif estado_obs == "resuelta":
        q = q.filter(
            obs_count_sq.c.obs_total > 0,
            obs_count_sq.c.obs_pendientes == 0,
        )

    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(100, max(10, request.args.get("per_page", type=int) or 25))
    total = q.with_entities(func.count(DenunciaWeb.id)).scalar() or 0
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages

    raw_rows = (
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

    ids = [r.id for r, _, _ in raw_rows]
    obs_by_den = {i: {} for i in ids}
    if ids:
        for o in AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_DENUNCIAS,
            or_(
                AuditoriaObs.registro_id.in_(ids),
                AuditoriaObs.denuncia_id.in_(ids),
            ),
        ).all():
            rid = o.registro_id or o.denuncia_id
            if rid:
                obs_by_den[rid][o.campo] = o

    items = []
    for r, obs_total, obs_pendientes in raw_rows:
        obs_map = obs_by_den.get(r.id, {})
        if obs_total and not obs_pendientes:
            row_estado = "auditado"
        else:
            row_estado = "pendiente"
        campos = []
        for key, label in CAMPOS_LISTADO:
            obs = obs_map.get(key)
            valor = _valor_campo(r, key)
            short = valor if len(valor) <= 80 else (valor[:77] + "…")
            campos.append(
                {
                    "key": key,
                    "label": label,
                    "valor": valor,
                    "short": short or "—",
                    "obs": obs,
                    "aud_short": (
                        ((obs.valor_auditor or obs.nota or "")[:80] + ("…" if len(obs.valor_auditor or obs.nota or "") > 80 else ""))
                        if obs and (obs.valor_auditor or obs.nota)
                        else ""
                    ),
                }
            )
        items.append(
            {
                "row": r,
                "obs_total": int(obs_total or 0),
                "obs_pendientes": int(obs_pendientes or 0),
                "row_estado": row_estado,
                "campos": campos,
                "general": obs_map.get(CAMPO_GENERAL),
            }
        )

    args_no_page = request.args.to_dict(flat=False)
    args_no_page.pop("page", None)
    qs_no_page = urlencode(args_no_page, doseq=True)
    listado_url = url_for("auditoria.listado")
    if qs_no_page:
        listado_url = f"{listado_url}?{qs_no_page}"
        if page > 1:
            listado_url += f"&page={page}"
    elif page > 1:
        listado_url = f"{listado_url}?page={page}"

    selected = ad_routes._selected_filters()
    selected["solo_obs"] = solo_obs
    selected["estado_obs"] = estado_obs

    return render_template(
        "auditoria/listado.html",
        items=items,
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        qs_no_page=qs_no_page,
        listado_url=listado_url,
        columnas=CAMPOS_LISTADO,
        columnas_ocultables=sorted(COLUMNAS_OCULTABLES),
        filtros=ad_routes._filter_options(),
        selected=selected,
        can_edit=_can_edit(),
        campo_general=CAMPO_GENERAL,
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
        estado_label=ESTADO_LABEL,
    )


@bp.route("/denuncias/<int:denuncia_id>/obs", methods=["POST"])
@login_required
def guardar_obs(denuncia_id: int):
    if not _can_edit():
        flash("No tenés permiso para cargar observaciones de auditoría.", "warning")
        return _redirect_after(denuncia_id)
    _ensure_schema()

    row = _denuncia_or_404(denuncia_id)
    campo = (request.form.get("campo") or "").strip()
    if campo != CAMPO_GENERAL and campo not in CAMPOS_AUDITABLES_MAP:
        flash("Campo de auditoría inválido.", "danger")
        return _redirect_after(denuncia_id)

    valor_auditor = (request.form.get("valor_auditor") or "").strip() or None
    nota = (request.form.get("nota") or "").strip() or None
    if not valor_auditor and not nota:
        flash("Indicá al menos el valor según auditoría o una nota.", "warning")
        return _redirect_after(denuncia_id)

    valor_sistema = None if campo == CAMPO_GENERAL else (_valor_campo(row, campo) or None)

    obs = AuditoriaObs.query.filter(
        AuditoriaObs.unidad_id == current_user.unidad_id,
        AuditoriaObs.modulo == MODULO_DENUNCIAS,
        AuditoriaObs.campo == campo,
        or_(
            AuditoriaObs.registro_id == row.id,
            AuditoriaObs.denuncia_id == row.id,
        ),
    ).first()
    if not obs:
        obs = AuditoriaObs(
            unidad_id=current_user.unidad_id,
            modulo=MODULO_DENUNCIAS,
            registro_id=row.id,
            denuncia_id=row.id,
            campo=campo,
            auditor_id=current_user.id,
        )
        db.session.add(obs)

    obs.modulo = MODULO_DENUNCIAS
    obs.registro_id = row.id
    obs.denuncia_id = row.id
    obs.causas_id = row.causas_id
    obs.valor_sistema = valor_sistema
    obs.valor_auditor = valor_auditor
    obs.nota = nota
    obs.estado = "pendiente"
    obs.auditor_id = current_user.id
    obs.updated_at = datetime.utcnow()
    db.session.commit()

    flash("Observación de auditoría guardada (el dato original no se modificó).", "success")
    return _redirect_after(denuncia_id)


@bp.route("/denuncias/<int:denuncia_id>/obs/<int:obs_id>/estado", methods=["POST"])
@login_required
def cambiar_estado(denuncia_id: int, obs_id: int):
    if not _can_edit():
        flash("No tenés permiso para modificar observaciones.", "warning")
        return _redirect_after(denuncia_id)
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
        return _redirect_after(denuncia_id)

    obs.estado = nuevo
    obs.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"Marcado como {_estado_ui(nuevo)}.", "success")
    return _redirect_after(denuncia_id)


@bp.route("/denuncias/<int:denuncia_id>/obs/<int:obs_id>/borrar", methods=["POST"])
@login_required
def borrar_obs(denuncia_id: int, obs_id: int):
    if not _can_edit():
        flash("No tenés permiso para borrar observaciones.", "warning")
        return _redirect_after(denuncia_id)
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
    return _redirect_after(denuncia_id)


def _filtered_denuncias_q():
    return ad_routes._apply_filters(ad_routes._base_q())


@bp.route("/export.xlsx")
@login_required
def export_xlsx():
    """Exporta Excel según modo: completo | observaciones."""
    if not _can_view():
        flash("No tenés permiso para exportar auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()

    modo = (request.args.get("modo") or "completo").strip().lower()
    if modo not in ("completo", "observaciones"):
        modo = "completo"

    from io import BytesIO

    import pandas as pd
    from flask import send_file

    q = _filtered_denuncias_q().order_by(DenunciaWeb.fecha_denuncia.desc(), DenunciaWeb.id.desc())
    denuncias = q.limit(20000).all()
    ids = [d.id for d in denuncias]

    obs_rows = []
    if ids:
        obs_rows = (
            AuditoriaObs.query.filter(
                AuditoriaObs.unidad_id == current_user.unidad_id,
                AuditoriaObs.modulo == MODULO_DENUNCIAS,
                or_(
                    AuditoriaObs.registro_id.in_(ids),
                    AuditoriaObs.denuncia_id.in_(ids),
                ),
            )
            .order_by(AuditoriaObs.campo.asc())
            .all()
        )
    obs_by_den = {}
    for o in obs_rows:
        rid = o.registro_id or o.denuncia_id
        if rid:
            obs_by_den.setdefault(rid, []).append(o)

    buf = BytesIO()
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M")

    if modo == "observaciones":
        # Solo lo que anotó el auditor (para entregar / imprimir a auditados)
        data = []
        for d in denuncias:
            for o in obs_by_den.get(d.id, []):
                data.append(
                    {
                        "Nro actuación": d.nro_actuacion or "",
                        "Causa ID": d.causas_id or o.causas_id or "",
                        "Fecha denuncia": d.fecha_denuncia.strftime("%d/%m/%Y") if d.fecha_denuncia else "",
                        "Dependencia": d.desc_dep_registro or "",
                        "Actuario": f"{(d.actuario_grado or '').strip()} {(d.actuario_apenom or '').strip()}".strip(),
                        "Campo": o.campo_label,
                        "Valor según sistema (al auditar)": o.valor_sistema or "",
                        "Valor según auditoría": o.valor_auditor or "",
                        "Nota del auditor": o.nota or "",
                        "Estado": ESTADO_LABEL.get(o.estado, o.estado),
                        "Fecha observación": o.updated_at.strftime("%d/%m/%Y %H:%M") if o.updated_at else "",
                    }
                )
        df = pd.DataFrame(data)
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Observaciones auditoría")
        fname = f"auditoria_solo_observaciones_{stamp}.xlsx"
    else:
        # Completo: datos cargados + columnas de auditoría por campo con obs
        base_rows = []
        for d in denuncias:
            base = {
                "Nro actuación": d.nro_actuacion or "",
                "Causa ID": d.causas_id or "",
                "Fecha denuncia": d.fecha_denuncia.strftime("%d/%m/%Y") if d.fecha_denuncia else "",
                "Estado causa": d.causa_estado or "",
                "Dependencia": d.desc_dep_registro or "",
                "Dep. actuario": d.desc_dep_actuario or "",
                "Actuario": f"{(d.actuario_grado or '').strip()} {(d.actuario_apenom or '').strip()}".strip(),
                "Localidad": d.localidad or "",
                "Barrio": d.barrio or "",
                "Latitud": d.latitud if d.latitud is not None else "",
                "Longitud": d.longitud if d.longitud is not None else "",
                "Investigados": d.investigados or "",
                "Relato": (d.relato_original or d.relato or ""),
            }
            obs_list = obs_by_den.get(d.id, [])
            if not obs_list:
                base["Estado auditoría"] = "Pendiente a auditar"
                base_rows.append(base)
            else:
                pendientes = sum(1 for o in obs_list if o.estado == "pendiente")
                base["Estado auditoría"] = "Pendiente a auditar" if pendientes else "Auditado"
                base["Cant. observaciones"] = len(obs_list)
                base_rows.append(base)

        obs_data = []
        for d in denuncias:
            for o in obs_by_den.get(d.id, []):
                obs_data.append(
                    {
                        "Nro actuación": d.nro_actuacion or "",
                        "Causa ID": d.causas_id or "",
                        "Campo": o.campo_label,
                        "Valor cargado (snapshot)": o.valor_sistema or "",
                        "Valor según auditoría": o.valor_auditor or "",
                        "Nota": o.nota or "",
                        "Estado": ESTADO_LABEL.get(o.estado, o.estado),
                    }
                )

        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame(base_rows).to_excel(writer, index=False, sheet_name="Denuncias")
            pd.DataFrame(obs_data).to_excel(writer, index=False, sheet_name="Observaciones")
        fname = f"auditoria_completo_{stamp}.xlsx"

    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
"""
Rutas de auditoría para Análisis de Intervenciones.
"""
from __future__ import annotations

from datetime import date, datetime, time
from io import BytesIO
from urllib.parse import urlencode

import pandas as pd
from flask import flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_

from app.blueprints.analisis_intervenciones import routes as ai_routes
from app.blueprints.auditoria import bp
from app.blueprints.auditoria.routes import (
    _can_edit,
    _can_view,
    _ensure_schema,
    _fmt_valor,
    _is_superadmin,
    _redirect_after,
    _safe_next,
)
from app.extensions import db
from app.models.analisis_intervenciones import AnalisisIntervencion
from app.models.auditoria import (
    CAMPO_GENERAL,
    CAMPOS_INTERV_LISTADO,
    CAMPOS_INTERV_MAP,
    CAMPOS_INTERV_PRINCIPALES,
    CAMPOS_INTERV_SECUNDARIOS,
    COLUMNAS_OCULTABLES_INTERV,
    ESTADO_LABEL,
    MODULO_INTERVENCIONES,
    AuditoriaObs,
)


def _fmt_num_ar(v: float, decimals: int = 2) -> str:
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_gramos(v: float | int | None) -> str:
    n = float(v or 0)
    if n == 0:
        return "0 g"
    if abs(n) >= 1000:
        return f"{_fmt_num_ar(n / 1000, 3)} kg"
    # enteros sin decimales innecesarios
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))} g"
    return f"{_fmt_num_ar(n, 2)} g"


def _fmt_unidades(v: float | int | None, unidad: str = "u.") -> str:
    n = float(v or 0)
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))} {unidad}"
    return f"{_fmt_num_ar(n, 2)} {unidad}"


def _fmt_dinero(v: float | int | None, signo: str) -> str:
    n = float(v or 0)
    return f"{signo} {_fmt_num_ar(n, 2)}"


_CAMPOS_GRAMOS = frozenset(
    {"secuestro_marihuana", "secuestro_cocaina", "hojas_coca", "secuestro_dosis"}
)
_CAMPOS_UNIDADES = frozenset(
    {"secuestro_plantas", "secuestro_plantines", "secuestro_semillas"}
)
_CAMPOS_DINERO = {
    "pesos_arg": "$",
    "dolares": "US$",
    "euro": "€",
    "reales": "R$",
    "bolivianos": "Bs",
}


def _valor_campo_interv(row: AnalisisIntervencion, campo: str) -> str:
    if campo == "detenidos_total":
        total = (
            (row.det_hombre_may or 0)
            + (row.det_hombre_men or 0)
            + (row.det_mujer_may or 0)
            + (row.det_mujer_men or 0)
        )
        return str(int(total))
    if campo == "identificados_total":
        total = (
            (row.is_hombre_may or 0)
            + (row.is_hombre_men or 0)
            + (row.is_mujer_may or 0)
            + (row.is_mujer_men or 0)
        )
        return str(int(total))
    if campo == "interv_fecha":
        v = row.interv_fecha
        if isinstance(v, date):
            return v.strftime("%d/%m/%Y")
        return _fmt_valor(v)

    raw = getattr(row, campo, None)
    if campo in _CAMPOS_GRAMOS:
        return _fmt_gramos(raw)
    if campo in _CAMPOS_UNIDADES:
        return _fmt_unidades(raw)
    if campo in _CAMPOS_DINERO:
        return _fmt_dinero(raw, _CAMPOS_DINERO[campo])

    if isinstance(raw, float):
        if raw == int(raw):
            return str(int(raw))
        return _fmt_num_ar(raw, 2)
    if isinstance(raw, time):
        return raw.strftime("%H:%M")
    return _fmt_valor(raw)


def _interv_or_404(interv_id: int) -> AnalisisIntervencion:
    from flask import abort

    row = AnalisisIntervencion.query.filter(
        AnalisisIntervencion.id == interv_id,
        AnalisisIntervencion.unidad_id == current_user.unidad_id,
        AnalisisIntervencion.activo.is_(True),
    ).first()
    if not row:
        abort(404)
    return row


def _obs_map_interv(interv_id: int) -> dict[str, AuditoriaObs]:
    rows = (
        AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_INTERVENCIONES,
            or_(
                AuditoriaObs.registro_id == interv_id,
                AuditoriaObs.intervencion_id == interv_id,
            ),
        )
        .order_by(AuditoriaObs.updated_at.desc())
        .all()
    )
    return {o.campo: o for o in rows}


def _build_campos_interv(row, obs_by_campo, spec):
    out = []
    for key, label in spec:
        obs = obs_by_campo.get(key)
        valor = _valor_campo_interv(row, key)
        out.append(
            {
                "key": key,
                "label": label,
                "valor": valor,
                "obs": obs,
                "es_largo": len(valor) > 180,
            }
        )
    return out


@bp.route("/intervenciones")
@login_required
def listado_intervenciones():
    if not _can_view():
        flash("No tenés permiso para ver Auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()

    solo_obs = (request.args.get("solo_obs") or "").strip() == "1"
    estado_obs = (request.args.get("estado_obs") or "").strip()

    q = ai_routes._apply_filters(ai_routes._base_q())

    obs_count_sq = (
        db.session.query(
            func.coalesce(AuditoriaObs.registro_id, AuditoriaObs.intervencion_id).label("intervencion_id"),
            func.count(AuditoriaObs.id).label("obs_total"),
            func.sum(case((AuditoriaObs.estado == "pendiente", 1), else_=0)).label("obs_pendientes"),
        )
        .filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_INTERVENCIONES,
        )
        .group_by(func.coalesce(AuditoriaObs.registro_id, AuditoriaObs.intervencion_id))
        .subquery()
    )

    q = q.outerjoin(obs_count_sq, AnalisisIntervencion.id == obs_count_sq.c.intervencion_id)
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
        q = q.filter(obs_count_sq.c.obs_total > 0, obs_count_sq.c.obs_pendientes == 0)

    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(100, max(10, request.args.get("per_page", type=int) or 25))
    total = q.with_entities(func.count(AnalisisIntervencion.id)).scalar() or 0
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages

    raw_rows = (
        q.with_entities(
            AnalisisIntervencion,
            func.coalesce(obs_count_sq.c.obs_total, 0).label("obs_total"),
            func.coalesce(obs_count_sq.c.obs_pendientes, 0).label("obs_pendientes"),
        )
        .order_by(AnalisisIntervencion.interv_fecha.desc(), AnalisisIntervencion.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    ids = [r.id for r, _, _ in raw_rows]
    obs_by = {i: {} for i in ids}
    if ids:
        for o in AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_INTERVENCIONES,
            or_(
                AuditoriaObs.registro_id.in_(ids),
                AuditoriaObs.intervencion_id.in_(ids),
            ),
        ).all():
            rid = o.registro_id or o.intervencion_id
            if rid:
                obs_by[rid][o.campo] = o

    items = []
    for r, obs_total, obs_pendientes in raw_rows:
        obs_map = obs_by.get(r.id, {})
        row_estado = "auditado" if obs_total and not obs_pendientes else "pendiente"
        campos = []
        for key, label in CAMPOS_INTERV_LISTADO:
            obs = obs_map.get(key)
            valor = _valor_campo_interv(r, key)
            short = valor if len(valor) <= 80 else (valor[:77] + "…")
            campos.append(
                {
                    "key": key,
                    "label": label,
                    "valor": valor,
                    "short": short or "—",
                    "obs": obs,
                    "aud_short": (
                        ((obs.valor_auditor or obs.nota or "")[:80]
                         + ("…" if len(obs.valor_auditor or obs.nota or "") > 80 else ""))
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
    listado_url = url_for("auditoria.listado_intervenciones")
    if qs_no_page:
        listado_url = f"{listado_url}?{qs_no_page}"
        if page > 1:
            listado_url += f"&page={page}"
    elif page > 1:
        listado_url = f"{listado_url}?page={page}"

    selected = {"solo_obs": solo_obs, "estado_obs": estado_obs}
    # filtros avanzados de intervenciones
    try:
        filtros = ai_routes._filter_options()
        selected.update(ai_routes._selected_filters())
    except Exception:
        filtros = {}

    return render_template(
        "auditoria/listado_intervenciones.html",
        items=items,
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        qs_no_page=qs_no_page,
        listado_url=listado_url,
        columnas=CAMPOS_INTERV_LISTADO,
        columnas_ocultables=sorted(COLUMNAS_OCULTABLES_INTERV),
        filtros=filtros,
        selected=selected,
        can_edit=_can_edit(),
        campo_general=CAMPO_GENERAL,
    )


@bp.route("/intervenciones/<int:interv_id>")
@login_required
def detalle_intervencion(interv_id: int):
    if not _can_view():
        flash("No tenés permiso para ver Auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()
    row = _interv_or_404(interv_id)
    obs_by = _obs_map_interv(interv_id)
    return render_template(
        "auditoria/detalle_intervencion.html",
        row=row,
        campos=_build_campos_interv(row, obs_by, CAMPOS_INTERV_PRINCIPALES),
        campos_sec=_build_campos_interv(row, obs_by, CAMPOS_INTERV_SECUNDARIOS),
        general=obs_by.get(CAMPO_GENERAL),
        campo_general=CAMPO_GENERAL,
        can_edit=_can_edit(),
        estado_label=ESTADO_LABEL,
    )


@bp.route("/intervenciones/<int:interv_id>/obs", methods=["POST"])
@login_required
def guardar_obs_intervencion(interv_id: int):
    if not _can_edit():
        flash("No tenés permiso para cargar observaciones.", "warning")
        return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))
    _ensure_schema()
    row = _interv_or_404(interv_id)
    campo = (request.form.get("campo") or "").strip()
    if campo != CAMPO_GENERAL and campo not in CAMPOS_INTERV_MAP:
        flash("Campo inválido.", "danger")
        return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))

    valor_auditor = (request.form.get("valor_auditor") or "").strip() or None
    nota = (request.form.get("nota") or "").strip() or None
    if not valor_auditor and not nota:
        flash("Indicá valor según auditoría o una nota.", "warning")
        return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))

    valor_sistema = None if campo == CAMPO_GENERAL else (_valor_campo_interv(row, campo) or None)
    negocio = str(row.causas_interv_id)

    obs = AuditoriaObs.query.filter(
        AuditoriaObs.unidad_id == current_user.unidad_id,
        AuditoriaObs.modulo == MODULO_INTERVENCIONES,
        AuditoriaObs.campo == campo,
        or_(
            AuditoriaObs.registro_id == row.id,
            AuditoriaObs.intervencion_id == row.id,
        ),
    ).first()
    if not obs:
        obs = AuditoriaObs(
            unidad_id=current_user.unidad_id,
            modulo=MODULO_INTERVENCIONES,
            registro_id=row.id,
            intervencion_id=row.id,
            campo=campo,
            auditor_id=current_user.id,
        )
        db.session.add(obs)

    obs.modulo = MODULO_INTERVENCIONES
    obs.registro_id = row.id
    obs.intervencion_id = row.id
    obs.causas_id = negocio
    obs.valor_sistema = valor_sistema
    obs.valor_auditor = valor_auditor
    obs.nota = nota
    obs.estado = "pendiente"
    obs.auditor_id = current_user.id
    obs.updated_at = datetime.utcnow()
    db.session.commit()

    flash("Observación guardada (dato original intacto).", "success")
    nxt = _safe_next()
    if nxt:
        return redirect(nxt)
    return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))


@bp.route("/intervenciones/<int:interv_id>/obs/<int:obs_id>/estado", methods=["POST"])
@login_required
def cambiar_estado_intervencion(interv_id: int, obs_id: int):
    if not _can_edit():
        flash("Sin permiso.", "warning")
        return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))
    _ensure_schema()
    _interv_or_404(interv_id)
    obs = AuditoriaObs.query.filter(
        AuditoriaObs.id == obs_id,
        AuditoriaObs.unidad_id == current_user.unidad_id,
        AuditoriaObs.modulo == MODULO_INTERVENCIONES,
        or_(
            AuditoriaObs.registro_id == interv_id,
            AuditoriaObs.intervencion_id == interv_id,
        ),
    ).first_or_404()
    nuevo = (request.form.get("estado") or "").strip()
    if nuevo not in ("pendiente", "resuelta"):
        flash("Estado inválido.", "danger")
        return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))
    obs.estado = nuevo
    obs.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"Marcado como {ESTADO_LABEL.get(nuevo, nuevo)}.", "success")
    nxt = _safe_next()
    if nxt:
        return redirect(nxt)
    return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))


@bp.route("/intervenciones/<int:interv_id>/obs/<int:obs_id>/borrar", methods=["POST"])
@login_required
def borrar_obs_intervencion(interv_id: int, obs_id: int):
    if not _can_edit():
        flash("Sin permiso.", "warning")
        return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))
    _ensure_schema()
    _interv_or_404(interv_id)
    obs = AuditoriaObs.query.filter(
        AuditoriaObs.id == obs_id,
        AuditoriaObs.unidad_id == current_user.unidad_id,
        AuditoriaObs.modulo == MODULO_INTERVENCIONES,
        or_(
            AuditoriaObs.registro_id == interv_id,
            AuditoriaObs.intervencion_id == interv_id,
        ),
    ).first_or_404()
    db.session.delete(obs)
    db.session.commit()
    flash("Observación eliminada.", "info")
    nxt = _safe_next()
    if nxt:
        return redirect(nxt)
    return redirect(url_for("auditoria.detalle_intervencion", interv_id=interv_id))


@bp.route("/export-intervenciones.xlsx")
@login_required
def export_intervenciones_xlsx():
    if not _can_view():
        flash("No tenés permiso.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()
    modo = (request.args.get("modo") or "observaciones").strip().lower()
    q = ai_routes._apply_filters(ai_routes._base_q()).order_by(
        AnalisisIntervencion.interv_fecha.desc()
    )
    rows = q.limit(20000).all()
    ids = [r.id for r in rows]
    obs_by = {}
    if ids:
        for o in AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_INTERVENCIONES,
            or_(AuditoriaObs.registro_id.in_(ids), AuditoriaObs.intervencion_id.in_(ids)),
        ).all():
            rid = o.registro_id or o.intervencion_id
            obs_by.setdefault(rid, []).append(o)

    data = []
    for r in rows:
        for o in obs_by.get(r.id, []):
            data.append(
                {
                    "Nro intervención": r.causas_interv_id,
                    "Fecha": r.interv_fecha.strftime("%d/%m/%Y") if r.interv_fecha else "",
                    "Tipo": r.tipo_interv_desc or "",
                    "Personal interviniente": r.pers_interviniente or "",
                    "Campo": o.campo_label,
                    "Valor sistema": o.valor_sistema or "",
                    "Valor auditoría": o.valor_auditor or "",
                    "Nota": o.nota or "",
                    "Estado": ESTADO_LABEL.get(o.estado, o.estado),
                }
            )
        if modo == "completo" and r.id not in obs_by:
            data.append(
                {
                    "Nro intervención": r.causas_interv_id,
                    "Fecha": r.interv_fecha.strftime("%d/%m/%Y") if r.interv_fecha else "",
                    "Tipo": r.tipo_interv_desc or "",
                    "Personal interviniente": r.pers_interviniente or "",
                    "Campo": "",
                    "Valor sistema": "",
                    "Valor auditoría": "",
                    "Nota": "",
                    "Estado": "Pendiente a auditar",
                }
            )

    buf = BytesIO()
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(data).to_excel(writer, index=False, sheet_name="Auditoría intervenciones")
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"auditoria_intervenciones_{modo}_{stamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

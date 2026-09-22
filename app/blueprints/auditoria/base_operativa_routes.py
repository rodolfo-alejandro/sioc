"""
Auditoría de Base Operativa (Excel Capital / Interior).
Mismo estilo que denuncias web e intervenciones.
"""
from __future__ import annotations

from datetime import date, datetime, time
from io import BytesIO
from urllib.parse import urlencode

import pandas as pd
from flask import flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_

from app.blueprints.auditoria import bp
from app.blueprints.auditoria.routes import (
    _can_edit,
    _can_view,
    _ensure_schema,
    _fmt_valor,
    _safe_next,
)
from app.blueprints.base_operativa import routes as bo_routes
from app.extensions import db
from app.models.auditoria import (
    CAMPO_GENERAL,
    CAMPOS_BASE_LISTADO,
    CAMPOS_BASE_MAP,
    CAMPOS_BASE_PRINCIPALES,
    CAMPOS_BASE_SECUNDARIOS,
    COLUMNAS_OCULTABLES_BASE,
    ESTADO_LABEL,
    MODULO_BASE_OPERATIVA,
    AuditoriaObs,
)
from app.models.base_operativa import BaseProcedimiento


def _fmt_num_ar(v: float, decimals: int = 2) -> str:
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_gramos(v: float | int | None) -> str:
    n = float(v or 0)
    if n == 0:
        return "0 g"
    if abs(n) >= 1000:
        return f"{_fmt_num_ar(n / 1000, 3)} kg"
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))} g"
    return f"{_fmt_num_ar(n, 2)} g"


def _fmt_kg(v: float | int | None) -> str:
    n = float(v or 0)
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))} kg"
    return f"{_fmt_num_ar(n, 3)} kg"


def _fmt_unidades(v: float | int | None) -> str:
    n = float(v or 0)
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))} u."
    return f"{_fmt_num_ar(n, 2)} u."


def _fmt_dinero(v: float | int | None, signo: str) -> str:
    return f"{signo} {_fmt_num_ar(float(v or 0), 2)}"


_CAMPOS_GRAMOS = frozenset({"marihuana_grs", "cocaina_grs"})
_CAMPOS_KG = frozenset({"hoja_coca_kg"})
_CAMPOS_UNIDADES = frozenset({"plantas", "plantines", "semillas"})
_CAMPOS_DINERO = {
    "pesos_arg": "$",
    "dolares": "US$",
    "euro": "€",
    "reales": "R$",
    "bolivianos": "Bs",
}


def _valor_campo_base(row: BaseProcedimiento, campo: str) -> str:
    if campo == "ambito":
        return (row.ambito or "").capitalize()
    if campo == "fecha":
        v = row.fecha
        return v.strftime("%d/%m/%Y") if isinstance(v, date) else _fmt_valor(v)

    raw = getattr(row, campo, None)
    if campo in _CAMPOS_GRAMOS:
        return _fmt_gramos(raw)
    if campo in _CAMPOS_KG:
        return _fmt_kg(raw)
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


def _proc_or_404(proc_id: int) -> BaseProcedimiento:
    from flask import abort

    row = BaseProcedimiento.query.filter(
        BaseProcedimiento.id == proc_id,
        BaseProcedimiento.unidad_id == current_user.unidad_id,
        BaseProcedimiento.activo.is_(True),
    ).first()
    if not row:
        abort(404)
    return row


def _obs_map(proc_id: int) -> dict[str, AuditoriaObs]:
    rows = (
        AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_BASE_OPERATIVA,
            AuditoriaObs.registro_id == proc_id,
        )
        .order_by(AuditoriaObs.updated_at.desc())
        .all()
    )
    return {o.campo: o for o in rows}


def _build_campos(row, obs_by_campo, spec):
    out = []
    for key, label in spec:
        obs = obs_by_campo.get(key)
        valor = _valor_campo_base(row, key)
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


def _base_q():
    return BaseProcedimiento.query.filter(
        BaseProcedimiento.unidad_id == current_user.unidad_id,
        BaseProcedimiento.activo.is_(True),
    )


def _apply_filters(q):
    ambito = (request.args.get("ambito") or "").strip().lower()
    if ambito in ("capital", "interior"):
        q = q.filter(BaseProcedimiento.ambito == ambito)

    qtxt = (request.args.get("q") or "").strip()
    if qtxt:
        like = f"%{qtxt}%"
        q = q.filter(
            or_(
                BaseProcedimiento.registro_nro.ilike(like),
                BaseProcedimiento.lugar_proced.ilike(like),
                BaseProcedimiento.localidad.ilike(like),
                BaseProcedimiento.barrio.ilike(like),
                BaseProcedimiento.acusados_texto.ilike(like),
                BaseProcedimiento.of_interviniente.ilike(like),
                BaseProcedimiento.delito.ilike(like),
                BaseProcedimiento.dependencia.ilike(like),
            )
        )

    localidad = (request.args.get("localidad") or "").strip()
    if localidad:
        q = q.filter(BaseProcedimiento.localidad == localidad)

    desde = (request.args.get("desde") or "").strip()
    hasta = (request.args.get("hasta") or "").strip()
    if desde:
        try:
            q = q.filter(BaseProcedimiento.fecha >= datetime.strptime(desde, "%Y-%m-%d").date())
        except Exception:
            pass
    if hasta:
        try:
            q = q.filter(BaseProcedimiento.fecha <= datetime.strptime(hasta, "%Y-%m-%d").date())
        except Exception:
            pass
    return q


@bp.route("/base-operativa")
@login_required
def listado_base_operativa():
    if not _can_view():
        flash("No tenés permiso para ver Auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()
    bo_routes._ensure_tables()

    solo_obs = (request.args.get("solo_obs") or "").strip() == "1"
    estado_obs = (request.args.get("estado_obs") or "").strip()

    q = _apply_filters(_base_q())

    obs_count_sq = (
        db.session.query(
            AuditoriaObs.registro_id.label("proc_id"),
            func.count(AuditoriaObs.id).label("obs_total"),
            func.sum(case((AuditoriaObs.estado == "pendiente", 1), else_=0)).label("obs_pendientes"),
        )
        .filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_BASE_OPERATIVA,
        )
        .group_by(AuditoriaObs.registro_id)
        .subquery()
    )

    q = q.outerjoin(obs_count_sq, BaseProcedimiento.id == obs_count_sq.c.proc_id)
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
    total = q.with_entities(func.count(BaseProcedimiento.id)).scalar() or 0
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages

    raw_rows = (
        q.with_entities(
            BaseProcedimiento,
            func.coalesce(obs_count_sq.c.obs_total, 0).label("obs_total"),
            func.coalesce(obs_count_sq.c.obs_pendientes, 0).label("obs_pendientes"),
        )
        .order_by(BaseProcedimiento.fecha.desc(), BaseProcedimiento.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    ids = [r.id for r, _, _ in raw_rows]
    obs_by = {i: {} for i in ids}
    if ids:
        for o in AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_BASE_OPERATIVA,
            AuditoriaObs.registro_id.in_(ids),
        ).all():
            if o.registro_id:
                obs_by[o.registro_id][o.campo] = o

    items = []
    for r, obs_total, obs_pendientes in raw_rows:
        obs_map = obs_by.get(r.id, {})
        row_estado = "auditado" if obs_total and not obs_pendientes else "pendiente"
        campos = []
        for key, label in CAMPOS_BASE_LISTADO:
            obs = obs_map.get(key)
            valor = _valor_campo_base(r, key)
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
    listado_url = url_for("auditoria.listado_base_operativa")
    if qs_no_page:
        listado_url = f"{listado_url}?{qs_no_page}"
        if page > 1:
            listado_url += f"&page={page}"
    elif page > 1:
        listado_url = f"{listado_url}?page={page}"

    localidades = [
        x[0]
        for x in db.session.query(BaseProcedimiento.localidad)
        .filter(
            BaseProcedimiento.unidad_id == current_user.unidad_id,
            BaseProcedimiento.activo.is_(True),
            BaseProcedimiento.localidad.isnot(None),
            BaseProcedimiento.localidad != "",
        )
        .distinct()
        .order_by(BaseProcedimiento.localidad)
        .limit(500)
        .all()
    ]

    return render_template(
        "auditoria/listado_base_operativa.html",
        items=items,
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        qs_no_page=qs_no_page,
        listado_url=listado_url,
        columnas=CAMPOS_BASE_LISTADO,
        columnas_ocultables=sorted(COLUMNAS_OCULTABLES_BASE),
        localidades=localidades,
        selected={
            "ambito": (request.args.get("ambito") or "").strip(),
            "q": (request.args.get("q") or "").strip(),
            "localidad": (request.args.get("localidad") or "").strip(),
            "desde": (request.args.get("desde") or "").strip(),
            "hasta": (request.args.get("hasta") or "").strip(),
            "solo_obs": solo_obs,
            "estado_obs": estado_obs,
        },
        can_edit=_can_edit(),
        campo_general=CAMPO_GENERAL,
    )


@bp.route("/base-operativa/<int:proc_id>")
@login_required
def detalle_base_operativa(proc_id: int):
    if not _can_view():
        flash("No tenés permiso para ver Auditoría.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()
    bo_routes._ensure_tables()
    row = _proc_or_404(proc_id)
    obs_by = _obs_map(proc_id)
    from app.models.base_operativa import BaseIdentificado

    identificados = (
        BaseIdentificado.query.filter_by(procedimiento_id=row.id)
        .order_by(BaseIdentificado.id)
        .all()
    )
    return render_template(
        "auditoria/detalle_base_operativa.html",
        row=row,
        campos=_build_campos(row, obs_by, CAMPOS_BASE_PRINCIPALES),
        campos_sec=_build_campos(row, obs_by, CAMPOS_BASE_SECUNDARIOS),
        identificados=identificados,
        general=obs_by.get(CAMPO_GENERAL),
        campo_general=CAMPO_GENERAL,
        can_edit=_can_edit(),
        estado_label=ESTADO_LABEL,
    )


@bp.route("/base-operativa/<int:proc_id>/obs", methods=["POST"])
@login_required
def guardar_obs_base(proc_id: int):
    if not _can_edit():
        flash("No tenés permiso para cargar observaciones.", "warning")
        return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))
    _ensure_schema()
    row = _proc_or_404(proc_id)
    campo = (request.form.get("campo") or "").strip()
    if campo != CAMPO_GENERAL and campo not in CAMPOS_BASE_MAP:
        flash("Campo inválido.", "danger")
        return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))

    valor_auditor = (request.form.get("valor_auditor") or "").strip() or None
    nota = (request.form.get("nota") or "").strip() or None
    if not valor_auditor and not nota:
        flash("Indicá valor según auditoría o una nota.", "warning")
        return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))

    valor_sistema = None if campo == CAMPO_GENERAL else (_valor_campo_base(row, campo) or None)

    obs = AuditoriaObs.query.filter(
        AuditoriaObs.unidad_id == current_user.unidad_id,
        AuditoriaObs.modulo == MODULO_BASE_OPERATIVA,
        AuditoriaObs.registro_id == row.id,
        AuditoriaObs.campo == campo,
    ).first()
    if not obs:
        obs = AuditoriaObs(
            unidad_id=current_user.unidad_id,
            modulo=MODULO_BASE_OPERATIVA,
            registro_id=row.id,
            campo=campo,
            auditor_id=current_user.id,
        )
        db.session.add(obs)

    obs.causas_id = row.clave_negocio
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
    return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))


@bp.route("/base-operativa/<int:proc_id>/obs/<int:obs_id>/estado", methods=["POST"])
@login_required
def cambiar_estado_base(proc_id: int, obs_id: int):
    if not _can_edit():
        flash("Sin permiso.", "warning")
        return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))
    _ensure_schema()
    _proc_or_404(proc_id)
    obs = AuditoriaObs.query.filter(
        AuditoriaObs.id == obs_id,
        AuditoriaObs.unidad_id == current_user.unidad_id,
        AuditoriaObs.modulo == MODULO_BASE_OPERATIVA,
        AuditoriaObs.registro_id == proc_id,
    ).first_or_404()
    nuevo = (request.form.get("estado") or "").strip()
    if nuevo not in ("pendiente", "resuelta"):
        flash("Estado inválido.", "danger")
        return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))
    obs.estado = nuevo
    obs.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"Marcado como {ESTADO_LABEL.get(nuevo, nuevo)}.", "success")
    nxt = _safe_next()
    if nxt:
        return redirect(nxt)
    return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))


@bp.route("/base-operativa/<int:proc_id>/obs/<int:obs_id>/borrar", methods=["POST"])
@login_required
def borrar_obs_base(proc_id: int, obs_id: int):
    if not _can_edit():
        flash("Sin permiso.", "warning")
        return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))
    _ensure_schema()
    _proc_or_404(proc_id)
    obs = AuditoriaObs.query.filter(
        AuditoriaObs.id == obs_id,
        AuditoriaObs.unidad_id == current_user.unidad_id,
        AuditoriaObs.modulo == MODULO_BASE_OPERATIVA,
        AuditoriaObs.registro_id == proc_id,
    ).first_or_404()
    db.session.delete(obs)
    db.session.commit()
    flash("Observación eliminada.", "info")
    nxt = _safe_next()
    if nxt:
        return redirect(nxt)
    return redirect(url_for("auditoria.detalle_base_operativa", proc_id=proc_id))


@bp.route("/export-base-operativa.xlsx")
@login_required
def export_base_operativa_xlsx():
    if not _can_view():
        flash("No tenés permiso.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_schema()
    modo = (request.args.get("modo") or "observaciones").strip().lower()
    q = _apply_filters(_base_q()).order_by(BaseProcedimiento.fecha.desc())
    rows = q.limit(20000).all()
    ids = [r.id for r in rows]
    obs_by: dict[int, list] = {}
    if ids:
        for o in AuditoriaObs.query.filter(
            AuditoriaObs.unidad_id == current_user.unidad_id,
            AuditoriaObs.modulo == MODULO_BASE_OPERATIVA,
            AuditoriaObs.registro_id.in_(ids),
        ).all():
            obs_by.setdefault(o.registro_id, []).append(o)

    data = []
    for r in rows:
        for o in obs_by.get(r.id, []):
            data.append(
                {
                    "CAP": r.registro_nro,
                    "Ámbito": (r.ambito or "").capitalize(),
                    "Fecha": r.fecha.strftime("%d/%m/%Y") if r.fecha else "",
                    "Lugar": r.lugar_proced or "",
                    "Acusados": r.acusados_texto or "",
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
                    "CAP": r.registro_nro,
                    "Ámbito": (r.ambito or "").capitalize(),
                    "Fecha": r.fecha.strftime("%d/%m/%Y") if r.fecha else "",
                    "Lugar": r.lugar_proced or "",
                    "Acusados": r.acusados_texto or "",
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
        pd.DataFrame(data).to_excel(writer, index=False, sheet_name="Auditoría Base Op.")
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"auditoria_base_operativa_{modo}_{stamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

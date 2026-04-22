from __future__ import annotations

import hashlib
import json
import csv
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pandas as pd
from flask import Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, inspect

from app.blueprints.billeteras_virtuales import bp
from app.extensions import db
from app.models.billeteras_virtuales import BilleteraCarga, BilleteraMovimiento, BilleteraSalida


_bv_schema_checked = False


def _permiso_view():
    return current_user.has_permission("SABANA_LLAMADAS_VIEW") or current_user.has_permission("SABANA_LLAMADAS_UPLOAD")


def _permiso_upload():
    return current_user.has_permission("SABANA_LLAMADAS_UPLOAD")


def _is_superadmin():
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _ensure_billeteras_schema():
    global _bv_schema_checked
    if _bv_schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    if BilleteraCarga.__tablename__ not in existing:
        BilleteraCarga.__table__.create(bind=db.engine)
    if BilleteraMovimiento.__tablename__ not in existing:
        BilleteraMovimiento.__table__.create(bind=db.engine)
    if BilleteraSalida.__tablename__ not in existing:
        BilleteraSalida.__table__.create(bind=db.engine)
    _bv_schema_checked = True


def _q_cargas():
    q = BilleteraCarga.query
    if not _is_superadmin():
        q = q.filter(BilleteraCarga.unidad_id == current_user.unidad_id)
    return q


def _q_movimientos():
    q = BilleteraMovimiento.query
    if not _is_superadmin():
        q = q.filter(BilleteraMovimiento.unidad_id == current_user.unidad_id)
    return q


def _q_salidas():
    q = BilleteraSalida.query
    if not _is_superadmin():
        q = q.filter(BilleteraSalida.unidad_id == current_user.unidad_id)
    return q


def _clean_str(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _parse_dt(v):
    if v is None:
        return None
    try:
        d = pd.to_datetime(v, errors="coerce")
        if pd.isna(d):
            return None
        return d.to_pydatetime()
    except Exception:
        return None


def _parse_num(v):
    try:
        n = pd.to_numeric(v, errors="coerce")
        if pd.isna(n):
            return None
        return Decimal(f"{float(n):.2f}")
    except Exception:
        return None


def _detect_tipo_archivo(df: pd.DataFrame) -> str | None:
    cols = {str(c).strip().upper() for c in df.columns}
    if {"TIPO DE MOVIMIENTO", "FECHA CREACION PAGO", "TOTAL PAGADO"}.issubset(cols):
        return "movimientos"
    if {"ID RETIRO", "FECHA CREACION", "MONTO RETIRADO"}.issubset(cols):
        return "salidas"
    return None


def _ingestar_movimientos(df: pd.DataFrame, carga: BilleteraCarga):
    validos = 0
    fechas = []
    for _, row in df.iterrows():
        fecha = _parse_dt(row.get("FECHA CREACION PAGO"))
        monto = _parse_num(row.get("TOTAL PAGADO"))
        if fecha:
            fechas.append(fecha)
        obj = BilleteraMovimiento(
            carga_id=carga.id,
            unidad_id=carga.unidad_id,
            tipo_dato_consulta=_clean_str(row.get("TIPO DE DATO CONSULTA")),
            tipo_dato=_clean_str(row.get("TIPO DE DATO")),
            dato=_clean_str(row.get("DATO")),
            apodo=_clean_str(row.get("APODO")),
            tipo_movimiento=_clean_str(row.get("TIPO DE MOVIMIENTO")),
            fecha_operacion=fecha,
            payment_id=_clean_str(row.get("PAYMENT ID")),
            order_id=_clean_str(row.get("ORDER ID")),
            estado_payment=_clean_str(row.get("ESTADO PAYMENT")),
            total_pagado=monto,
            id_buyer=_clean_str(row.get("ID BUYER")),
            apodo_buyer=_clean_str(row.get("APODO BUYER")),
            nombre_buyer=_clean_str(row.get("NOMBRE BUYER")),
            documento_buyer=_clean_str(row.get("NUMERO DOCUMENTO BUYER")),
            id_seller=_clean_str(row.get("ID SELLER")),
            apodo_seller=_clean_str(row.get("APODO SELLER")),
            nombre_seller=_clean_str(row.get("NOMBRE SELLER")),
            metodo_pago=_clean_str(row.get("METODO PAGO")),
            origen_transferencia=_clean_str(row.get("ORIGIN TRANSFERENCIA BANCARIA")),
            documento_origen_account=_clean_str(row.get("DOCUMENTO ORIGIN ACCOUNT")),
            nombre_origen_account=_clean_str(row.get("NOMBRE ORIGIN ACCOUNT")),
            destino_transferencia=_clean_str(row.get("DESTINO TRANSFERENCIA BANCARIA")),
            destino_tipo_transferencia=_clean_str(row.get("DESTINO TIPO TRANSFERENCIA BANCARIA")),
            documento_destino_account=_clean_str(row.get("DOCUMENTO DESTINO ACCOUNT")),
            nombre_destino_account=_clean_str(row.get("NOMBRE DESTINO ACCOUNT")),
        )
        db.session.add(obj)
        validos += 1

    carga.registros_validos = validos
    carga.fecha_min = min(fechas) if fechas else None
    carga.fecha_max = max(fechas) if fechas else None


def _ingestar_salidas(df: pd.DataFrame, carga: BilleteraCarga):
    validos = 0
    fechas = []
    for _, row in df.iterrows():
        fecha = _parse_dt(row.get("FECHA CREACION"))
        monto = _parse_num(row.get("MONTO RETIRADO"))
        if fecha:
            fechas.append(fecha)
        obj = BilleteraSalida(
            carga_id=carga.id,
            unidad_id=carga.unidad_id,
            tipo_dato_consulta=_clean_str(row.get("TIPO DE DATO CONSULTA")),
            tipo_dato=_clean_str(row.get("TIPO DE DATO")),
            dato=_clean_str(row.get("DATO")),
            apodo=_clean_str(row.get("APODO")),
            fecha_operacion=fecha,
            id_usuario_origen=_clean_str(row.get("ID USUARIO ORIGEN")),
            id_retiro=_clean_str(row.get("ID RETIRO")),
            detalle=_clean_str(row.get("DETALLE")),
            monto_retirado=monto,
            estado=_clean_str(row.get("ESTADO")),
            titular_origen=_clean_str(row.get("TITULAR ORIGEN")),
            titular_destino=_clean_str(row.get("TITULAR DESTINO")),
            documento_destino=_clean_str(row.get("DOCUMENTO DESTINO")),
            cuenta_destino=_clean_str(row.get("CUENTA DESTINO")),
            entidad=_clean_str(row.get("ENTIDAD")),
        )
        db.session.add(obj)
        validos += 1

    carga.registros_validos = validos
    carga.fecha_min = min(fechas) if fechas else None
    carga.fecha_max = max(fechas) if fechas else None


def _apply_common_filters(q, model):
    desde = _parse_dt(request.args.get("desde"))
    hasta = _parse_dt(request.args.get("hasta"))
    estado = _clean_str(request.args.get("estado"))
    qtxt = _clean_str(request.args.get("q"))
    if desde:
        q = q.filter(model.fecha_operacion >= desde)
    if hasta:
        q = q.filter(model.fecha_operacion <= hasta)
    if estado:
        if model is BilleteraMovimiento:
            q = q.filter(BilleteraMovimiento.estado_payment.ilike(f"%{estado}%"))
        else:
            q = q.filter(BilleteraSalida.estado.ilike(f"%{estado}%"))
    if qtxt:
        if model is BilleteraMovimiento:
            q = q.filter(
                (BilleteraMovimiento.nombre_buyer.ilike(f"%{qtxt}%"))
                | (BilleteraMovimiento.documento_buyer.ilike(f"%{qtxt}%"))
                | (BilleteraMovimiento.nombre_destino_account.ilike(f"%{qtxt}%"))
                | (BilleteraMovimiento.documento_destino_account.ilike(f"%{qtxt}%"))
                | (BilleteraMovimiento.metodo_pago.ilike(f"%{qtxt}%"))
            )
        else:
            q = q.filter(
                (BilleteraSalida.titular_destino.ilike(f"%{qtxt}%"))
                | (BilleteraSalida.documento_destino.ilike(f"%{qtxt}%"))
                | (BilleteraSalida.entidad.ilike(f"%{qtxt}%"))
            )
    return q


def _build_analisis_context():
    mov_q = _apply_common_filters(_q_movimientos(), BilleteraMovimiento)
    sal_q = _apply_common_filters(_q_salidas(), BilleteraSalida)

    tipo_mov = _clean_str(request.args.get("tipo_movimiento"))
    entidad = _clean_str(request.args.get("entidad"))
    if tipo_mov:
        mov_q = mov_q.filter(BilleteraMovimiento.tipo_movimiento == tipo_mov)
    if entidad:
        sal_q = sal_q.filter(BilleteraSalida.entidad.ilike(f"%{entidad}%"))

    mov_items = mov_q.order_by(BilleteraMovimiento.fecha_operacion.desc()).limit(500).all()
    sal_items = sal_q.order_by(BilleteraSalida.fecha_operacion.desc()).limit(300).all()

    mov_count, mov_total = mov_q.with_entities(
        func.count(BilleteraMovimiento.id), func.coalesce(func.sum(BilleteraMovimiento.total_pagado), 0)
    ).first()
    sal_count, sal_total = sal_q.with_entities(
        func.count(BilleteraSalida.id), func.coalesce(func.sum(BilleteraSalida.monto_retirado), 0)
    ).first()

    top_buyer = (
        mov_q.with_entities(
            BilleteraMovimiento.nombre_buyer,
            BilleteraMovimiento.documento_buyer,
            func.count(BilleteraMovimiento.id).label("cantidad"),
            func.coalesce(func.sum(BilleteraMovimiento.total_pagado), 0).label("total"),
        )
        .group_by(BilleteraMovimiento.nombre_buyer, BilleteraMovimiento.documento_buyer)
        .order_by(func.coalesce(func.sum(BilleteraMovimiento.total_pagado), 0).desc())
        .limit(10)
        .all()
    )

    top_entidad = (
        sal_q.with_entities(
            BilleteraSalida.entidad,
            func.count(BilleteraSalida.id).label("cantidad"),
            func.coalesce(func.sum(BilleteraSalida.monto_retirado), 0).label("total"),
        )
        .group_by(BilleteraSalida.entidad)
        .order_by(func.coalesce(func.sum(BilleteraSalida.monto_retirado), 0).desc())
        .limit(10)
        .all()
    )

    # Serie diaria (gráfico temporal)
    mov_daily_raw = (
        mov_q.filter(BilleteraMovimiento.fecha_operacion.isnot(None))
        .with_entities(
            func.date(BilleteraMovimiento.fecha_operacion).label("d"),
            func.coalesce(func.sum(BilleteraMovimiento.total_pagado), 0).label("total"),
        )
        .group_by(func.date(BilleteraMovimiento.fecha_operacion))
        .order_by(func.date(BilleteraMovimiento.fecha_operacion))
        .all()
    )
    sal_daily_raw = (
        sal_q.filter(BilleteraSalida.fecha_operacion.isnot(None))
        .with_entities(
            func.date(BilleteraSalida.fecha_operacion).label("d"),
            func.coalesce(func.sum(BilleteraSalida.monto_retirado), 0).label("total"),
        )
        .group_by(func.date(BilleteraSalida.fecha_operacion))
        .order_by(func.date(BilleteraSalida.fecha_operacion))
        .all()
    )
    mov_daily = [{"fecha": str(r[0]), "total": float(r[1] or 0)} for r in mov_daily_raw if r[0]]
    sal_daily = [{"fecha": str(r[0]), "total": float(r[1] or 0)} for r in sal_daily_raw if r[0]]

    # Grafo simple: usuario central -> top buyers y top entidades
    buyer_graph = []
    for r in top_buyer[:12]:
        nombre = (r[0] or "Sin nombre").strip()
        doc = (r[1] or "").strip()
        etiqueta = f"{nombre} ({doc})" if doc else nombre
        buyer_graph.append({"label": etiqueta, "total": float(r[3] or 0)})
    entidad_graph = []
    for r in top_entidad[:12]:
        etiqueta = (r[0] or "Sin entidad").strip()
        entidad_graph.append({"label": etiqueta, "total": float(r[2] or 0)})

    # Alertas automáticas básicas
    alertas = []
    if float(sal_total or 0) > 0 and float(mov_total or 0) > 0:
        ratio = float(sal_total) / max(float(mov_total), 1.0)
        if ratio >= 0.6:
            alertas.append(
                f"Alto egreso detectado: las salidas representan {ratio * 100:.1f}% del monto total movido."
            )
    if top_buyer:
        top = float(top_buyer[0][3] or 0)
        if float(mov_total or 0) > 0 and (top / float(mov_total)) >= 0.35:
            alertas.append(
                "Concentración en contraparte: la principal contraparte supera el 35% del monto en movimientos."
            )
    if top_entidad:
        top_e = float(top_entidad[0][2] or 0)
        if float(sal_total or 0) > 0 and (top_e / float(sal_total)) >= 0.5:
            alertas.append(
                "Concentración por entidad: más del 50% de salidas se dirige a una misma entidad."
            )
    sin_doc_destino = (
        sal_q.filter(
            (BilleteraSalida.documento_destino.is_(None))
            | (BilleteraSalida.documento_destino == "")
        )
        .count()
    )
    if sin_doc_destino > 0:
        alertas.append(f"Existen {sin_doc_destino} salidas sin documento de destino informado.")

    tipo_mov_opts = (
        _q_movimientos()
        .with_entities(BilleteraMovimiento.tipo_movimiento)
        .filter(BilleteraMovimiento.tipo_movimiento.isnot(None))
        .distinct()
        .order_by(BilleteraMovimiento.tipo_movimiento.asc())
        .all()
    )

    return {
        "mov_items": mov_items,
        "sal_items": sal_items,
        "mov_count": int(mov_count or 0),
        "mov_total": float(mov_total or 0),
        "sal_count": int(sal_count or 0),
        "sal_total": float(sal_total or 0),
        "top_buyer": top_buyer,
        "top_entidad": top_entidad,
        "tipo_mov_opts": [r[0] for r in tipo_mov_opts if r[0]],
        "alertas": alertas,
        "mov_daily_json": json.dumps(mov_daily),
        "sal_daily_json": json.dumps(sal_daily),
        "buyer_graph_json": json.dumps(buyer_graph),
        "entidad_graph_json": json.dumps(entidad_graph),
    }


@bp.before_request
@login_required
def _before():
    _ensure_billeteras_schema()


@bp.route("/")
def index():
    if not _permiso_view():
        flash("No tiene permisos para ver Billeteras Virtuales.", "warning")
        return redirect(url_for("core.dashboard"))

    cargas_recientes = _q_cargas().order_by(BilleteraCarga.created_at.desc()).limit(20).all()

    kpi_mov = _q_movimientos().with_entities(
        func.count(BilleteraMovimiento.id), func.coalesce(func.sum(BilleteraMovimiento.total_pagado), 0)
    ).first()
    kpi_sal = _q_salidas().with_entities(
        func.count(BilleteraSalida.id), func.coalesce(func.sum(BilleteraSalida.monto_retirado), 0)
    ).first()

    return render_template(
        "billeteras_virtuales/index.html",
        cargas=cargas_recientes,
        mov_count=int(kpi_mov[0] or 0),
        mov_total=float(kpi_mov[1] or 0),
        sal_count=int(kpi_sal[0] or 0),
        sal_total=float(kpi_sal[1] or 0),
    )


@bp.route("/cargas", methods=["GET", "POST"])
def cargas():
    if not _permiso_view():
        flash("No tiene permisos para ver Billeteras Virtuales.", "warning")
        return redirect(url_for("core.dashboard"))

    if request.method == "POST":
        if not _permiso_upload():
            flash("No tiene permisos para cargar archivos.", "danger")
            return redirect(url_for("billeteras_virtuales.cargas"))

        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccione un archivo Excel.", "warning")
            return redirect(url_for("billeteras_virtuales.cargas"))

        if not f.filename.lower().endswith(".xlsx"):
            flash("Formato inválido. Solo se admite .xlsx", "danger")
            return redirect(url_for("billeteras_virtuales.cargas"))

        raw = f.read()
        if not raw:
            flash("El archivo está vacío.", "warning")
            return redirect(url_for("billeteras_virtuales.cargas"))
        file_hash = hashlib.sha256(raw).hexdigest()

        try:
            df = pd.read_excel(BytesIO(raw))
        except Exception as exc:
            flash(f"No se pudo leer el Excel: {exc}", "danger")
            return redirect(url_for("billeteras_virtuales.cargas"))

        tipo = _detect_tipo_archivo(df)
        if not tipo:
            flash("No se detectó un formato compatible (movimientos o salidas).", "danger")
            return redirect(url_for("billeteras_virtuales.cargas"))

        carga = BilleteraCarga(
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            tipo_archivo=tipo,
            nombre_archivo=f.filename,
            archivo_hash=file_hash,
            registros_total=int(len(df.index)),
        )
        db.session.add(carga)
        db.session.flush()

        if tipo == "movimientos":
            _ingestar_movimientos(df, carga)
        else:
            _ingestar_salidas(df, carga)

        db.session.commit()
        flash(
            f"Carga procesada: {carga.registros_validos}/{carga.registros_total} registros ({tipo}).",
            "success",
        )
        return redirect(url_for("billeteras_virtuales.cargas"))

    cargas_q = _q_cargas().order_by(BilleteraCarga.created_at.desc())
    tipo = _clean_str(request.args.get("tipo"))
    if tipo in {"movimientos", "salidas"}:
        cargas_q = cargas_q.filter(BilleteraCarga.tipo_archivo == tipo)

    cargas_list = cargas_q.limit(200).all()
    return render_template("billeteras_virtuales/cargas.html", cargas=cargas_list, tipo=tipo or "")


@bp.route("/analisis")
def analisis():
    if not _permiso_view():
        flash("No tiene permisos para ver Billeteras Virtuales.", "warning")
        return redirect(url_for("core.dashboard"))

    ctx = _build_analisis_context()
    return render_template("billeteras_virtuales/analisis.html", **ctx)


@bp.route("/analisis/export.csv")
def analisis_export_csv():
    if not _permiso_view():
        flash("No tiene permisos para ver Billeteras Virtuales.", "warning")
        return redirect(url_for("core.dashboard"))

    mov_q = _apply_common_filters(_q_movimientos(), BilleteraMovimiento)
    sal_q = _apply_common_filters(_q_salidas(), BilleteraSalida)
    tipo_mov = _clean_str(request.args.get("tipo_movimiento"))
    entidad = _clean_str(request.args.get("entidad"))
    if tipo_mov:
        mov_q = mov_q.filter(BilleteraMovimiento.tipo_movimiento == tipo_mov)
    if entidad:
        sal_q = sal_q.filter(BilleteraSalida.entidad.ilike(f"%{entidad}%"))

    mov_items = mov_q.order_by(BilleteraMovimiento.fecha_operacion.desc()).limit(2000).all()
    sal_items = sal_q.order_by(BilleteraSalida.fecha_operacion.desc()).limit(2000).all()

    # little shim: csv.writer expects file-like with write()
    class _W:
        def __init__(self):
            self.parts = []
        def write(self, s):
            self.parts.append(s)
    w = _W()
    cw = csv.writer(w)
    cw.writerow(["tipo", "fecha", "estado", "monto", "nombre", "documento", "detalle", "entidad"])
    for r in mov_items:
        cw.writerow(
            [
                "movimiento",
                r.fecha_operacion.isoformat() if r.fecha_operacion else "",
                r.estado_payment or "",
                float(r.total_pagado or 0),
                r.nombre_buyer or r.nombre_destino_account or "",
                r.documento_buyer or r.documento_destino_account or "",
                r.tipo_movimiento or r.metodo_pago or "",
                "",
            ]
        )
    for r in sal_items:
        cw.writerow(
            [
                "salida",
                r.fecha_operacion.isoformat() if r.fecha_operacion else "",
                r.estado or "",
                float(r.monto_retirado or 0),
                r.titular_destino or "",
                r.documento_destino or "",
                r.detalle or "",
                r.entidad or "",
            ]
        )
    csv_data = "".join(w.parts)
    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=billeteras_analisis.csv"},
    )


@bp.route("/analisis/informe")
def analisis_informe():
    if not _permiso_view():
        flash("No tiene permisos para ver Billeteras Virtuales.", "warning")
        return redirect(url_for("core.dashboard"))
    ctx = _build_analisis_context()
    ctx["emitido_en"] = datetime.utcnow()
    return render_template("billeteras_virtuales/informe.html", **ctx)

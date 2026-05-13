from __future__ import annotations

import hashlib
import json
import csv
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pandas as pd
from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, exists, func, inspect, or_, text

from app.blueprints.billeteras_virtuales import bp
from app.extensions import db
from app.models.analisis_puntos import AnalisisPuntoCaso, AnalisisPuntoCasoCompartido
from app.models.billeteras_virtuales import (
    BilleteraCarga,
    BilleteraCargaCompartida,
    BilleteraMovimiento,
    BilleteraSalida,
)
from app.models.sabana_llamadas import Sujeto, SujetoCompartido
from app.models.user import User


_bv_schema_checked = False
# Máximo de filas en JSON para drill-down del gráfico (evita respuestas enormes).
_BV_DETALLE_JSON_CAP = 5000
_BV_FECHA_ARG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIPO_MOV_LABELS = {
    "money_transfer": "Transferencia",
    "regular_payment": "Pago",
    "account_fund": "Ingreso de dinero",
}
_ESTADO_LABELS = {
    "approved": "Aprobado",
    "rejected": "Rechazado",
    "cancelled": "Cancelado",
    "pending": "Pendiente",
}
_MESES_ES = [
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
]


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
    if BilleteraCargaCompartida.__tablename__ not in existing:
        BilleteraCargaCompartida.__table__.create(bind=db.engine)
    # Migración idempotente de columnas nuevas para vínculo a caso/sujeto
    cols = {c.get("name") for c in inspect(db.engine).get_columns(BilleteraCarga.__tablename__)}
    if "sujeto_id" not in cols:
        db.session.execute(text("ALTER TABLE bv_cargas ADD COLUMN sujeto_id INTEGER NULL"))
    if "caso_id" not in cols:
        db.session.execute(text("ALTER TABLE bv_cargas ADD COLUMN caso_id INTEGER NULL"))
    try:
        idxs = inspect(db.engine).get_indexes(BilleteraCargaCompartida.__tablename__)
        if not any((ix.get("name") or "").lower() == "idx_bv_cargas_compartidas_shared_with" for ix in idxs):
            db.session.execute(
                text("CREATE INDEX idx_bv_cargas_compartidas_shared_with ON bv_cargas_compartidas(shared_with_user_id)")
            )
    except Exception:
        pass
    db.session.commit()
    _bv_schema_checked = True


def _carga_access_predicate():
    if _is_superadmin():
        return True
    owned = (BilleteraCarga.user_id == current_user.id)
    shared_carga = exists().where(
        and_(
            BilleteraCargaCompartida.carga_id == BilleteraCarga.id,
            BilleteraCargaCompartida.shared_with_user_id == current_user.id,
        )
    )
    shared_suj = exists().where(
        and_(
            BilleteraCarga.sujeto_id == SujetoCompartido.sujeto_id,
            SujetoCompartido.shared_with_user_id == current_user.id,
        )
    )
    shared_case = exists().where(
        and_(
            BilleteraCarga.caso_id == AnalisisPuntoCasoCompartido.caso_id,
            AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
        )
    )
    return or_(owned, shared_carga, shared_suj, shared_case)


def _q_cargas():
    q = BilleteraCarga.query.filter(BilleteraCarga.unidad_id == current_user.unidad_id)
    pred = _carga_access_predicate()
    if pred is not True:
        q = q.filter(pred)
    return q


def _assert_owner_or_404(obj):
    if _is_superadmin():
        return obj
    if not obj or getattr(obj, "user_id", None) != current_user.id:
        abort(404)
    return obj


def _q_movimientos():
    carga_ids = _q_cargas().with_entities(BilleteraCarga.id)
    return BilleteraMovimiento.query.filter(BilleteraMovimiento.carga_id.in_(carga_ids))


def _q_salidas():
    carga_ids = _q_cargas().with_entities(BilleteraCarga.id)
    return BilleteraSalida.query.filter(BilleteraSalida.carga_id.in_(carga_ids))


def _get_int_list_arg(name):
    out = []
    for raw in request.args.getlist(name):
        try:
            v = int(raw)
            if v > 0:
                out.append(v)
        except Exception:
            continue
    return sorted(set(out))


def _get_str_list_arg(name):
    out = []
    for raw in request.args.getlist(name):
        s = _clean_str(raw)
        if s:
            out.append(s)
    return sorted(set(out))


def _q_casos_accesibles():
    q = AnalisisPuntoCaso.query.filter(AnalisisPuntoCaso.unidad_id == current_user.unidad_id)
    if not _is_superadmin():
        shared_case = exists().where(
            and_(
                AnalisisPuntoCasoCompartido.caso_id == AnalisisPuntoCaso.id,
                AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
            )
        )
        q = q.filter(or_(AnalisisPuntoCaso.user_id == current_user.id, shared_case))
    return q


def _q_sujetos_accesibles():
    q = Sujeto.query.filter(Sujeto.unidad_id == current_user.unidad_id)
    if not _is_superadmin():
        shared_suj = exists().where(
            and_(
                SujetoCompartido.sujeto_id == Sujeto.id,
                SujetoCompartido.shared_with_user_id == current_user.id,
            )
        )
        shared_via_carga = exists().where(
            and_(
                BilleteraCarga.sujeto_id == Sujeto.id,
                BilleteraCargaCompartida.carga_id == BilleteraCarga.id,
                BilleteraCargaCompartida.shared_with_user_id == current_user.id,
            )
        )
        shared_via_case = exists().where(
            and_(
                BilleteraCarga.sujeto_id == Sujeto.id,
                BilleteraCarga.caso_id == AnalisisPuntoCasoCompartido.caso_id,
                AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
            )
        )
        q = q.filter(or_(Sujeto.user_id == current_user.id, shared_suj, shared_via_carga, shared_via_case))
    return q


def _get_caso_accesible(caso_id):
    if not caso_id:
        return None
    try:
        cid = int(caso_id)
    except Exception:
        return None
    return _q_casos_accesibles().filter(AnalisisPuntoCaso.id == cid).first()


def _get_sujeto_accesible(sujeto_id):
    if not sujeto_id:
        return None
    try:
        sid = int(sujeto_id)
    except Exception:
        return None
    return _q_sujetos_accesibles().filter(Sujeto.id == sid).first()


def _clean_str(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _carga_meta_dict(carga: BilleteraCarga | None) -> dict:
    """Metadatos de carga para tablas, JSON de detalle e informes."""
    if not carga:
        return {
            "id": None,
            "archivo": "",
            "hash_corto": "",
            "caso_codigo": "",
            "sujeto": "",
            "label": "—",
            "title": "",
        }
    h = (carga.archivo_hash or "")[:12]
    caso = getattr(carga, "caso", None)
    suj = getattr(carga, "sujeto", None)
    caso_c = (caso.codigo or "").strip() if caso else ""
    suj_s = ""
    if suj and hasattr(suj, "display_name"):
        suj_s = (suj.display_name() or "").strip()
    nom = (carga.nombre_archivo or "").strip()
    label = f"#{carga.id}"
    if nom:
        label = f"{label} · {nom[:48]}{'…' if len(nom) > 48 else ''}"
    title_bits = [f"Carga #{carga.id}", nom or "(sin nombre)", f"SHA-256: {carga.archivo_hash or '—'}"]
    if caso_c:
        title_bits.append(f"Caso: {caso_c}")
    if suj_s:
        title_bits.append(f"Sujeto: {suj_s}")
    return {
        "id": carga.id,
        "archivo": nom,
        "hash_corto": h,
        "caso_codigo": caso_c,
        "sujeto": suj_s,
        "label": label,
        "title": " · ".join(title_bits),
    }


def _aporte_por_carga_filtrado(mov_q, sal_q, limit: int = 15) -> list[dict]:
    """Agrupa operaciones y montos por archivo de carga dentro del filtro actual."""
    agg: dict[int, dict] = defaultdict(lambda: {"mov_n": 0, "mov_monto": 0.0, "sal_n": 0, "sal_monto": 0.0})
    for cid, n, m in (
        mov_q.with_entities(
            BilleteraMovimiento.carga_id,
            func.count(BilleteraMovimiento.id),
            func.coalesce(func.sum(BilleteraMovimiento.total_pagado), 0),
        )
        .group_by(BilleteraMovimiento.carga_id)
        .all()
    ):
        agg[int(cid)]["mov_n"] = int(n or 0)
        agg[int(cid)]["mov_monto"] = float(m or 0)
    for cid, n, m in (
        sal_q.with_entities(
            BilleteraSalida.carga_id,
            func.count(BilleteraSalida.id),
            func.coalesce(func.sum(BilleteraSalida.monto_retirado), 0),
        )
        .group_by(BilleteraSalida.carga_id)
        .all()
    ):
        agg[int(cid)]["sal_n"] = int(n or 0)
        agg[int(cid)]["sal_monto"] = float(m or 0)
    if not agg:
        return []
    pred = _carga_access_predicate()
    cq = BilleteraCarga.query.filter(
        BilleteraCarga.unidad_id == current_user.unidad_id,
        BilleteraCarga.id.in_(list(agg.keys())),
    )
    if pred is not True:
        cq = cq.filter(pred)
    cargas = {
        c.id: c
        for c in cq.options(joinedload(BilleteraCarga.caso), joinedload(BilleteraCarga.sujeto)).all()
    }
    tot_ops = sum(int(x["mov_n"] + x["sal_n"]) for x in agg.values())
    tot_monto = sum(float(x["mov_monto"] + x["sal_monto"]) for x in agg.values())
    rows_out: list[dict] = []
    for cid, data in agg.items():
        meta = _carga_meta_dict(cargas.get(cid))
        ops = int(data["mov_n"] + data["sal_n"])
        mon = float(data["mov_monto"] + data["sal_monto"])
        pct_ops = (100.0 * ops / tot_ops) if tot_ops else 0.0
        pct_mon = (100.0 * mon / tot_monto) if tot_monto else 0.0
        rows_out.append(
            {
                **meta,
                "mov_n": int(data["mov_n"]),
                "sal_n": int(data["sal_n"]),
                "ops": ops,
                "mov_monto": float(data["mov_monto"]),
                "sal_monto": float(data["sal_monto"]),
                "monto": mon,
                "pct_ops": round(pct_ops, 1),
                "pct_monto": round(pct_mon, 1),
            }
        )
    rows_out.sort(key=lambda x: x["monto"], reverse=True)
    return rows_out[:limit]


def _label_tipo_mov(v):
    k = (_clean_str(v) or "").lower()
    return _TIPO_MOV_LABELS.get(k, v or "—")


def _label_estado(v):
    k = (_clean_str(v) or "").lower()
    return _ESTADO_LABELS.get(k, v or "—")


def _infer_sentido_mov(r: BilleteraMovimiento):
    """
    Intenta inferir sentido respecto al usuario consultado:
    - Ingreso: entra dinero a la cuenta consultada
    - Salida: sale dinero de la cuenta consultada
    """
    sujeto = _clean_str(r.dato)
    buyer = _clean_str(r.id_buyer)
    seller = _clean_str(r.id_seller)
    tipo = (_clean_str(r.tipo_movimiento) or "").lower()

    if sujeto and buyer and seller:
        if seller == sujeto and buyer != sujeto:
            return "Ingreso"
        if buyer == sujeto and seller != sujeto:
            return "Salida"

    # Fallback por tipo cuando no alcanza la metadata
    if tipo == "account_fund":
        return "Ingreso"
    if tipo == "regular_payment":
        return "Salida"
    if tipo == "money_transfer":
        return "Transferencia"
    return "Sin clasificar"


def _display_persona(nombre, doc, fallback=None):
    n = _clean_str(nombre)
    d = _clean_str(doc)
    if n and d:
        return f"{n} ({d})"
    if n:
        return n
    if d:
        return d
    return fallback or "—"


def _pair_labels_movimiento(r: BilleteraMovimiento) -> tuple[str, str]:
    """Etiquetas De/Hacia alineadas con la vista de tabla (origen/destino inferidos)."""
    sujeto_id = _clean_str(r.dato)
    buyer_id = _clean_str(r.id_buyer)
    seller_id = _clean_str(r.id_seller)
    cuenta_investigada = _clean_str(r.apodo) or (f"Cuenta {sujeto_id}" if sujeto_id else "Cuenta investigada")
    buyer_lbl = _display_persona(r.nombre_buyer, r.documento_buyer, _clean_str(r.apodo_buyer) or buyer_id or "—")
    seller_lbl = _display_persona(r.nombre_seller, None, _clean_str(r.apodo_seller) or seller_id or "—")
    destino_lbl = _display_persona(r.nombre_destino_account, r.documento_destino_account, seller_lbl)
    origen_lbl = buyer_lbl
    hacia_lbl = destino_lbl
    if sujeto_id and seller_id and seller_id == sujeto_id:
        origen_lbl = buyer_lbl
        hacia_lbl = cuenta_investigada
    elif sujeto_id and buyer_id and buyer_id == sujeto_id:
        origen_lbl = cuenta_investigada
        hacia_lbl = destino_lbl
    return origen_lbl, hacia_lbl


def _pair_labels_salida(r: BilleteraSalida) -> tuple[str, str]:
    origen_sal = _display_persona(r.titular_origen, None, _clean_str(r.id_usuario_origen) or "Cuenta investigada")
    destino_sal = _display_persona(r.titular_destino, r.documento_destino, _clean_str(r.entidad) or "Destino externo")
    return origen_sal, destino_sal


def _detalle_mov_dict(r: BilleteraMovimiento) -> dict:
    de, hacia = _pair_labels_movimiento(r)
    fecha_dia = r.fecha_operacion.date().isoformat() if r.fecha_operacion else ""
    cmeta = _carga_meta_dict(getattr(r, "carga", None))
    return {
        "fecha_dia": fecha_dia,
        "fecha": str(r.fecha_operacion) if r.fecha_operacion else "",
        "tipo": "Movimiento",
        "sentido": _infer_sentido_mov(r),
        "estado": _label_estado(r.estado_payment),
        "monto": float(r.total_pagado or 0),
        "de": de,
        "hacia": hacia,
        "metodo": r.metodo_pago or "—",
        "referencia": r.nombre_destino_account or r.documento_destino_account or r.nombre_seller or "—",
        "entidad": "—",
        "serie": "Movimientos",
        "carga_id": cmeta["id"],
        "carga_label": cmeta["label"],
        "carga_title": cmeta["title"],
    }


def _detalle_sal_dict(r: BilleteraSalida) -> dict:
    de, hacia = _pair_labels_salida(r)
    fecha_dia = r.fecha_operacion.date().isoformat() if r.fecha_operacion else ""
    cmeta = _carga_meta_dict(getattr(r, "carga", None))
    return {
        "fecha_dia": fecha_dia,
        "fecha": str(r.fecha_operacion) if r.fecha_operacion else "",
        "tipo": "Salida",
        "sentido": "Salida / Extracción",
        "estado": _label_estado(r.estado),
        "monto": float(r.monto_retirado or 0),
        "de": de,
        "hacia": hacia,
        "metodo": r.cuenta_destino or "—",
        "referencia": r.detalle or "—",
        "entidad": r.entidad or "—",
        "serie": "Salidas",
        "carga_id": cmeta["id"],
        "carga_label": cmeta["label"],
        "carga_title": cmeta["title"],
    }


def _stream_vinculos_totales(mov_q, sal_q):
    """Agrega vínculos De→Hacia sobre **todo** el conjunto filtrado (no solo la tabla paginada)."""
    vinculos = defaultdict(
        lambda: {
            "de": "—",
            "hacia": "—",
            "cantidad": 0,
            "monto_total": 0.0,
            "movimientos": 0,
            "salidas": 0,
        }
    )
    mq = mov_q.order_by(None)
    for r in mq.yield_per(800):
        de, hacia = _pair_labels_movimiento(r)
        monto = float(r.total_pagado or 0)
        key = (de, hacia)
        v = vinculos[key]
        v["de"] = de
        v["hacia"] = hacia
        v["cantidad"] += 1
        v["monto_total"] += monto
        v["movimientos"] += 1
    sq = sal_q.order_by(None)
    for r in sq.yield_per(800):
        de, hacia = _pair_labels_salida(r)
        monto = float(r.monto_retirado or 0)
        key = (de, hacia)
        v = vinculos[key]
        v["de"] = de
        v["hacia"] = hacia
        v["cantidad"] += 1
        v["monto_total"] += monto
        v["salidas"] += 1
    return vinculos


def _detalle_diario_capped(mov_q, sal_q, cap: int):
    """Muestra reciente para interacción en gráfico; el total filtrado está en los KPI."""
    out = []
    lim_mov_det = max(0, min(cap, int(cap * 0.65)))
    lim_sal_det = max(0, cap - lim_mov_det)
    mov_ld = joinedload(BilleteraMovimiento.carga).joinedload(BilleteraCarga.caso)
    mov_ls = joinedload(BilleteraMovimiento.carga).joinedload(BilleteraCarga.sujeto)
    sal_ld = joinedload(BilleteraSalida.carga).joinedload(BilleteraCarga.caso)
    sal_ls = joinedload(BilleteraSalida.carga).joinedload(BilleteraCarga.sujeto)
    if lim_mov_det:
        for r in (
            mov_q.options(mov_ld, mov_ls)
            .order_by(BilleteraMovimiento.fecha_operacion.desc())
            .limit(lim_mov_det)
        ):
            out.append(_detalle_mov_dict(r))
    if lim_sal_det:
        for r in (
            sal_q.options(sal_ld, sal_ls)
            .order_by(BilleteraSalida.fecha_operacion.desc())
            .limit(lim_sal_det)
        ):
            out.append(_detalle_sal_dict(r))
    return out


def _tab_limit(name: str, default: int, hard_max: int) -> int:
    v = request.args.get(name, type=int)
    if v is None:
        return default
    return max(1, min(hard_max, int(v)))


def _min_tx_vinculo() -> int:
    v = request.args.get("min_tx_vinculo", type=int)
    if v is None:
        return 1
    return max(1, min(50, int(v)))


def _parse_dt(v):
    """Import y filtros: día/mes/año (Argentina); format='mixed' tolera ISO en la misma columna."""
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    try:
        d = pd.to_datetime(v, errors="coerce", dayfirst=True, format="mixed")
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


def _fmt_fecha_es(d):
    if not d:
        return ""
    try:
        return f"{d.day:02d} {_MESES_ES[d.month - 1]} {d.year}"
    except Exception:
        return str(d)


def _detect_tipo_archivo(df: pd.DataFrame) -> str | None:
    cols = {str(c).strip().upper() for c in df.columns}
    if {"TIPO DE MOVIMIENTO", "FECHA CREACION PAGO", "TOTAL PAGADO"}.issubset(cols):
        return "movimientos"
    if {"ID RETIRO", "FECHA CREACION", "MONTO RETIRADO"}.issubset(cols):
        return "salidas"
    return None


def _row_signature(row) -> str:
    """
    Firma canónica de fila para detectar duplicados exactos dentro del mismo Excel.
    Evita omitir filas válidas solo por repetir PAYMENT ID/ID RETIRO.
    """
    parts = []
    for _, val in row.items():
        if pd.isna(val):
            parts.append("")
        else:
            parts.append(str(val).strip())
    return "|".join(parts)


def _ingestar_movimientos(df: pd.DataFrame, carga: BilleteraCarga):
    validos = 0
    fechas = []
    seen_rows: set[str] = set()
    omit_dup = 0
    for _, row in df.iterrows():
        sig = _row_signature(row)
        if sig in seen_rows:
            omit_dup += 1
            continue
        seen_rows.add(sig)
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
    return omit_dup


def _ingestar_salidas(df: pd.DataFrame, carga: BilleteraCarga):
    validos = 0
    fechas = []
    seen_rows: set[str] = set()
    omit_dup = 0
    for _, row in df.iterrows():
        sig = _row_signature(row)
        if sig in seen_rows:
            omit_dup += 1
            continue
        seen_rows.add(sig)
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
    return omit_dup


def _apply_common_filters(q, model):
    desde = _parse_dt(request.args.get("desde"))
    hasta_raw = request.args.get("hasta")
    hasta = _parse_dt(hasta_raw)
    estado = _clean_str(request.args.get("estado"))
    estados = _get_str_list_arg("estados[]")
    qtxt = _clean_str(request.args.get("q"))
    de_q = _clean_str(request.args.get("de_q"))
    hacia_q = _clean_str(request.args.get("hacia_q"))
    caso_ids = _get_int_list_arg("caso_ids[]")
    sujeto_ids = _get_int_list_arg("sujeto_ids[]")
    carga_ids = _get_int_list_arg("carga_ids[]")
    # Backward compatibility con filtros simples
    caso_id = request.args.get("caso_id", type=int)
    sujeto_id = request.args.get("sujeto_id", type=int)
    if caso_id and caso_id not in caso_ids:
        caso_ids.append(caso_id)
    if sujeto_id and sujeto_id not in sujeto_ids:
        sujeto_ids.append(sujeto_id)
    if caso_ids:
        q = q.filter(model.carga_id.in_(db.session.query(BilleteraCarga.id).filter(BilleteraCarga.caso_id.in_(caso_ids))))
    if sujeto_ids:
        q = q.filter(model.carga_id.in_(db.session.query(BilleteraCarga.id).filter(BilleteraCarga.sujeto_id.in_(sujeto_ids))))
    if carga_ids:
        q = q.filter(model.carga_id.in_(carga_ids))
    if desde:
        q = q.filter(model.fecha_operacion >= desde)
    if hasta:
        # Incluir todo el día "hasta" cuando viene solo como fecha (YYYY-MM-DD).
        hs = (hasta_raw or "").strip()
        if _BV_FECHA_ARG_RE.match(hs):
            try:
                hasta = hasta.replace(hour=23, minute=59, second=59, microsecond=999999)
            except Exception:
                pass
        q = q.filter(model.fecha_operacion <= hasta)
    if estados:
        if model is BilleteraMovimiento:
            q = q.filter(BilleteraMovimiento.estado_payment.in_(estados))
        else:
            q = q.filter(BilleteraSalida.estado.in_(estados))
    elif estado:
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
    if de_q:
        pat = f"%{de_q}%"
        if model is BilleteraMovimiento:
            q = q.filter(
                or_(
                    BilleteraMovimiento.nombre_buyer.ilike(pat),
                    BilleteraMovimiento.apodo_buyer.ilike(pat),
                    BilleteraMovimiento.documento_buyer.ilike(pat),
                    BilleteraMovimiento.id_buyer.ilike(pat),
                    BilleteraMovimiento.apodo.ilike(pat),
                    BilleteraMovimiento.dato.ilike(pat),
                )
            )
        else:
            q = q.filter(
                or_(
                    BilleteraSalida.titular_origen.ilike(pat),
                    BilleteraSalida.id_usuario_origen.ilike(pat),
                    BilleteraSalida.apodo.ilike(pat),
                    BilleteraSalida.dato.ilike(pat),
                )
            )
    if hacia_q:
        hp = f"%{hacia_q}%"
        if model is BilleteraMovimiento:
            q = q.filter(
                or_(
                    BilleteraMovimiento.nombre_destino_account.ilike(hp),
                    BilleteraMovimiento.documento_destino_account.ilike(hp),
                    BilleteraMovimiento.nombre_seller.ilike(hp),
                    BilleteraMovimiento.apodo_seller.ilike(hp),
                    BilleteraMovimiento.id_seller.ilike(hp),
                    BilleteraMovimiento.metodo_pago.ilike(hp),
                )
            )
        else:
            q = q.filter(
                or_(
                    BilleteraSalida.titular_destino.ilike(hp),
                    BilleteraSalida.documento_destino.ilike(hp),
                    BilleteraSalida.entidad.ilike(hp),
                    BilleteraSalida.detalle.ilike(hp),
                    BilleteraSalida.cuenta_destino.ilike(hp),
                )
            )
    return q


def _build_analisis_context():
    mov_q = _apply_common_filters(_q_movimientos(), BilleteraMovimiento)
    sal_q = _apply_common_filters(_q_salidas(), BilleteraSalida)

    tipo_mov = _clean_str(request.args.get("tipo_movimiento"))
    entidad = _clean_str(request.args.get("entidad"))
    tipos_mov = _get_str_list_arg("tipos_movimiento[]")
    entidades = _get_str_list_arg("entidades[]")
    if tipo_mov and tipo_mov not in tipos_mov:
        tipos_mov.append(tipo_mov)
    if entidad and entidad not in entidades:
        entidades.append(entidad)
    if tipos_mov:
        mov_q = mov_q.filter(BilleteraMovimiento.tipo_movimiento.in_(tipos_mov))
    if entidades:
        sal_q = sal_q.filter(BilleteraSalida.entidad.in_(entidades))

    lim_mov = _tab_limit("lim_mov", 500, 2000)
    lim_sal = _tab_limit("lim_sal", 300, 2000)
    min_tx = _min_tx_vinculo()

    mov_items = (
        mov_q.options(joinedload(BilleteraMovimiento.carga).joinedload(BilleteraCarga.caso), joinedload(BilleteraMovimiento.carga).joinedload(BilleteraCarga.sujeto))
        .order_by(BilleteraMovimiento.fecha_operacion.desc())
        .limit(lim_mov)
        .all()
    )
    sal_items = (
        sal_q.options(joinedload(BilleteraSalida.carga).joinedload(BilleteraCarga.caso), joinedload(BilleteraSalida.carga).joinedload(BilleteraCarga.sujeto))
        .order_by(BilleteraSalida.fecha_operacion.desc())
        .limit(lim_sal)
        .all()
    )

    mov_rows = []
    for r in mov_items:
        origen_lbl, destino_lbl = _pair_labels_movimiento(r)
        mov_rows.append(
            {
                "row": r,
                "tipo_label": _label_tipo_mov(r.tipo_movimiento),
                "estado_label": _label_estado(r.estado_payment),
                "sentido_label": _infer_sentido_mov(r),
                "origen_label": origen_lbl,
                "destino_label": destino_lbl,
                "carga_meta": _carga_meta_dict(getattr(r, "carga", None)),
            }
        )

    sal_rows = []
    for r in sal_items:
        origen_sal, destino_sal = _pair_labels_salida(r)
        sal_rows.append(
            {
                "row": r,
                "estado_label": _label_estado(r.estado),
                "sentido_label": "Salida / Extracción",
                "origen_label": origen_sal,
                "destino_label": destino_sal,
                "carga_meta": _carga_meta_dict(getattr(r, "carga", None)),
            }
        )

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
    mov_daily = [
        {"fecha": str(r[0]), "fecha_label": _fmt_fecha_es(r[0]), "total": float(r[1] or 0)}
        for r in mov_daily_raw
        if r[0]
    ]
    sal_daily = [
        {"fecha": str(r[0]), "fecha_label": _fmt_fecha_es(r[0]), "total": float(r[1] or 0)}
        for r in sal_daily_raw
        if r[0]
    ]

    # Compatibilidad para secciones anteriores (informe)
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

    # Vínculos y grafo: todo el universo filtrado (alineado con KPI). Tabla: solo últimos N.
    vinculos_map = _stream_vinculos_totales(mov_q, sal_q)
    resumen_vinculos = sorted(
        vinculos_map.values(),
        key=lambda x: (float(x["monto_total"] or 0), int(x["cantidad"] or 0)),
        reverse=True,
    )
    resumen_vinculos_filtrado = [v for v in resumen_vinculos if int(v.get("cantidad") or 0) >= min_tx]
    sum_ops_vinculos = sum(int(v.get("cantidad") or 0) for v in resumen_vinculos)
    sum_monto_vinculos = sum(float(v.get("monto_total") or 0) for v in resumen_vinculos)
    expected_ops = int(mov_count or 0) + int(sal_count or 0)
    expected_monto = float(mov_total or 0) + float(sal_total or 0)
    vinculos_match_ops = sum_ops_vinculos == expected_ops
    vinculos_match_monto = abs(sum_monto_vinculos - expected_monto) < 0.05
    graph_edges = [
        {
            "source": v["de"],
            "target": v["hacia"],
            "cantidad": int(v["cantidad"] or 0),
            "monto_total": float(v["monto_total"] or 0),
        }
        for v in resumen_vinculos_filtrado[:140]
    ]
    detalle_diario = _detalle_diario_capped(mov_q, sal_q, _BV_DETALLE_JSON_CAP)
    aporte_cargas = _aporte_por_carga_filtrado(mov_q, sal_q, limit=15)
    vinculos_delta_monto = float(sum_monto_vinculos) - float(expected_monto)

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

    ratio_salidas = 0.0
    if float(mov_total or 0) > 0:
        ratio_salidas = float(sal_total or 0) / float(mov_total or 1)

    contraparte_top_txt = "Sin contraparte dominante"
    if top_buyer:
        nom = (top_buyer[0][0] or "Sin nombre").strip()
        doc = (top_buyer[0][1] or "").strip()
        cant = int(top_buyer[0][2] or 0)
        total = float(top_buyer[0][3] or 0)
        contraparte_top_txt = f"{nom}{f' ({doc})' if doc else ''}: {cant} operaciones por $ {total:,.2f}"

    entidad_top_txt = "Sin entidad dominante"
    if top_entidad:
        ent = (top_entidad[0][0] or "Sin entidad").strip()
        cant_e = int(top_entidad[0][1] or 0)
        tot_e = float(top_entidad[0][2] or 0)
        entidad_top_txt = f"{ent}: {cant_e} salidas por $ {tot_e:,.2f}"

    resumen_narrativo = (
        f"Con los filtros aplicados se identificaron {int(mov_count or 0)} movimientos por un total de "
        f"$ {float(mov_total or 0):,.2f} y {int(sal_count or 0)} salidas por $ {float(sal_total or 0):,.2f}. "
        f"El nivel de egreso representa aproximadamente {ratio_salidas * 100:.1f}% del monto de movimientos. "
        f"Principal contraparte: {contraparte_top_txt}. Principal entidad de salida: {entidad_top_txt}."
    )

    recomendaciones = []
    if ratio_salidas >= 0.6:
        recomendaciones.append(
            "Priorizar trazabilidad de fondos en salidas y validar beneficiarios finales de los mayores egresos."
        )
    if top_buyer and float(mov_total or 0) > 0 and (float(top_buyer[0][3] or 0) / float(mov_total)) >= 0.35:
        recomendaciones.append(
            "Ampliar análisis sobre la contraparte principal por posible concentración operativa."
        )
    if sin_doc_destino > 0:
        recomendaciones.append(
            "Regularizar identificación de destinos sin documento para reducir riesgo de anonimización."
        )
    if not recomendaciones:
        recomendaciones.append(
            "Mantener monitoreo periódico y comparar contra nuevas cargas para detectar variaciones atípicas."
        )

    tipo_mov_opts = (
        _q_movimientos()
        .with_entities(BilleteraMovimiento.tipo_movimiento)
        .filter(BilleteraMovimiento.tipo_movimiento.isnot(None))
        .distinct()
        .order_by(BilleteraMovimiento.tipo_movimiento.asc())
        .all()
    )
    estado_mov_opts = (
        _q_movimientos()
        .with_entities(BilleteraMovimiento.estado_payment)
        .filter(BilleteraMovimiento.estado_payment.isnot(None))
        .distinct()
        .order_by(BilleteraMovimiento.estado_payment.asc())
        .all()
    )
    estado_sal_opts = (
        _q_salidas()
        .with_entities(BilleteraSalida.estado)
        .filter(BilleteraSalida.estado.isnot(None))
        .distinct()
        .order_by(BilleteraSalida.estado.asc())
        .all()
    )
    entidad_opts = (
        _q_salidas()
        .with_entities(BilleteraSalida.entidad)
        .filter(BilleteraSalida.entidad.isnot(None))
        .distinct()
        .order_by(BilleteraSalida.entidad.asc())
        .all()
    )

    casos_opts = _q_casos_accesibles().order_by(AnalisisPuntoCaso.created_at.desc()).limit(300).all()
    sujetos_opts = _q_sujetos_accesibles().order_by(Sujeto.apodo, Sujeto.nombre).limit(500).all()

    return {
        "mov_items": mov_items,
        "sal_items": sal_items,
        "mov_rows": mov_rows,
        "sal_rows": sal_rows,
        "mov_count": int(mov_count or 0),
        "mov_total": float(mov_total or 0),
        "sal_count": int(sal_count or 0),
        "sal_total": float(sal_total or 0),
        "top_buyer": top_buyer,
        "top_entidad": top_entidad,
        "tipo_mov_opts": [r[0] for r in tipo_mov_opts if r[0]],
        "estado_opts": sorted(set([r[0] for r in estado_mov_opts if r[0]] + [r[0] for r in estado_sal_opts if r[0]])),
        "entidad_opts": [r[0] for r in entidad_opts if r[0]],
        "casos_opts": casos_opts,
        "sujetos_opts": sujetos_opts,
        "selected_caso_ids": _get_int_list_arg("caso_ids[]"),
        "selected_sujeto_ids": _get_int_list_arg("sujeto_ids[]"),
        "selected_tipos_mov": tipos_mov,
        "selected_estados": _get_str_list_arg("estados[]"),
        "selected_entidades": entidades,
        "alertas": alertas,
        "resumen_narrativo": resumen_narrativo,
        "recomendaciones": recomendaciones,
        "top_vinculos": resumen_vinculos_filtrado[:10],
        "mov_daily_json": json.dumps(mov_daily),
        "sal_daily_json": json.dumps(sal_daily),
        "detalle_diario_json": json.dumps(detalle_diario),
        "resumen_vinculos_json": json.dumps(resumen_vinculos_filtrado[:500]),
        "rel_graph_json": json.dumps(graph_edges),
        "buyer_graph_json": json.dumps(buyer_graph),
        "entidad_graph_json": json.dumps(entidad_graph),
        "lim_mov_tabla": lim_mov,
        "lim_sal_tabla": lim_sal,
        "min_tx_vinculo": min_tx,
        "selected_de_q": _clean_str(request.args.get("de_q")) or "",
        "selected_hacia_q": _clean_str(request.args.get("hacia_q")) or "",
        "detalle_json_cap": _BV_DETALLE_JSON_CAP,
        "mov_mostrados": len(mov_items),
        "sal_mostrados": len(sal_items),
        "sum_ops_vinculos": int(sum_ops_vinculos),
        "sum_monto_vinculos": float(sum_monto_vinculos),
        "vinculos_expected_ops": int(expected_ops),
        "vinculos_expected_monto": float(expected_monto),
        "vinculos_match_ops": vinculos_match_ops,
        "vinculos_match_monto": vinculos_match_monto,
        "vinculos_delta_monto": float(vinculos_delta_monto),
        "aporte_cargas": aporte_cargas,
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
    casos_count = _q_casos_accesibles().count()
    sujetos_count = _q_sujetos_accesibles().count()

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
        casos_count=casos_count,
        sujetos_count=sujetos_count,
    )


@bp.route("/cargas", methods=["GET", "POST"])
def cargas():
    if not _permiso_view():
        flash("No tiene permisos para ver Billeteras Virtuales.", "warning")
        return redirect(url_for("core.dashboard"))

    casos_opts = _q_casos_accesibles().order_by(AnalisisPuntoCaso.created_at.desc()).limit(300).all()
    sujetos_opts = _q_sujetos_accesibles().order_by(Sujeto.apodo, Sujeto.nombre).limit(500).all()

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

        dup = BilleteraCarga.query.filter(
            BilleteraCarga.unidad_id == current_user.unidad_id,
            BilleteraCarga.archivo_hash == file_hash,
        ).first()
        if dup:
            flash(
                f"Este archivo ya fue cargado (mismo contenido, hash SHA-256). "
                f"Carga #{dup.id}: {dup.nombre_archivo or 'sin nombre'}. No se duplicó.",
                "warning",
            )
            return redirect(url_for("billeteras_virtuales.cargas"))

        try:
            df = pd.read_excel(BytesIO(raw))
        except Exception as exc:
            flash(f"No se pudo leer el Excel: {exc}", "danger")
            return redirect(url_for("billeteras_virtuales.cargas"))

        tipo = _detect_tipo_archivo(df)
        if not tipo:
            flash("No se detectó un formato compatible (movimientos o salidas).", "danger")
            return redirect(url_for("billeteras_virtuales.cargas"))

        caso = _get_caso_accesible(request.form.get("caso_id"))
        if not caso:
            flash("Debe seleccionar un caso válido.", "warning")
            return redirect(url_for("billeteras_virtuales.cargas"))
        sujeto = _get_sujeto_accesible(request.form.get("sujeto_id"))

        carga = BilleteraCarga(
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            sujeto_id=sujeto.id if sujeto else None,
            caso_id=caso.id,
            tipo_archivo=tipo,
            nombre_archivo=f.filename,
            archivo_hash=file_hash,
            registros_total=int(len(df.index)),
        )
        db.session.add(carga)
        db.session.flush()

        omit_dup = 0
        if tipo == "movimientos":
            omit_dup = _ingestar_movimientos(df, carga)
        else:
            omit_dup = _ingestar_salidas(df, carga)

        db.session.commit()
        msg = (
            f"Carga procesada: {carga.registros_validos}/{carga.registros_total} registros insertados ({tipo})."
        )
        if omit_dup:
            msg += f" Omitidas {omit_dup} filas duplicadas exactas dentro del Excel."
        flash(msg, "success")
        return redirect(url_for("billeteras_virtuales.cargas"))

    cargas_q = _q_cargas().order_by(BilleteraCarga.created_at.desc())
    tipo = _clean_str(request.args.get("tipo"))
    archivo_q = _clean_str(request.args.get("archivo_q"))
    caso_id = request.args.get("caso_id", type=int)
    sujeto_id = request.args.get("sujeto_id", type=int)
    if tipo in {"movimientos", "salidas"}:
        cargas_q = cargas_q.filter(BilleteraCarga.tipo_archivo == tipo)
    if archivo_q:
        pat = f"%{archivo_q}%"
        cargas_q = cargas_q.filter(
            or_(
                BilleteraCarga.nombre_archivo.ilike(pat),
                BilleteraCarga.archivo_hash.ilike(pat),
            )
        )
    if caso_id:
        cargas_q = cargas_q.filter(BilleteraCarga.caso_id == caso_id)
    if sujeto_id:
        cargas_q = cargas_q.filter(BilleteraCarga.sujeto_id == sujeto_id)

    cargas_list = cargas_q.limit(200).all()
    return render_template(
        "billeteras_virtuales/cargas.html",
        cargas=cargas_list,
        tipo=tipo or "",
        archivo_q=archivo_q or "",
        caso_id=caso_id,
        sujeto_id=sujeto_id,
        casos_opts=casos_opts,
        sujetos_opts=sujetos_opts,
    )


@bp.route("/cargas/<int:carga_id>/vincular", methods=["GET", "POST"])
def cargas_vincular(carga_id):
    if not _permiso_upload():
        flash("Sin permiso para vincular cargas.", "warning")
        return redirect(url_for("billeteras_virtuales.cargas"))

    carga = _q_cargas().filter(BilleteraCarga.id == carga_id).first_or_404()
    _assert_owner_or_404(carga)

    casos_opts = _q_casos_accesibles().order_by(AnalisisPuntoCaso.created_at.desc()).limit(300).all()
    sujetos_opts = _q_sujetos_accesibles().order_by(Sujeto.apodo, Sujeto.nombre).limit(500).all()

    if request.method == "POST":
        caso = _get_caso_accesible(request.form.get("caso_id"))
        if not caso:
            flash("Debe seleccionar un caso válido.", "warning")
            return render_template(
                "billeteras_virtuales/carga_vincular.html",
                carga=carga,
                casos_opts=casos_opts,
                sujetos_opts=sujetos_opts,
            )
        sujeto = _get_sujeto_accesible(request.form.get("sujeto_id"))
        carga.caso_id = caso.id
        carga.sujeto_id = sujeto.id if sujeto else None
        db.session.commit()
        flash("Vinculación actualizada.", "success")
        return redirect(url_for("billeteras_virtuales.cargas"))

    return render_template(
        "billeteras_virtuales/carga_vincular.html",
        carga=carga,
        casos_opts=casos_opts,
        sujetos_opts=sujetos_opts,
    )


@bp.route("/cargas/<int:carga_id>/eliminar", methods=["POST"])
def cargas_eliminar(carga_id):
    if not _permiso_upload():
        flash("Sin permiso para eliminar cargas.", "warning")
        return redirect(url_for("billeteras_virtuales.cargas"))

    carga = _q_cargas().filter(BilleteraCarga.id == carga_id).first_or_404()
    _assert_owner_or_404(carga)
    nombre = carga.nombre_archivo or f"Carga #{carga.id}"

    db.session.delete(carga)
    db.session.commit()
    flash(f"Carga eliminada: {nombre}", "success")
    return redirect(url_for("billeteras_virtuales.cargas"))


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
    tipos_mov = _get_str_list_arg("tipos_movimiento[]")
    entidades = _get_str_list_arg("entidades[]")
    tipo_mov = _clean_str(request.args.get("tipo_movimiento"))
    entidad = _clean_str(request.args.get("entidad"))
    if tipo_mov and tipo_mov not in tipos_mov:
        tipos_mov.append(tipo_mov)
    if entidad and entidad not in entidades:
        entidades.append(entidad)
    if tipos_mov:
        mov_q = mov_q.filter(BilleteraMovimiento.tipo_movimiento.in_(tipos_mov))
    if entidades:
        sal_q = sal_q.filter(BilleteraSalida.entidad.in_(entidades))

    mov_items = (
        mov_q.options(joinedload(BilleteraMovimiento.carga).joinedload(BilleteraCarga.caso), joinedload(BilleteraMovimiento.carga).joinedload(BilleteraCarga.sujeto))
        .order_by(BilleteraMovimiento.fecha_operacion.desc())
        .limit(2000)
        .all()
    )
    sal_items = (
        sal_q.options(joinedload(BilleteraSalida.carga).joinedload(BilleteraCarga.caso), joinedload(BilleteraSalida.carga).joinedload(BilleteraCarga.sujeto))
        .order_by(BilleteraSalida.fecha_operacion.desc())
        .limit(2000)
        .all()
    )

    # little shim: csv.writer expects file-like with write()
    class _W:
        def __init__(self):
            self.parts = []
        def write(self, s):
            self.parts.append(s)
    w = _W()
    cw = csv.writer(w)
    cw.writerow(
        [
            "tipo",
            "carga_id",
            "archivo_carga",
            "hash_sha256",
            "caso",
            "sujeto",
            "fecha",
            "estado",
            "monto",
            "nombre",
            "documento",
            "detalle",
            "entidad",
        ]
    )
    for r in mov_items:
        cg = r.carga
        cw.writerow(
            [
                "movimiento",
                cg.id if cg else "",
                (cg.nombre_archivo or "") if cg else "",
                (cg.archivo_hash or "") if cg else "",
                cg.caso.codigo if cg and cg.caso else "",
                cg.sujeto.display_name() if cg and cg.sujeto else "",
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
        cg = r.carga
        cw.writerow(
            [
                "salida",
                cg.id if cg else "",
                (cg.nombre_archivo or "") if cg else "",
                (cg.archivo_hash or "") if cg else "",
                cg.caso.codigo if cg and cg.caso else "",
                cg.sujeto.display_name() if cg and cg.sujeto else "",
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


@bp.route("/api/share/users")
def api_share_users():
    """Busca usuarios activos de la misma unidad para compartir."""
    if not _permiso_view():
        return Response("[]", mimetype="application/json"), 403
    q = (request.args.get("q") or "").strip().lower()
    users_q = User.query.filter(User.unidad_id == current_user.unidad_id, User.active.is_(True), User.id != current_user.id)
    if q:
        users_q = users_q.filter(or_(User.username.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    users = users_q.order_by(User.username.asc()).limit(30).all()
    payload = [{"id": u.id, "username": u.username, "email": u.email} for u in users]
    return Response(json.dumps(payload), mimetype="application/json")


@bp.route("/api/share/carga/<int:carga_id>", methods=["GET", "POST", "DELETE"])
def api_share_carga(carga_id):
    carga = _q_cargas().filter(BilleteraCarga.id == carga_id).first_or_404()
    if not (_is_superadmin() or carga.user_id == current_user.id):
        return Response(json.dumps({"error": "Sin permiso para compartir esta carga"}), mimetype="application/json"), 403

    if request.method == "GET":
        shares = (
            BilleteraCargaCompartida.query
            .join(User, User.id == BilleteraCargaCompartida.shared_with_user_id)
            .filter(BilleteraCargaCompartida.carga_id == carga_id)
            .order_by(User.username.asc())
            .all()
        )
        payload = [{"id": s.shared_with.id, "username": s.shared_with.username, "email": s.shared_with.email} for s in shares]
        return Response(json.dumps(payload), mimetype="application/json")

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        try:
            user_id = int(user_id)
        except Exception:
            return Response(json.dumps({"error": "user_id inválido"}), mimetype="application/json"), 400
        user = User.query.filter(User.id == user_id, User.unidad_id == current_user.unidad_id, User.active.is_(True)).first()
        if not user or user.id == current_user.id:
            return Response(json.dumps({"error": "Usuario destino inválido"}), mimetype="application/json"), 400
        exists_row = BilleteraCargaCompartida.query.filter_by(carga_id=carga_id, shared_with_user_id=user.id).first()
        if not exists_row:
            db.session.add(
                BilleteraCargaCompartida(
                    carga_id=carga_id,
                    shared_with_user_id=user.id,
                    shared_by_user_id=current_user.id,
                )
            )
            db.session.commit()
        return Response(json.dumps({"ok": True}), mimetype="application/json")

    # DELETE
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return Response(json.dumps({"error": "user_id requerido"}), mimetype="application/json"), 400
    BilleteraCargaCompartida.query.filter_by(carga_id=carga_id, shared_with_user_id=user_id).delete(synchronize_session=False)
    db.session.commit()
    return Response(json.dumps({"ok": True}), mimetype="application/json")

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime, time
from io import BytesIO, StringIO
from urllib.parse import urlencode

import pandas as pd
from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, extract, inspect, or_

from app.blueprints.analisis_intervenciones import bp
from app.extensions import db
from app.models.analisis_intervenciones import AnalisisIntervencion


_schema_checked = False
_EXPECTED_COLUMNS = {
    "causas_id",
    "causas_interv_id",
    "tipo_interv_desc",
    "causa_escala",
    "causa_actividad",
    "tipo_operativo",
    "barrios_id",
    "barrios_nombre",
    "Localidad_Nombre",
    "Zona",
    "coordX",
    "coordY",
    "interv_fecha",
    "interv_hora",
    "interv_dia_semana",
    "interv_mes",
    "interv_trimestre",
    "pers_inteviniente",
    "dep_interviniente",
    "distrito",
    "Dep_policial",
    "departamento_operativo",
    "secuestro_marihuana",
    "secuestro_cocaina",
    "secuestro_plantas",
    "secuestro_plantines",
    "secuestro_semillas",
    "Pesos Arg",
    "Dolares",
    "Euro",
    "Reales",
    "Bolivianos",
    "Hojas de coca",
    "Det_Hombre_May",
    "Det_Hombre_Men",
    "Det_Mujer_May",
    "Det_Mujer_Men",
    "IS_Hombre_May",
    "IS_Hombre_Men",
    "IS_Mujer_May",
    "IS_Mujer_Men",
}
_MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("ANALISIS_INTERVENCIONES_VIEW")


def _can_import() -> bool:
    return _is_superadmin() or current_user.has_permission("ANALISIS_INTERVENCIONES_IMPORT")


def _can_export() -> bool:
    return _is_superadmin() or current_user.has_permission("ANALISIS_INTERVENCIONES_EXPORT")


def _can_dashboard() -> bool:
    return _is_superadmin() or current_user.has_permission("ANALISIS_INTERVENCIONES_DASHBOARD")


def _ensure_schema():
    global _schema_checked
    if _schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    if AnalisisIntervencion.__tablename__ not in existing:
        AnalisisIntervencion.__table__.create(bind=db.engine)
    _schema_checked = True


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
        s = str(v).strip()
        if not s:
            return None
        return int(float(s.replace(",", ".")))
    except Exception:
        return None


def _parse_float(v: object) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except Exception:
        return None


def _parse_date(v: object) -> date | None:
    """CSV intervenciones: día/mes/año; format='mixed' tolera ISO u otros en la misma columna."""
    try:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        d = pd.to_datetime(v, errors="coerce", dayfirst=True, format="mixed")
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


def _parse_time(v: object) -> time | None:
    s = _clean(v)
    if not s:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except Exception:
            continue
    try:
        t = pd.to_datetime(s, errors="coerce")
        if pd.isna(t):
            return None
        return t.to_pydatetime().time()
    except Exception:
        return None


def _to_num(v: float | int | None) -> float:
    return float(v or 0)


def _to_int(v: int | None) -> int:
    return int(v or 0)


def _fmt_float(v: float | int | None) -> str:
    return f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_int(v: int | float | None) -> str:
    return f"{int(v or 0):,}".replace(",", ".")


def _total_detenidos(row: AnalisisIntervencion) -> int:
    return (
        _to_int(row.det_hombre_may)
        + _to_int(row.det_hombre_men)
        + _to_int(row.det_mujer_may)
        + _to_int(row.det_mujer_men)
    )


def _total_identificados(row: AnalisisIntervencion) -> int:
    return (
        _to_int(row.is_hombre_may)
        + _to_int(row.is_hombre_men)
        + _to_int(row.is_mujer_may)
        + _to_int(row.is_mujer_men)
    )


def _as_datetime(fecha: date | None, hora: time | None) -> datetime | None:
    if not fecha:
        return None
    return datetime.combine(fecha, hora or time.min)


def _is_allanamiento(tipo: str | None) -> bool:
    return "allan" in (tipo or "").strip().lower()


def _is_procedimiento(tipo: str | None) -> bool:
    return "proced" in (tipo or "").strip().lower()


def _is_cod_aduanero_row(row: AnalisisIntervencion) -> bool:
    """Heurística para columna tipo 'Cód. aduanero' de los cuadros oficiales (no hay flag dedicado en el CSV)."""
    act = (row.causa_actividad or "").lower()
    top = (row.tipo_operativo or "").lower()
    if "contrabando" in act:
        return True
    if "aduana" in act or "aduana" in top:
        return True
    if "cod ad" in top or "cód ad" in top or "cod. ad" in top:
        return True
    return False


def _row_escala_bucket(row: AnalisisIntervencion) -> str:
    """Clasificación exclusiva: cód. aduanero primero, luego Macro/Micro por causa_escala."""
    if _is_cod_aduanero_row(row):
        return "cod_ad"
    esc = (row.causa_escala or "").strip().lower()
    if "macro" in esc:
        return "macro"
    return "micro"


def _new_cuadros_agg() -> dict:
    return {
        "causas": set(),
        "allanamientos": 0,
        "procedimientos": 0,
        "detenidos": 0,
        "identificados": 0,
        "marihuana": 0.0,
        "cocaina": 0.0,
        "hojas_coca": 0.0,
        "pesos": 0.0,
        "dolares": 0.0,
    }


def _cuadros_agg_add_row(agg: dict, row: AnalisisIntervencion) -> None:
    if _is_allanamiento(row.tipo_interv_desc):
        ck = _cause_key(row)
        if ck is not None:
            agg["causas"].add(ck)
        agg["allanamientos"] += 1
    elif _is_procedimiento(row.tipo_interv_desc):
        agg["procedimientos"] += 1
    agg["detenidos"] += _total_detenidos(row)
    agg["identificados"] += _total_identificados(row)
    agg["marihuana"] += _to_num(row.secuestro_marihuana)
    agg["cocaina"] += _to_num(row.secuestro_cocaina)
    agg["hojas_coca"] += _to_num(row.hojas_coca)
    agg["pesos"] += _to_num(row.pesos_arg)
    agg["dolares"] += _to_num(row.dolares)


def _cuadros_agg_finalize(agg: dict) -> dict:
    return {
        "causas_allanadas": len(agg["causas"]),
        "allanamientos": int(agg["allanamientos"] or 0),
        "procedimientos": int(agg["procedimientos"] or 0),
        "detenidos": int(agg["detenidos"] or 0),
        "identificados": int(agg["identificados"] or 0),
        "marihuana": float(agg["marihuana"] or 0),
        "cocaina": float(agg["cocaina"] or 0),
        "hojas_coca": float(agg["hojas_coca"] or 0),
        "pesos": float(agg["pesos"] or 0),
        "dolares": float(agg["dolares"] or 0),
    }


def _cuadros_sum_display_rows(rows: list[dict]) -> dict:
    keys = [
        "causas_allanadas",
        "allanamientos",
        "procedimientos",
        "detenidos",
        "identificados",
        "marihuana",
        "cocaina",
        "hojas_coca",
        "pesos",
        "dolares",
    ]
    t = {k: 0 for k in keys}
    for r in rows:
        for k in keys:
            t[k] += float(r.get(k) or 0)
    for k in ("causas_allanadas", "allanamientos", "procedimientos", "detenidos", "identificados"):
        t[k] = int(t[k])
    return t


def _cuadros_data(rows: list[AnalisisIntervencion]) -> dict:
    """Agregaciones para cuadros tipo tabulación oficial (filtros ya aplicados)."""
    by_zona: dict[str, dict] = defaultdict(_new_cuadros_agg)
    by_sinar: dict[str, dict] = defaultdict(_new_cuadros_agg)
    by_dep: dict[str, dict] = defaultdict(_new_cuadros_agg)
    by_distrito: dict[str, dict] = defaultdict(_new_cuadros_agg)
    by_distrito_micro: dict[str, dict] = defaultdict(_new_cuadros_agg)
    by_distrito_macro: dict[str, dict] = defaultdict(_new_cuadros_agg)
    b_micro = _new_cuadros_agg()
    b_macro = _new_cuadros_agg()
    b_cod = _new_cuadros_agg()
    by_year_bucket: dict[int, dict[str, dict]] = defaultdict(
        lambda: {"micro": _new_cuadros_agg(), "macro": _new_cuadros_agg(), "cod_ad": _new_cuadros_agg()}
    )

    for row in rows:
        zona = (row.zona or "Sin dato").strip() or "Sin dato"
        sinar = (row.dep_interviniente or "Sin dato").strip() or "Sin dato"
        depop = (row.departamento_operativo or "Sin dato").strip() or "Sin dato"
        distrito = (row.distrito or "Sin dato").strip() or "Sin dato"
        _cuadros_agg_add_row(by_zona[zona], row)
        _cuadros_agg_add_row(by_sinar[sinar], row)
        _cuadros_agg_add_row(by_dep[depop], row)
        _cuadros_agg_add_row(by_distrito[distrito], row)
        bucket = _row_escala_bucket(row)
        if bucket == "cod_ad":
            _cuadros_agg_add_row(b_cod, row)
        elif bucket == "macro":
            _cuadros_agg_add_row(b_macro, row)
            _cuadros_agg_add_row(by_distrito_macro[distrito], row)
        else:
            _cuadros_agg_add_row(b_micro, row)
            _cuadros_agg_add_row(by_distrito_micro[distrito], row)
        y = _to_int(row.anio) or (row.interv_fecha.year if row.interv_fecha else None)
        if y:
            _cuadros_agg_add_row(by_year_bucket[y][bucket], row)

    def sort_table(items: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        return sorted(items, key=lambda x: (-_cuadros_agg_finalize(x[1])["allanamientos"] - x[1]["procedimientos"], x[0]))

    def finalize_map(m: dict[str, dict]) -> list[dict]:
        out = []
        for label, raw in sort_table(list(m.items())):
            d = _cuadros_agg_finalize(raw)
            d["label"] = label
            out.append(d)
        return out

    def _distrito_orden_key(label: str) -> tuple:
        m = re.search(r"(\d+)", label or "")
        num = int(m.group(1)) if m else 10**9
        return (num, (label or "").lower())

    def finalize_map_distrito(m: dict[str, dict]) -> list[dict]:
        out = []
        for label, raw in sorted(m.items(), key=lambda x: _distrito_orden_key(x[0])):
            d = _cuadros_agg_finalize(raw)
            d["label"] = label
            out.append(d)
        return out

    tabla_zona = finalize_map(by_zona)
    tabla_sinar = finalize_map(by_sinar)
    tabla_dep = finalize_map(by_dep)
    tabla_distrito = finalize_map_distrito(by_distrito)
    tabla_distrito_micro = finalize_map_distrito(by_distrito_micro)
    tabla_distrito_macro = finalize_map_distrito(by_distrito_macro)

    mic = _cuadros_agg_finalize(b_micro)
    mac = _cuadros_agg_finalize(b_macro)
    cod = _cuadros_agg_finalize(b_cod)

    def cell(d: dict, k: str) -> int | float:
        return d.get(k) or 0

    clasificacion_filas = [
        {
            "label": "Causas allanadas",
            "micro": cell(mic, "causas_allanadas"),
            "macro": cell(mac, "causas_allanadas"),
            "cod_ad": cell(cod, "causas_allanadas"),
            "total_mm": cell(mic, "causas_allanadas") + cell(mac, "causas_allanadas"),
            "total_mmc": cell(mic, "causas_allanadas") + cell(mac, "causas_allanadas") + cell(cod, "causas_allanadas"),
        },
        {
            "label": "Allanamientos (interv.)",
            "micro": cell(mic, "allanamientos"),
            "macro": cell(mac, "allanamientos"),
            "cod_ad": cell(cod, "allanamientos"),
            "total_mm": cell(mic, "allanamientos") + cell(mac, "allanamientos"),
            "total_mmc": cell(mic, "allanamientos") + cell(mac, "allanamientos") + cell(cod, "allanamientos"),
        },
        {
            "label": "Procedimientos",
            "micro": cell(mic, "procedimientos"),
            "macro": cell(mac, "procedimientos"),
            "cod_ad": cell(cod, "procedimientos"),
            "total_mm": cell(mic, "procedimientos") + cell(mac, "procedimientos"),
            "total_mmc": cell(mic, "procedimientos") + cell(mac, "procedimientos") + cell(cod, "procedimientos"),
        },
        {
            "label": "Detenidos",
            "micro": cell(mic, "detenidos"),
            "macro": cell(mac, "detenidos"),
            "cod_ad": cell(cod, "detenidos"),
            "total_mm": cell(mic, "detenidos") + cell(mac, "detenidos"),
            "total_mmc": cell(mic, "detenidos") + cell(mac, "detenidos") + cell(cod, "detenidos"),
        },
        {
            "label": "Identificados / supeditados",
            "micro": cell(mic, "identificados"),
            "macro": cell(mac, "identificados"),
            "cod_ad": cell(cod, "identificados"),
            "total_mm": cell(mic, "identificados") + cell(mac, "identificados"),
            "total_mmc": cell(mic, "identificados") + cell(mac, "identificados") + cell(cod, "identificados"),
        },
        {
            "label": "Marihuana (unid. importe)",
            "micro": cell(mic, "marihuana"),
            "macro": cell(mac, "marihuana"),
            "cod_ad": cell(cod, "marihuana"),
            "total_mm": cell(mic, "marihuana") + cell(mac, "marihuana"),
            "total_mmc": cell(mic, "marihuana") + cell(mac, "marihuana") + cell(cod, "marihuana"),
            "num": True,
        },
        {
            "label": "Cocaína (unid. importe)",
            "micro": cell(mic, "cocaina"),
            "macro": cell(mac, "cocaina"),
            "cod_ad": cell(cod, "cocaina"),
            "total_mm": cell(mic, "cocaina") + cell(mac, "cocaina"),
            "total_mmc": cell(mic, "cocaina") + cell(mac, "cocaina") + cell(cod, "cocaina"),
            "num": True,
        },
        {
            "label": "Hoja de coca (unid. importe)",
            "micro": cell(mic, "hojas_coca"),
            "macro": cell(mac, "hojas_coca"),
            "cod_ad": cell(cod, "hojas_coca"),
            "total_mm": cell(mic, "hojas_coca") + cell(mac, "hojas_coca"),
            "total_mmc": cell(mic, "hojas_coca") + cell(mac, "hojas_coca") + cell(cod, "hojas_coca"),
            "num": True,
        },
        {
            "label": "Pesos Arg",
            "micro": cell(mic, "pesos"),
            "macro": cell(mac, "pesos"),
            "cod_ad": cell(cod, "pesos"),
            "total_mm": cell(mic, "pesos") + cell(mac, "pesos"),
            "total_mmc": cell(mic, "pesos") + cell(mac, "pesos") + cell(cod, "pesos"),
            "num": True,
        },
        {
            "label": "Dólares",
            "micro": cell(mic, "dolares"),
            "macro": cell(mac, "dolares"),
            "cod_ad": cell(cod, "dolares"),
            "total_mm": cell(mic, "dolares") + cell(mac, "dolares"),
            "total_mmc": cell(mic, "dolares") + cell(mac, "dolares") + cell(cod, "dolares"),
            "num": True,
        },
    ]

    years_sorted = sorted(by_year_bucket.keys())
    comparativo_anios = []
    for y in years_sorted:
        yb = by_year_bucket[y]
        ym = _cuadros_agg_finalize(yb["micro"])
        ymac = _cuadros_agg_finalize(yb["macro"])
        ycod = _cuadros_agg_finalize(yb["cod_ad"])

        comparativo_anios.append(
            {
                "anio": y,
                "micro": ym,
                "macro": ymac,
                "cod_ad": ycod,
                "tot_micro_macro": {k: int(ym[k]) + int(ymac[k]) if k in ("causas_allanadas", "allanamientos", "procedimientos", "detenidos", "identificados") else float(ym[k] or 0) + float(ymac[k] or 0) for k in ym},
                "tot_todo": {k: float(ym[k] or 0) + float(ymac[k] or 0) + float(ycod[k] or 0) for k in ym},
            }
        )
    # Normalizar totales comparativos a int donde aplica
    for block in comparativo_anios:
        for key in ("causas_allanadas", "allanamientos", "procedimientos", "detenidos", "identificados"):
            block["tot_micro_macro"][key] = int(block["tot_micro_macro"][key])
            block["tot_todo"][key] = int(block["tot_todo"][key])

    int_keys = ("causas_allanadas", "allanamientos", "procedimientos", "detenidos", "identificados")
    comparativo_filas: list[dict] = []
    for label, key, is_float in (
        ("Causas allanadas", "causas_allanadas", False),
        ("Allanamientos (interv.)", "allanamientos", False),
        ("Procedimientos", "procedimientos", False),
        ("Detenidos", "detenidos", False),
        ("Identificados / supeditados", "identificados", False),
        ("Marihuana (unid. importe)", "marihuana", True),
        ("Cocaína (unid. importe)", "cocaina", True),
        ("Hoja de coca (unid. importe)", "hojas_coca", True),
        ("Pesos Arg", "pesos", True),
        ("Dólares", "dolares", True),
    ):
        fila = {"label": label, "is_float": is_float, "por_anio": []}
        for b in comparativo_anios:
            ym, ymac, ycod = b["micro"], b["macro"], b["cod_ad"]
            vm, vma, vc = ym[key], ymac[key], ycod[key]
            if key in int_keys:
                tot = int(vm) + int(vma) + int(vc)
            else:
                tot = float(vm or 0) + float(vma or 0) + float(vc or 0)
            fila["por_anio"].append(
                {
                    "anio": b["anio"],
                    "micro": vm,
                    "macro": vma,
                    "cod_ad": vc,
                    "total": tot,
                }
            )
        comparativo_filas.append(fila)

    return {
        "tabla_zona": tabla_zona,
        "totales_zona": _cuadros_sum_display_rows(tabla_zona),
        "tabla_sinar": tabla_sinar,
        "totales_sinar": _cuadros_sum_display_rows(tabla_sinar),
        "tabla_dep": tabla_dep,
        "totales_dep": _cuadros_sum_display_rows(tabla_dep),
        "tabla_distrito": tabla_distrito,
        "totales_distrito": _cuadros_sum_display_rows(tabla_distrito),
        "tabla_distrito_micro": tabla_distrito_micro,
        "totales_distrito_micro": _cuadros_sum_display_rows(tabla_distrito_micro),
        "tabla_distrito_macro": tabla_distrito_macro,
        "totales_distrito_macro": _cuadros_sum_display_rows(tabla_distrito_macro),
        "clasificacion_filas": clasificacion_filas,
        "comparativo_anios": comparativo_anios,
        "comparativo_filas": comparativo_filas,
        "nota_cod_ad": "La columna «Cód. aduanero» usa heurística: causa actividad «Contrabando» o texto con «aduana» en actividad/tipo operativo.",
    }


def _base_q():
    return AnalisisIntervencion.query.filter(
        AnalisisIntervencion.unidad_id == current_user.unidad_id,
        AnalisisIntervencion.activo.is_(True),
    )


def _get_list_arg(name: str) -> list[str]:
    vals: list[str] = []
    for raw in request.args.getlist(name):
        s = _clean(raw)
        if s:
            vals.append(s)
    return sorted(set(vals))


def _selected_filters() -> dict:
    data = {
        "q": _clean(request.args.get("q")) or "",
        "fecha_desde": _clean(request.args.get("fecha_desde")) or "",
        "fecha_hasta": _clean(request.args.get("fecha_hasta")) or "",
        "preset_periodo": _clean(request.args.get("preset_periodo")) or "",
        "comparar_mismo_periodo": _clean(request.args.get("comparar_mismo_periodo")) == "1",
        "anios": _get_list_arg("anio[]"),
        "zonas": _get_list_arg("zona[]"),
        "sinares": _get_list_arg("sinar[]"),
        "departamentos_operativos": _get_list_arg("departamento_operativo[]"),
        "tipos_interv": _get_list_arg("tipo_interv[]"),
        "localidades": _get_list_arg("localidad[]"),
        "barrios": _get_list_arg("barrio[]"),
    }
    if data["preset_periodo"] == "enero_hoy" and not data["fecha_desde"] and not data["fecha_hasta"]:
        today = date.today()
        data["fecha_desde"] = date(today.year, 1, 1).isoformat()
        data["fecha_hasta"] = today.isoformat()
    return data


def _resolve_period_dates(s: dict) -> tuple[date | None, date | None]:
    fd = _parse_date(s.get("fecha_desde"))
    fh = _parse_date(s.get("fecha_hasta"))
    if s.get("preset_periodo") == "enero_hoy" and not fd and not fh:
        today = date.today()
        return date(today.year, 1, 1), today
    return fd, fh


def _month_day_value(dt: date | None) -> int | None:
    if not dt:
        return None
    return dt.month * 100 + dt.day


def _apply_same_period_filter(q, fd: date | None, fh: date | None):
    md_expr = extract("month", AnalisisIntervencion.interv_fecha) * 100 + extract("day", AnalisisIntervencion.interv_fecha)
    md_from = _month_day_value(fd)
    md_to = _month_day_value(fh)
    if md_from and md_to:
        if md_from <= md_to:
            return q.filter(and_(md_expr >= md_from, md_expr <= md_to))
        return q.filter(or_(md_expr >= md_from, md_expr <= md_to))
    if md_from:
        return q.filter(md_expr >= md_from)
    if md_to:
        return q.filter(md_expr <= md_to)
    return q


def _apply_filters(q):
    s = _selected_filters()
    if s["q"]:
        pat = f"%{s['q']}%"
        filters = [
            AnalisisIntervencion.tipo_interv_desc.ilike(pat),
            AnalisisIntervencion.causa_escala.ilike(pat),
            AnalisisIntervencion.causa_actividad.ilike(pat),
            AnalisisIntervencion.tipo_operativo.ilike(pat),
            AnalisisIntervencion.barrios_nombre.ilike(pat),
            AnalisisIntervencion.localidad_nombre.ilike(pat),
            AnalisisIntervencion.zona.ilike(pat),
            AnalisisIntervencion.pers_interviniente.ilike(pat),
            AnalisisIntervencion.dep_interviniente.ilike(pat),
            AnalisisIntervencion.distrito.ilike(pat),
            AnalisisIntervencion.dep_policial.ilike(pat),
            AnalisisIntervencion.departamento_operativo.ilike(pat),
        ]
        qnum = _parse_int(s["q"])
        if qnum is not None:
            filters.extend(
                [
                    AnalisisIntervencion.causas_id == qnum,
                    AnalisisIntervencion.causas_interv_id == qnum,
                    AnalisisIntervencion.anio == qnum,
                ]
            )
        q = q.filter(or_(*filters))
    fd, fh = _resolve_period_dates(s)
    if s["anios"]:
        anios = [_parse_int(x) for x in s["anios"]]
        anios = [x for x in anios if x is not None]
        if anios:
            q = q.filter(AnalisisIntervencion.anio.in_(anios))
    if s["comparar_mismo_periodo"]:
        q = _apply_same_period_filter(q, fd, fh)
    else:
        if fd:
            q = q.filter(AnalisisIntervencion.interv_fecha >= fd)
        if fh:
            q = q.filter(AnalisisIntervencion.interv_fecha <= fh)
    if s["zonas"]:
        q = q.filter(AnalisisIntervencion.zona.in_(s["zonas"]))
    if s["sinares"]:
        q = q.filter(AnalisisIntervencion.dep_interviniente.in_(s["sinares"]))
    if s["departamentos_operativos"]:
        q = q.filter(AnalisisIntervencion.departamento_operativo.in_(s["departamentos_operativos"]))
    if s["tipos_interv"]:
        q = q.filter(AnalisisIntervencion.tipo_interv_desc.in_(s["tipos_interv"]))
    if s["localidades"]:
        q = q.filter(AnalisisIntervencion.localidad_nombre.in_(s["localidades"]))
    if s["barrios"]:
        q = q.filter(AnalisisIntervencion.barrios_nombre.in_(s["barrios"]))
    return q


def _distinct_values(column) -> list[str]:
    return [r[0] for r in _base_q().with_entities(column).distinct().order_by(column.asc()).all() if r[0]]


def _filter_options() -> dict:
    anios = [r[0] for r in _base_q().with_entities(AnalisisIntervencion.anio).distinct().order_by(AnalisisIntervencion.anio.asc()).all() if r[0]]
    return {
        "anios": [str(x) for x in anios],
        "zonas": _distinct_values(AnalisisIntervencion.zona),
        "sinares": _distinct_values(AnalisisIntervencion.dep_interviniente),
        "departamentos_operativos": _distinct_values(AnalisisIntervencion.departamento_operativo),
        "tipos_interv": _distinct_values(AnalisisIntervencion.tipo_interv_desc),
        "localidades": _distinct_values(AnalisisIntervencion.localidad_nombre),
        "barrios": _distinct_values(AnalisisIntervencion.barrios_nombre),
    }


def _decode_upload(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _import_from_text(text: str) -> dict:
    if not text.strip():
        return {"error": "Archivo vacío."}
    reader = csv.DictReader(StringIO(text), delimiter=";")
    fields = set(reader.fieldnames or [])
    miss = sorted(x for x in _EXPECTED_COLUMNS if x not in fields)
    if miss:
        return {"error": f"Faltan columnas: {', '.join(miss)}"}

    now = datetime.utcnow()
    parsed: dict[int, AnalisisIntervencion] = {}
    skipped = 0
    duplicated = 0
    years: set[int] = set()

    for row in reader:
        causas_interv_id = _parse_int(row.get("causas_interv_id"))
        fecha = _parse_date(row.get("interv_fecha"))
        if causas_interv_id is None or fecha is None:
            skipped += 1
            continue
        years.add(fecha.year)
        if causas_interv_id in parsed:
            duplicated += 1
        parsed[causas_interv_id] = AnalisisIntervencion(
            unidad_id=current_user.unidad_id,
            creado_por=current_user.id,
            fecha_importacion=now,
            activo=True,
            anio=fecha.year,
            causas_id=_parse_int(row.get("causas_id")),
            causas_interv_id=causas_interv_id,
            tipo_interv_desc=_clean(row.get("tipo_interv_desc")),
            causa_escala=_clean(row.get("causa_escala")),
            causa_actividad=_clean(row.get("causa_actividad")),
            tipo_operativo=_clean(row.get("tipo_operativo")),
            barrios_id=_parse_int(row.get("barrios_id")),
            barrios_nombre=_clean(row.get("barrios_nombre")),
            localidad_nombre=_clean(row.get("Localidad_Nombre")),
            zona=_clean(row.get("Zona")),
            coordx=_parse_float(row.get("coordX")),
            coordy=_parse_float(row.get("coordY")),
            interv_fecha=fecha,
            interv_hora=_parse_time(row.get("interv_hora")),
            interv_dia_semana=_clean(row.get("interv_dia_semana")),
            interv_mes=_clean(row.get("interv_mes")),
            interv_mes_num=fecha.month,
            interv_trimestre=_parse_int(row.get("interv_trimestre")),
            pers_interviniente=_clean(row.get("pers_inteviniente")),
            dep_interviniente=_clean(row.get("dep_interviniente")),
            distrito=_clean(row.get("distrito")),
            dep_policial=_clean(row.get("Dep_policial")),
            departamento_operativo=_clean(row.get("departamento_operativo")),
            secuestro_marihuana=_parse_float(row.get("secuestro_marihuana")) or 0,
            secuestro_cocaina=_parse_float(row.get("secuestro_cocaina")) or 0,
            secuestro_plantas=_parse_float(row.get("secuestro_plantas")) or 0,
            secuestro_plantines=_parse_float(row.get("secuestro_plantines")) or 0,
            secuestro_semillas=_parse_float(row.get("secuestro_semillas")) or 0,
            pesos_arg=_parse_float(row.get("Pesos Arg")) or 0,
            dolares=_parse_float(row.get("Dolares")) or 0,
            euro=_parse_float(row.get("Euro")) or 0,
            reales=_parse_float(row.get("Reales")) or 0,
            bolivianos=_parse_float(row.get("Bolivianos")) or 0,
            hojas_coca=_parse_float(row.get("Hojas de coca")) or 0,
            det_hombre_may=_parse_int(row.get("Det_Hombre_May")) or 0,
            det_hombre_men=_parse_int(row.get("Det_Hombre_Men")) or 0,
            det_mujer_may=_parse_int(row.get("Det_Mujer_May")) or 0,
            det_mujer_men=_parse_int(row.get("Det_Mujer_Men")) or 0,
            is_hombre_may=_parse_int(row.get("IS_Hombre_May")) or 0,
            is_hombre_men=_parse_int(row.get("IS_Hombre_Men")) or 0,
            is_mujer_may=_parse_int(row.get("IS_Mujer_May")) or 0,
            is_mujer_men=_parse_int(row.get("IS_Mujer_Men")) or 0,
            us_carga=_clean(row.get("Us_carga")),
        )

    if not parsed:
        return {"error": "No se encontraron filas válidas para importar."}
    if len(years) != 1:
        years_sorted = ", ".join(str(x) for x in sorted(years))
        return {"error": f"El archivo contiene más de un año ({years_sorted}). Subí un archivo por año."}

    anio = next(iter(years))
    try:
        deleted = (
            AnalisisIntervencion.query.filter(
                AnalisisIntervencion.unidad_id == current_user.unidad_id,
                AnalisisIntervencion.anio == anio,
            ).delete(synchronize_session=False)
        )
        db.session.bulk_save_objects(list(parsed.values()))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return {"error": f"No se pudo importar el archivo: {exc}"}

    return {
        "anio": anio,
        "importados": len(parsed),
        "omitidos": skipped,
        "duplicados": duplicated,
        "eliminados_previos": deleted,
    }


def _blank_year_row(anio: int) -> dict:
    return {
        "anio": anio,
        "total": 0,
        "allanamientos": 0,
        "causas_allanadas": 0,
        "procedimientos": 0,
        "otros_tipos": 0,
        "marihuana": 0.0,
        "cocaina": 0.0,
        "plantas": 0.0,
        "plantines": 0.0,
        "semillas": 0.0,
        "hojas_coca": 0.0,
        "pesos_arg": 0.0,
        "dolares": 0.0,
        "euro": 0.0,
        "reales": 0.0,
        "bolivianos": 0.0,
        "detenidos": 0,
        "identificados": 0,
    }


def _cause_key(row: AnalisisIntervencion) -> int | None:
    return row.causas_id or row.causas_interv_id


def _count_by(rows: list[AnalisisIntervencion], key_fn, limit: int | None = None) -> list[dict]:
    acc: dict[str, int] = defaultdict(int)
    for row in rows:
        label = key_fn(row) or "Sin dato"
        acc[str(label)] += 1
    items = [{"label": k, "value": int(v)} for k, v in acc.items()]
    items.sort(key=lambda x: (-x["value"], x["label"]))
    if limit:
        items = items[:limit]
    return items


def _sum_chart(items: list[tuple[str, float]], limit: int | None = None) -> list[dict]:
    out = [{"label": label, "value": round(float(value or 0), 2)} for label, value in items]
    out.sort(key=lambda x: (-x["value"], x["label"]))
    if limit:
        out = out[:limit]
    return out


def _grouped_dimension_chart(rows: list[AnalisisIntervencion], key_fn, limit: int = 10) -> dict:
    years = sorted({_to_int(r.anio) for r in rows if _to_int(r.anio)})
    totals: dict[str, int] = defaultdict(int)
    by_label_year: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        label = str(key_fn(row) or "Sin dato").strip() or "Sin dato"
        year = _to_int(row.anio)
        if not year:
            continue
        totals[label] += 1
        by_label_year[label][year] += 1
    categories = [label for label, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]]
    return {
        "categories": categories,
        "series": [{"name": str(year), "values": [by_label_year[label].get(year, 0) for label in categories]} for year in years],
    }


def _empty_metric_row() -> dict:
    return {
        "total": 0,
        "allanamientos": 0,
        "causas_allanadas": 0,
        "procedimientos": 0,
        "marihuana": 0.0,
        "cocaina": 0.0,
        "pesos_arg": 0.0,
        "detenidos": 0,
        "identificados": 0,
    }


def _grouped_dimension_bundle(rows: list[AnalisisIntervencion], key_fn, limit: int = 8) -> dict:
    years = sorted({_to_int(r.anio) for r in rows if _to_int(r.anio)})
    totals: dict[str, int] = defaultdict(int)
    nested: dict[str, dict[int, dict]] = defaultdict(lambda: defaultdict(_empty_metric_row))
    causas_sets: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))

    for row in rows:
        label = str(key_fn(row) or "Sin dato").strip() or "Sin dato"
        year = _to_int(row.anio)
        if not year:
            continue
        totals[label] += 1
        item = nested[label][year]
        item["total"] += 1
        if _is_allanamiento(row.tipo_interv_desc):
            item["allanamientos"] += 1
            cause_key = _cause_key(row)
            if cause_key is not None:
                causas_sets[label][year].add(cause_key)
        elif _is_procedimiento(row.tipo_interv_desc):
            item["procedimientos"] += 1
        item["marihuana"] += _to_num(row.secuestro_marihuana)
        item["cocaina"] += _to_num(row.secuestro_cocaina)
        item["pesos_arg"] += _to_num(row.pesos_arg)
        item["detenidos"] += _total_detenidos(row)
        item["identificados"] += _total_identificados(row)

    categories = [label for label, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    def metric_chart(metric: str, digits: int) -> dict:
        return {
            "digits": digits,
            "categories": categories,
            "series": [
                {
                    "name": str(year),
                    "values": [
                        (
                            len(causas_sets[label][year])
                            if metric == "causas_allanadas"
                            else round(float(nested[label][year][metric]), digits)
                            if digits > 0
                            else int(nested[label][year][metric] or 0)
                        )
                        for label in categories
                    ],
                }
                for year in years
            ],
        }

    table_rows = []
    for label in categories:
        for year in years:
            item = nested[label][year]
            table_rows.append(
                {
                    "label": label,
                    "anio": year,
                    "total": int(item["total"] or 0),
                    "allanamientos": int(item["allanamientos"] or 0),
                    "causas_allanadas": len(causas_sets[label][year]),
                    "procedimientos": int(item["procedimientos"] or 0),
                    "marihuana": round(float(item["marihuana"] or 0), 2),
                    "cocaina": round(float(item["cocaina"] or 0), 2),
                    "pesos_arg": round(float(item["pesos_arg"] or 0), 2),
                    "detenidos": int(item["detenidos"] or 0),
                    "identificados": int(item["identificados"] or 0),
                }
            )

    return {
        "years": years,
        "categories": categories,
        "metrics": {
            "total": metric_chart("total", 0),
            "allanamientos": metric_chart("allanamientos", 0),
            "causas_allanadas": metric_chart("causas_allanadas", 0),
            "procedimientos": metric_chart("procedimientos", 0),
            "marihuana": metric_chart("marihuana", 2),
            "cocaina": metric_chart("cocaina", 2),
            "pesos_arg": metric_chart("pesos_arg", 2),
            "detenidos": metric_chart("detenidos", 0),
            "identificados": metric_chart("identificados", 0),
        },
        "table_rows": table_rows,
    }


def _dashboard_data(rows: list[AnalisisIntervencion]) -> dict:
    comparativo: dict[int, dict] = {}
    mensual: dict[int, list[int]] = defaultdict(lambda: [0] * 12)
    trimestral: dict[int, list[int]] = defaultdict(lambda: [0] * 4)
    zonas_count: dict[str, int] = defaultdict(int)
    sinares_count: dict[str, int] = defaultdict(int)
    depops_count: dict[str, int] = defaultdict(int)
    tipos_count: dict[str, int] = defaultdict(int)
    localidades_count: dict[str, int] = defaultdict(int)
    tipo_por_anio: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    personas_chart = {
        "Det. hombre mayor": 0,
        "Det. hombre menor": 0,
        "Det. mujer mayor": 0,
        "Det. mujer menor": 0,
        "IS hombre mayor": 0,
        "IS hombre menor": 0,
        "IS mujer mayor": 0,
        "IS mujer menor": 0,
    }
    secuestros_totales = {
        "Marihuana": 0.0,
        "Cocaina": 0.0,
        "Plantas": 0.0,
        "Plantines": 0.0,
        "Semillas": 0.0,
        "Hojas de coca": 0.0,
    }
    dinero_totales = {
        "Pesos Arg": 0.0,
        "Dolares": 0.0,
        "Euro": 0.0,
        "Reales": 0.0,
        "Bolivianos": 0.0,
    }

    total = len(rows)
    allanamientos = 0
    causas_allanadas: set[int] = set()
    procedimientos = 0
    detenidos_total = 0
    identificados_total = 0
    causas_allanadas_por_anio: dict[int, set[int]] = defaultdict(set)

    for row in rows:
        year = _to_int(row.anio)
        if year not in comparativo:
            comparativo[year] = _blank_year_row(year)
        comp = comparativo[year]
        comp["total"] += 1

        tipo = (row.tipo_interv_desc or "Sin dato").strip() or "Sin dato"
        tipo_por_anio[tipo][year] += 1
        tipos_count[tipo] += 1
        zonas_count[row.zona or "Sin dato"] += 1
        sinares_count[row.dep_interviniente or "Sin dato"] += 1
        depops_count[row.departamento_operativo or "Sin dato"] += 1
        localidades_count[row.localidad_nombre or "Sin dato"] += 1

        if _is_allanamiento(row.tipo_interv_desc):
            allanamientos += 1
            comp["allanamientos"] += 1
            cause_key = _cause_key(row)
            if cause_key is not None:
                causas_allanadas.add(cause_key)
                causas_allanadas_por_anio[year].add(cause_key)
        elif _is_procedimiento(row.tipo_interv_desc):
            procedimientos += 1
            comp["procedimientos"] += 1
        else:
            comp["otros_tipos"] += 1

        if row.interv_mes_num and 1 <= row.interv_mes_num <= 12:
            mensual[year][row.interv_mes_num - 1] += 1
        trimestre = _to_int(row.interv_trimestre)
        if 1 <= trimestre <= 4:
            trimestral[year][trimestre - 1] += 1

        comp["marihuana"] += _to_num(row.secuestro_marihuana)
        comp["cocaina"] += _to_num(row.secuestro_cocaina)
        comp["plantas"] += _to_num(row.secuestro_plantas)
        comp["plantines"] += _to_num(row.secuestro_plantines)
        comp["semillas"] += _to_num(row.secuestro_semillas)
        comp["hojas_coca"] += _to_num(row.hojas_coca)
        comp["pesos_arg"] += _to_num(row.pesos_arg)
        comp["dolares"] += _to_num(row.dolares)
        comp["euro"] += _to_num(row.euro)
        comp["reales"] += _to_num(row.reales)
        comp["bolivianos"] += _to_num(row.bolivianos)
        personas_chart["Det. hombre mayor"] += _to_int(row.det_hombre_may)
        personas_chart["Det. hombre menor"] += _to_int(row.det_hombre_men)
        personas_chart["Det. mujer mayor"] += _to_int(row.det_mujer_may)
        personas_chart["Det. mujer menor"] += _to_int(row.det_mujer_men)
        personas_chart["IS hombre mayor"] += _to_int(row.is_hombre_may)
        personas_chart["IS hombre menor"] += _to_int(row.is_hombre_men)
        personas_chart["IS mujer mayor"] += _to_int(row.is_mujer_may)
        personas_chart["IS mujer menor"] += _to_int(row.is_mujer_men)

        secuestros_totales["Marihuana"] += _to_num(row.secuestro_marihuana)
        secuestros_totales["Cocaina"] += _to_num(row.secuestro_cocaina)
        secuestros_totales["Plantas"] += _to_num(row.secuestro_plantas)
        secuestros_totales["Plantines"] += _to_num(row.secuestro_plantines)
        secuestros_totales["Semillas"] += _to_num(row.secuestro_semillas)
        secuestros_totales["Hojas de coca"] += _to_num(row.hojas_coca)
        dinero_totales["Pesos Arg"] += _to_num(row.pesos_arg)
        dinero_totales["Dolares"] += _to_num(row.dolares)
        dinero_totales["Euro"] += _to_num(row.euro)
        dinero_totales["Reales"] += _to_num(row.reales)
        dinero_totales["Bolivianos"] += _to_num(row.bolivianos)

        detenidos = _total_detenidos(row)
        identificados = _total_identificados(row)
        detenidos_total += detenidos
        identificados_total += identificados
        comp["detenidos"] += detenidos
        comp["identificados"] += identificados

    for year, causes in causas_allanadas_por_anio.items():
        if year in comparativo:
            comparativo[year]["causas_allanadas"] = len(causes)

    comparativo_anual = [comparativo[k] for k in sorted(comparativo)]
    chart_anio_total = [{"label": str(r["anio"]), "value": r["total"]} for r in comparativo_anual]
    chart_anio_allanamientos = [{"label": str(r["anio"]), "value": r["allanamientos"]} for r in comparativo_anual]
    chart_anio_causas_allanadas = [{"label": str(r["anio"]), "value": r["causas_allanadas"]} for r in comparativo_anual]
    chart_anio_procedimientos = [{"label": str(r["anio"]), "value": r["procedimientos"]} for r in comparativo_anual]
    chart_anio_marihuana = [{"label": str(r["anio"]), "value": round(r["marihuana"], 2)} for r in comparativo_anual]
    chart_anio_cocaina = [{"label": str(r["anio"]), "value": round(r["cocaina"], 2)} for r in comparativo_anual]
    chart_anio_plantas = [{"label": str(r["anio"]), "value": round(r["plantas"], 2)} for r in comparativo_anual]
    chart_anio_plantines = [{"label": str(r["anio"]), "value": round(r["plantines"], 2)} for r in comparativo_anual]
    chart_anio_semillas = [{"label": str(r["anio"]), "value": round(r["semillas"], 2)} for r in comparativo_anual]
    chart_anio_hojas_coca = [{"label": str(r["anio"]), "value": round(r["hojas_coca"], 2)} for r in comparativo_anual]
    chart_anio_pesos = [{"label": str(r["anio"]), "value": round(r["pesos_arg"], 2)} for r in comparativo_anual]
    chart_anio_detenidos = [{"label": str(r["anio"]), "value": r["detenidos"]} for r in comparativo_anual]
    chart_anio_identificados = [{"label": str(r["anio"]), "value": r["identificados"]} for r in comparativo_anual]
    chart_compare_depops = _grouped_dimension_chart(rows, lambda r: r.departamento_operativo, limit=8)
    chart_compare_sinares = _grouped_dimension_chart(rows, lambda r: r.dep_interviniente, limit=8)
    chart_compare_zonas = _grouped_dimension_chart(rows, lambda r: r.zona, limit=8)
    dimension_compare = {
        "depops": _grouped_dimension_bundle(rows, lambda r: r.departamento_operativo, limit=8),
        "sinares": _grouped_dimension_bundle(rows, lambda r: r.dep_interviniente, limit=8),
        "zonas": _grouped_dimension_bundle(rows, lambda r: r.zona, limit=8),
    }
    years = [r["anio"] for r in comparativo_anual]
    chart_tipo_por_anio = {
        "categories": [str(y) for y in years],
        "series": [
            {"name": tipo, "values": [tipo_por_anio[tipo].get(y, 0) for y in years]}
            for tipo in sorted(tipo_por_anio.keys())
        ],
    }
    chart_mensual_por_anio = {
        "categories": _MONTH_LABELS,
        "series": [{"name": str(y), "values": mensual[y]} for y in years],
    }
    chart_trimestral_por_anio = {
        "categories": ["T1", "T2", "T3", "T4"],
        "series": [{"name": str(y), "values": trimestral[y]} for y in years],
    }
    chart_zonas = _sum_chart(list(zonas_count.items()), limit=15)
    chart_sinares = _sum_chart(list(sinares_count.items()), limit=15)
    chart_depops = _sum_chart(list(depops_count.items()), limit=15)
    chart_tipos = _sum_chart(list(tipos_count.items()))
    chart_localidades = _sum_chart(list(localidades_count.items()), limit=12)
    chart_secuestros = _sum_chart(list(secuestros_totales.items()))
    chart_dinero = _sum_chart(list(dinero_totales.items()))
    chart_personas = _sum_chart([(k, float(v)) for k, v in personas_chart.items()])

    return {
        "kpis": {
            "total": total,
            "allanamientos": allanamientos,
            "causas_allanadas": len(causas_allanadas),
            "procedimientos": procedimientos,
            "marihuana": round(secuestros_totales["Marihuana"], 2),
            "cocaina": round(secuestros_totales["Cocaina"], 2),
            "detenidos": detenidos_total,
            "identificados": identificados_total,
        },
        "comparativo_anual": comparativo_anual,
        "chart_anio_total": chart_anio_total,
        "chart_anio_allanamientos": chart_anio_allanamientos,
        "chart_anio_causas_allanadas": chart_anio_causas_allanadas,
        "chart_anio_procedimientos": chart_anio_procedimientos,
        "chart_anio_marihuana": chart_anio_marihuana,
        "chart_anio_cocaina": chart_anio_cocaina,
        "chart_anio_plantas": chart_anio_plantas,
        "chart_anio_plantines": chart_anio_plantines,
        "chart_anio_semillas": chart_anio_semillas,
        "chart_anio_hojas_coca": chart_anio_hojas_coca,
        "chart_anio_pesos": chart_anio_pesos,
        "chart_anio_detenidos": chart_anio_detenidos,
        "chart_anio_identificados": chart_anio_identificados,
        "chart_compare_depops": chart_compare_depops,
        "chart_compare_sinares": chart_compare_sinares,
        "chart_compare_zonas": chart_compare_zonas,
        "dimension_compare": dimension_compare,
        "chart_tipo_por_anio": chart_tipo_por_anio,
        "chart_mensual_por_anio": chart_mensual_por_anio,
        "chart_trimestral_por_anio": chart_trimestral_por_anio,
        "chart_zonas": chart_zonas,
        "chart_sinares": chart_sinares,
        "chart_depops": chart_depops,
        "chart_tipos": chart_tipos,
        "chart_localidades": chart_localidades,
        "chart_secuestros": chart_secuestros,
        "chart_dinero": chart_dinero,
        "chart_personas": chart_personas,
        "ranking_zonas": chart_zonas,
        "ranking_sinares": chart_sinares,
        "ranking_depops": chart_depops,
    }


def _serialize_export_row(row: AnalisisIntervencion) -> dict:
    return {
        "anio": row.anio or "",
        "causas_id": row.causas_id or "",
        "causas_interv_id": row.causas_interv_id or "",
        "interv_fecha": row.interv_fecha.strftime("%Y-%m-%d") if row.interv_fecha else "",
        "interv_hora": row.interv_hora.strftime("%H:%M:%S") if row.interv_hora else "",
        "tipo_interv_desc": row.tipo_interv_desc or "",
        "causa_escala": row.causa_escala or "",
        "causa_actividad": row.causa_actividad or "",
        "tipo_operativo": row.tipo_operativo or "",
        "zona": row.zona or "",
        "dep_interviniente": row.dep_interviniente or "",
        "departamento_operativo": row.departamento_operativo or "",
        "distrito": row.distrito or "",
        "dep_policial": row.dep_policial or "",
        "localidad_nombre": row.localidad_nombre or "",
        "barrios_nombre": row.barrios_nombre or "",
        "coordx": row.coordx if row.coordx is not None else "",
        "coordy": row.coordy if row.coordy is not None else "",
        "secuestro_marihuana": row.secuestro_marihuana or 0,
        "secuestro_cocaina": row.secuestro_cocaina or 0,
        "secuestro_plantas": row.secuestro_plantas or 0,
        "secuestro_plantines": row.secuestro_plantines or 0,
        "secuestro_semillas": row.secuestro_semillas or 0,
        "hojas_coca": row.hojas_coca or 0,
        "pesos_arg": row.pesos_arg or 0,
        "dolares": row.dolares or 0,
        "euro": row.euro or 0,
        "reales": row.reales or 0,
        "bolivianos": row.bolivianos or 0,
        "det_hombre_may": row.det_hombre_may or 0,
        "det_hombre_men": row.det_hombre_men or 0,
        "det_mujer_may": row.det_mujer_may or 0,
        "det_mujer_men": row.det_mujer_men or 0,
        "is_hombre_may": row.is_hombre_may or 0,
        "is_hombre_men": row.is_hombre_men or 0,
        "is_mujer_may": row.is_mujer_may or 0,
        "is_mujer_men": row.is_mujer_men or 0,
        "detenidos_total": _total_detenidos(row),
        "identificados_total": _total_identificados(row),
    }


@bp.before_request
@login_required
def _before():
    _ensure_schema()


@bp.route("/")
def index():
    if not _can_view():
        abort(403)
    return redirect(url_for("analisis_intervenciones.listado"))


@bp.route("/importar", methods=["GET", "POST"])
def importar():
    if not _can_import():
        abort(403)
    if request.method == "POST":
        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccione un CSV.", "warning")
            return redirect(url_for("analisis_intervenciones.importar"))
        if not f.filename.lower().endswith(".csv"):
            flash("Formato inválido. Subí un archivo .csv.", "danger")
            return redirect(url_for("analisis_intervenciones.importar"))
        result = _import_from_text(_decode_upload(f.read()))
        if result.get("error"):
            flash(result["error"], "danger")
        else:
            flash(
                (
                    f"Año {result['anio']} importado. "
                    f"Nuevas filas: {result['importados']}. "
                    f"Reemplazadas previas: {result['eliminados_previos']}. "
                    f"Omitidas: {result['omitidos']}. "
                    f"Duplicadas internas: {result['duplicados']}. "
                    "La carga quedó compartida para toda la dependencia."
                ),
                "success",
            )
        return redirect(url_for("analisis_intervenciones.importar"))

    total = _base_q().count()
    resumen_por_anio = (
        _base_q()
        .with_entities(
            AnalisisIntervencion.anio,
            db.func.count(AnalisisIntervencion.id),
            db.func.max(AnalisisIntervencion.fecha_importacion),
        )
        .group_by(AnalisisIntervencion.anio)
        .order_by(AnalisisIntervencion.anio.asc())
        .all()
    )
    anios_cargados = []
    for anio, cantidad, fecha_importacion in resumen_por_anio:
        ultima = (
            _base_q()
            .filter(AnalisisIntervencion.anio == anio)
            .order_by(AnalisisIntervencion.fecha_importacion.desc(), AnalisisIntervencion.id.desc())
            .first()
        )
        anios_cargados.append(
            {
                "anio": anio,
                "cantidad": cantidad,
                "fecha_importacion": fecha_importacion,
                "usuario": (ultima.usuario_creador.username if ultima and ultima.usuario_creador else "—"),
            }
        )
    return render_template(
        "analisis_intervenciones/importar.html",
        total=total,
        anios_cargados=anios_cargados,
        fmt_int=_fmt_int,
    )


@bp.route("/listado")
def listado():
    if not _can_view():
        abort(403)
    q = _apply_filters(_base_q())
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(200, max(20, request.args.get("per_page", type=int) or 50))
    total = q.count()
    rows = (
        q.order_by(
            AnalisisIntervencion.interv_fecha.desc(),
            AnalisisIntervencion.interv_hora.desc(),
            AnalisisIntervencion.id.desc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    pages = max(1, (total + per_page - 1) // per_page)
    args_no_page = request.args.to_dict(flat=False)
    args_no_page.pop("page", None)
    qs_no_page = urlencode(args_no_page, doseq=True)
    return render_template(
        "analisis_intervenciones/listado.html",
        rows=rows,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        qs_no_page=qs_no_page,
        filtros=_filter_options(),
        selected=_selected_filters(),
        can_import=_can_import(),
        can_export=_can_export(),
        can_dashboard=_can_dashboard(),
        total_detenidos=_total_detenidos,
        total_identificados=_total_identificados,
        fmt_int=_fmt_int,
    )


@bp.route("/dashboard")
def dashboard():
    if not _can_dashboard():
        abort(403)
    rows = _apply_filters(_base_q()).order_by(
        AnalisisIntervencion.interv_fecha.asc(),
        AnalisisIntervencion.interv_hora.asc(),
    ).all()
    datos = _dashboard_data(rows)
    return render_template(
        "analisis_intervenciones/dashboard.html",
        datos_json=json.dumps(datos),
        kpis=datos["kpis"],
        comparativo_anual=datos["comparativo_anual"],
        ranking_zonas=datos["ranking_zonas"],
        ranking_sinares=datos["ranking_sinares"],
        ranking_depops=datos["ranking_depops"],
        filtros=_filter_options(),
        selected=_selected_filters(),
        can_view=_can_view(),
        fmt_float=_fmt_float,
        fmt_int=_fmt_int,
    )


_CUADROS_PESTANAS = frozenset({"zona", "sinar", "departamento", "distrito", "clasificacion", "comparativo"})


@bp.route("/cuadros")
def cuadros():
    if not _can_dashboard():
        abort(403)
    pestana = (request.args.get("pestana") or "zona").strip().lower()
    if pestana not in _CUADROS_PESTANAS:
        pestana = "zona"
    args = request.args.to_dict(flat=False)
    args.pop("pestana", None)
    filter_qs = urlencode(args, doseq=True)

    rows = _apply_filters(_base_q()).order_by(
        AnalisisIntervencion.interv_fecha.asc(),
        AnalisisIntervencion.interv_hora.asc(),
    ).all()
    datos = _cuadros_data(rows)
    sel = _selected_filters()
    fd, fh = _resolve_period_dates(sel)
    subtitulo_periodo = ""
    if fd and fh:
        subtitulo_periodo = f"{fd.strftime('%d/%m/%Y')} al {fh.strftime('%d/%m/%Y')}"
    elif fd:
        subtitulo_periodo = f"Desde {fd.strftime('%d/%m/%Y')}"
    elif fh:
        subtitulo_periodo = f"Hasta {fh.strftime('%d/%m/%Y')}"
    return render_template(
        "analisis_intervenciones/cuadros.html",
        cuadros=datos,
        pestana=pestana,
        pestana_cuadros=pestana,
        filter_qs=filter_qs,
        filtros=_filter_options(),
        selected=sel,
        subtitulo_periodo=subtitulo_periodo,
        n_registros=len(rows),
        can_view=_can_view(),
        can_import=_can_import(),
        can_export=_can_export(),
        can_dashboard=_can_dashboard(),
        fmt_float=_fmt_float,
        fmt_int=_fmt_int,
    )


@bp.route("/detalle/<int:intervencion_id>")
def detalle(intervencion_id: int):
    if not _can_view():
        abort(403)
    row = _base_q().filter(AnalisisIntervencion.id == intervencion_id).first_or_404()
    secuestros = [
        ("Marihuana", _to_num(row.secuestro_marihuana)),
        ("Cocaina", _to_num(row.secuestro_cocaina)),
        ("Plantas", _to_num(row.secuestro_plantas)),
        ("Plantines", _to_num(row.secuestro_plantines)),
        ("Semillas", _to_num(row.secuestro_semillas)),
        ("Hojas de coca", _to_num(row.hojas_coca)),
    ]
    dinero = [
        ("Pesos Arg", _to_num(row.pesos_arg)),
        ("Dolares", _to_num(row.dolares)),
        ("Euro", _to_num(row.euro)),
        ("Reales", _to_num(row.reales)),
        ("Bolivianos", _to_num(row.bolivianos)),
    ]
    return render_template(
        "analisis_intervenciones/detalle.html",
        row=row,
        secuestros=secuestros,
        dinero=dinero,
        total_detenidos=_total_detenidos(row),
        total_identificados=_total_identificados(row),
        fmt_float=_fmt_float,
        fmt_int=_fmt_int,
        fecha_hora=_as_datetime(row.interv_fecha, row.interv_hora),
    )


@bp.route("/export.csv")
def export_csv():
    if not _can_export():
        abort(403)
    q = _apply_filters(_base_q()).order_by(
        AnalisisIntervencion.interv_fecha.desc(),
        AnalisisIntervencion.interv_hora.desc(),
    )
    out = StringIO()
    fieldnames = list(_serialize_export_row(AnalisisIntervencion()).keys())
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for row in q.yield_per(500):
        writer.writerow(_serialize_export_row(row))
    return Response(
        out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=analisis_intervenciones_filtrado.csv"},
    )


@bp.route("/export.xlsx")
def export_xlsx():
    if not _can_export():
        abort(403)
    q = _apply_filters(_base_q()).order_by(
        AnalisisIntervencion.interv_fecha.desc(),
        AnalisisIntervencion.interv_hora.desc(),
    )
    data = [_serialize_export_row(row) for row in q.yield_per(500)]
    bio = BytesIO()
    pd.DataFrame(data).to_excel(bio, index=False)
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=analisis_intervenciones_filtrado.xlsx"},
    )

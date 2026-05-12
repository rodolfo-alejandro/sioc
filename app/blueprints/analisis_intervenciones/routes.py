from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime, time
from io import BytesIO, StringIO
from urllib.parse import urlencode

import pandas as pd
from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, or_

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
    try:
        d = pd.to_datetime(v, errors="coerce", dayfirst=True)
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
    return {
        "q": _clean(request.args.get("q")) or "",
        "fecha_desde": _clean(request.args.get("fecha_desde")) or "",
        "fecha_hasta": _clean(request.args.get("fecha_hasta")) or "",
        "anios": _get_list_arg("anio[]"),
        "zonas": _get_list_arg("zona[]"),
        "sinares": _get_list_arg("sinar[]"),
        "departamentos_operativos": _get_list_arg("departamento_operativo[]"),
        "tipos_interv": _get_list_arg("tipo_interv[]"),
        "localidades": _get_list_arg("localidad[]"),
        "barrios": _get_list_arg("barrio[]"),
    }


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
    if s["fecha_desde"]:
        fd = _parse_date(s["fecha_desde"])
        if fd:
            q = q.filter(AnalisisIntervencion.interv_fecha >= fd)
    if s["fecha_hasta"]:
        fh = _parse_date(s["fecha_hasta"])
        if fh:
            q = q.filter(AnalisisIntervencion.interv_fecha <= fh)
    if s["anios"]:
        anios = [_parse_int(x) for x in s["anios"]]
        anios = [x for x in anios if x is not None]
        if anios:
            q = q.filter(AnalisisIntervencion.anio.in_(anios))
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

"""
Importación y listado básico de Base Operativa (Excel Capital/Interior).

Upsert por (unidad, ámbito, REGISTRO N° / CAP): reimportar no cambia IDs
ni pierde observaciones de auditoría.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from datetime import date, datetime, time, timedelta
from io import BytesIO

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app.blueprints.base_operativa import bp
from app.extensions import db
from app.models.base_operativa import BaseIdentificado, BaseProcedimiento

_XLS_EPOCH = datetime(1899, 12, 30)

_SHEETS = (
    ("BASE CAPITAL", "IDENTIFICADOS CAPITAL", "capital"),
    ("BASE INTERIOR", "IDENTIFICADOS INTERIOR", "interior"),
)


def _can_view() -> bool:
    return (
        current_user.is_authenticated
        and (
            current_user.has_permission("BASE_OPERATIVA_VIEW")
            or current_user.has_permission("AUDITORIA_VIEW")
            or getattr(current_user, "is_superadmin", False)
            or (getattr(current_user, "role", None) and current_user.role.name == "SUPERADMIN")
        )
    )


def _can_import() -> bool:
    return (
        current_user.is_authenticated
        and (
            current_user.has_permission("BASE_OPERATIVA_IMPORT")
            or getattr(current_user, "is_superadmin", False)
            or (getattr(current_user, "role", None) and current_user.role.name == "SUPERADMIN")
        )
    )


def _norm_header(h) -> str:
    if h is None:
        return ""
    s = str(h).replace("\xa0", " ").strip().upper()
    s = re.sub(r"\s+", " ", s)
    # normalizar grados / enie rotas
    s = s.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    s = s.replace("Ñ", "N").replace("º", "O").replace("°", "")
    return s


def _clean(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "null", "-"):
        return None
    return s


def _parse_float(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)
    s = str(v).strip().replace(".", "").replace(",", ".") if False else str(v).strip()
    s = s.replace(" ", "").replace("$", "")
    # AR-style: 1.234,56 → try comma decimal
    if re.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(v) -> int | None:
    f = _parse_float(v)
    if f is None:
        return None
    return int(round(f))


def _parse_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        try:
            return (_XLS_EPOCH + timedelta(days=float(v))).date()
        except Exception:
            return None
    s = str(v).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except Exception:
            continue
    return None


def _parse_time(v) -> time | None:
    if v is None or v == "":
        return None
    if isinstance(v, time):
        return v
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        # fracción de día Excel
        try:
            frac = float(v) % 1
            secs = int(round(frac * 86400))
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            return time(h % 24, m, s)
        except Exception:
            return None
    s = str(v).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except Exception:
            continue
    return None


def _get(row: dict, *aliases: str):
    for a in aliases:
        key = _norm_header(a)
        if key in row:
            return row[key]
    return None


def _row_dict(headers: list, values: list) -> dict:
    out = {}
    for i, h in enumerate(headers):
        nh = _norm_header(h)
        if not nh or nh.startswith("UNNAMED"):
            continue
        out[nh] = values[i] if i < len(values) else None
    return out


def _iter_sheet_rows(wb, sheet_name: str):
    """Yields dict rows; works with pyxlsb workbook or openpyxl."""
    # pyxlsb
    if hasattr(wb, "get_sheet"):
        with wb.get_sheet(sheet_name) as sheet:
            headers = None
            for row in sheet.rows():
                vals = [c.v for c in row]
                if headers is None:
                    headers = vals
                    continue
                if not any(v is not None and str(v).strip() for v in vals):
                    continue
                yield _row_dict(headers, vals)
        return

    # openpyxl / pandas ExcelFile fallback via pandas
    import pandas as pd

    df = pd.read_excel(wb, sheet_name=sheet_name, dtype=object)
    for _, series in df.iterrows():
        headers = list(df.columns)
        vals = [series[c] for c in headers]
        if not any(v is not None and str(v).strip() not in ("", "nan", "NaN") for v in vals):
            continue
        yield _row_dict(headers, vals)


def _map_procedimiento(row: dict, ambito: str) -> dict | None:
    reg = _clean(_get(row, "REGISTRO N", "REGISTRO NO", "REGISTRO NRO", "REGISTRO"))
    if not reg:
        # a veces queda REGISTRO N° normalizado raro
        for k, v in row.items():
            if k.startswith("REGISTRO"):
                reg = _clean(v)
                break
    if not reg:
        return None

    fecha = _parse_date(_get(row, "FECHA"))
    anio = fecha.year if fecha else datetime.utcnow().year

    delito = _clean(
        _get(
            row,
            "DELITO",
            "PROC. POR BOCA DE EXPENDIO, CONSUMO, COMERCIO, PROC NN, TRASPORTE, CODIGO ADUANERO",
            "WHATSAPP",
        )
    )
    # Interior: tipología en columna larga
    if not delito:
        for k, v in row.items():
            if "BOCA DE EXPENDIO" in k or k == "WHATSAPP":
                delito = _clean(v)
                if delito:
                    break

    of_int = _clean(_get(row, "OF INTERVINIENTE", "OFICIAL INTERVINIENTE"))
    return {
        "ambito": ambito,
        "registro_nro": reg.upper(),
        "nro_ap": _clean(_get(row, "N AP", "NO AP", "NRO AP")),
        "anio": anio,
        "sector": _clean(_get(row, "SECTOR")),
        "tipo_informe": _clean(_get(row, "TIPO DE INFORME")),
        "estado": _clean(_get(row, "ESTADO")),
        "lugar_proced": _clean(_get(row, "LUGAR DE PROCED.")),
        "causa_allanada": _clean(_get(row, "CAUSA ALLANADA", "CAUSAS ALLANADAS")),
        "cantidad_lugares": _parse_int(_get(row, "CANTIDAD DE LUGARES")),
        "barrio": _clean(_get(row, "BARRIO")),
        "localidad": _clean(_get(row, "LOCALIDAD")),
        "departamento": _clean(_get(row, "DEPARTAMENTO", "DEPARTAMENTOS", "DEPARTAMENTO.1")),
        "dependencia": _clean(_get(row, "DEPENDENCIA")),
        "dur": _clean(_get(row, "DUR")),
        "latitud": _parse_float(_get(row, "COORD.X (LATITUD)", "COORD.X(LATITUD)", "COORD.X")),
        "longitud": _parse_float(_get(row, "COORD.Y (LONGITUD)", "COORD.Y(LONGITUD)", "COORD.Y")),
        "fecha": fecha,
        "hora": _parse_time(_get(row, "HORA")),
        "dia_proc": _clean(_get(row, "DIA DE PROC.")),
        "mes": _clean(_get(row, "MES")),
        "semana": _clean(_get(row, "SEMANA")),
        "trimestre": _clean(_get(row, "TRIMESTRE EN ESTUDIO")),
        "of_interviniente": of_int,
        "sinar_interviniente": _clean(_get(row, "SINAR INTERVINIENTE")),
        "nro_expediente": _clean(_get(row, "N DE EXPEDIENTE", "NO DE EXPEDIENTE")),
        "micro_macro": _clean(_get(row, "MICRO-MACRO", "MICRO")),
        "tipo_operativo": _clean(_get(row, "TIPO DE OPERATIVO")),
        "delito": delito,
        "info_relev": _clean(_get(row, "INF. RELEV.", "WHATSAPP")),
        "dinares": _clean(_get(row, "DINARES")),
        "personas_ident_operativo": _parse_int(_get(row, "PERSONAS IDENTIFICADAS EN OPERATIVO")),
        "marihuana_grs": _parse_float(_get(row, "MARIHUANA GRS", "MARIHUANA GR")) or 0,
        "cocaina_grs": _parse_float(_get(row, "COCAINA GRS", "COCAINA    GRS")) or 0,
        "hoja_coca_kg": _parse_float(_get(row, "HOJA DE COCA (KG)", "HOJA DE COCA")) or 0,
        "plantas": _parse_float(_get(row, "PLANTAS DE CANNABIS SATIVA")) or 0,
        "plantines": _parse_float(_get(row, "PLANTINES DE CANNABIS SATIVA")) or 0,
        "semillas": _parse_float(_get(row, "SEMILLAS (UNIDADES)")) or 0,
        "pastillas_cant": _parse_float(_get(row, "PASTILLAS CANTIDAD")) or 0,
        "otras_sustancias": _clean(_get(row, "OTRAS SUSTANCIAS/PASTILLAS TIPO")),
        "pesos_arg": _parse_float(_get(row, "DINERO")) or 0,
        "dolares": _parse_float(_get(row, "DOLARES", "DOLARES")) or 0,
        "euro": _parse_float(_get(row, "EURO")) or 0,
        "reales": _parse_float(_get(row, "REALES")) or 0,
        "bolivianos": _parse_float(_get(row, "BOLIVIANO", "BOLIVIANOS")) or 0,
        "otras_divisas": _clean(_get(row, "OTRAS DIVISAS")),
        "total_detenidos_demorados": _parse_int(_get(row, "TOTAL DETENIDOS / DEMORADOS")) or 0,
        "total_detenidos": _parse_int(_get(row, "TOTAL DETENIDOS")) or 0,
        "total_demorados": _parse_int(_get(row, "TOTAL DEMORADOS")) or 0,
        "det_hombre_may": _parse_int(_get(row, "DET-APR. HOMBRE-MAYOR")) or 0,
        "det_hombre_men": _parse_int(_get(row, "DET-APR. HOMBRE-MENOR")) or 0,
        "det_mujer_may": _parse_int(_get(row, "DET-APR. MUJER-MAYOR")) or 0,
        "det_mujer_men": _parse_int(_get(row, "DET-APR. MUJER-MENOR")) or 0,
        "is_hombre_may": _parse_int(_get(row, "ID. SIMPLE HOMBRE-MAYOR")) or 0,
        "is_hombre_men": _parse_int(_get(row, "ID. SIMPLE HOMBRE-MENOR")) or 0,
        "is_mujer_may": _parse_int(_get(row, "ID. SIMPLE MUJER-MAYOR")) or 0,
        "is_mujer_men": _parse_int(_get(row, "ID. SIMPLE MUJER-MENOR")) or 0,
        "fiscalia": _clean(_get(row, "FISCALIA")),
        "juzgado": _clean(_get(row, "JUZGADO")),
        "otros_secuestros": _clean(_get(row, "OTROS SECUESTROS")),
        "dominios": _clean(_get(row, "DOMINIOS")),
    }


def _map_identificado(row: dict, ambito: str) -> dict | None:
    reg = None
    for k, v in row.items():
        if k.startswith("REGISTRO"):
            reg = _clean(v)
            break
    if not reg:
        return None
    nombre = _clean(_get(row, "NOMBRE Y APELLIDO"))
    dni_raw = _get(row, "DNI")
    dni = None
    if dni_raw is not None:
        if isinstance(dni_raw, float):
            dni = str(int(dni_raw)) if not math.isnan(dni_raw) else None
        else:
            dni = _clean(dni_raw)
    return {
        "ambito": ambito,
        "registro_nro": reg.upper(),
        "tipo": _clean(_get(row, "DETENIDO / DEMORADO")),
        "nombre": nombre,
        "edad": _parse_int(_get(row, "EDAD")),
        "fecha_nacimiento": _parse_date(_get(row, "FECHA DE NACIMIENTO")),
        "dni": dni,
        "domicilio": _clean(_get(row, "DOMICILIO")),
        "latitud": _parse_float(_get(row, "COORD.X (LATITUD)", "COORD.X")),
        "longitud": _parse_float(_get(row, "COORD.Y (LONGITUD)", "COORD.Y")),
        "barrio": _clean(_get(row, "BARRIO DEL ACUSADO")),
        "sector": _clean(_get(row, "SECTOR")),
        "ocupacion": _clean(_get(row, "OCUPACION")),
        "alias": _clean(_get(row, "ALIAS")),
        "localidad": _clean(_get(row, "LOCALIDAD DE RESIDENCIA")),
        "nacionalidad": _clean(_get(row, "NACIONALIDAD")),
    }


def _open_workbook(raw: bytes, filename: str):
    name = (filename or "").lower()
    if name.endswith(".xlsb"):
        import tempfile
        from pyxlsb import open_workbook

        tmp = tempfile.NamedTemporaryFile(suffix=".xlsb", delete=False)
        try:
            tmp.write(raw)
            tmp.close()
            return open_workbook(tmp.name), "pyxlsb", tmp.name
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise
    import pandas as pd

    return pd.ExcelFile(BytesIO(raw)), "pandas", None


def _sheet_names(wb, kind: str) -> list[str]:
    if kind == "pyxlsb":
        return list(wb.sheets)
    return list(wb.sheet_names)


def _import_file(raw: bytes, filename: str) -> dict:
    tmp_path = None
    wb = None
    try:
        try:
            wb, kind, tmp_path = _open_workbook(raw, filename)
        except Exception as exc:
            return {"error": f"No se pudo abrir el Excel: {exc}"}

        names = {_norm_header(n): n for n in _sheet_names(wb, kind)}
        now = datetime.utcnow()
        unidad_id = current_user.unidad_id

        procs_data: dict[tuple[str, str], dict] = {}
        idents_data: list[dict] = []
        skipped_proc = 0
        skipped_ident = 0

        for base_name, ident_name, ambito in _SHEETS:
            real_base = names.get(_norm_header(base_name))
            real_ident = names.get(_norm_header(ident_name))
            if not real_base:
                continue

            for row in _iter_sheet_rows(wb, real_base):
                mapped = _map_procedimiento(row, ambito)
                if not mapped:
                    skipped_proc += 1
                    continue
                key = (ambito, mapped["registro_nro"])
                procs_data[key] = mapped

            if real_ident:
                for row in _iter_sheet_rows(wb, real_ident):
                    mapped = _map_identificado(row, ambito)
                    if not mapped or not mapped.get("nombre"):
                        skipped_ident += 1
                        continue
                    idents_data.append(mapped)

        # Cerrar workbook antes del commit largo / borrado temp
        try:
            if wb is not None and hasattr(wb, "close"):
                wb.close()
        except Exception:
            pass
        wb = None

        if not procs_data:
            return {"error": "No se encontraron filas en BASE CAPITAL / BASE INTERIOR."}

        existing = {
            (r.ambito, r.registro_nro): r
            for r in BaseProcedimiento.query.filter(
                BaseProcedimiento.unidad_id == unidad_id,
                BaseProcedimiento.activo.is_(True),
            ).all()
        }

        created = 0
        updated = 0

        try:
            for key, data in procs_data.items():
                obj = existing.get(key)
                if obj is None:
                    obj = BaseProcedimiento(
                        unidad_id=unidad_id,
                        creado_por=current_user.id,
                        activo=True,
                        ambito=data["ambito"],
                        registro_nro=data["registro_nro"],
                    )
                    db.session.add(obj)
                    created += 1
                else:
                    updated += 1

                for field, value in data.items():
                    setattr(obj, field, value)
                obj.fecha_importacion = now
                obj.activo = True
                obj.updated_at = now

            db.session.flush()

            by_key = {
                (r.ambito, r.registro_nro): r
                for r in BaseProcedimiento.query.filter(
                    BaseProcedimiento.unidad_id == unidad_id,
                    BaseProcedimiento.activo.is_(True),
                ).all()
            }

            regs_in_file = {(d["ambito"], d["registro_nro"]) for d in idents_data}
            regs_in_file |= set(procs_data.keys())
            proc_ids = [by_key[k].id for k in regs_in_file if k in by_key]
            if proc_ids:
                BaseIdentificado.query.filter(
                    BaseIdentificado.unidad_id == unidad_id,
                    BaseIdentificado.procedimiento_id.in_(proc_ids),
                ).delete(synchronize_session=False)

            idents_by_reg: dict[tuple[str, str], list[dict]] = {}
            for d in idents_data:
                idents_by_reg.setdefault((d["ambito"], d["registro_nro"]), []).append(d)

            for key, items in idents_by_reg.items():
                proc = by_key.get(key)
                if not proc:
                    continue
                names_txt = []
                for d in items:
                    db.session.add(
                        BaseIdentificado(
                            unidad_id=unidad_id,
                            procedimiento_id=proc.id,
                            **d,
                        )
                    )
                    bit = d.get("nombre") or ""
                    if d.get("tipo"):
                        bit = f"{bit} ({d['tipo']})"
                    if d.get("dni"):
                        bit = f"{bit} DNI {d['dni']}"
                    if bit:
                        names_txt.append(bit)
                proc.acusados_texto = " | ".join(names_txt) if names_txt else None

            for key, proc in by_key.items():
                if key in procs_data and key not in idents_by_reg:
                    proc.acusados_texto = None

            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return {"error": f"Error al guardar: {exc}"}

        return {
            "created": created,
            "updated": updated,
            "identificados": len(idents_data),
            "skipped_proc": skipped_proc,
            "skipped_ident": skipped_ident,
            "total": created + updated,
        }
    finally:
        try:
            if wb is not None and hasattr(wb, "close"):
                wb.close()
        except Exception:
            pass
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _ensure_tables():
    from sqlalchemy import inspect, text

    insp = inspect(db.engine)
    if "base_operativa_procedimientos" not in insp.get_table_names():
        BaseProcedimiento.__table__.create(db.engine, checkfirst=True)
    if "base_operativa_identificados" not in insp.get_table_names():
        BaseIdentificado.__table__.create(db.engine, checkfirst=True)


@bp.route("/")
@login_required
def index():
    if not _can_view():
        flash("No tenés permiso para ver Base Operativa.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_tables()
    total = (
        BaseProcedimiento.query.filter(
            BaseProcedimiento.unidad_id == current_user.unidad_id,
            BaseProcedimiento.activo.is_(True),
        ).count()
    )
    por_ambito = (
        db.session.query(BaseProcedimiento.ambito, func.count(BaseProcedimiento.id))
        .filter(
            BaseProcedimiento.unidad_id == current_user.unidad_id,
            BaseProcedimiento.activo.is_(True),
        )
        .group_by(BaseProcedimiento.ambito)
        .all()
    )
    ultima = (
        BaseProcedimiento.query.filter(
            BaseProcedimiento.unidad_id == current_user.unidad_id,
        )
        .order_by(BaseProcedimiento.fecha_importacion.desc())
        .first()
    )
    return render_template(
        "base_operativa/importar.html",
        total=total,
        por_ambito=dict(por_ambito),
        ultima=ultima,
        can_import=_can_import(),
    )


@bp.route("/importar", methods=["GET", "POST"])
@login_required
def importar():
    if not _can_import():
        flash("No tenés permiso para importar Base Operativa.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_tables()

    if request.method == "POST":
        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccioná un archivo Excel (.xlsb / .xlsx).", "warning")
            return redirect(url_for("base_operativa.importar"))
        filename = secure_filename(f.filename)
        if not filename.lower().endswith((".xlsb", ".xlsx", ".xlsm")):
            flash("Formato no soportado. Usá .xlsb o .xlsx.", "danger")
            return redirect(url_for("base_operativa.importar"))
        raw = f.read()
        if not raw:
            flash("Archivo vacío.", "warning")
            return redirect(url_for("base_operativa.importar"))

        res = _import_file(raw, filename)
        if res.get("error"):
            flash(res["error"], "danger")
        else:
            flash(
                f"Import OK: {res['created']} nuevos, {res['updated']} actualizados, "
                f"{res['identificados']} identificados. "
                f"Auditoría intacta (upsert por CAP).",
                "success",
            )
        return redirect(url_for("base_operativa.importar"))

    total = (
        BaseProcedimiento.query.filter(
            BaseProcedimiento.unidad_id == current_user.unidad_id,
            BaseProcedimiento.activo.is_(True),
        ).count()
    )
    por_ambito = (
        db.session.query(BaseProcedimiento.ambito, func.count(BaseProcedimiento.id))
        .filter(
            BaseProcedimiento.unidad_id == current_user.unidad_id,
            BaseProcedimiento.activo.is_(True),
        )
        .group_by(BaseProcedimiento.ambito)
        .all()
    )
    ultima = (
        BaseProcedimiento.query.filter(
            BaseProcedimiento.unidad_id == current_user.unidad_id,
        )
        .order_by(BaseProcedimiento.fecha_importacion.desc())
        .first()
    )
    return render_template(
        "base_operativa/importar.html",
        total=total,
        por_ambito=dict(por_ambito),
        ultima=ultima,
        can_import=True,
    )

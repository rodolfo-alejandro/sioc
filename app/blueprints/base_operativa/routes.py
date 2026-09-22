"""
Importación y listado básico de Base Operativa (Excel Capital/Interior).

Upsert por (unidad, ámbito, REGISTRO N° / CAP): reimportar no cambia IDs
ni pierde observaciones de auditoría.

El import corre en un hilo en background para no clavar Gunicorn.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import traceback
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app.blueprints.base_operativa import bp
from app.extensions import db
from app.models.base_operativa import BaseIdentificado, BaseProcedimiento

_log = logging.getLogger(__name__)

_XLS_EPOCH = datetime(1899, 12, 30)

_SHEETS = (
    ("BASE CAPITAL", "IDENTIFICADOS CAPITAL", "capital"),
    ("BASE INTERIOR", "IDENTIFICADOS INTERIOR", "interior"),
)

_JOB_DIR = Path("/tmp/sioc_base_operativa_jobs")
_import_lock = threading.Lock()


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


def _job_path(unidad_id: int) -> Path:
    _JOB_DIR.mkdir(parents=True, exist_ok=True)
    return _JOB_DIR / f"unidad_{unidad_id}.json"


def _write_job(unidad_id: int, data: dict) -> None:
    data = dict(data)
    data["updated_at"] = datetime.utcnow().isoformat() + "Z"
    path = _job_path(unidad_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_job(unidad_id: int) -> dict | None:
    path = _job_path(unidad_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _norm_header(h) -> str:
    if h is None:
        return ""
    s = str(h).replace("\xa0", " ").strip().upper()
    s = re.sub(r"\s+", " ", s)
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
    s = str(v).strip().replace(" ", "").replace("$", "")
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
    n = min(len(headers), len(values))
    for i in range(n):
        nh = _norm_header(headers[i])
        if not nh or nh.startswith("UNNAMED"):
            continue
        out[nh] = values[i]
    return out


def _iter_sheet_rows(wb, sheet_name: str, max_cols: int = 120):
    """Yields dict rows. Truncates wide sparse Excel ranges (crítico en .xlsb)."""
    if hasattr(wb, "get_sheet"):
        with wb.get_sheet(sheet_name) as sheet:
            headers = None
            header_len = 0
            empty_streak = 0
            for row in sheet.rows():
                if headers is None:
                    vals = []
                    for i, c in enumerate(row):
                        if i >= max_cols:
                            break
                        vals.append(c.v)
                    while vals and vals[-1] is None:
                        vals.pop()
                    headers = vals
                    header_len = len(headers) or 1
                    continue

                vals = []
                for i, c in enumerate(row):
                    if i >= header_len:
                        break
                    vals.append(c.v)

                if not any(v is not None and str(v).strip() for v in vals):
                    empty_streak += 1
                    if empty_streak >= 50:
                        break
                    continue
                empty_streak = 0
                yield _row_dict(headers, vals)
        return

    import pandas as pd

    df = pd.read_excel(wb, sheet_name=sheet_name, dtype=object, usecols=range(0, max_cols))
    headers = list(df.columns)
    for _, series in df.iterrows():
        vals = [series[c] for c in headers]
        if not any(v is not None and str(v).strip() not in ("", "nan", "NaN") for v in vals):
            continue
        yield _row_dict(headers, vals)


def _map_procedimiento(row: dict, ambito: str) -> dict | None:
    reg = _clean(_get(row, "REGISTRO N", "REGISTRO NO", "REGISTRO NRO", "REGISTRO"))
    if not reg:
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
        "dolares": _parse_float(_get(row, "DOLARES")) or 0,
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


def _open_workbook(path: str | Path):
    name = str(path).lower()
    if name.endswith(".xlsb"):
        from pyxlsb import open_workbook

        return open_workbook(str(path)), "pyxlsb"
    import pandas as pd

    return pd.ExcelFile(str(path)), "pandas"


def _sheet_names(wb, kind: str) -> list[str]:
    if kind == "pyxlsb":
        return list(wb.sheets)
    return list(wb.sheet_names)


def _import_from_path(path: str | Path, unidad_id: int, user_id: int) -> dict:
    wb = None
    try:
        try:
            wb, kind = _open_workbook(path)
        except Exception as exc:
            return {"error": f"No se pudo abrir el Excel: {exc}"}

        names = {_norm_header(n): n for n in _sheet_names(wb, kind)}
        now = datetime.utcnow()

        procs_data: dict[tuple[str, str], dict] = {}
        idents_data: list[dict] = []
        skipped_proc = 0
        skipped_ident = 0

        for base_name, ident_name, ambito in _SHEETS:
            real_base = names.get(_norm_header(base_name))
            real_ident = names.get(_norm_header(ident_name))
            if not real_base:
                continue

            _write_job(
                unidad_id,
                {
                    "status": "running",
                    "message": f"Leyendo {base_name}…",
                    "filename": Path(path).name,
                },
            )
            max_cols = 110 if "BASE" in base_name.upper() else 20
            for row in _iter_sheet_rows(wb, real_base, max_cols=max_cols):
                mapped = _map_procedimiento(row, ambito)
                if not mapped:
                    skipped_proc += 1
                    continue
                procs_data[(ambito, mapped["registro_nro"])] = mapped

            if real_ident:
                _write_job(
                    unidad_id,
                    {
                        "status": "running",
                        "message": f"Leyendo {ident_name}…",
                        "filename": Path(path).name,
                    },
                )
                for row in _iter_sheet_rows(wb, real_ident, max_cols=20):
                    mapped = _map_identificado(row, ambito)
                    if not mapped or not mapped.get("nombre"):
                        skipped_ident += 1
                        continue
                    idents_data.append(mapped)

        try:
            if wb is not None and hasattr(wb, "close"):
                wb.close()
        except Exception:
            pass
        wb = None

        if not procs_data:
            return {"error": "No se encontraron filas en BASE CAPITAL / BASE INTERIOR."}

        _write_job(
            unidad_id,
            {
                "status": "running",
                "message": f"Guardando {len(procs_data)} procedimientos…",
                "filename": Path(path).name,
            },
        )

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
                        creado_por=user_id,
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


def _bg_import(app, path: Path, unidad_id: int, user_id: int, filename: str) -> None:
    with app.app_context():
        acquired = _import_lock.acquire(blocking=False)
        if not acquired:
            _write_job(
                unidad_id,
                {
                    "status": "error",
                    "message": "Ya hay una importación en curso. Esperá a que termine.",
                    "filename": filename,
                },
            )
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            return
        try:
            _write_job(
                unidad_id,
                {
                    "status": "running",
                    "message": "Procesando Excel (puede tardar varios minutos)…",
                    "filename": filename,
                },
            )
            res = _import_from_path(path, unidad_id, user_id)
            if res.get("error"):
                _write_job(
                    unidad_id,
                    {"status": "error", "message": res["error"], "filename": filename},
                )
            else:
                _write_job(
                    unidad_id,
                    {
                        "status": "ok",
                        "message": (
                            f"Listo: {res['created']} nuevos, {res['updated']} actualizados, "
                            f"{res['identificados']} identificados."
                        ),
                        "filename": filename,
                        "result": res,
                    },
                )
        except Exception as exc:
            _log.exception("Import Base Operativa falló")
            _write_job(
                unidad_id,
                {
                    "status": "error",
                    "message": f"Error inesperado: {exc}",
                    "filename": filename,
                    "trace": traceback.format_exc()[-1500:],
                },
            )
        finally:
            _import_lock.release()
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def _ensure_tables():
    from sqlalchemy import inspect

    insp = inspect(db.engine)
    if "base_operativa_procedimientos" not in insp.get_table_names():
        BaseProcedimiento.__table__.create(db.engine, checkfirst=True)
    if "base_operativa_identificados" not in insp.get_table_names():
        BaseIdentificado.__table__.create(db.engine, checkfirst=True)


def _page_stats():
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
    return total, dict(por_ambito), ultima


@bp.route("/")
@login_required
def index():
    return redirect(url_for("base_operativa.importar"))


@bp.route("/importar", methods=["GET", "POST"])
@login_required
def importar():
    if request.method == "POST":
        if not _can_import():
            flash("No tenés permiso para importar Base Operativa.", "warning")
            return redirect(url_for("core.dashboard"))
        _ensure_tables()

        job = _read_job(current_user.unidad_id)
        if job and job.get("status") == "running":
            flash("Ya hay una importación en curso. Esperá a que termine.", "warning")
            return redirect(url_for("base_operativa.importar"))

        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccioná un archivo Excel (.xlsb / .xlsx).", "warning")
            return redirect(url_for("base_operativa.importar"))
        filename = secure_filename(f.filename) or "base.xlsb"
        if not filename.lower().endswith((".xlsb", ".xlsx", ".xlsm")):
            flash("Formato no soportado. Usá .xlsb o .xlsx.", "danger")
            return redirect(url_for("base_operativa.importar"))

        upload_dir = _JOB_DIR / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"u{current_user.unidad_id}_{int(datetime.utcnow().timestamp())}_{filename}"
        f.save(str(dest))

        if dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            flash("Archivo vacío.", "warning")
            return redirect(url_for("base_operativa.importar"))

        _write_job(
            current_user.unidad_id,
            {
                "status": "running",
                "message": "Archivo recibido. Procesando en segundo plano…",
                "filename": filename,
            },
        )

        app = current_app._get_current_object()
        th = threading.Thread(
            target=_bg_import,
            args=(app, dest, current_user.unidad_id, current_user.id, filename),
            daemon=True,
        )
        th.start()

        flash(
            "Importación iniciada en segundo plano. Podés seguir usando SIOC; "
            "esta página se actualiza sola cuando termine (el .xlsb puede tardar varios minutos).",
            "info",
        )
        return redirect(url_for("base_operativa.importar"))

    if not _can_view() and not _can_import():
        flash("No tenés permiso para ver Base Operativa.", "warning")
        return redirect(url_for("core.dashboard"))
    _ensure_tables()
    total, por_ambito, ultima = _page_stats()
    job = _read_job(current_user.unidad_id)
    return render_template(
        "base_operativa/importar.html",
        total=total,
        por_ambito=por_ambito,
        ultima=ultima,
        can_import=_can_import(),
        job=job,
    )


@bp.route("/importar/estado")
@login_required
def importar_estado():
    if not _can_view() and not _can_import():
        return {"error": "sin permiso"}, 403
    job = _read_job(current_user.unidad_id) or {"status": "idle"}
    return job

"""
Lógica de negocio: importaciones padrón/inscriptos, validación y asistencia.
"""
from __future__ import annotations

import io
import os
import re
import secrets
import string
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from flask import Request, Response
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.capacitaciones import (
    EventoCapacitacion,
    InscriptoEvento,
    MomentoAsistencia,
    PadronDrogas,
    RegistroAsistencia,
)


def normalize_dni(raw: str | None) -> tuple[str, str]:
    """Devuelve (dni_key solo dígitos, dni display limpio)."""
    if raw is None:
        return "", ""
    if isinstance(raw, float):
        if pd.isna(raw):
            return "", ""
        try:
            if raw == int(raw):
                raw = int(raw)
        except Exception:
            pass
    if isinstance(raw, int):
        raw = str(raw)
    s = str(raw).strip()
    # Excel/pandas suele devolver "24338994.0"
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    digits = "".join(re.findall(r"\d", s))
    return digits, s


def is_dni_plausible(dni_key: str) -> bool:
    return 7 <= len(dni_key) <= 9


def generate_codigo_momento() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def generate_token_publico_momento() -> str:
    """Token opaco para URL/QR de asistencia pública (sin login)."""
    return secrets.token_urlsafe(32)


def generate_token_publico_unique(exclude_momento_id: int | None = None) -> str:
    """Genera token único para cap_momentos_asistencia.token_publico."""
    for _ in range(40):
        t = generate_token_publico_momento()
        q = MomentoAsistencia.query.filter_by(token_publico=t)
        if exclude_momento_id is not None:
            q = q.filter(MomentoAsistencia.id != exclude_momento_id)
        if not q.first():
            return t
    raise RuntimeError("No se pudo generar token público único")


def ensure_capacitaciones_db() -> None:
    """
    Crea tablas del módulo y completa columna token_publico en momentos (despliegues sin migrate).
    """
    from sqlalchemy import inspect, text

    _ = (PadronDrogas, EventoCapacitacion, InscriptoEvento, MomentoAsistencia, RegistroAsistencia)
    db.create_all()

    insp = inspect(db.engine)
    try:
        cols = [c["name"] for c in insp.get_columns("cap_momentos_asistencia")]
    except Exception:
        return

    if "token_publico" not in cols:
        db.session.execute(
            text(
                "ALTER TABLE cap_momentos_asistencia ADD COLUMN token_publico VARCHAR(64) NULL"
            )
        )
        db.session.commit()

    q = MomentoAsistencia.query.filter(
        (MomentoAsistencia.token_publico.is_(None)) | (MomentoAsistencia.token_publico == "")
    )
    for m in q.all():
        m.token_publico = generate_token_publico_unique(exclude_momento_id=m.id)
    db.session.commit()

    insp2 = inspect(db.engine)
    idx_names = {i.get("name") for i in insp2.get_indexes("cap_momentos_asistencia")}
    if "uq_cap_momento_token_publico" not in idx_names:
        try:
            db.session.execute(
                text(
                    "CREATE UNIQUE INDEX uq_cap_momento_token_publico ON cap_momentos_asistencia (token_publico)"
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()


def qr_svg_response_for_url(url: str) -> Response:
    """Devuelve Response SVG con QR (dependencia segno)."""
    import io

    import segno

    q = segno.make(url, error="m")
    out = io.StringIO()
    q.save(out, kind="svg", scale=3, border=2)
    return Response(out.getvalue(), mimetype="image/svg+xml; charset=utf-8")


def qr_png_response_for_url(url: str) -> Response:
    """PNG para <img> y compatibilidad (segno + Pillow)."""
    import io

    import segno

    q = segno.make(url, error="m")
    out = io.BytesIO()
    q.save(out, kind="png", scale=5, border=2)
    out.seek(0)
    return Response(
        out.getvalue(),
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _read_upload_to_dataframe(file_storage) -> pd.DataFrame:
    name = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if name.endswith(".csv"):
        best_df = None
        best_ncols = 0
        for sep in (";", ",", "\t"):
            for enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    df_try = pd.read_csv(io.BytesIO(raw), encoding=enc, sep=sep)
                    n = len(df_try.columns)
                    if n > best_ncols:
                        best_df = df_try
                        best_ncols = n
                except Exception:
                    continue
        if best_df is not None and best_ncols > 1:
            return best_df
        if best_df is not None:
            return best_df
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except Exception:
                continue
        return pd.read_csv(io.BytesIO(raw))
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    raise ValueError("Formato no soportado. Use CSV o XLSX.")


def _norm_col(c: str) -> str:
    s = str(c).strip().lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s)


def _map_row_columns(df: pd.DataFrame, synonym_map: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Devuelve lista de dicts con claves canónicas según mapa de sinónimos."""
    col_map: dict[str, str] = {}
    for col in df.columns:
        n = _norm_col(col)
        for canonical, syns in synonym_map.items():
            if n in [_norm_col(s) for s in syns] or n == _norm_col(canonical):
                col_map[col] = canonical
                break
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        out: dict[str, Any] = {}
        for orig, can in col_map.items():
            v = row.get(orig)
            if pd.isna(v):
                out[can] = None
            else:
                out[can] = v
        rows.append(out)
    return rows


PADRON_SYNONYMS = {
    "legajo": ["legajo", "nro legajo", "n° legajo", "nro_legajo", "datospers legajo", "datos pers legajo"],
    "apellido": ["apellido", "apellidos"],
    "nombre": ["nombre", "nombres"],
    "dni": [
        "dni",
        "documento",
        "d.n.i.",
        "dni n°",
        "nro documento",
        "rrhh datospers nrodoc",
        "datospers nrodoc",
        "nrodoc",
        "nro doc",
        "documento nacional",
    ],
    "grado": ["grado", "jerarquía", "jerarquia", "rango", "tipogrados desc", "tipo grados desc", "tipo grado"],
    "sexo": ["sexo", "genero", "género"],
    "dependencia": [
        "dependencia",
        "reparticion",
        "repartición",
        "unidad",
        "destino",
        "organismos descripcion",
        "organismo descripcion",
        "descripcion organismo",
        "organismos derecho",
        "organismos izquierdo",
    ],
    "organismo": ["organismo", "fuerza", "institución", "institucion", "organismos derecho"],
}

INSCRIPTO_SYNONYMS = {
    "apellido_nombre": [
        "apellido y nombre",
        "apellido_nombre",
        "nombre y apellido",
        "nombre completo",
        "nombre",
    ],
    "dni": [
        "dni",
        "documento",
        "d.n.i.",
        "d.n.i",
        "d. n. i",
        "d. n. i.",
        "documento nacional",
        "nro documento",
        "nro doc",
        "numero de documento",
        "número de documento",
        "cédula",
        "cedula",
        "n° documento",
    ],
    "telefono": ["telefono", "teléfono", "celular", "whatsapp", "phone", "tel"],
    "correo": ["correo", "email", "e-mail", "mail", "correo electronico", "correo electrónico", "e mail"],
    "dependencia_declarada": ["dependencia", "reparticion", "repartición", "unidad", "comisaría", "comisaria"],
    "cargo": ["cargo", "puesto", "función", "funcion"],
    "modalidad_declarada": ["modalidad", "asistencia", "virtual/presencial"],
    "comentarios": ["comentarios", "observaciones", "nota", "notas"],
}


def _header_compact(s: str) -> str:
    """Quita puntuación/espacios para comparar encabezados (ej. d.n.i → dni)."""
    return re.sub(r"[.\s_\-]", "", str(s).strip().lower())


def _heuristic_rename_dni_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Si ningún encabezado matchea la clave canónica «dni», intenta detectar la columna
    por nombre (UCASAL, Google Forms: «D.N.I», «Documento», etc.).
    """
    syn_dni = INSCRIPTO_SYNONYMS.get("dni", [])
    for col in df.columns:
        n = _norm_col(col)
        if n in [_norm_col(s) for s in syn_dni] or n == _norm_col("dni"):
            return df
        hc = _header_compact(col)
        if hc in ("dni", "dn", "documento", "nrodoc", "documentonacional", "cedula", "cédula", "numerodocumento"):
            return df.rename(columns={col: "dni"})
    for col in list(df.columns):
        hc = _header_compact(col)
        if "dni" in hc or hc.endswith("doc") or "documento" in hc:
            return df.rename(columns={col: "dni"})
    return df


def _map_inscripto_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    df2 = _heuristic_rename_dni_column(df.copy())
    return _map_row_columns(df2, INSCRIPTO_SYNONYMS)


def importar_padron_drogas(
    file_storage,
    origen_archivo: str,
    es_padron_completo: bool,
) -> dict[str, Any]:
    """
    Importa padrón desde CSV/XLSX.
    Retorna estadísticas: leidos, insertados, actualizados, invalidos, desactivados.
    """
    df = _read_upload_to_dataframe(file_storage)
    rows = _map_row_columns(df, PADRON_SYNONYMS)
    stats = {
        "leidos": len(rows),
        "insertados": 0,
        "actualizados": 0,
        "invalidos": 0,
        "desactivados": 0,
    }
    seen_keys: set[str] = set()
    now = datetime.utcnow()

    for r in rows:
        dni_key, dni_show = normalize_dni(r.get("dni"))
        if not dni_key or not is_dni_plausible(dni_key):
            stats["invalidos"] += 1
            continue
        seen_keys.add(dni_key)
        existing = PadronDrogas.query.filter_by(dni_key=dni_key).first()
        payload = {
            "legajo": _clean_str(r.get("legajo")),
            "apellido": _clean_str(r.get("apellido")),
            "nombre": _clean_str(r.get("nombre")),
            "dni": dni_show or dni_key,
            "grado": _clean_str(r.get("grado")),
            "sexo": _clean_str(r.get("sexo")),
            "dependencia": _clean_str(r.get("dependencia")),
            "organismo": _clean_str(r.get("organismo")),
            "activo": True,
            "fecha_importacion": now,
            "fecha_actualizacion": now,
            "origen_archivo": origen_archivo[:500] if origen_archivo else None,
        }
        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
            stats["actualizados"] += 1
        else:
            db.session.add(PadronDrogas(dni_key=dni_key, **payload))
            stats["insertados"] += 1

    if es_padron_completo and seen_keys:
        q = PadronDrogas.query.filter(~PadronDrogas.dni_key.in_(seen_keys), PadronDrogas.activo.is_(True))
        for p in q.all():
            p.activo = False
            p.fecha_actualizacion = now
            stats["desactivados"] += 1

    db.session.commit()
    return stats


def _clean_str(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def importar_inscriptos_evento(evento_id: int, file_storage, origen: str) -> dict[str, Any]:
    df = _read_upload_to_dataframe(file_storage)
    rows = _map_inscripto_rows(df)
    stats = {
        "total": len(rows),
        "validado_drogas": 0,
        "externo": 0,
        "dni_invalido": 0,
        "duplicado": 0,
        "insertados": 0,
        "actualizados": 0,
    }
    dni_seen: set[str] = set()
    for idx, r in enumerate(rows):
        dni_key, dni_show = normalize_dni(r.get("dni"))
        apellido_nombre = _clean_str(r.get("apellido_nombre")) or ""

        if not dni_key or not is_dni_plausible(dni_key):
            fake_key = f"__inv_{evento_id}_{idx}__"
            ins = InscriptoEvento(
                evento_id=evento_id,
                apellido_nombre=apellido_nombre,
                dni=dni_show,
                dni_key=fake_key,
                telefono=_clean_str(r.get("telefono")),
                correo=_clean_str(r.get("correo")),
                dependencia_declarada=_clean_str(r.get("dependencia_declarada")),
                cargo=_clean_str(r.get("cargo")),
                modalidad_declarada=_clean_str(r.get("modalidad_declarada")),
                comentarios=_clean_str(r.get("comentarios")),
                pertenece_drogas=False,
                padron_drogas_id=None,
                estado_validacion="dni_invalido",
                observacion_validacion="DNI inválido o vacío",
            )
            db.session.add(ins)
            stats["dni_invalido"] += 1
            stats["insertados"] += 1
            continue

        if dni_key in dni_seen:
            stats["duplicado"] += 1
            continue
        dni_seen.add(dni_key)

        pad = PadronDrogas.query.filter_by(dni_key=dni_key, activo=True).first()
        pertenece = pad is not None
        est_val = "validado_drogas" if pertenece else "externo"
        obs = None
        if pertenece:
            stats["validado_drogas"] += 1
        else:
            stats["externo"] += 1

        existing = InscriptoEvento.query.filter_by(evento_id=evento_id, dni_key=dni_key).first()
        payload = {
            "apellido_nombre": apellido_nombre or (_compose_nombre_padron(pad) if pad else apellido_nombre),
            "dni": dni_show or dni_key,
            "telefono": _clean_str(r.get("telefono")),
            "correo": _clean_str(r.get("correo")),
            "dependencia_declarada": _clean_str(r.get("dependencia_declarada")),
            "cargo": _clean_str(r.get("cargo")),
            "modalidad_declarada": _clean_str(r.get("modalidad_declarada")),
            "comentarios": _clean_str(r.get("comentarios")),
            "pertenece_drogas": pertenece,
            "padron_drogas_id": pad.id if pad else None,
            "estado_validacion": est_val,
            "observacion_validacion": obs,
        }
        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
            stats["actualizados"] += 1
        else:
            db.session.add(InscriptoEvento(evento_id=evento_id, dni_key=dni_key, **payload))
            stats["insertados"] += 1

    db.session.commit()
    return stats


def _compose_nombre_padron(p: PadronDrogas) -> str:
    parts = [_clean_str(p.apellido), _clean_str(p.nombre)]
    return " ".join(x for x in parts if x) or ""


def _cap_event_tz() -> ZoneInfo:
    """Zona horaria para vigencia de momentos (formulario guarda hora local sin TZ)."""
    name = (os.environ.get("CAPACITACIONES_TZ") or os.environ.get("APP_TIMEZONE") or "America/Argentina/Salta").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Argentina/Buenos_Aires")


def _moment_dt_in_event_tz(dt: datetime | None, tz: ZoneInfo) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(tz)
    return dt.replace(tzinfo=tz)


def registrar_asistencia(
    evento: EventoCapacitacion,
    momento: MomentoAsistencia,
    dni_raw: str,
    codigo_raw: str,
    request: Request,
) -> tuple[bool, str]:
    """
    Registra intento de asistencia. Siempre persiste registro; valido indica éxito.
    Retorna (exito, mensaje_codigo).
    """
    tz = _cap_event_tz()
    now_local = datetime.now(tz)
    apertura = _moment_dt_in_event_tz(momento.fecha_apertura, tz)
    cierre = _moment_dt_in_event_tz(momento.fecha_cierre, tz)
    stamp_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    dni_key, _ = normalize_dni(dni_raw)
    codigo = (codigo_raw or "").strip().upper()
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64]
    ua = (request.headers.get("User-Agent") or "")[:500]

    # No incluir motivo ni inscripto_id aquí: al hacer RegistroAsistencia(**base_kw, motivo=…)
    # Python 3 falla con "got multiple values" si la clave ya venía en el dict.
    base_kw = dict(
        evento_id=evento.id,
        momento_id=momento.id,
        dni_ingresado=dni_raw,
        dni_key=dni_key or None,
        codigo_ingresado=codigo,
        fecha_hora=stamp_utc,
        ip=ip,
        user_agent=ua,
        valido=False,
    )

    if not momento.activo:
        r = RegistroAsistencia(**base_kw, motivo="momento_inactivo")
        db.session.add(r)
        db.session.commit()
        return False, "momento_inactivo"

    if apertura and now_local < apertura:
        r = RegistroAsistencia(**base_kw, motivo="fuera_horario")
        db.session.add(r)
        db.session.commit()
        return False, "fuera_horario"
    if cierre and now_local > cierre:
        r = RegistroAsistencia(**base_kw, motivo="fuera_horario")
        db.session.add(r)
        db.session.commit()
        return False, "fuera_horario"

    if codigo != (momento.codigo_validacion or "").strip().upper():
        r = RegistroAsistencia(**base_kw, motivo="codigo_incorrecto")
        db.session.add(r)
        db.session.commit()
        return False, "codigo_incorrecto"

    if not dni_key:
        r = RegistroAsistencia(**base_kw, motivo="dni_no_inscripto")
        db.session.add(r)
        db.session.commit()
        return False, "dni_no_inscripto"

    ins = InscriptoEvento.query.filter_by(evento_id=evento.id, dni_key=dni_key).first()
    if not ins:
        r = RegistroAsistencia(**base_kw, motivo="dni_no_inscripto")
        db.session.add(r)
        db.session.commit()
        return False, "dni_no_inscripto"

    prev = (
        RegistroAsistencia.query.filter_by(
            evento_id=evento.id,
            momento_id=momento.id,
            inscripto_id=ins.id,
            valido=True,
        ).first()
    )
    if prev:
        r = RegistroAsistencia(**base_kw, inscripto_id=ins.id, motivo="ya_registrado")
        db.session.add(r)
        db.session.commit()
        return False, "ya_registrado"

    r = RegistroAsistencia(
        evento_id=evento.id,
        momento_id=momento.id,
        inscripto_id=ins.id,
        dni_ingresado=dni_raw,
        dni_key=dni_key,
        codigo_ingresado=codigo,
        fecha_hora=stamp_utc,
        ip=ip,
        user_agent=ua,
        valido=True,
        motivo="ok",
    )
    db.session.add(r)
    db.session.commit()
    return True, "ok"


def resultado_final_asistencia(inscripto: InscriptoEvento, momentos_ordenados: list[MomentoAsistencia]) -> str:
    mids = [m.id for m in momentos_ordenados]
    if not mids:
        return "N/A"
    ok = 0
    for m in momentos_ordenados:
        hit = (
            RegistroAsistencia.query.filter_by(
                inscripto_id=inscripto.id,
                momento_id=m.id,
                valido=True,
            ).first()
        )
        if hit:
            ok += 1
    if ok == 0:
        return "AUSENTE"
    if ok == len(momentos_ordenados):
        return "PRESENTE"
    return "INCOMPLETO"


def export_dataframe_inscriptos(evento_id: int, solo: str | None) -> pd.DataFrame:
    q = InscriptoEvento.query.filter_by(evento_id=evento_id)
    if solo == "validados":
        q = q.filter(InscriptoEvento.estado_validacion == "validado_drogas")
    elif solo == "externos":
        q = q.filter(InscriptoEvento.estado_validacion == "externo")
    rows = q.order_by(InscriptoEvento.id.asc()).all()
    data = []
    for x in rows:
        data.append(
            {
                "apellido_nombre": x.apellido_nombre,
                "dni": x.dni,
                "dni_key": x.dni_key,
                "telefono": x.telefono,
                "correo": x.correo,
                "dependencia_declarada": x.dependencia_declarada,
                "cargo": x.cargo,
                "modalidad_declarada": x.modalidad_declarada,
                "pertenece_drogas": x.pertenece_drogas,
                "estado_validacion": x.estado_validacion,
                "observacion_validacion": x.observacion_validacion,
            }
        )
    return pd.DataFrame(data)


def build_reporte_dataframe(evento: EventoCapacitacion, momentos: list[MomentoAsistencia]) -> pd.DataFrame:
    ins_list = (
        InscriptoEvento.query.options(joinedload(InscriptoEvento.padron_ref))
        .filter_by(evento_id=evento.id)
        .order_by(InscriptoEvento.apellido_nombre.asc(), InscriptoEvento.id.asc())
        .all()
    )
    regs = {
        (r.inscripto_id, r.momento_id)
        for r in RegistroAsistencia.query.filter(
            RegistroAsistencia.evento_id == evento.id,
            RegistroAsistencia.valido.is_(True),
            RegistroAsistencia.inscripto_id.isnot(None),
        ).all()
    }
    rows_out = []
    for ins in ins_list:
        row: dict[str, Any] = {
            "dni": ins.dni,
            "nombre": ins.apellido_nombre,
            "dependencia": ins.dependencia_para_reporte,
            "pertenece_drogas": "SI" if ins.pertenece_drogas else "NO",
            "estado_validacion": ins.estado_validacion,
        }
        presencias = []
        for m in momentos:
            ok = (ins.id, m.id) in regs
            label = f"M{m.id} · {(m.nombre or '')[:35]}"
            row[label] = "SI" if ok else "NO"
            presencias.append(ok)
        row["resultado_final"] = resultado_final_asistencia(ins, momentos)
        rows_out.append(row)
    return pd.DataFrame(rows_out)

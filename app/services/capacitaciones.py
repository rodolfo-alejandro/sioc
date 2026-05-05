"""
Lógica de negocio: importaciones padrón/inscriptos, validación y asistencia.
"""
from __future__ import annotations

import io
import re
import secrets
import string
from datetime import datetime
from typing import Any

import pandas as pd
from flask import Request
from sqlalchemy import or_

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
    s = str(raw).strip()
    digits = "".join(re.findall(r"\d", s))
    return digits, s


def is_dni_plausible(dni_key: str) -> bool:
    return 7 <= len(dni_key) <= 9


def generate_codigo_momento() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _read_upload_to_dataframe(file_storage) -> pd.DataFrame:
    name = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if name.endswith(".csv"):
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except Exception:
                continue
        return pd.read_csv(io.BytesIO(raw))
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    raise ValueError("Formato no soportado. Use CSV o XLSX.")


def _norm_col(c: str) -> str:
    return re.sub(r"\s+", " ", str(c).strip().lower())


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
    "legajo": ["legajo", "nro legajo", "n° legajo", "nro_legajo"],
    "apellido": ["apellido", "apellidos"],
    "nombre": ["nombre", "nombres"],
    "dni": ["dni", "documento", "d.n.i.", "dni n°", "nro documento"],
    "grado": ["grado", "jerarquía", "jerarquia", "rango"],
    "sexo": ["sexo", "genero", "género"],
    "dependencia": ["dependencia", "reparticion", "repartición", "unidad", "destino"],
    "organismo": ["organismo", "fuerza", "institución", "institucion"],
}

INSCRIPTO_SYNONYMS = {
    "apellido_nombre": [
        "apellido y nombre",
        "apellido_nombre",
        "nombre y apellido",
        "nombre completo",
        "nombre",
    ],
    "dni": ["dni", "documento", "d.n.i."],
    "telefono": ["telefono", "teléfono", "celular", "whatsapp", "phone"],
    "correo": ["correo", "email", "e-mail", "mail"],
    "dependencia_declarada": ["dependencia", "reparticion", "repartición", "unidad", "comisaría", "comisaria"],
    "cargo": ["cargo", "puesto", "función", "funcion"],
    "modalidad_declarada": ["modalidad", "asistencia", "virtual/presencial"],
    "comentarios": ["comentarios", "observaciones", "nota", "notas"],
}


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
    rows = _map_row_columns(df, INSCRIPTO_SYNONYMS)
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
    now = datetime.utcnow()
    dni_key, _ = normalize_dni(dni_raw)
    codigo = (codigo_raw or "").strip().upper()
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64]
    ua = (request.headers.get("User-Agent") or "")[:500]

    base_kw = dict(
        evento_id=evento.id,
        momento_id=momento.id,
        dni_ingresado=dni_raw,
        dni_key=dni_key or None,
        codigo_ingresado=codigo,
        fecha_hora=now,
        ip=ip,
        user_agent=ua,
        valido=False,
        motivo=None,
        inscripto_id=None,
    )

    if not momento.activo:
        r = RegistroAsistencia(**base_kw, motivo="momento_inactivo")
        db.session.add(r)
        db.session.commit()
        return False, "momento_inactivo"

    if momento.fecha_apertura and now < momento.fecha_apertura:
        r = RegistroAsistencia(**base_kw, motivo="fuera_horario")
        db.session.add(r)
        db.session.commit()
        return False, "fuera_horario"
    if momento.fecha_cierre and now > momento.fecha_cierre:
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
        fecha_hora=now,
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
        InscriptoEvento.query.filter_by(evento_id=evento.id).order_by(InscriptoEvento.apellido_nombre.asc(), InscriptoEvento.id.asc()).all()
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
            "dependencia": ins.dependencia_declarada,
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

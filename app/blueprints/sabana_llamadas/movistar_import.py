"""
Importación de sábanas Movistar (TEMIS / Solicitud *.xlsx).
Un archivo puede traer solo DATOS, solo LLAMADA/SMS o mezclado → genera cargas VOZ y/o GPRS.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime

import pandas as pd

from app.blueprints.sabana_llamadas.movistar_common import (
    cell_at,
    col_index,
    detect_header_and_columns,
    es_formato_movistar,
    extract_metadata_movistar,
    map_direccion_evento,
    parse_coord_movistar,
    tipo_es_datos,
    tipo_es_voz,
)
from app.blueprints.sabana_llamadas.services import (
    _ensure_caso_sujeto_link,
    _normalize_celda_id,
    _parse_fecha,
    _save_sabana_file,
    _valor_str,
)
from app.extensions import db
from app.models.sabana_llamadas import (
    CargaLlamada,
    DatoTecnico,
    ResultadoTraficoGPRS,
    ResultadoTraficoVOZ,
)
from app.services.audit import audit_log


def _split_fecha_hora(val):
    dt = _parse_fecha(val)
    if not dt:
        return None, None
    if isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day), dt.strftime("%H:%M:%S")
    return dt, None


def _clean_device_id(val, max_len=50):
    s = _valor_str(val, max_len)
    if not s:
        return None
    low = s.lower()
    if low in ("no solicitado", "no disponible", "n/a", "na", "-", "none", "null"):
        return None
    return s


def _upsert_dato_tecnico(
    carga_id,
    tipo_trafico,
    celda_id,
    lat,
    lon,
    direccion,
    localidad,
    provincia,
    radio,
    azimut,
    a_vert,
    a_horiz,
    cache: dict,
):
    celda_norm = _normalize_celda_id(celda_id, 100)
    if not celda_norm:
        return
    lat_f = parse_coord_movistar(lat)
    lon_f = parse_coord_movistar(lon)
    if (
        lat_f is None
        and lon_f is None
        and not direccion
        and not localidad
        and not provincia
    ):
        return

    dt = cache.get(celda_norm)
    if not dt:
        try:
            dt = DatoTecnico.query.filter_by(
                carga_id=carga_id, tipo=tipo_trafico, celda_id=celda_norm
            ).first()
        except Exception:
            dt = None
    if not dt:
        dt = DatoTecnico(carga_id=carga_id, tipo=tipo_trafico, celda_id=celda_norm)
        cache[celda_norm] = dt

    if direccion and not dt.celda_direccion:
        dt.celda_direccion = _valor_str(direccion, 255)
    if localidad and not dt.celda_loc:
        dt.celda_loc = _valor_str(localidad, 200)
    if provincia and not dt.celda_prov:
        dt.celda_prov = _valor_str(provincia, 200)
    if radio and not dt.rad_cob_km:
        dt.rad_cob_km = _valor_str(radio, 50)
    if azimut and not dt.azimuth:
        dt.azimuth = _valor_str(azimut, 50)
    if a_horiz and not dt.a_horiz:
        dt.a_horiz = _valor_str(a_horiz, 50)
    if a_vert and not dt.a_vert:
        dt.a_vert = _valor_str(a_vert, 50)
    if dt.lat is None and lat_f is not None:
        dt.lat = lat_f
    if dt.long is None and lon_f is not None:
        dt.long = lon_f
    db.session.add(dt)


def _build_criterio(meta: dict) -> str | None:
    parts = []
    if meta.get("banner"):
        parts.append(str(meta["banner"]))
    if meta.get("solicitud"):
        parts.append(f"Solicitud N°: {meta['solicitud']}")
    if meta.get("criterio"):
        parts.append(f"criterio: {meta['criterio']}")
    if meta.get("valor"):
        parts.append(f"valor: {meta['valor']}")
    parts.append("Formato: sábana Movistar TEMIS")
    return "\n".join(parts) if parts else None


def _new_carga(
    *,
    unidad_id,
    user_id,
    sujeto_id,
    caso_id,
    tipo,
    operadora,
    safe_name,
    sha,
    size,
    rango_desde,
    rango_hasta,
    criterio,
):
    return CargaLlamada(
        unidad_id=unidad_id,
        user_id=user_id,
        sujeto_id=sujeto_id or None,
        caso_id=caso_id or None,
        tipo=tipo,
        operadora=operadora,
        nombre_archivo=safe_name,
        sha256=sha,
        size_bytes=size,
        rango_desde=rango_desde,
        rango_hasta=rango_hasta,
        criterio_busqueda=criterio,
    )


def procesar_archivo_movistar(
    file,
    unidad_id,
    user_id,
    sujeto_id=None,
    operadora=None,
    caso_id=None,
):
    """
    Procesa sábana Movistar TEMIS.
    Retorna (carga_voz|None, carga_gprs|None, stats, error_msg).
    """
    try:
        file_path, safe_name = _save_sabana_file(file, unidad_id, suffix="movistar")
    except Exception as e:
        return None, None, {}, str(e)

    if not es_formato_movistar(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
        return None, None, {}, (
            "El archivo no parece una sábana Movistar TEMIS "
            "(faltan columnas Fecha Evento / Nro A / Tipo Trafico / Celda)."
        )

    try:
        df = pd.read_excel(file_path, header=None)
    except Exception as e:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return None, None, {}, f"No se pudo leer el Excel: {e}"

    header_row, colmap = detect_header_and_columns(df)
    if header_row is None:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return None, None, {}, "No se encontró la fila de encabezados Movistar."

    meta = extract_metadata_movistar(df)
    criterio = _build_criterio(meta)

    sha256 = hashlib.sha256()
    with open(file_path, "rb") as rf:
        for chunk in iter(lambda: rf.read(8192), b""):
            sha256.update(chunk)
    sha = sha256.hexdigest()
    size = os.path.getsize(file_path)
    op = (str(operadora).strip().upper() if operadora else "MOVISTAR") or "MOVISTAR"
    batch_id = str(uuid.uuid4())

    idx_fecha = col_index(colmap, "Fecha Evento", "fecha evento", "Fecha", "fecha")
    idx_nro_a = col_index(colmap, "Nro A", "nro a", "NroA", "origen", "msisdn")
    idx_nro_b = col_index(colmap, "Nro B", "nro b", "NroB", "destino")
    idx_dir = col_index(colmap, "Direccion Evento", "Dirección Evento", "direccion evento")
    idx_dur = col_index(colmap, "Duracion", "Duración", "duracion")
    idx_imsi = col_index(colmap, "IMSI", "imsi")
    idx_imei = col_index(colmap, "IMEI", "imei")
    idx_tipo = col_index(colmap, "Tipo Trafico", "Tipo Tráfico", "tipo trafico")
    idx_sms = col_index(colmap, "Estado SMS", "estado sms")
    idx_celda = col_index(colmap, "Celda", "celda", "Celda ID")
    idx_dir_c = col_index(colmap, "Direccion", "Dirección", "direccion")
    idx_loc = col_index(colmap, "Localidad", "localidad")
    idx_prov = col_index(colmap, "Provincia", "provincia")
    idx_lat = col_index(colmap, "Latitud", "latitud", "Lat")
    idx_lon = col_index(colmap, "Longitud", "longitud", "Long")
    idx_radio = col_index(colmap, "Radio Cobertura", "radio cobertura", "Radio")
    idx_az = col_index(colmap, "Azimut", "Azimuth", "azimut")
    idx_av = col_index(colmap, "Apertura Vertical", "a. vert", "A. Vert")
    idx_ah = col_index(colmap, "Apertura Horizontal", "a. horiz", "A. Horiz")

    # Primera pasada: clasificar y rangos
    rows_data = []
    fechas = []
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i]
        fe_raw = cell_at(row, idx_fecha)
        nro_a = _valor_str(cell_at(row, idx_nro_a), 64)
        nro_b = _valor_str(cell_at(row, idx_nro_b), 100)
        tipo_t = _valor_str(cell_at(row, idx_tipo), 50) or ""
        # Fila vacía
        if not fe_raw and not nro_a and not cell_at(row, idx_celda):
            continue
        # Si no hay tipo, infiere por Nro B (APN vs teléfono)
        if not tipo_t:
            nb = (nro_b or "").lower()
            if any(x in nb for x in (".", "gprs", "apn", "wap", "ims", "movistar", "data")):
                tipo_t = "DATOS"
            else:
                tipo_t = "LLAMADA"
        fecha, hora = _split_fecha_hora(fe_raw)
        if fecha:
            fechas.append(fecha)
        rows_data.append((row, tipo_t, fecha, hora, nro_a, nro_b))

    if not rows_data:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return None, None, {}, "No se encontraron eventos de tráfico en el archivo Movistar."

    rango_desde = min(fechas) if fechas else None
    rango_hasta = max(fechas) if fechas else None

    n_datos = sum(1 for _, t, *_ in rows_data if tipo_es_datos(t))
    n_voz = sum(1 for _, t, *_ in rows_data if tipo_es_voz(t) and not tipo_es_datos(t))
    # tipificar residuales como voz si no son datos
    if n_datos == 0 and n_voz == 0:
        n_voz = len(rows_data)

    carga_voz = None
    carga_gprs = None
    if n_voz > 0:
        carga_voz = _new_carga(
            unidad_id=unidad_id,
            user_id=user_id,
            sujeto_id=sujeto_id,
            caso_id=caso_id,
            tipo="voz",
            operadora=op,
            safe_name=safe_name,
            sha=sha,
            size=size,
            rango_desde=rango_desde,
            rango_hasta=rango_hasta,
            criterio=criterio,
        )
        db.session.add(carga_voz)
    if n_datos > 0:
        carga_gprs = _new_carga(
            unidad_id=unidad_id,
            user_id=user_id,
            sujeto_id=sujeto_id,
            caso_id=caso_id,
            tipo="gprs",
            operadora=op,
            safe_name=safe_name,
            sha=sha,
            size=size,
            rango_desde=rango_desde,
            rango_hasta=rango_hasta,
            criterio=criterio,
        )
        db.session.add(carga_gprs)
    db.session.flush()

    stats = {
        "voz": 0,
        "gprs": 0,
        "salientes": 0,
        "entrantes": 0,
        "otros_dir": 0,
        "datos": 0,
        "llamadas": 0,
        "sms": 0,
        "tecnicos_voz": 0,
        "tecnicos_gprs": 0,
    }
    cache_tec_voz: dict = {}
    cache_tec_gprs: dict = {}

    try:
        for row, tipo_t, fecha, hora, nro_a, nro_b in rows_data:
            # extras: mapear por nombre de header
            extras = {}
            for h, j in colmap.items():
                v = cell_at(row, j)
                if v is not None:
                    extras[h] = v if not isinstance(v, (datetime,)) else v.isoformat(sep=" ")

            imsi = _clean_device_id(cell_at(row, idx_imsi), 50)
            imei = _clean_device_id(cell_at(row, idx_imei), 50)
            dir_evt = map_direccion_evento(_valor_str(cell_at(row, idx_dir), 50) or "")
            duracion = _valor_str(cell_at(row, idx_dur), 50)
            celda = cell_at(row, idx_celda)
            dir_c = cell_at(row, idx_dir_c)
            loc = cell_at(row, idx_loc)
            prov = cell_at(row, idx_prov)
            lat = cell_at(row, idx_lat)
            lon = cell_at(row, idx_lon)
            radio = cell_at(row, idx_radio)
            az = cell_at(row, idx_az)
            av = cell_at(row, idx_av)
            ah = cell_at(row, idx_ah)
            estado_sms = _valor_str(cell_at(row, idx_sms), 50)

            es_data = tipo_es_datos(tipo_t)
            if es_data and carga_gprs is None:
                continue
            if not es_data and carga_voz is None:
                # residual a gprs if only gprs? shouldn't happen
                if carga_gprs is not None:
                    es_data = True
                else:
                    continue

            if es_data:
                r = ResultadoTraficoGPRS(carga_id=carga_gprs.id)
                r.numero = nro_a
                r.imsi = imsi
                r.imei = imei
                r.fecha = fecha
                r.hora = hora
                r.duracion = duracion
                r.celda = _normalize_celda_id(celda, 100)
                r.celda_direccion = _valor_str(dir_c, 255)
                r.celda_localidad = _valor_str(loc, 200)
                r.celda_provincia = _valor_str(prov, 200)
                # Nro B en datos suele ser APN / servicio
                if nro_b:
                    extras["apn_o_destino"] = nro_b
                    if "." in nro_b or any(
                        x in nro_b.lower() for x in ("gprs", "wap", "apn", "ims", "movistar")
                    ):
                        pass
                    else:
                        r.ip = _valor_str(nro_b, 100)
                extras["tipo_trafico_movistar"] = tipo_t
                extras["direccion_evento"] = dir_evt
                extras["source_format"] = "movistar_temis"
                r.extras = json.dumps(extras, ensure_ascii=False, default=str)
                db.session.add(r)
                stats["gprs"] += 1
                stats["datos"] += 1
                _upsert_dato_tecnico(
                    carga_gprs.id,
                    "gprs",
                    celda,
                    lat,
                    lon,
                    dir_c,
                    loc,
                    prov,
                    radio,
                    az,
                    av,
                    ah,
                    cache_tec_gprs,
                )
            else:
                r = ResultadoTraficoVOZ(carga_id=carga_voz.id)
                r.numero = nro_a
                r.otro = nro_b
                r.imsi = imsi
                r.imei = imei
                r.fecha = fecha
                r.hora = hora
                r.duracion = duracion
                r.tipo = dir_evt or _valor_str(tipo_t, 50)
                r.celda_id = _normalize_celda_id(celda, 100)
                r.celda_calle_altura = _valor_str(dir_c, 255)
                r.celda_localidad = _valor_str(loc, 200)
                r.celda_provincia = _valor_str(prov, 200)
                extras["tipo_trafico_movistar"] = tipo_t
                extras["direccion_evento"] = dir_evt
                extras["estado_sms"] = estado_sms
                extras["source_format"] = "movistar_temis"
                r.extras = json.dumps(extras, ensure_ascii=False, default=str)
                db.session.add(r)
                stats["voz"] += 1
                tl = (tipo_t or "").lower()
                if "sms" in tl:
                    stats["sms"] += 1
                else:
                    stats["llamadas"] += 1
                if dir_evt == "Saliente":
                    stats["salientes"] += 1
                elif dir_evt == "Entrante":
                    stats["entrantes"] += 1
                else:
                    stats["otros_dir"] += 1
                _upsert_dato_tecnico(
                    carga_voz.id,
                    "voz",
                    celda,
                    lat,
                    lon,
                    dir_c,
                    loc,
                    prov,
                    radio,
                    az,
                    av,
                    ah,
                    cache_tec_voz,
                )

        stats["tecnicos_voz"] = len(cache_tec_voz)
        stats["tecnicos_gprs"] = len(cache_tec_gprs)

        meta_base = {
            "source_format": "movistar_temis",
            "movistar_batch_id": batch_id,
            "solicitud": meta.get("solicitud"),
            "criterio": meta.get("criterio"),
            "valor": meta.get("valor"),
        }
        if carga_voz is not None:
            carga_voz.processing_detail = json.dumps(
                {
                    **meta_base,
                    "paired_carga_id": carga_gprs.id if carga_gprs else None,
                    "eventos_importados": stats["voz"],
                    "salientes": stats["salientes"],
                    "entrantes": stats["entrantes"],
                    "datos_tecnicos_importados": stats["tecnicos_voz"],
                },
                ensure_ascii=False,
            )
        if carga_gprs is not None:
            carga_gprs.processing_detail = json.dumps(
                {
                    **meta_base,
                    "paired_carga_id": carga_voz.id if carga_voz else None,
                    "eventos_importados": stats["gprs"],
                    "datos_tecnicos_importados": stats["tecnicos_gprs"],
                },
                ensure_ascii=False,
            )

        _ensure_caso_sujeto_link(caso_id, sujeto_id, unidad_id, user_id)
        db.session.commit()
        audit_log(
            "SABANA_MOVISTAR_UPLOAD",
            f"Movistar batch {batch_id}: voz={getattr(carga_voz, 'id', None)} ({stats['voz']}), "
            f"gprs={getattr(carga_gprs, 'id', None)} ({stats['gprs']})",
            user_id=user_id,
        )
        return carga_voz, carga_gprs, stats, None

    except Exception as e:
        db.session.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None, None, {}, str(e)

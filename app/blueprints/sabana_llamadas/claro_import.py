"""
Importación de sábanas Claro (archivo único: Clientes, IMEI, Salientes, Entrantes).
Genera dos CargaLlamada (voz + gprs) en un solo upload.
"""
import os
import json
import hashlib
import uuid
import pandas as pd
from datetime import datetime

from app.extensions import db
from app.models.sabana_llamadas import (
    CargaLlamada, ResultadoTraficoGPRS, ResultadoTraficoVOZ, DatoTecnico,
)
from app.blueprints.sabana_llamadas.services import (
    _save_sabana_file,
    _read_excel_sheet,
    _parse_fecha,
    _valor_str,
    _normalize_celda_id,
    _parse_float,
    _row_extras,
    _normalize_col_name,
    _ensure_caso_sujeto_link,
)
from app.blueprints.sabana_llamadas.claro_common import (
    CLARO_SHEET_SALIENTES,
    CLARO_SHEET_ENTRANTES,
    CLARO_SHEET_CLIENTES,
    CLARO_SHEET_IMEI_TERMINAL,
    CLARO_SHEET_IMEI_TRACK,
    HEADER_ROW_TRAFICO_CLARO,
    HEADER_ROW_CLIENTES_CLARO,
    HEADER_ROW_IMEI_CLARO,
    destino_es_gprs_claro,
    es_formato_claro_trafico,
    sheet_index as _sheet_index,
    extract_metadata_claro as _extract_metadata_claro,
    make_col_getter as _make_col_getter,
)
from app.services.audit import audit_log


def es_formato_claro(path):
    """True si el libro tiene hojas Salientes + Entrantes (sábana Claro)."""
    return es_formato_claro_trafico(path)


def _split_fecha_hora(val):
    """Datetime combinado Claro -> (fecha date-only datetime, hora HH:MM:SS)."""
    dt = _parse_fecha(val)
    if not dt:
        return None, None
    if isinstance(dt, datetime):
        fecha = datetime(dt.year, dt.month, dt.day)
        hora = dt.strftime('%H:%M:%S')
        return fecha, hora
    return dt, None


def _destino_es_gprs(destino):
    return destino_es_gprs_claro(destino, record=False)


def _build_criterio_claro(path, lineas, periodo_txt):
    parts = []
    if lineas:
        parts.append(f'Líneas Claro: {lineas}')
    if periodo_txt:
        parts.append(f'Periodo: {periodo_txt}')
    parts.append('Formato: sábana Claro unificada')

    try:
        idx = _sheet_index(path, CLARO_SHEET_CLIENTES)
        if idx is not None:
            df = _read_excel_sheet(
                path, sheet_index=idx, header_row=HEADER_ROW_CLIENTES_CLARO,
                keywords=['celular', 'apellido'],
            )
            if not df.empty:
                parts.append('--- Titulares (Clientes) ---')
                for _, row in df.iterrows():
                    cel = _valor_str(row.get('CELULAR') if 'CELULAR' in row.index else None, 30)
                    ape = _valor_str(row.get('APELLIDO') if 'APELLIDO' in row.index else None, 80)
                    nom = _valor_str(row.get('NOMBRE') if 'NOMBRE' in row.index else None, 80)
                    dni = _valor_str(row.get('DNI') if 'DNI' in row.index else None, 20)
                    if cel or ape or nom:
                        parts.append(
                            ' | '.join(x for x in [
                                f'CEL {cel}' if cel else None,
                                f'{ape} {nom}'.strip() if (ape or nom) else None,
                                f'DNI {dni}' if dni else None,
                            ] if x)
                        )
    except Exception:
        pass

    return '\n'.join(parts) if parts else None


def _read_imei_sheet(path, sheet_name):
    out = []
    try:
        idx = _sheet_index(path, sheet_name)
        if idx is None:
            return out
        df = _read_excel_sheet(
            path, sheet_index=idx, header_row=HEADER_ROW_IMEI_CLARO,
            keywords=['celular', 'imei'],
        )
        cols = {_normalize_col_name(c): c for c in df.columns}
        imei_col = None
        for k in cols:
            if 'imei' in k.lower():
                imei_col = cols[k]
                break
        cel_col = cols.get('CELULAR')
        fecha_col = cols.get('FECHA')
        modelo_col = None
        for k in cols:
            if 'marca' in k.lower() or 'modelo' in k.lower():
                modelo_col = cols[k]
                break
        for _, row in df.iterrows():
            cel = _valor_str(row.get(cel_col) if cel_col else None, 30)
            imei = _valor_str(row.get(imei_col) if imei_col else None, 50)
            if not cel and not imei:
                continue
            out.append({
                'celular': cel,
                'imei': imei,
                'fecha': _extras_datetime(row.get(fecha_col) if fecha_col else None),
                'modelo': _valor_str(row.get(modelo_col) if modelo_col else None, 200),
            })
    except Exception:
        pass
    return out


def _extras_datetime(val):
    dt = _parse_fecha(val)
    if dt and isinstance(dt, datetime):
        return dt.isoformat(sep=' ')
    return _valor_str(val, 50)


def _upsert_dato_tecnico(carga_id, tipo_trafico, celda_id, lat, lon, direccion, descripcion, cache):
    """
    Upsert DatoTecnico por celda en esta carga. cache: dict celda_id -> DatoTecnico pendiente.
    """
    celda_norm = _normalize_celda_id(celda_id, 100)
    if not celda_norm:
        return
    dt_lat = _parse_float(lat)
    dt_lon = _parse_float(lon)
    if dt_lat is None and dt_lon is None and not direccion and not descripcion:
        return

    dt = cache.get(celda_norm)
    if not dt:
        try:
            dt = DatoTecnico.query.filter_by(
                carga_id=carga_id, tipo=tipo_trafico, celda_id=celda_norm,
            ).first()
        except Exception:
            dt = None
    if not dt:
        dt = DatoTecnico(carga_id=carga_id, tipo=tipo_trafico, celda_id=celda_norm)
        cache[celda_norm] = dt

    if direccion and not dt.celda_direccion:
        dt.celda_direccion = _valor_str(direccion, 255)
    if descripcion and not dt.celda_loc:
        dt.celda_loc = _valor_str(descripcion, 200)
    if dt.lat is None and dt_lat is not None:
        dt.lat = dt_lat
    if dt.long is None and dt_lon is not None:
        dt.long = dt_lon
    db.session.add(dt)


def procesar_archivo_claro(file, unidad_id, user_id, sujeto_id=None, operadora=None, caso_id=None):
    """
    Procesa sábana Claro unificada. Retorna
    (carga_voz, carga_gprs, stats_dict, error_msg).
    stats_dict: voz, gprs, tecnicos_voz, tecnicos_gprs, entrantes, salientes_voz, conexion_movil
    """
    try:
        file_path, safe_name = _save_sabana_file(file, unidad_id, suffix='claro')
    except Exception as e:
        return None, None, {}, str(e)

    if not es_formato_claro_trafico(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
        return None, None, {}, (
            'El archivo no parece una sábana Claro (faltan hojas Salientes/Entrantes).'
        )

    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as rf:
        for chunk in iter(lambda: rf.read(8192), b''):
            sha256.update(chunk)
    sha = sha256.hexdigest()
    size = os.path.getsize(file_path)
    op = (str(operadora).strip().upper() if operadora else 'CLARO') or 'CLARO'
    batch_id = str(uuid.uuid4())

    lineas, periodo_txt, rango_desde, rango_hasta = _extract_metadata_claro(file_path)
    criterio = _build_criterio_claro(file_path, lineas, periodo_txt)
    imei_terminal = _read_imei_sheet(file_path, CLARO_SHEET_IMEI_TERMINAL)
    imei_track = _read_imei_sheet(file_path, CLARO_SHEET_IMEI_TRACK)

    carga_voz = CargaLlamada(
        unidad_id=unidad_id,
        user_id=user_id,
        sujeto_id=sujeto_id or None,
        caso_id=caso_id or None,
        tipo='voz',
        operadora=op,
        nombre_archivo=safe_name,
        sha256=sha,
        size_bytes=size,
        rango_desde=rango_desde,
        rango_hasta=rango_hasta,
        criterio_busqueda=criterio,
    )
    carga_gprs = CargaLlamada(
        unidad_id=unidad_id,
        user_id=user_id,
        sujeto_id=sujeto_id or None,
        caso_id=caso_id or None,
        tipo='gprs',
        operadora=op,
        nombre_archivo=safe_name,
        sha256=sha,
        size_bytes=size,
        rango_desde=rango_desde,
        rango_hasta=rango_hasta,
        criterio_busqueda=criterio,
    )
    db.session.add(carga_voz)
    db.session.add(carga_gprs)
    db.session.flush()

    stats = {
        'voz': 0,
        'gprs': 0,
        'entrantes': 0,
        'salientes_voz': 0,
        'conexion_movil': 0,
        'tecnicos_voz': 0,
        'tecnicos_gprs': 0,
    }
    cache_tec_voz = {}
    cache_tec_gprs = {}

    try:
        # --- Salientes ---
        idx_sal = _sheet_index(file_path, CLARO_SHEET_SALIENTES)
        df_sal = _read_excel_sheet(
            file_path, sheet_index=idx_sal, header_row=HEADER_ROW_TRAFICO_CLARO,
            keywords=['llamante', 'destino', 'fecha'],
        )
        cols_sal = {_normalize_col_name(c): i for i, c in enumerate(df_sal.columns)}
        get_sal = _make_col_getter(cols_sal)

        for _, row in df_sal.iterrows():
            extras = _row_extras(row)
            if not any(v is not None for v in extras.values()):
                continue

            destino = get_sal(row, ['Destino', 'destino'])
            llamante = _valor_str(get_sal(row, ['Nro. Llamante', 'Nro Llamante']), 64)
            llamado = _valor_str(get_sal(row, ['Nro. Llamado', 'Nro Llamado']), 64)
            fh_raw = get_sal(row, ['fecha y hora', 'Fecha y Hora', 'Fecha y hora'])
            fecha, hora = _split_fecha_hora(fh_raw)
            duracion = _valor_str(get_sal(row, ['Duracion (Seg)', 'Duración (Seg)']), 50)
            celda = get_sal(row, ['Id. celda', 'id. celda', 'Id. Celda'])
            desc_celda = get_sal(row, ['Descripc. Celda', 'Descripc. celda'])
            lat = get_sal(row, ['Latitud', 'latitud'])
            lon = get_sal(row, ['Longitud', 'longitud'])
            dir_celda = get_sal(row, ['Dir Celda', 'Dir celda'])

            if _destino_es_gprs(destino):
                r = ResultadoTraficoGPRS(carga_id=carga_gprs.id)
                r.numero = llamante
                r.fecha = fecha
                r.hora = hora
                r.duracion = duracion
                r.celda = _normalize_celda_id(celda, 100)
                r.celda_direccion = _valor_str(dir_celda, 255)
                r.celda_localidad = _valor_str(desc_celda, 200)
                extras['destino_claro'] = _valor_str(destino, 100)
                extras['nro_llamado'] = llamado
                extras['direccion_llamada'] = 'Saliente'
                r.extras = json.dumps(extras, ensure_ascii=False, default=str)
                db.session.add(r)
                stats['gprs'] += 1
                stats['conexion_movil'] += 1
                _upsert_dato_tecnico(
                    carga_gprs.id, 'gprs', celda, lat, lon, dir_celda, desc_celda, cache_tec_gprs,
                )
            else:
                r = ResultadoTraficoVOZ(carga_id=carga_voz.id)
                r.numero = llamante
                r.otro = llamado
                r.fecha = fecha
                r.hora = hora
                r.duracion = duracion
                r.tipo = 'Saliente'
                r.celda_id = _normalize_celda_id(celda, 100)
                r.celda_calle_altura = _valor_str(dir_celda, 255)
                r.celda_localidad = _valor_str(desc_celda, 200)
                extras['destino_claro'] = _valor_str(destino, 100)
                extras['direccion_llamada'] = 'Saliente'
                r.extras = json.dumps(extras, ensure_ascii=False, default=str)
                db.session.add(r)
                stats['voz'] += 1
                stats['salientes_voz'] += 1
                _upsert_dato_tecnico(
                    carga_voz.id, 'voz', celda, lat, lon, dir_celda, desc_celda, cache_tec_voz,
                )

        # --- Entrantes ---
        idx_ent = _sheet_index(file_path, CLARO_SHEET_ENTRANTES)
        df_ent = _read_excel_sheet(
            file_path, sheet_index=idx_ent, header_row=HEADER_ROW_TRAFICO_CLARO,
            keywords=['llamado', 'llamante', 'fecha'],
        )
        cols_ent = {_normalize_col_name(c): i for i, c in enumerate(df_ent.columns)}
        get_ent = _make_col_getter(cols_ent)

        for _, row in df_ent.iterrows():
            extras = _row_extras(row)
            if not any(v is not None for v in extras.values()):
                continue

            llamado = _valor_str(get_ent(row, ['Nro. Llamado', 'Nro Llamado']), 64)
            llamante = _valor_str(get_ent(row, ['Nro. Llamante', 'Nro Llamante']), 64)
            fh_raw = get_ent(row, ['Fecha y Hora', 'fecha y hora', 'Fecha y hora'])
            fecha, hora = _split_fecha_hora(fh_raw)
            duracion = _valor_str(get_ent(row, ['Duracion (Seg)', 'Duración (Seg)']), 50)
            celda = get_ent(row, ['id. Celda', 'Id. celda', 'Id. Celda'])
            desc_celda = get_ent(row, ['Descripc. Celda', 'Descripc. celda'])
            lat = get_ent(row, ['Latitud', 'latitud'])
            lon = get_ent(row, ['Longitud', 'longitud'])
            dir_celda = get_ent(row, ['Dir Celda', 'Dir celda'])

            r = ResultadoTraficoVOZ(carga_id=carga_voz.id)
            r.numero = llamado
            r.otro = llamante
            r.fecha = fecha
            r.hora = hora
            r.duracion = duracion
            r.tipo = 'Entrante'
            r.celda_id = _normalize_celda_id(celda, 100)
            r.celda_calle_altura = _valor_str(dir_celda, 255)
            r.celda_localidad = _valor_str(desc_celda, 200)
            extras['direccion_llamada'] = 'Entrante'
            r.extras = json.dumps(extras, ensure_ascii=False, default=str)
            db.session.add(r)
            stats['voz'] += 1
            stats['entrantes'] += 1
            _upsert_dato_tecnico(
                carga_voz.id, 'voz', celda, lat, lon, dir_celda, desc_celda, cache_tec_voz,
            )

        stats['tecnicos_voz'] = len(cache_tec_voz)
        stats['tecnicos_gprs'] = len(cache_tec_gprs)

        meta_base = {
            'source_format': 'claro_unificado',
            'claro_batch_id': batch_id,
            'lineas_claro': lineas,
            'periodo_claro': periodo_txt,
            'imei_terminal': imei_terminal,
            'imei_track': imei_track,
        }
        carga_voz.processing_detail = json.dumps({
            **meta_base,
            'paired_carga_id': carga_gprs.id,
            'eventos_importados': stats['voz'],
            'entrantes': stats['entrantes'],
            'salientes_voz': stats['salientes_voz'],
            'datos_tecnicos_importados': stats['tecnicos_voz'],
        }, ensure_ascii=False)
        carga_gprs.processing_detail = json.dumps({
            **meta_base,
            'paired_carga_id': carga_voz.id,
            'eventos_importados': stats['gprs'],
            'conexion_movil': stats['conexion_movil'],
            'datos_tecnicos_importados': stats['tecnicos_gprs'],
        }, ensure_ascii=False)

        _ensure_caso_sujeto_link(caso_id, sujeto_id, unidad_id, user_id)
        db.session.commit()
        audit_log(
            'SABANA_CLARO_UPLOAD',
            f'Claro batch {batch_id}: voz={carga_voz.id} ({stats["voz"]}), '
            f'gprs={carga_gprs.id} ({stats["gprs"]})',
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

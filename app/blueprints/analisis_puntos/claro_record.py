"""
Importación Record Claro (Salientes + Entrantes) → dos fuentes ap_* (VOZ + GPRS).
"""
import json
import os
import uuid

import pandas as pd
from datetime import datetime

from app.extensions import db
from app.models.analisis_puntos import (
    AnalisisPuntoCelda,
    AnalisisPuntoEvento,
    AnalisisPuntoFuente,
)
from app.blueprints.sabana_llamadas.services import (
    _read_excel_sheet,
    _parse_fecha,
    _valor_str,
    _normalize_celda_id,
    _parse_float,
    _row_extras,
    _normalize_col_name,
)
from app.blueprints.sabana_llamadas.claro_common import (
    CLARO_SHEET_SALIENTES,
    CLARO_SHEET_ENTRANTES,
    HEADER_ROW_TRAFICO_CLARO,
    destino_es_gprs_claro,
    es_formato_claro_record,
    sheet_index,
    extract_metadata_claro,
    make_col_getter,
    _norm_text,
)
from app.services.audit import audit_log

BATCH_FLUSH = 3000


def _split_event_dt(val):
    dt = _parse_fecha(val)
    if not dt or not isinstance(dt, datetime):
        return None, None, None
    event_dt = dt
    event_date = dt.strftime('%Y-%m-%d')
    event_hour = dt.strftime('%H')
    return event_dt, event_date, event_hour


def _duration_sec(val):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        s = str(val).strip().replace(',', '.')
        if not s:
            return None
        f = float(s)
        if f < 0:
            return None
        return int(f) if f <= 2147483647 else 2147483647
    except Exception:
        return None


def _upsert_ap_celda(unidad_id, celda_code, lat, lon, direccion, descripcion, cache):
    celda_norm = _normalize_celda_id(celda_code, 100)
    if not celda_norm:
        return None
    dt_lat = _parse_float(lat)
    dt_lon = _parse_float(lon)
    if dt_lat is None or dt_lon is None:
        return cache.get(celda_norm)

    celda_id = cache.get(celda_norm)
    if celda_id:
        return celda_id

    celda = AnalisisPuntoCelda.query.filter_by(unidad_id=unidad_id, cell_code=celda_norm).first()
    if not celda:
        celda = AnalisisPuntoCelda(unidad_id=unidad_id, cell_code=celda_norm)
    celda.lat = dt_lat
    celda.lon = dt_lon
    if direccion:
        celda.address = _valor_str(direccion, 255)
    if descripcion and not celda.locality:
        celda.locality = _valor_str(descripcion, 200)
    db.session.add(celda)
    db.session.flush()
    cache[celda_norm] = celda.id
    return celda.id


def _add_evento(
    fuente, source_type, event_dt, event_date, event_hour,
    origin, target, event_type, duration_sec, raw_cell, cell_id, payload,
    stats_key, stats,
):
    e = AnalisisPuntoEvento(
        caso_id=fuente.caso_id,
        fuente_id=fuente.id,
        unidad_id=fuente.unidad_id,
        user_id=fuente.user_id,
        source_type=source_type,
        event_dt=event_dt,
        event_date=event_date,
        event_hour=event_hour,
        origin_msisdn=origin,
        target_msisdn=target,
        event_type=event_type,
        duration_sec=duration_sec,
        raw_cell_code=raw_cell,
        cell_id=cell_id,
        raw_payload_json=json.dumps(payload, ensure_ascii=False, default=str),
    )
    db.session.add(e)
    stats[stats_key] = stats.get(stats_key, 0) + 1


def procesar_record_claro(fuente_voz: AnalisisPuntoFuente, fuente_gprs: AnalisisPuntoFuente, absolute_path: str):
    """
    Procesa record Claro desde path ya guardado. Requiere dos fuentes (VOZ y GPRS) del mismo upload.
    """
    if not os.path.exists(absolute_path):
        raise FileNotFoundError('No se encontró el archivo subido para procesar.')

    if not es_formato_claro_record(absolute_path):
        raise ValueError(
            'El archivo no parece un Record Claro (hojas Salientes/Entrantes sin titulares IMEI). '
            'Si es sábana con Clientes, use Sábana Claro completa.'
        )

    batch_id = str(uuid.uuid4())
    celdas_cache = {}
    lineas, periodo_txt, date_from, date_to = extract_metadata_claro(
        absolute_path,
        label_lineas=('Lineas Claro',),
        label_celdas=('Celdas',),
    )

    for fuente in (fuente_voz, fuente_gprs):
        fuente.date_from = date_from
        fuente.date_to = date_to
        AnalisisPuntoEvento.query.filter_by(fuente_id=fuente.id).delete(synchronize_session=False)

    stats = {
        'voz': 0,
        'gprs': 0,
        'entrantes': 0,
        'salientes_voz': 0,
        'conexion_movil': 0,
        'filas_salientes': 0,
        'filas_entrantes': 0,
        'celdas_unicas': 0,
    }
    pending = 0

    # --- Salientes ---
    idx_sal = sheet_index(absolute_path, CLARO_SHEET_SALIENTES)
    df_sal = _read_excel_sheet(
        absolute_path, sheet_index=idx_sal, header_row=HEADER_ROW_TRAFICO_CLARO,
        keywords=['llamante', 'destino', 'fecha'],
    )
    cols_sal = {_normalize_col_name(c): i for i, c in enumerate(df_sal.columns)}
    get_sal = make_col_getter(cols_sal)

    for _, row in df_sal.iterrows():
        stats['filas_salientes'] += 1
        extras = _row_extras(row)
        if not any(v is not None for v in extras.values()):
            continue

        destino = get_sal(row, ['Destino', 'destino'])
        llamante = _valor_str(get_sal(row, ['Nro. Llamante', 'Nro Llamante']), 64)
        llamado = _valor_str(get_sal(row, ['Nro. Llamado', 'Nro Llamado']), 64)
        fh_raw = get_sal(row, ['fecha y hora', 'Fecha y Hora'])
        event_dt, event_date, event_hour = _split_event_dt(fh_raw)
        duracion = _duration_sec(get_sal(row, ['Duracion (Seg)', 'Duración (Seg)']))
        celda = get_sal(row, ['Id. celda', 'id. celda'])
        desc_celda = get_sal(row, ['Descripc. Celda'])
        lat = get_sal(row, ['Latitud'])
        lon = get_sal(row, ['Longitud'])
        dir_celda = get_sal(row, ['Dir Celda'])
        raw_cell = _normalize_celda_id(celda, 100)
        cell_id = _upsert_ap_celda(
            fuente_voz.unidad_id, raw_cell, lat, lon, dir_celda, desc_celda, celdas_cache,
        )

        extras['destino_claro'] = _valor_str(destino, 100)
        extras['direccion_llamada'] = 'Saliente'

        if destino_es_gprs_claro(destino, record=True):
            extras['nro_llamado'] = llamado
            fuente = fuente_gprs
            if 'conexion movil' in _norm_text(destino):
                stats['conexion_movil'] += 1
            _add_evento(
                fuente, 'GPRS', event_dt, event_date, event_hour,
                llamante, llamado, _valor_str(destino, 50), duracion,
                raw_cell, cell_id, extras, 'gprs', stats,
            )
        else:
            fuente = fuente_voz
            _add_evento(
                fuente, 'VOZ', event_dt, event_date, event_hour,
                llamante, llamado, 'Saliente', duracion,
                raw_cell, cell_id, extras, 'voz', stats,
            )
            stats['salientes_voz'] += 1

        pending += 1
        if pending >= BATCH_FLUSH:
            db.session.flush()
            pending = 0

    # --- Entrantes ---
    idx_ent = sheet_index(absolute_path, CLARO_SHEET_ENTRANTES)
    df_ent = _read_excel_sheet(
        absolute_path, sheet_index=idx_ent, header_row=HEADER_ROW_TRAFICO_CLARO,
        keywords=['llamado', 'llamante', 'fecha'],
    )
    cols_ent = {_normalize_col_name(c): i for i, c in enumerate(df_ent.columns)}
    get_ent = make_col_getter(cols_ent)

    for _, row in df_ent.iterrows():
        stats['filas_entrantes'] += 1
        extras = _row_extras(row)
        if not any(v is not None for v in extras.values()):
            continue

        llamado = _valor_str(get_ent(row, ['Nro. Llamado', 'Nro Llamado']), 64)
        llamante = _valor_str(get_ent(row, ['Nro. Llamante', 'Nro Llamante']), 64)
        fh_raw = get_ent(row, ['Fecha y Hora', 'fecha y hora'])
        event_dt, event_date, event_hour = _split_event_dt(fh_raw)
        duracion = _duration_sec(get_ent(row, ['Duracion (Seg)', 'Duración (Seg)']))
        celda = get_ent(row, ['id. Celda', 'Id. celda'])
        desc_celda = get_ent(row, ['Descripc. Celda'])
        lat = get_ent(row, ['Latitud'])
        lon = get_ent(row, ['Longitud'])
        dir_celda = get_ent(row, ['Dir Celda'])
        raw_cell = _normalize_celda_id(celda, 100)
        cell_id = _upsert_ap_celda(
            fuente_voz.unidad_id, raw_cell, lat, lon, dir_celda, desc_celda, celdas_cache,
        )
        extras['direccion_llamada'] = 'Entrante'

        _add_evento(
            fuente_voz, 'VOZ', event_dt, event_date, event_hour,
            llamante, llamado, 'Entrante', duracion,
            raw_cell, cell_id, extras, 'voz', stats,
        )
        stats['entrantes'] += 1

        pending += 1
        if pending >= BATCH_FLUSH:
            db.session.flush()
            pending = 0

    stats['celdas_unicas'] = len(celdas_cache)
    meta = {
        'source_format': 'claro_record',
        'claro_batch_id': batch_id,
        'lineas_o_celdas': lineas,
        'periodo_claro': periodo_txt,
        **stats,
    }

    for fuente, stype, count_key in (
        (fuente_voz, 'VOZ', 'voz'),
        (fuente_gprs, 'GPRS', 'gprs'),
    ):
        summary = {
            'source_type': stype,
            'source_format': 'claro_record',
            'claro_batch_id': batch_id,
            'paired_fuente_id': fuente_gprs.id if stype == 'VOZ' else fuente_voz.id,
            'eventos_importados': stats.get(count_key, 0),
            'processing_summary': meta,
        }
        fuente.upload_status = 'PROCESSED'
        fuente.error_detail = json.dumps(summary, ensure_ascii=False)
        db.session.add(fuente)

    db.session.commit()
    audit_log(
        'RECORD_CLARO_UPLOAD',
        f'Record Claro batch {batch_id}: voz={fuente_voz.id} ({stats["voz"]}), '
        f'gprs={fuente_gprs.id} ({stats["gprs"]})',
        user_id=fuente_voz.user_id,
    )
    return stats

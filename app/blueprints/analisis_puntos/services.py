import json
import logging
import os
from datetime import datetime

import pandas as pd

from app.extensions import db
from app.models.analisis_puntos import (
    AnalisisPuntoCelda,
    AnalisisPuntoEvento,
    AnalisisPuntoFuente,
    AnalisisPuntoTitular,
)

BATCH_FLUSH = int(os.environ.get("IMPORT_BATCH_FLUSH", "500"))
_log = logging.getLogger(__name__)


def _flush_batch(pending: int, *, label: str = "") -> int:
    if pending >= BATCH_FLUSH:
        db.session.commit()
        db.session.expunge_all()
        if label:
            _log.info("Import %s: lote de %s filas guardado", label, BATCH_FLUSH)
        return 0
    return pending


def _normalize_col_name(col):
    if col is None or (isinstance(col, float) and pd.isna(col)):
        return ""
    return str(col).strip()


def _valor_str(val, max_len=500):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s[:max_len] if s else None


def _parse_float(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str):
        s = val.strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _normalize_celda_id(val, max_len=100):
    if pd.isna(val) or val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            f = float(val)
            if f.is_integer():
                s = str(int(f)).strip().upper()
                return s[:max_len] if s else None
    except Exception:
        pass
    s = str(val).strip().upper()
    if not s:
        return None
    if s.endswith(".0"):
        s = s[:-2]
    return s[:max_len] if s else None


def _normalize_hora_str(val, max_len=20):
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%H:%M:%S")
    s = str(val).strip()
    if not s:
        return None
    if "." in s:
        s = s.split(".", 1)[0]
    parts = s.split(":")
    try:
        hh = int(parts[0]) if len(parts) > 0 and parts[0] else 0
        mm = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        ss = int(parts[2]) if len(parts) > 2 and parts[2] else 0
        out = f"{hh:02d}:{mm:02d}:{ss:02d}"
        return out[:max_len]
    except Exception:
        return _valor_str(s, max_len=max_len)


def _parse_fecha(valor):
    if pd.isna(valor) or valor is None:
        return None
    if isinstance(valor, datetime):
        return valor
    try:
        dt = pd.to_datetime(valor, errors="coerce", dayfirst=True)
        if pd.isna(dt) or dt is None:
            return None
        try:
            return dt.to_pydatetime()
        except Exception:
            return dt
    except Exception:
        return None


def _read_excel_sheet(path, sheet_name_or_index, header_row, keywords=None):
    """Lee una hoja detectando el encabezado. Solo previsualiza 12 filas (no carga 2 veces el Excel entero)."""

    def detect_header_index_rows(rows, default_idx, keywords_local):
        if not keywords_local:
            return default_idx
        kws = [k.lower() for k in keywords_local]
        max_scan = min(12, len(rows))
        for r in range(max_scan):
            vals = [str(v).strip().lower() for v in rows[r]]
            for k in kws:
                if k in vals:
                    return r
        return default_idx

    # Preview liviano: evita cargar dos veces hojas GPRS de cientos de miles de filas.
    df_preview = pd.read_excel(path, sheet_name=sheet_name_or_index, header=None, nrows=12)
    preview_rows = df_preview.values.tolist()
    hdr_idx = detect_header_index_rows(preview_rows, header_row, keywords)
    del df_preview
    return pd.read_excel(path, sheet_name=sheet_name_or_index, header=hdr_idx)


def _sheet_name_like(path, include_tokens, fallback_index=None, *, required=False):
    """
    Busca una hoja cuyos nombres contengan todos los tokens.
    Si required=True y no hay match, retorna None (no usa fallback engañoso).
    """
    xls = pd.ExcelFile(path)
    for name in xls.sheet_names:
        nl = str(name).lower()
        if all(t in nl for t in include_tokens):
            return name
    if required:
        return None
    if fallback_index is None:
        return None
    return fallback_index


def _get_with_aliases(row, cols_map, names, default=None):
    for n in names:
        if n in cols_map:
            # row puede ser Series (iterrows) o tupla/namedtuple (itertuples)
            idx = cols_map[n]
            try:
                val = row.iloc[idx] if hasattr(row, "iloc") else row[idx]
            except Exception:
                val = default
            if not pd.isna(val):
                return val
    return default


def _payload_from_row_values(columns, values):
    out = {}
    for k, v in zip(columns, values):
        out[str(k)] = None if pd.isna(v) else str(v)
    return out


def _payload_from_row(row):
    return {str(k): (None if pd.isna(v) else str(v)) for k, v in row.to_dict().items()}


def _payload_has_data(payload):
    if not payload:
        return False
    for v in payload.values():
        if v is None:
            continue
        if str(v).strip() != "":
            return True
    return False


def _reattach_fuente(fuente: AnalisisPuntoFuente) -> AnalisisPuntoFuente:
    """Tras expunge_all() el objeto fuente queda detached; rehidratar por id."""
    fid = getattr(fuente, "id", None)
    if fid is None:
        return fuente
    fresh = db.session.get(AnalisisPuntoFuente, fid)
    return fresh or fuente


def _upsert_celdas(absolute_path, unidad_id):
    sheet_tec = _sheet_name_like(absolute_path, ["datos", "tecnic"], 1)
    if sheet_tec is None:
        raise ValueError("No se encontró la hoja de Datos Técnicos en el Excel.")
    df_tec = _read_excel_sheet(absolute_path, sheet_tec, 3, keywords=["lat", "long"])
    cols_tec = {_normalize_col_name(c): i for i, c in enumerate(df_tec.columns)}
    celdas_by_code = {}

    for _, row in df_tec.iterrows():
        celda_code = _normalize_celda_id(_get_with_aliases(row, cols_tec, ["CeldaID"]), 100)
        if not celda_code:
            continue
        lat = _parse_float(_get_with_aliases(row, cols_tec, ["Lat", "lat"]))
        lon = _parse_float(_get_with_aliases(row, cols_tec, ["Long", "long"]))
        if lat is None or lon is None:
            continue
        rad_km = _get_with_aliases(row, cols_tec, ["Rad Cob (KM)"])
        rad_m = None
        try:
            v = float(str(rad_km).replace(",", ".")) if rad_km is not None else None
            if v is not None:
                rad_m = int(round(v * 1000))
        except Exception:
            rad_m = None

        celda = AnalisisPuntoCelda.query.filter_by(unidad_id=unidad_id, cell_code=celda_code).first()
        if not celda:
            celda = AnalisisPuntoCelda(unidad_id=unidad_id, cell_code=celda_code)
        celda.address = _valor_str(_get_with_aliases(row, cols_tec, ["Celda Direccion"]), 255)
        celda.locality = _valor_str(_get_with_aliases(row, cols_tec, ["Celda Loc"]), 200)
        celda.province = _valor_str(_get_with_aliases(row, cols_tec, ["Celda Prov"]), 200)
        celda.lat = lat
        celda.lon = lon
        if rad_m:
            celda.coverage_radius_m = rad_m
        az = _get_with_aliases(row, cols_tec, ["Azimuth"])
        ah = _get_with_aliases(row, cols_tec, ["A. Horiz"])
        av = _get_with_aliases(row, cols_tec, ["A. Vert"])
        celda.azimuth_deg = int(float(az or 0)) if az not in (None, "") else None
        celda.aperture_h_deg = int(float(ah or 0)) if ah not in (None, "") else None
        celda.aperture_v_deg = int(float(av or 0)) if av not in (None, "") else None
        db.session.add(celda)
        db.session.flush()
        celdas_by_code[celda_code] = celda.id
    del df_tec
    return celdas_by_code


def _upsert_titulares(absolute_path, caso_id, unidad_id, fuente_id):
    sheet_tit = _sheet_name_like(absolute_path, ["titular"], required=True)
    if sheet_tit is None:
        _log.info("Sin hoja Titulares; se omite ese bloque")
        return
    df_tit = _read_excel_sheet(absolute_path, sheet_tit, 3, keywords=["titular", "número"])
    cols_tit = {_normalize_col_name(c): i for i, c in enumerate(df_tit.columns)}
    for _, row in df_tit.iterrows():
        msisdn = _valor_str(_get_fuzzy(row, cols_tit, ["Número", "Numero"]), 64)
        if not msisdn:
            continue
        t = AnalisisPuntoTitular.query.filter_by(caso_id=caso_id, msisdn=msisdn).first()
        if not t:
            t = AnalisisPuntoTitular(caso_id=caso_id, fuente_id=fuente_id, unidad_id=unidad_id, msisdn=msisdn)
        t.holder_name = _valor_str(_get_with_aliases(row, cols_tit, ["Titular"]), 255)
        t.doc_number = _valor_str(_get_fuzzy(row, cols_tit, ["Número Doc", "Numero Doc"]), 64)
        t.service_type = _valor_str(_get_with_aliases(row, cols_tit, ["Servicio"]), 100)
        t.market_type = _valor_str(_get_with_aliases(row, cols_tit, ["Mercado"]), 100)
        t.billing_address = _valor_str(
            _get_fuzzy(row, cols_tit, ["Dirección Facturación", "Direccion Facturacion"]), 255
        )
        t.contact_phone = _valor_str(_get_with_aliases(row, cols_tit, ["Contacto"]), 64)
        db.session.add(t)
    del df_tit


def _col_idx_fuzzy(cols_map, *needles):
    """Busca columna por nombre aproximado (tolera encoding roto de Número)."""
    for n in needles:
        if n in cols_map:
            return cols_map[n]
    needles_l = [n.lower() for n in needles]
    for key, idx in cols_map.items():
        kl = key.lower()
        for n in needles_l:
            if n in kl or kl in n:
                return idx
            if "mero" in n and "mero" in kl and "doc" not in n and "doc" not in kl:
                return idx
    return None


def _get_fuzzy(row, cols_map, names, default=None):
    idx = _col_idx_fuzzy(cols_map, *names)
    if idx is None:
        return default
    try:
        val = row.iloc[idx] if hasattr(row, "iloc") else row[idx]
    except Exception:
        return default
    if pd.isna(val):
        return default
    return val


def procesar_fuente_voz(fuente: AnalisisPuntoFuente, absolute_path: str):
    if not os.path.exists(absolute_path):
        raise FileNotFoundError("No se encontró el archivo subido para procesar.")

    caso_id = fuente.caso_id
    unidad_id = fuente.unidad_id
    user_id = fuente.user_id
    fuente_id = fuente.id
    _log.info("VOZ: iniciando %s (batch=%s)", os.path.basename(absolute_path), BATCH_FLUSH)

    celdas_by_code = _upsert_celdas(absolute_path, unidad_id)
    _upsert_titulares(absolute_path, caso_id, unidad_id, fuente_id)

    sheet_traf = _sheet_name_like(absolute_path, ["resultado", "traf"], 0)
    if sheet_traf is None:
        raise ValueError("No se encontró la hoja Resultado de Tráfico en el Excel.")
    df_traf = _read_excel_sheet(absolute_path, sheet_traf, 3, keywords=["imei", "imsi"])
    cols_traf = {_normalize_col_name(c): i for i, c in enumerate(df_traf.columns)}
    traf_columns = list(df_traf.columns)

    AnalisisPuntoEvento.query.filter_by(fuente_id=fuente_id).delete(synchronize_session=False)

    total_filas_trafico = 0
    count_eventos = 0
    skipped_empty = 0
    pending = 0
    for row in df_traf.itertuples(index=False, name=None):
        total_filas_trafico += 1
        if total_filas_trafico % 5000 == 0:
            _log.info("VOZ: %s filas leídas, %s eventos", total_filas_trafico, count_eventos)
        payload = _payload_from_row_values(traf_columns, row)
        if not _payload_has_data(payload):
            skipped_empty += 1
            continue
        origin = _valor_str(_get_fuzzy(row, cols_traf, ["Número", "Numero"]), 64)
        fecha = _parse_fecha(_get_fuzzy(row, cols_traf, ["Fecha"]))
        hora = _normalize_hora_str(_get_fuzzy(row, cols_traf, ["Hora"]), 20)
        event_dt = None
        if fecha is not None:
            event_dt = fecha
            try:
                if hora:
                    hh, mm, ss = [int(x) for x in hora.split(":")]
                    event_dt = datetime(fecha.year, fecha.month, fecha.day, hh, mm, ss)
            except Exception:
                pass
        dur = _get_fuzzy(row, cols_traf, ["Duracion", "Duración"])
        duration_sec = None
        try:
            if dur is not None and str(dur).strip() != "":
                duration_sec = int(float(str(dur).replace(",", ".")))
        except Exception:
            duration_sec = None

        raw_cell = _normalize_celda_id(_get_fuzzy(row, cols_traf, ["Celda ID", "Celda", "CeldaID"]), 100)
        e = AnalisisPuntoEvento(
            caso_id=caso_id,
            fuente_id=fuente_id,
            unidad_id=unidad_id,
            user_id=user_id,
            source_type="VOZ",
            event_dt=event_dt,
            event_date=event_dt.strftime("%Y-%m-%d") if event_dt else None,
            event_hour=event_dt.strftime("%H") if event_dt else None,
            origin_msisdn=origin,
            target_msisdn=_valor_str(_get_fuzzy(row, cols_traf, ["Otro"]), 64),
            imei=_valor_str(_get_fuzzy(row, cols_traf, ["IMEI"]), 64),
            imsi=_valor_str(_get_fuzzy(row, cols_traf, ["IMSI"]), 64),
            event_type=_valor_str(_get_fuzzy(row, cols_traf, ["Tipo"]), 50),
            duration_sec=duration_sec,
            raw_cell_code=raw_cell,
            cell_id=celdas_by_code.get(raw_cell),
            raw_payload_json=json.dumps(payload, ensure_ascii=False),
        )
        db.session.add(e)
        count_eventos += 1
        pending = _flush_batch(pending + 1, label="VOZ")

    del df_traf
    fuente = db.session.get(AnalisisPuntoFuente, fuente_id) or fuente
    summary = {
        "source_type": "VOZ",
        "filas_trafico_leidas": int(total_filas_trafico),
        "eventos_importados": int(count_eventos),
        "filas_omitidas_vacias": int(skipped_empty),
        "filas_omitidas_total": int(skipped_empty),
    }
    fuente.upload_status = "PROCESSED"
    fuente.error_detail = json.dumps({"processing_summary": summary}, ensure_ascii=False)
    db.session.add(fuente)
    db.session.commit()
    _log.info("VOZ: listo %s eventos", count_eventos)
    return summary


def procesar_fuente_gprs(fuente: AnalisisPuntoFuente, absolute_path: str):
    """
    Procesa un archivo Record GPRS (estructura tipo sábana) hacia ap_*.

    - ap_celdas: upsert por unidad + cell_code
    - ap_titulares: upsert por caso + msisdn
    - ap_eventos: sesiones GPRS con source_type='GPRS'
    """
    if not os.path.exists(absolute_path):
        raise FileNotFoundError("No se encontró el archivo subido para procesar.")

    caso_id = fuente.caso_id
    unidad_id = fuente.unidad_id
    user_id = fuente.user_id
    fuente_id = fuente.id
    _log.info("GPRS: iniciando %s (batch=%s)", os.path.basename(absolute_path), BATCH_FLUSH)

    celdas_by_code = _upsert_celdas(absolute_path, unidad_id)
    _upsert_titulares(absolute_path, caso_id, unidad_id, fuente_id)

    sheet_traf = _sheet_name_like(absolute_path, ["resultado", "traf"], 0)
    if sheet_traf is None:
        raise ValueError("No se encontró la hoja Resultado de Tráfico en el Excel.")
    df_traf = _read_excel_sheet(absolute_path, sheet_traf, 3, keywords=["imei", "imsi"])
    cols_traf = {_normalize_col_name(c): i for i, c in enumerate(df_traf.columns)}
    traf_columns = list(df_traf.columns)
    _log.info("GPRS: hoja tráfico=%s filas=%s cols=%s", sheet_traf, len(df_traf), list(traf_columns))

    AnalisisPuntoEvento.query.filter_by(fuente_id=fuente_id).delete(synchronize_session=False)

    total_filas_trafico = 0
    count_eventos = 0
    skipped_empty = 0
    pending = 0
    for row in df_traf.itertuples(index=False, name=None):
        total_filas_trafico += 1
        if total_filas_trafico % 5000 == 0:
            _log.info("GPRS: %s filas leídas, %s eventos", total_filas_trafico, count_eventos)
        payload = _payload_from_row_values(traf_columns, row)
        if not _payload_has_data(payload):
            skipped_empty += 1
            continue
        origin = _valor_str(_get_fuzzy(row, cols_traf, ["Número", "Numero"]), 64)
        fecha = _parse_fecha(_get_fuzzy(row, cols_traf, ["Fecha"]))
        hora = _normalize_hora_str(_get_fuzzy(row, cols_traf, ["Hora"]), 20)
        raw_cell = _normalize_celda_id(_get_fuzzy(row, cols_traf, ["Celda", "Celda ID", "CeldaID"]), 100)
        imei = _valor_str(_get_fuzzy(row, cols_traf, ["IMEI"]), 64)
        imsi = _valor_str(_get_fuzzy(row, cols_traf, ["IMSI"]), 64)

        event_dt = None
        if fecha is not None:
            event_dt = fecha
            try:
                if hora:
                    hh, mm, ss = [int(x) for x in hora.split(":")]
                    event_dt = datetime(fecha.year, fecha.month, fecha.day, hh, mm, ss)
            except Exception:
                pass

        dur = _get_fuzzy(row, cols_traf, ["Duracion", "Duración"])
        duration_sec = None
        try:
            if dur is not None and str(dur).strip() != "":
                duration_sec = int(float(str(dur).replace(",", ".")))
        except Exception:
            duration_sec = None

        bytes_up = None
        bytes_down = None
        volumen_kb = _get_fuzzy(row, cols_traf, ["Volumen (kb)", "Volumen(kb)", "Volumen KB"])
        try:
            if volumen_kb is not None and str(volumen_kb).strip() != "":
                kb = float(str(volumen_kb).replace(",", "."))
                if kb >= 0:
                    bytes_up = int(round(kb * 1024))
        except Exception:
            bytes_up = None

        e = AnalisisPuntoEvento(
            caso_id=caso_id,
            fuente_id=fuente_id,
            unidad_id=unidad_id,
            user_id=user_id,
            source_type="GPRS",
            event_dt=event_dt,
            event_date=event_dt.strftime("%Y-%m-%d") if event_dt else None,
            event_hour=event_dt.strftime("%H") if event_dt else None,
            origin_msisdn=origin,
            target_msisdn=None,
            imei=imei,
            imsi=imsi,
            event_type=_valor_str(_get_fuzzy(row, cols_traf, ["Tipo"]), 50) or "SESION",
            duration_sec=duration_sec,
            bytes_up=bytes_up,
            bytes_down=bytes_down,
            raw_cell_code=raw_cell,
            cell_id=celdas_by_code.get(raw_cell),
            raw_payload_json=json.dumps(payload, ensure_ascii=False),
        )
        db.session.add(e)
        count_eventos += 1
        pending = _flush_batch(pending + 1, label="GPRS")

    del df_traf
    fuente = db.session.get(AnalisisPuntoFuente, fuente_id) or fuente
    summary = {
        "source_type": "GPRS",
        "filas_trafico_leidas": int(total_filas_trafico),
        "eventos_importados": int(count_eventos),
        "filas_omitidas_vacias": int(skipped_empty),
        "filas_omitidas_total": int(skipped_empty),
    }
    fuente.upload_status = "PROCESSED"
    fuente.error_detail = json.dumps({"processing_summary": summary}, ensure_ascii=False)
    db.session.add(fuente)
    db.session.commit()
    _log.info("GPRS: listo %s eventos", count_eventos)
    return summary

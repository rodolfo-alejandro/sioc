"""
Servicios del módulo Sabana de Llamadas: procesamiento de archivos GPRS/VOZ y almacenamiento de imagen de sujeto.
"""
import os
import re
import json
import hashlib
import pandas as pd
from datetime import datetime, date
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.sabana_llamadas import (
    CargaLlamada, ResultadoTraficoGPRS, ResultadoTraficoVOZ, DatoTecnico
)

BATCH_FLUSH = 3000


def _flush_batch(pending: int) -> int:
    if pending >= BATCH_FLUSH:
        db.session.commit()
        return 0
    return pending


def _ensure_caso_sujeto_link(caso_id, sujeto_id, unidad_id, user_id):
    """Si hay caso y sujeto en una sábana, asegura fila en ap_caso_sujetos (sin duplicar)."""
    if not caso_id or not sujeto_id:
        return
    from app.models.analisis_puntos import AnalisisPuntoCasoSujeto
    ex = AnalisisPuntoCasoSujeto.query.filter_by(caso_id=caso_id, sujeto_id=sujeto_id).first()
    if ex:
        return
    db.session.add(
        AnalisisPuntoCasoSujeto(
            caso_id=caso_id,
            sujeto_id=sujeto_id,
            unidad_id=unidad_id,
            user_id=user_id,
            nota=None,
        )
    )
from app.services.audit import audit_log
from app.services.utils import get_safe_filename


# Extensiones permitidas para imagen de sujeto
IMAGEN_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

# Extensiones permitidas para archivos sabana
SABANA_EXTENSIONS = {'xls', 'xlsx', 'xlsm'}


def _save_sabana_file(file, unidad_id, suffix=''):
    """Guarda archivo Excel de sabana en instance/uploads/unidad_id/sabana/. Retorna (path_absoluto, safe_name)."""
    from flask import current_app
    if not file or not file.filename:
        raise ValueError("No hay archivo")
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in SABANA_EXTENSIONS:
        raise ValueError(f"Formato no permitido. Use: {', '.join(SABANA_EXTENSIONS)}")
    upload_folder = current_app.config['UPLOAD_FOLDER']
    # Asegurar ruta absoluta (soporta valores relativos como 'instance/uploads')
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(current_app.root_path, upload_folder)
    subdir = os.path.join(str(unidad_id), 'sabana')
    os.makedirs(os.path.join(upload_folder, subdir), exist_ok=True)
    safe_name = get_safe_filename(file.filename)
    if suffix:
        base, e = os.path.splitext(safe_name)
        safe_name = f"{base}_{suffix}{e}"
    full_path = os.path.join(upload_folder, subdir, safe_name)
    file.save(full_path)
    return full_path, safe_name


# Filas de encabezado en los Excel (valor por defecto / fallback)
# En muchos reportes vienen:
#  - Fila 0: Desde
#  - Fila 1: Hasta
#  - Fila 2: vacía
#  - Fila 3: encabezados reales (CeldaID, Lat, Long, etc.)
# Pero al re-guardar como .xlsx algunas veces se pierden esas primeras filas
# y los encabezados quedan en la fila 0. Por eso más abajo detectamos
# automáticamente la fila de encabezados, usando estos valores solo como
# fallback.
HEADER_ROW_TRAFICO = 3
HEADER_ROW_DATOS_TECNICOS = 3


def _find_datos_tecnicos_sheet_index(path, default_index=1):
    """
    Intenta localizar la hoja de 'Datos Técnicos' por nombre en el libro.
    Esto permite manejar archivos donde la hoja no está siempre en el índice 1
    (por ejemplo, cuando existe una hoja intermedia de 'Titulares').
    """
    try:
        ext = os.path.splitext(path)[1].lower()
        names = []
        if ext == '.xls':
            import xlrd
            try:
                book = xlrd.open_workbook(path, on_demand=True, ignore_workbook_corruption=True)
            except TypeError:
                book = xlrd.open_workbook(path, on_demand=True)
            names = [str(n or '').strip() for n in book.sheet_names()]
        else:
            # xlsx/xlsm
            xls = pd.ExcelFile(path)
            names = [str(n or '').strip() for n in xls.sheet_names]

        for idx, name in enumerate(names):
            nl = name.lower()
            if 'datos' in nl and 'tecnic' in nl:
                return idx
    except Exception:
        pass
    return default_index


def _read_excel_sheet(path, sheet_index, header_row, keywords=None):
    """
    Lee una hoja de Excel devolviendo un DataFrame.

    - Para .xls usa xlrd.open_workbook(ignore_workbook_corruption=True)
      y construye el DataFrame a mano.
    - Para .xlsx/.xlsm usa pandas.read_excel normal.
    """
    ext = os.path.splitext(path)[1].lower()

    # Detectar automáticamente la fila de encabezados buscando columnas clave
    # en las primeras filas. keywords puede ser, por ejemplo:
    #  - ['lat', 'long'] para Datos Técnicos
    #  - ['imei', 'imsi'] para Resultado de Tráfico
    def detect_header_index_rows(rows, default_idx, keywords_local):
        if not keywords_local:
            return default_idx
        kws = [k.lower() for k in keywords_local]
        # Claro (record/sábana) puede tener encabezados en fila 10–14.
        max_scan = min(20, len(rows))
        for r in range(max_scan):
            vals = [str(v).strip().lower() for v in rows[r]]
            for k in kws:
                if k in vals:
                    return r
        return default_idx

    if ext == '.xls':
        import xlrd

        # Algunas versiones de xlrd aceptan ignore_workbook_corruption y otras no.
        # Probamos con el flag y si no lo soporta, reintentamos sin él.
        try:
            book = xlrd.open_workbook(path, ignore_workbook_corruption=True)
        except TypeError:
            book = xlrd.open_workbook(path)
        sheet = book.sheet_by_index(sheet_index)

        # Leer una ventana de filas inicial para detectar encabezados
        preview_rows = []
        max_preview = min(20, sheet.nrows)
        for r in range(max_preview):
            preview_rows.append(sheet.row_values(r))
        hdr_idx = detect_header_index_rows(preview_rows, header_row, keywords)

        # Tomar desde hdr_idx hasta el final
        rows = []
        for r in range(hdr_idx, sheet.nrows):
            rows.append(sheet.row_values(r))
        if not rows:
            return pd.DataFrame()
        headers = [str(c) if c is not None else f'col_{i}' for i, c in enumerate(rows[0])]
        data = rows[1:]
        return pd.DataFrame(data, columns=headers)
    else:
        # xlsx/xlsm con openpyxl: leer sin encabezados, detectar fila y re-leer
        df_raw = pd.read_excel(path, sheet_name=sheet_index, header=None)
        preview_rows = df_raw.values.tolist()
        hdr_idx = detect_header_index_rows(preview_rows, header_row, keywords)
        return pd.read_excel(path, sheet_name=sheet_index, header=hdr_idx)


def _parse_fecha(valor):
    if pd.isna(valor) or valor is None:
        return None
    if isinstance(valor, str) and not valor.strip():
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        # Algunos Excel traen fecha sin hora
        return datetime(valor.year, valor.month, valor.day)
    try:
        # En las sábanas suele venir dd/mm/yyyy; dayfirst + mixed tolera ISO u otros en la misma columna.
        dt = pd.to_datetime(valor, errors='coerce', dayfirst=True, format='mixed')
        if pd.isna(dt) or dt is None:
            return None
        # pandas Timestamp -> datetime nativo (evita NaT/formatos raros)
        try:
            return dt.to_pydatetime()
        except Exception:
            return dt
    except Exception:
        return None


def _valor_str(val, max_len=500):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s[:max_len] if s else None


def _normalize_celda_id(val, max_len=100):
    """
    Normaliza IDs de celda para que matcheen entre:
    - Tráfico (GPRS.celda / VOZ.celda_id)
    - Datos técnicos (DatoTecnico.celda_id)

    Problemas típicos en Excel:
    - valores numéricos como 123.0
    - espacios / strings vacíos
    """
    if pd.isna(val) or val is None:
        return None
    # Si viene numérico (ej. 123.0), volverlo entero si aplica
    try:
        if isinstance(val, (int, float)) and not pd.isna(val):
            f = float(val)
            if f.is_integer():
                s = str(int(f)).strip()
                s = s.upper()
                return s[:max_len] if s else None
    except Exception:
        pass
    s = str(val).strip()
    if not s:
        return None
    s = s.replace(',', '.')  # por si viene "123,0"
    if s.endswith('.0'):
        s = s[:-2]
    # Segundo intento: si quedó como float entero en string
    try:
        f2 = float(s)
        if f2.is_integer():
            s = str(int(f2)).strip()
    except Exception:
        pass
    s = s.strip().upper()
    return s[:max_len] if s else None


def _normalize_hora_str(val, max_len=20):
    """
    Normaliza hora a formato 'HH:MM:SS' (zero-padded) para:
    - ordenar cronológicamente correctamente
    - que filtros por hora funcionen con comparación lexicográfica (substr)
    """
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime('%H:%M:%S')
    try:
        import datetime as _dt
        if isinstance(val, _dt.time):
            return val.strftime('%H:%M:%S')
    except Exception:
        pass
    s = str(val).strip()
    if not s:
        return None
    # Quitar milisegundos si vienen (ej. 09:05:00.000)
    if '.' in s:
        s = s.split('.', 1)[0].strip()
    parts = s.split(':')
    try:
        hh = int(parts[0]) if len(parts) > 0 and parts[0] != '' else 0
        mm = int(parts[1]) if len(parts) > 1 and parts[1] != '' else 0
        ss = int(parts[2]) if len(parts) > 2 and parts[2] != '' else 0
        out = f"{hh:02d}:{mm:02d}:{ss:02d}"
        return out[:max_len] if out else None
    except Exception:
        # Fallback: guardar lo que venga, pero recortado
        return _valor_str(s, max_len=max_len)


def _extras_value(v):
    """Convierte valores de pandas/Excel a tipos serializables para JSON (sin perder columnas)."""
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if v is None:
        return None
    # timestamps/fechas
    try:
        if isinstance(v, pd.Timestamp):
            dt = v.to_pydatetime()
            return dt.isoformat(sep=' ')
    except Exception:
        pass
    if isinstance(v, datetime):
        return v.isoformat(sep=' ')
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day).isoformat(sep=' ')
    # numpy scalars / ints / floats / bools
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            f = float(v)
            # si es entero exacto, guardar como int para legibilidad
            return int(f) if f.is_integer() else f
        if isinstance(v, (np.bool_,)):
            return bool(v)
    except Exception:
        pass
    if isinstance(v, bool):
        return bool(v)
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return int(v) if float(v).is_integer() else float(v)
    if isinstance(v, str):
        s = v.strip()
        return s if s != '' else None
    # fallback (objetos)
    return str(v)


def _row_extras(row):
    """
    Devuelve dict con TODAS las columnas de la fila (sin omitir ninguna).
    Se guarda en DB como JSON en el campo `extras`.
    """
    d = {}
    seen = {}
    # Iterar por posición para soportar columnas duplicadas sin colisionar.
    try:
        keys = list(getattr(row, 'index', []))
        for i, k in enumerate(keys):
            v = row.iloc[i]
            # Preservar el nombre tal como viene del Excel (incluye espacios si existen).
            kk = '' if k is None else str(k)
            try:
                if isinstance(k, float) and pd.isna(k):
                    kk = ''
            except Exception:
                pass
            if kk.strip() == '':
                kk = f'col_{i}'
            # Si hay columnas repetidas, desambiguar sin perder datos.
            if kk in seen:
                seen[kk] += 1
                kk2 = f"{kk}__dup{seen[kk]}"
            else:
                seen[kk] = 0
                kk2 = kk
            d[kk2] = _extras_value(v)
        return d
    except Exception:
        pass
    # Fallback genérico (sin garantías de columnas duplicadas)
    try:
        for k, v in row.to_dict().items():
            kk = '' if k is None else str(k)
            if kk.strip() == '':
                kk = 'col'
            if kk in seen:
                seen[kk] += 1
                kk = f"{kk}__dup{seen[kk]}"
            else:
                seen[kk] = 0
            d[kk] = _extras_value(v)
    except Exception:
        return {}
    return d


def _extract_rango_desde_hasta(path, sheet_index=0):
    """
    Lee las primeras filas del Excel (sheet 0) para extraer:
    - Desde: dd/mm/yyyy - HH:MM:SS
    - Hasta: dd/mm/yyyy - HH:MM:SS
    """
    try:
        df = pd.read_excel(path, sheet_name=sheet_index, header=None)
        vals = df.head(10).fillna('').values.tolist()
        desde = None
        hasta = None
        for row in vals:
            for cell in row:
                s = str(cell).strip()
                if not s:
                    continue
                if s.lower().startswith('desde:'):
                    desde = s.split(':', 1)[-1].strip()
                if s.lower().startswith('hasta:'):
                    hasta = s.split(':', 1)[-1].strip()
        def parse_dt(s):
            if not s:
                return None
            # Ej: "01/01/2026 - 00:00:00"
            s = s.replace(' - ', ' ').strip()
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    pass
            return None
        return parse_dt(desde), parse_dt(hasta)
    except Exception:
        return None, None


def _read_criterio_busqueda_text(path, sheet_index=2):
    try:
        df = pd.read_excel(path, sheet_name=sheet_index, header=None)
        lines = []
        for v in df.iloc[:, 0].fillna('').tolist():
            s = str(v).strip()
            if s:
                lines.append(s)
        return "\n".join(lines) if lines else None
    except Exception:
        return None


def _normalize_col_name(col):
    if col is None or (isinstance(col, float) and pd.isna(col)):
        return ''
    return str(col).strip()


def _parse_float(val):
    """
    Convierte valores de lat/long a float soportando:
    - None / NaN
    - cadenas con coma decimal (ej. '-26,1234')
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        # Reemplazar coma decimal por punto
        s = s.replace(',', '.')
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def procesar_archivo_gprs(file, unidad_id, user_id, sujeto_id=None, operadora=None, caso_id=None):
    """
    Procesa un archivo .xls/.xlsx de sabana GPRS.
    Retorna (carga, cantidad_trafico, cantidad_datos_tecnicos, error_msg).
    """
    try:
        file_path, safe_name = _save_sabana_file(file, unidad_id, suffix='gprs')
    except Exception as e:
        return None, 0, 0, str(e)

    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as rf:
        for chunk in iter(lambda: rf.read(8192), b''):
            sha256.update(chunk)

    carga = CargaLlamada(
        unidad_id=unidad_id,
        user_id=user_id,
        sujeto_id=sujeto_id or None,
        caso_id=caso_id or None,
        tipo='gprs',
        operadora=(str(operadora).strip().upper() if operadora else None),
        nombre_archivo=safe_name,
        sha256=sha256.hexdigest(),
        size_bytes=os.path.getsize(file_path),
    )
    db.session.add(carga)
    db.session.flush()
    # Rango / criterio (si existe en el archivo)
    rd, rh = _extract_rango_desde_hasta(file_path, sheet_index=0)
    carga.rango_desde = rd
    carga.rango_hasta = rh
    carga.criterio_busqueda = _read_criterio_busqueda_text(file_path, sheet_index=2)

    total_filas_trafico = 0
    skipped_trafico_empty = 0
    count_trafico = 0
    count_tecnicos = 0
    pending = 0

    try:
        # Resultado de Tráfico: buscar encabezados por columnas IMEI/IMSI
        df_trafico = _read_excel_sheet(file_path, sheet_index=0, header_row=HEADER_ROW_TRAFICO, keywords=['imei', 'imsi'])
        cols = {_normalize_col_name(c): i for i, c in enumerate(df_trafico.columns)}

        def get(row, names, default=None):
            for n in names:
                if n in cols:
                    val = row.iloc[cols[n]] if cols[n] < len(row) else default
                    return val if not pd.isna(val) else default
            return default

        for idx, row in df_trafico.iterrows():
            total_filas_trafico += 1
            extras = _row_extras(row)
            # Saltar filas totalmente vacías (pero no filtrar por IMEI; queremos guardar todo)
            if not any(v is not None for v in extras.values()):
                skipped_trafico_empty += 1
                continue
            r = ResultadoTraficoGPRS(carga_id=carga.id)
            r.imei = _valor_str(get(row, ['IMEI', 'imei']), 50)
            r.imsi = _valor_str(get(row, ['IMSI', 'imsi']), 50)
            r.numero = _valor_str(get(row, [
                'N�mero',  # como viene en los Excel ejemplo
                'Número', 'Numero', 'Nro', 'N°', 'Nº',
                'MSISDN', 'msisdn',
                'Teléfono', 'Telefono', 'Teléfonos', 'Telefonos',
                'Línea', 'Linea', 'Número línea', 'Numero linea',
                'Número origen', 'Numero origen', 'Origen',
                'Número destino', 'Numero destino', 'Destino',
            ]), 64)
            r.fecha = _parse_fecha(get(row, ['Fecha', 'fecha']))
            r.hora = _normalize_hora_str(get(row, ['Hora', 'hora']), 20)
            r.duracion = _valor_str(get(row, ['Duracion', 'duracion']), 50)
            r.ip = _valor_str(get(row, ['IP', 'ip']), 100)
            r.ip_dual_stack = _valor_str(get(row, ['IP Dual Stack', 'IP Dual Stack']), 100)
            r.volumen_kb = _valor_str(get(row, ['Volumen (kb)', 'Volumen (kb)']), 50)
            r.celda = _normalize_celda_id(get(row, ['Celda', 'celda']), 100)
            r.celda_direccion = _valor_str(get(row, ['Celda direccion', 'Celda direccion']), 255)
            r.celda_localidad = _valor_str(get(row, ['Celda localidad', 'Celda localidad']), 200)
            r.celda_provincia = _valor_str(get(row, ['Celda provincia', 'Celda provincia']), 200)
            r.ip_wifi = _valor_str(get(row, ['IP WIFI', 'IP WIFI']), 100)
            # Guardar TODAS las columnas originales
            r.extras = json.dumps(extras, ensure_ascii=False, default=str)
            db.session.add(r)
            count_trafico += 1
            pending = _flush_batch(pending + 1)

        # Datos técnicos: localizar hoja por nombre (por si hay hoja intermedia "Titulares")
        idx_tec = _find_datos_tecnicos_sheet_index(file_path, default_index=1)
        df_tec = _read_excel_sheet(file_path, sheet_index=idx_tec, header_row=HEADER_ROW_DATOS_TECNICOS, keywords=['lat', 'long'])
        cols_tec = {_normalize_col_name(c): i for i, c in enumerate(df_tec.columns)}

        def get_tec(row, names):
            for n in names:
                if n in cols_tec:
                    val = row.iloc[cols_tec[n]] if cols_tec[n] < len(row) else None
                    return val if not pd.isna(val) else None
            return None

        for idx, row in df_tec.iterrows():
            extras = _row_extras(row)
            rango = get_tec(row, ['Rango de consulta', 'Rango de consulta'])
            celda_id = get_tec(row, ['CeldaID', 'CeldaID'])
            lat = get_tec(row, ['Lat', 'lat'])
            lon = get_tec(row, ['Long', 'long'])
            # Guardar filas aunque no tengan coords (se filtran en el mapa), pero saltar filas vacías.
            if not any(v is not None for v in extras.values()):
                continue
            celda_norm = _normalize_celda_id(celda_id, 100)
            dt_lat = _parse_float(lat)
            dt_lon = _parse_float(lon)

            # Upsert lógico: si ya existe un técnico para esa celda en ESTA carga y le faltan coords,
            # completar sin duplicar (evita basura y mismatches).
            dt = None
            try:
                if celda_norm and (dt_lat is not None or dt_lon is not None):
                    dt = DatoTecnico.query.filter_by(carga_id=carga.id, tipo='gprs', celda_id=celda_norm).filter(
                        (DatoTecnico.lat.is_(None)) | (DatoTecnico.long.is_(None))
                    ).order_by(DatoTecnico.id.asc()).first()
            except Exception:
                dt = None
            if not dt:
                dt = DatoTecnico(carga_id=carga.id, tipo='gprs')
                dt.celda_id = celda_norm
            dt.rango_consulta = _valor_str(rango, 100)
            dt.celda_direccion = _valor_str(get_tec(row, ['Celda Direccion', 'Celda Direccion']), 255)
            dt.celda_loc = _valor_str(get_tec(row, ['Celda Loc', 'Celda Loc']), 200)
            dt.celda_prov = _valor_str(get_tec(row, ['Celda Prov', 'Celda Prov']), 200)
            dt.rad_cob_km = _valor_str(get_tec(row, ['Rad Cob (KM)', 'Rad Cob (KM)']), 50)
            dt.azimuth = _valor_str(get_tec(row, ['Azimuth', 'azimuth']), 50)
            if dt.lat is None and dt_lat is not None:
                dt.lat = dt_lat
            if dt.long is None and dt_lon is not None:
                dt.long = dt_lon
            dt.a_horiz = _valor_str(get_tec(row, ['A. Horiz', 'A. Horiz']), 50)
            dt.a_vert = _valor_str(get_tec(row, ['A. Vert', 'A. Vert']), 50)
            # Preferir no pisar extras ya existentes si solo estamos completando coords
            if not dt.extras:
                dt.extras = json.dumps(extras, ensure_ascii=False, default=str)
            db.session.add(dt)
            count_tecnicos += 1

        carga.processing_detail = json.dumps({
            'source_type': 'GPRS',
            'filas_trafico_leidas': int(total_filas_trafico),
            'eventos_importados': int(count_trafico),
            'filas_omitidas_vacias': int(skipped_trafico_empty),
            'filas_omitidas_total': int(skipped_trafico_empty),
            'datos_tecnicos_importados': int(count_tecnicos),
        }, ensure_ascii=False)
        _ensure_caso_sujeto_link(caso_id, sujeto_id, unidad_id, user_id)
        db.session.commit()
        audit_log('SABANA_GPRS_UPLOAD', f'Carga GPRS {carga.id}: {count_trafico} tráfico, {count_tecnicos} datos técnicos', user_id=user_id)
        return carga, count_trafico, count_tecnicos, None
    except Exception as e:
        db.session.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None, 0, 0, str(e)


def procesar_archivo_voz(file, unidad_id, user_id, sujeto_id=None, operadora=None, caso_id=None):
    """
    Procesa un archivo .xls/.xlsx de sabana VOZ.
    Retorna (carga, cantidad_trafico, cantidad_datos_tecnicos, error_msg).
    """
    try:
        file_path, safe_name = _save_sabana_file(file, unidad_id, suffix='voz')
    except Exception as e:
        return None, 0, 0, str(e)

    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as rf:
        for chunk in iter(lambda: rf.read(8192), b''):
            sha256.update(chunk)

    carga = CargaLlamada(
        unidad_id=unidad_id,
        user_id=user_id,
        sujeto_id=sujeto_id or None,
        caso_id=caso_id or None,
        tipo='voz',
        operadora=(str(operadora).strip().upper() if operadora else None),
        nombre_archivo=safe_name,
        sha256=sha256.hexdigest(),
        size_bytes=os.path.getsize(file_path),
    )
    db.session.add(carga)
    db.session.flush()
    rd, rh = _extract_rango_desde_hasta(file_path, sheet_index=0)
    carga.rango_desde = rd
    carga.rango_hasta = rh
    carga.criterio_busqueda = _read_criterio_busqueda_text(file_path, sheet_index=2)

    total_filas_trafico = 0
    skipped_trafico_empty = 0
    count_trafico = 0
    count_tecnicos = 0
    pending = 0

    try:
        df_trafico = _read_excel_sheet(file_path, sheet_index=0, header_row=HEADER_ROW_TRAFICO, keywords=['imei', 'imsi'])
        cols = {_normalize_col_name(c): i for i, c in enumerate(df_trafico.columns)}

        def get(row, names):
            for n in names:
                if n in cols:
                    val = row.iloc[cols[n]] if cols[n] < len(row) else None
                    return val if not pd.isna(val) else None
            return None

        for idx, row in df_trafico.iterrows():
            total_filas_trafico += 1
            extras = _row_extras(row)
            if not any(v is not None for v in extras.values()):
                skipped_trafico_empty += 1
                continue
            r = ResultadoTraficoVOZ(carga_id=carga.id)
            r.imei = _valor_str(get(row, ['IMEI', 'imei']), 50)
            r.imsi = _valor_str(get(row, ['IMSI', 'imsi']), 50)
            r.numero = _valor_str(get(row, [
                'N�mero',
                'Número', 'Numero', 'Nro', 'N°', 'Nº',
                'MSISDN', 'msisdn',
                'Teléfono', 'Telefono', 'Telefonos', 'Teléfonos',
                'Línea', 'Linea',
            ]), 64)
            r.fecha = _parse_fecha(get(row, ['Fecha', 'fecha']))
            r.hora = _normalize_hora_str(get(row, ['Hora', 'hora']), 20)
            r.tipo = _valor_str(get(row, ['Tipo', 'tipo']), 50)
            r.duracion = _valor_str(get(row, ['Duracion', 'duracion']), 50)
            # En distintos reportes el "número" puede venir con nombres distintos.
            r.otro = _valor_str(get(row, [
                'Otro', 'otro',
                'Número', 'Numero', 'Nro', 'N°', 'Nº',
                'Número destino', 'Numero destino', 'Destino',
                'B Number', 'B-Number', 'B_Number',
                'MSISDN', 'msisdn',
                'Teléfono', 'Telefono', 'Telefonos', 'Teléfonos',
                'Llamado', 'Llamante', 'Número llamado', 'Numero llamado',
            ]), 255)
            r.celda_id = _normalize_celda_id(get(row, ['Celda ID', 'Celda ID']), 100)
            r.celda_calle_altura = _valor_str(get(row, ['Celda Calle Altura', 'Celda Calle Altura']), 255)
            r.celda_localidad = _valor_str(get(row, ['Celda Localidad', 'Celda localidad']), 200)
            r.celda_provincia = _valor_str(get(row, ['Celda Provincia ', 'Celda Provincia', 'Celda provincia']), 200)
            r.extras = json.dumps(extras, ensure_ascii=False, default=str)
            db.session.add(r)
            count_trafico += 1
            pending = _flush_batch(pending + 1)

        idx_tec = _find_datos_tecnicos_sheet_index(file_path, default_index=1)
        df_tec = _read_excel_sheet(file_path, sheet_index=idx_tec, header_row=HEADER_ROW_DATOS_TECNICOS, keywords=['lat', 'long'])
        cols_tec = {_normalize_col_name(c): i for i, c in enumerate(df_tec.columns)}

        def get_tec(row, names):
            for n in names:
                if n in cols_tec:
                    val = row.iloc[cols_tec[n]] if cols_tec[n] < len(row) else None
                    return val if not pd.isna(val) else None
            return None

        for idx, row in df_tec.iterrows():
            extras = _row_extras(row)
            celda_id = get_tec(row, ['CeldaID', 'CeldaID'])
            lat = get_tec(row, ['Lat', 'lat'])
            lon = get_tec(row, ['Long', 'long'])
            if not any(v is not None for v in extras.values()):
                continue
            celda_norm = _normalize_celda_id(celda_id, 100)
            dt_lat = _parse_float(lat)
            dt_lon = _parse_float(lon)

            dt = None
            try:
                if celda_norm and (dt_lat is not None or dt_lon is not None):
                    dt = DatoTecnico.query.filter_by(carga_id=carga.id, tipo='voz', celda_id=celda_norm).filter(
                        (DatoTecnico.lat.is_(None)) | (DatoTecnico.long.is_(None))
                    ).order_by(DatoTecnico.id.asc()).first()
            except Exception:
                dt = None
            if not dt:
                dt = DatoTecnico(carga_id=carga.id, tipo='voz')
                dt.celda_id = celda_norm
            dt.rango_consulta = _valor_str(get_tec(row, ['Rango de consulta', 'Rango de consulta']), 100)
            dt.celda_direccion = _valor_str(get_tec(row, ['Celda Direccion', 'Celda Direccion']), 255)
            dt.celda_loc = _valor_str(get_tec(row, ['Celda Loc', 'Celda Loc']), 200)
            dt.celda_prov = _valor_str(get_tec(row, ['Celda Prov', 'Celda Prov']), 200)
            dt.rad_cob_km = _valor_str(get_tec(row, ['Rad Cob (KM)', 'Rad Cob (KM)']), 50)
            dt.azimuth = _valor_str(get_tec(row, ['Azimuth', 'azimuth']), 50)
            if dt.lat is None and dt_lat is not None:
                dt.lat = dt_lat
            if dt.long is None and dt_lon is not None:
                dt.long = dt_lon
            dt.a_horiz = _valor_str(get_tec(row, ['A. Horiz', 'A. Horiz']), 50)
            dt.a_vert = _valor_str(get_tec(row, ['A. Vert', 'A. Vert']), 50)
            if not dt.extras:
                dt.extras = json.dumps(extras, ensure_ascii=False, default=str)
            db.session.add(dt)
            count_tecnicos += 1

        carga.processing_detail = json.dumps({
            'source_type': 'VOZ',
            'filas_trafico_leidas': int(total_filas_trafico),
            'eventos_importados': int(count_trafico),
            'filas_omitidas_vacias': int(skipped_trafico_empty),
            'filas_omitidas_total': int(skipped_trafico_empty),
            'datos_tecnicos_importados': int(count_tecnicos),
        }, ensure_ascii=False)
        _ensure_caso_sujeto_link(caso_id, sujeto_id, unidad_id, user_id)
        db.session.commit()
        audit_log('SABANA_VOZ_UPLOAD', f'Carga VOZ {carga.id}: {count_trafico} tráfico, {count_tecnicos} datos técnicos', user_id=user_id)
        return carga, count_trafico, count_tecnicos, None
    except Exception as e:
        db.session.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return None, 0, 0, str(e)


def guardar_imagen_sujeto(file, unidad_id, sujeto_id=None):
    """
    Guarda la imagen de un sujeto. Retorna (ruta_relativa, None) o (None, error_msg).
    ruta_relativa es relativa a UPLOAD_FOLDER para almacenar en el modelo.
    """
    if not file or not file.filename:
        return None, "No se seleccionó archivo"
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in IMAGEN_EXTENSIONS:
        return None, f"Formato no permitido. Use: {', '.join(IMAGEN_EXTENSIONS)}"
    from flask import current_app
    upload_folder = current_app.config['UPLOAD_FOLDER']
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(current_app.root_path, upload_folder)
    subdir = os.path.join(str(unidad_id), 'sujetos')
    os.makedirs(os.path.join(upload_folder, subdir), exist_ok=True)
    import time
    safe = secure_filename(file.filename)
    base, _ = os.path.splitext(safe)
    safe_name = f"{int(time.time())}_{base}.{ext}"
    rel_path = os.path.join(subdir, safe_name)
    full_path = os.path.join(upload_folder, rel_path)
    file.save(full_path)
    return rel_path.replace('\\', '/'), None

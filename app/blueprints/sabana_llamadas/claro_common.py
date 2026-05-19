"""
Utilidades compartidas para importación Claro (sábana y record).
"""
import re
import unicodedata

import pandas as pd

CLARO_SHEET_SALIENTES = 'Salientes'
CLARO_SHEET_ENTRANTES = 'Entrantes'
CLARO_SHEET_CLIENTES = 'Clientes'
CLARO_SHEET_IMEI_TERMINAL = 'imei Terminal'
CLARO_SHEET_IMEI_TRACK = 'imei track'

HEADER_ROW_TRAFICO_CLARO = 10
HEADER_ROW_CLIENTES_CLARO = 16
HEADER_ROW_IMEI_CLARO = 13


def _norm_text(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip().lower()
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )


def destino_es_gprs_claro(destino, record=False):
    """
    Sábana: solo Conexión Móvil.
    Record: conexión móvil + tráfico de datos (tráfico incluido/gratuito, WhatsApp, Internet, APN, etc.).
    """
    s = _norm_text(destino)
    if not s or s == 'nan':
        return False
    if 'conexion movil' in s:
        return True
    if not record:
        return False
    for token in ('trafico', 'whatsapp', 'internet', ' apn', 'm2m', ' kb ', 'datos', 'gprs'):
        if token in s:
            return True
    return False


def es_formato_claro_trafico(path):
    """Hojas Salientes + Entrantes (base común sábana y record)."""
    try:
        xls = pd.ExcelFile(path)
        names = {str(n or '').strip().lower() for n in xls.sheet_names}
        return (
            CLARO_SHEET_SALIENTES.lower() in names
            and CLARO_SHEET_ENTRANTES.lower() in names
        )
    except Exception:
        return False


def es_formato_claro_sabana(path):
    """Sábana Claro: tráfico + hojas de titulares/IMEI."""
    if not es_formato_claro_trafico(path):
        return False
    try:
        xls = pd.ExcelFile(path)
        names = [str(n or '').strip().lower() for n in xls.sheet_names]
        return any('clientes' in n or 'imei' in n for n in names)
    except Exception:
        return False


def es_formato_claro_record(path):
    """Record Claro: solo Salientes + Entrantes (sin Clientes/IMEI)."""
    if not es_formato_claro_trafico(path):
        return False
    try:
        xls = pd.ExcelFile(path)
        names = [str(n or '').strip().lower() for n in xls.sheet_names]
        return not any('clientes' in n or 'imei' in n for n in names)
    except Exception:
        return False


def sheet_index(path, target_name):
    xls = pd.ExcelFile(path)
    tl = target_name.strip().lower()
    for i, n in enumerate(xls.sheet_names):
        if str(n or '').strip().lower() == tl:
            return i
    return None


def parse_periodo_claro(texto):
    if not texto:
        return None, None
    from app.blueprints.sabana_llamadas.services import _parse_fecha
    s = str(texto).strip()
    parts = re.split(r'\s+al\s+', s, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        return _parse_fecha(s), None
    return _parse_fecha(parts[0].strip()), _parse_fecha(parts[1].strip())


def extract_metadata_claro(path, label_lineas=('Lineas Claro',), label_celdas=('Celdas',)):
    """Lee líneas/celdas y periodo del encabezado de Salientes."""
    lineas = None
    periodo_txt = None
    try:
        idx = sheet_index(path, CLARO_SHEET_SALIENTES)
        if idx is None:
            return None, None, None, None
        df = pd.read_excel(path, sheet_name=idx, header=None)
        labels_lineas = {x.lower() for x in label_lineas}
        labels_celdas = {x.lower() for x in label_celdas}
        for row in df.head(14).values.tolist():
            for i, cell in enumerate(row):
                label = str(cell).strip() if pd.notna(cell) else ''
                ll = label.lower()
                if ll in labels_lineas and i + 1 < len(row):
                    v = row[i + 1]
                    if pd.notna(v):
                        lineas = str(v).strip()
                if ll in labels_celdas and i + 1 < len(row):
                    v = row[i + 1]
                    if pd.notna(v):
                        lineas = lineas or str(v).strip()
                if label == 'Periodo' and i + 1 < len(row):
                    v = row[i + 1]
                    if pd.notna(v):
                        periodo_txt = str(v).strip()
    except Exception:
        pass
    rd, rh = parse_periodo_claro(periodo_txt)
    return lineas, periodo_txt, rd, rh


def make_col_getter(cols_map):
    def get(row, names, default=None):
        for n in names:
            if n in cols_map:
                i = cols_map[n]
                val = row.iloc[i] if i < len(row) else default
                return val if not pd.isna(val) else default
        return default
    return get

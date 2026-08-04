"""
Utilidades y detección de sábana Movistar (formato TEMIS / Solicitud).
Una hoja plana: Fecha Evento, Nro A/B, Tipo Trafico, Celda, coordenadas, etc.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

# Columnas canónicas del reporte TEMIS
MOVISTAR_HEADER_MARKERS = (
    "fecha evento",
    "nro a",
    "tipo trafico",
    "celda",
)


def _norm_text(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _norm_header(val) -> str:
    return re.sub(r"\s+", " ", _norm_text(val)).strip()


def es_formato_movistar(path: str) -> bool:
    """
    True si el Excel es un reporte TEMIS Movistar (headers típicos o banner Sistema TEMIS).
    """
    try:
        df = pd.read_excel(path, header=None, nrows=25)
    except Exception:
        return False
    if df is None or df.empty:
        return False

    banner = False
    for row in df.head(8).values.tolist():
        for cell in row:
            t = _norm_text(cell)
            if "temis" in t or "reporte de trafico" in t or "reporte de tráfico" in t:
                banner = True
            if t.startswith("solicitud n"):
                banner = True

    header_row, colmap = detect_header_and_columns(df)
    if header_row is None or not colmap:
        return False
    keys = set(colmap.keys())
    has_core = (
        any("fecha" in k and "evento" in k for k in keys)
        and any(k in keys or k.startswith("nro a") or k == "nro a" for k in keys)
        and any("tipo" in k and "traf" in k for k in keys)
        and any(k == "celda" or k.startswith("celda") for k in keys)
    )
    # También sin "tipo trafico" exacto si hay Nro A + Celda + Fecha Evento
    has_minimal = (
        any("fecha" in k for k in keys)
        and any("nro a" in k or k == "nro a" for k in keys)
        and any("celda" in k for k in keys)
        and any("lat" in k for k in keys)
    )
    return bool(has_core or (banner and has_minimal) or (has_core and banner) or has_core)


def detect_header_and_columns(df: pd.DataFrame) -> tuple[int | None, dict[str, int]]:
    """
    Busca la fila de encabezados TEMIS y devuelve (índice_fila, {header_norm: col_idx}).
    """
    if df is None or df.empty:
        return None, {}
    max_scan = min(30, len(df))
    for i in range(max_scan):
        row = df.iloc[i].tolist()
        colmap: dict[str, int] = {}
        for j, cell in enumerate(row):
            h = _norm_header(cell)
            if not h:
                continue
            # primera coincidencia por nombre
            if h not in colmap:
                colmap[h] = j
        joined = " ".join(colmap.keys())
        score = 0
        if "fecha evento" in joined or ("fecha" in joined and "evento" in joined):
            score += 2
        if "nro a" in colmap or "nro a" in joined:
            score += 2
        if "tipo trafico" in joined or "tipo tráfico" in joined:
            score += 2
        if "celda" in colmap:
            score += 1
        if "imsi" in colmap:
            score += 1
        if score >= 4:
            return i, colmap
    return None, {}


def extract_metadata_movistar(df: pd.DataFrame) -> dict:
    """Solicitud, criterio y valor del encabezado TEMIS (filas previas al header)."""
    meta = {
        "solicitud": None,
        "criterio": None,
        "valor": None,
        "banner": None,
    }
    header_row, _ = detect_header_and_columns(df)
    limit = header_row if header_row is not None else min(10, len(df))
    for i in range(limit):
        cells = [c for c in df.iloc[i].tolist() if pd.notna(c) and str(c).strip()]
        if not cells:
            continue
        line = " ".join(str(c).strip() for c in cells)
        ln = _norm_text(line)
        if meta["banner"] is None and ("temis" in ln or "reporte" in ln):
            meta["banner"] = line[:200]
        m = re.search(r"solicitud\s*n[^\d]{0,6}(\d+)", line, re.I)
        if m:
            meta["solicitud"] = m.group(1)
        m = re.search(r"criterio\s*[:=]\s*(.+)", line, re.I)
        if m:
            meta["criterio"] = m.group(1).strip()[:120]
        m = re.search(r"valor\s*[:=]\s*(.+)", line, re.I)
        if m:
            meta["valor"] = m.group(1).strip()[:80]
    return meta


def parse_coord_movistar(val) -> float | None:
    """
    Lat/Lon Movistar suelen venir como enteros sin punto decimal
    (-26387491 → -26.387491). Si ya viene decimal (< |1000|), no escala.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        if isinstance(val, str):
            s = val.strip().replace(",", ".")
            if not s or s.lower() in ("nan", "none", "null"):
                return None
            num = float(s)
        else:
            num = float(val)
    except (TypeError, ValueError):
        return None
    if abs(num) > 180:
        # escala típica ×1e6
        return num / 1_000_000.0
    return num


def tipo_es_datos(tipo_trafico: str) -> bool:
    t = _norm_text(tipo_trafico)
    return any(x in t for x in ("dato", "gprs", "datos", "data"))


def tipo_es_voz(tipo_trafico: str) -> bool:
    t = _norm_text(tipo_trafico)
    if tipo_es_datos(tipo_trafico):
        return False
    return any(
        x in t
        for x in ("llamada", "voz", "sms", "mms", "ussd", "moc", "mtc", "llam")
    ) or bool(t)


def map_direccion_evento(val: str) -> str:
    """SALIENTE / ENTRANTE / OTROS → etiqueta normalizada para campo tipo VOZ."""
    t = _norm_text(val)
    if "saliente" in t or t in ("mo", "orig"):
        return "Saliente"
    if "entrante" in t or t in ("mt", "term"):
        return "Entrante"
    if t:
        return str(val).strip()[:50]
    return ""


def col_index(colmap: dict[str, int], *candidates: str) -> int | None:
    """Busca índice de columna por candidatos normalizados / substrings."""
    if not colmap:
        return None
    norms = {_norm_header(c): c for c in candidates}
    for cand in candidates:
        key = _norm_header(cand)
        if key in colmap:
            return colmap[key]
    # substring match
    for key, idx in colmap.items():
        for cand in candidates:
            ck = _norm_header(cand)
            if ck and (ck in key or key in ck):
                return idx
    return None


def cell_at(row, idx: int | None):
    if idx is None or idx < 0:
        return None
    try:
        val = row.iloc[idx] if hasattr(row, "iloc") else row[idx]
        if pd.isna(val):
            return None
        return val
    except Exception:
        return None

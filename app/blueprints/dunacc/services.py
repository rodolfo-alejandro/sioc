"""
Servicios del módulo DUNACC: importación de planillas Excel y geocodificación.

El importador es tolerante con el formato: detecta la fila de encabezados buscando
columnas conocidas (DEPENDENCIA / CARÁTULA / LUGAR…) y mapea por nombre normalizado.
Si la planilla trae LATITUD / LONGITUD las toma; si no, quedan vacías para cargar a mano.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, time

try:
    import openpyxl
except Exception:  # pragma: no cover
    openpyxl = None

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

_USER_AGENT = "Mozilla/5.0 (compatible; SIOC-DUNACC/1.0)"

# Nombres de columna normalizados -> campo del registro.
_COLMAP = {
    "n": "numero",
    "nro": "numero",
    "numero": "numero",
    "n ap": "numero_ap",
    "nap": "numero_ap",
    "n de ap": "numero_ap",
    "numero ap": "numero_ap",
    "ap": "numero_ap",
    "dependencia": "dependencia",
    "caratula": "caratula",
    "fecha": "fecha",
    "hora": "hora",
    "lugar": "lugar",
    "direccion": "lugar",
    "domicilio": "lugar",
    "informante": "informante",
    "acusado": "acusado",
    "breve relato": "relato",
    "relato": "relato",
    # --- Columnas de la planilla del CCO 911 ---
    "fecha y hora": "fecha_hora",
    "tipificacion": "caratula",
    "comentario alertante": "relato",
    "comentario": "relato",
    "ddp": "ddp",
    "ano": "anio",
    "anio": "anio",
    "lat": "lat",
    "latitud": "lat",
    "long": "lon",
    "lon": "lon",
    "lng": "lon",
    "longitud": "lon",
    "coordenadas": "coords",
    "lat long": "coords",
    "latitud longitud": "coords",
}

_CAMPOS_TEXTO = ("numero", "numero_ap", "dependencia", "caratula", "informante", "acusado")


def dependencias_faltantes() -> list[str]:
    faltan = []
    if openpyxl is None:
        faltan.append("openpyxl")
    return faltan


def _norm(v) -> str:
    s = "" if v is None else str(v)
    s = s.replace("°", "").replace("º", "").replace("N°", "n")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def _to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _parse_fecha(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_hora(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.strftime("%H:%M")
    if isinstance(v, time):
        return v.strftime("%H:%M")
    s = str(v).strip()
    m = re.search(r"(\d{1,2})[:.hH](\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return s[:20]


def _parse_float(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


def _parse_coords(v):
    """Parsea una celda tipo '-24.78, -65.41' -> (lat, lon)."""
    if v is None:
        return None, None
    nums = re.findall(r"-?\d+[.,]?\d*", str(v))
    if len(nums) >= 2:
        try:
            return float(nums[0].replace(",", ".")), float(nums[1].replace(",", "."))
        except ValueError:
            return None, None
    return None, None


def _coords_validas(lat, lon) -> bool:
    return (
        lat is not None
        and lon is not None
        and -90 <= lat <= 90
        and -180 <= lon <= 180
        and not (lat == 0 and lon == 0)
    )


def _dedupe_hash(reg: dict) -> str:
    base = "|".join(
        _norm(reg.get(k))
        for k in ("numero_ap", "fecha", "hora", "caratula", "lugar", "dependencia")
    )
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()


def _detectar_header(rows):
    """Devuelve (indice_fila_header, {indice_columna: campo}, fuente) o (None, None, None)."""
    for idx, row in enumerate(rows[:15]):
        mapeo = {}
        encontrados = set()
        keys = set()
        for col_idx, cell in enumerate(row):
            key = _norm(cell)
            if key:
                keys.add(key)
            if key in _COLMAP:
                campo = _COLMAP[key]
                mapeo[col_idx] = campo
                encontrados.add(campo)
        es_cco = bool(keys & {"fecha y hora", "tipificacion", "comentario alertante"})
        if (
            {"dependencia", "caratula"}.issubset(encontrados)
            or {"caratula", "lugar"}.issubset(encontrados)
            or (es_cco and "fecha_hora" in encontrados)
        ):
            return idx, mapeo, ("CCO911" if es_cco else "DUNACC")
    return None, None, None


def _anio_de_hoja(titulo_hoja: str, filas_previas) -> int | None:
    for fuente in [titulo_hoja] + [" ".join(_to_str(c) for c in r) for r in filas_previas]:
        m = re.search(r"(20\d{2})", fuente or "")
        if m:
            return int(m.group(1))
    return None


def importar_excel(path: str) -> tuple[list[dict], list[str]]:
    """
    Lee el Excel y devuelve (registros, advertencias).
    Cada registro es un dict listo para construir DunaccRegistro.
    """
    if openpyxl is None:
        return [], ["No está instalado openpyxl en el servidor."]

    advertencias: list[str] = []
    registros: list[dict] = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header_idx, mapeo, fuente = _detectar_header(rows)
        if header_idx is None:
            advertencias.append(f"Hoja «{ws.title}»: no se encontró la fila de encabezados; se omitió.")
            continue

        anio_hoja = _anio_de_hoja(ws.title, rows[:header_idx])

        for row in rows[header_idx + 1:]:
            reg = {campo: None for campo in (
                "numero", "numero_ap", "dependencia", "ddp", "caratula", "fecha", "hora",
                "lugar", "informante", "acusado", "relato", "anio", "lat", "lon",
            )}
            reg["fuente"] = fuente
            coords_combinadas = None
            for col_idx, campo in mapeo.items():
                if col_idx >= len(row):
                    continue
                val = row[col_idx]
                if campo == "coords":
                    coords_combinadas = val
                elif campo == "fecha_hora":
                    reg["fecha"] = _parse_fecha(val)
                    h = _parse_hora(val)
                    if h:
                        reg["hora"] = h
                elif campo == "fecha":
                    reg["fecha"] = _parse_fecha(val)
                elif campo == "hora":
                    reg["hora"] = _parse_hora(val) or None
                elif campo == "anio":
                    m = re.search(r"(20\d{2})", _to_str(val))
                    if m:
                        reg["anio"] = int(m.group(1))
                elif campo == "ddp":
                    reg["ddp"] = (_to_str(val)[:40] or None)
                elif campo in ("lat", "lon"):
                    reg[campo] = _parse_float(val)
                elif campo in ("lugar", "relato"):
                    reg[campo] = (_to_str(val) or None)
                else:
                    reg[campo] = (_to_str(val)[:255] or None)

            if coords_combinadas is not None and reg["lat"] is None and reg["lon"] is None:
                reg["lat"], reg["lon"] = _parse_coords(coords_combinadas)

            # Saltar filas vacías o de subtítulo (sin contenido real).
            if not any([reg["numero_ap"], reg["caratula"], reg["lugar"], reg["relato"], reg["dependencia"]]):
                continue

            if not _coords_validas(reg["lat"], reg["lon"]):
                reg["lat"] = None
                reg["lon"] = None
                reg["geo_origen"] = None
            else:
                reg["geo_origen"] = "importada"

            if reg["fecha"] is not None:
                reg["anio"] = reg["fecha"].year
            elif reg.get("anio") is None:
                reg["anio"] = anio_hoja

            reg["dedupe_hash"] = _dedupe_hash(reg)
            registros.append(reg)

    try:
        wb.close()
    except Exception:
        pass
    return registros, advertencias


# Palabras vacías (español) + términos procedimentales genéricos para el análisis de texto.
_STOPWORDS = {
    "de", "la", "que", "el", "en", "y", "los", "del", "se", "las", "por", "un",
    "para", "con", "una", "su", "sus", "al", "lo", "como", "mas", "más", "pero",
    "ya", "este", "esta", "esto", "estos", "estas", "porque", "entre", "cuando",
    "muy", "sin", "sobre", "tambien", "también", "hasta", "hay", "donde", "quien",
    "quienes", "desde", "todo", "todos", "toda", "todas", "nos", "durante", "uno",
    "les", "ni", "contra", "otros", "otro", "otra", "otras", "ese", "esa", "esos",
    "esas", "eso", "ante", "ellos", "ella", "ellas", "fue", "ser", "son", "habia",
    "había", "han", "ha", "le", "lugar", "fecha", "hora", "hs", "aprox", "aproximadamente",
    "sria", "cria", "nro", "n", "the", "una", "dos", "tres", "cuatro", "cinco",
    "manifiesta", "manifesto", "manifestó", "expresa", "expreso", "expresó", "refiere",
    "denunciante", "informante", "tomo", "tomó", "conocimiento", "parte", "personal",
    "policial", "mismo", "misma", "cual", "dicho", "dicha", "siendo", "cuenta",
    "realizo", "realizó", "hecho", "señor", "senor", "señora", "senora", "sr", "sra",
    "anos", "años", "edad", "vez", "asi", "así", "luego", "cabo", "raiz", "raíz",
}

_WORD_RE = re.compile(r"[a-záéíóúñ]{4,}", re.IGNORECASE)


def _tokens(texto: str) -> list[str]:
    s = unicodedata.normalize("NFKD", (texto or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [w for w in _WORD_RE.findall(s) if w not in _STOPWORDS]


def analizar_texto(textos: list[str], top: int = 25) -> dict:
    """Cuenta términos y pares de términos (bigramas) más frecuentes."""
    from collections import Counter

    uni = Counter()
    bi = Counter()
    for t in textos:
        toks = _tokens(t)
        uni.update(toks)
        for a, b in zip(toks, toks[1:]):
            bi.update([f"{a} {b}"])
    return {
        "palabras": uni.most_common(top),
        "bigramas": bi.most_common(top),
    }


def hora_a_int(v) -> int | None:
    """Extrae la hora (0-23) de un texto tipo '09:40' o '18.45'."""
    if not v:
        return None
    m = re.search(r"(\d{1,2})\s*[:.hH]\s*\d{2}", str(v))
    if not m:
        m = re.match(r"\s*(\d{1,2})\s*$", str(v))
    if not m:
        return None
    h = int(m.group(1))
    return h if 0 <= h <= 23 else None


def geocodificar(consulta: str) -> dict | None:
    """
    Geocodifica una dirección con Nominatim (OpenStreetMap, gratis).
    Devuelve {'lat', 'lon', 'display_name'} o None. Sesga la búsqueda a Argentina.
    """
    if requests is None:
        return None
    consulta = (consulta or "").strip()
    if not consulta:
        return None
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": consulta,
                "format": "json",
                "limit": 1,
                "countrycodes": "ar",
                "addressdetails": 0,
            },
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "es"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        item = data[0]
        return {
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "display_name": item.get("display_name", ""),
        }
    except Exception:
        return None

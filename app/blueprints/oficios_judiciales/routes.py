from __future__ import annotations

import io
import json
import os
import re
import unicodedata
from urllib.parse import urlencode
from datetime import datetime, timedelta, date

import pandas as pd
from flask import Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import false, func, inspect, or_, text

from app.blueprints.oficios_judiciales import bp
from app.extensions import db
from app.models.oficios_judiciales import (
    CatalogoBarrio,
    CatalogoFiscalia,
    CatalogoJuzgado,
    CatalogoTipoConsigna,
    CatalogoTipoMedida,
    ConsignaDiasPorTipo,
    ConsignaDomicilio,
    ConsignaJudicial,
    ConsignaMedidaDetalle,
    ConsignaPersona,
)

try:
    import requests
except Exception:
    requests = None

try:
    import pytesseract
    from PIL import Image, ImageOps
except Exception:
    pytesseract = None
    Image = None
    ImageOps = None

try:
    from pyzbar.pyzbar import decode as qr_decode
except Exception:
    qr_decode = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from pdf2image import convert_from_bytes
except Exception:
    convert_from_bytes = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except Exception:
    canvas = None
    A4 = None


_schema_checked = False


def _import_barrios_desde_geojson(payload: dict) -> int:
    """Inserta barrios desde GeoJSON FeatureCollection (properties.name). Devuelve cantidad de altas nuevas."""
    added = 0
    try:
        for ft in payload.get("features") or []:
            props = (ft or {}).get("properties") or {}
            nombre = _clean(props.get("name"))
            if not nombre:
                continue
            if not CatalogoBarrio.query.filter(func.lower(CatalogoBarrio.nombre) == nombre.lower()).first():
                db.session.add(CatalogoBarrio(nombre=nombre, activo=True))
                added += 1
        if added:
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return added
_MIN_PDF_TEXT_LEN = 120
_OCR_GOOD_ENOUGH_LEN = 900
_MAX_PDF_OCR_PAGES = 3


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("OFICIOS_JUDICIALES_VIEW")


def _can_upload() -> bool:
    return _is_superadmin() or current_user.has_permission("OFICIOS_JUDICIALES_UPLOAD")


def _can_export() -> bool:
    return _is_superadmin() or current_user.has_permission("OFICIOS_JUDICIALES_EXPORT")


def _ensure_schema():
    global _schema_checked
    if _schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    for model in (
        ConsignaJudicial,
        ConsignaPersona,
        ConsignaDomicilio,
        ConsignaMedidaDetalle,
        CatalogoJuzgado,
        CatalogoTipoMedida,
        CatalogoTipoConsigna,
        CatalogoFiscalia,
        CatalogoBarrio,
        ConsignaDiasPorTipo,
    ):
        if model.__tablename__ not in existing:
            model.__table__.create(bind=db.engine)
    cols = {c.get("name") for c in insp.get_columns(ConsignaJudicial.__tablename__)}
    if "tipo_consigna" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN tipo_consigna VARCHAR(30) NULL"))
        db.session.commit()
    if "dias_fija" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN dias_fija INT NULL"))
        db.session.commit()
    if "dias_ambulatoria" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN dias_ambulatoria INT NULL"))
        db.session.commit()
    if "dias_personalizada" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN dias_personalizada INT NULL"))
        db.session.commit()
    if "acusado_notificar" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN acusado_notificar VARCHAR(20) NULL"))
        db.session.commit()
    if "expediente_key" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN expediente_key VARCHAR(120) NULL"))
        db.session.commit()
    if "juzgado_key" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN juzgado_key VARCHAR(255) NULL"))
        db.session.commit()
    if "fiscalia" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN fiscalia VARCHAR(255) NULL"))
        db.session.commit()
    if "fiscalia_key" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN fiscalia_key VARCHAR(255) NULL"))
        db.session.commit()
    if "telefono_contacto" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN telefono_contacto VARCHAR(80) NULL"))
        db.session.commit()
    if "seps_ingreso" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN seps_ingreso VARCHAR(64) NULL"))
        db.session.commit()
    if "seps_salida" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN seps_salida VARCHAR(64) NULL"))
        db.session.commit()
    pcols = {c.get("name") for c in insp.get_columns(ConsignaPersona.__tablename__)}
    if "notificar" not in pcols:
        db.session.execute(text("ALTER TABLE oficios_consigna_personas ADD COLUMN notificar VARCHAR(20) NULL"))
        db.session.commit()
    if "nombre_key" not in pcols:
        db.session.execute(text("ALTER TABLE oficios_consigna_personas ADD COLUMN nombre_key VARCHAR(255) NULL"))
        db.session.commit()
    if "dni_key" not in pcols:
        db.session.execute(text("ALTER TABLE oficios_consigna_personas ADD COLUMN dni_key VARCHAR(20) NULL"))
        db.session.commit()
    dcols = {c.get("name") for c in insp.get_columns(ConsignaDomicilio.__tablename__)}
    if "latitud" not in dcols:
        db.session.execute(text("ALTER TABLE oficios_consigna_domicilios ADD COLUMN latitud DOUBLE NULL"))
        db.session.commit()
    if "longitud" not in dcols:
        db.session.execute(text("ALTER TABLE oficios_consigna_domicilios ADD COLUMN longitud DOUBLE NULL"))
        db.session.commit()
    if "barrio_codigo" not in dcols:
        db.session.execute(text("ALTER TABLE oficios_consigna_domicilios ADD COLUMN barrio_codigo VARCHAR(40) NULL"))
        db.session.commit()
    if "barrio_nombre" not in dcols:
        db.session.execute(text("ALTER TABLE oficios_consigna_domicilios ADD COLUMN barrio_nombre VARCHAR(255) NULL"))
        db.session.commit()
    _schema_checked = True


def _clean(v):
    if v is None:
        return ""
    return str(v).strip()


def _digits_only(v: str) -> str:
    return "".join(re.findall(r"\d", _clean(v)))


def _name_key(v: str) -> str:
    s = _clean_person_name(v)
    s = s.lower()
    s = re.sub(r"[^a-z0-9áéíóúñ ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _juzgado_key(v: str) -> str:
    s = _clean(v).lower()
    if not s:
        return ""
    s = re.sub(r"n[°º\*]\s*", "n ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bnominaci[oó]n\b", "nominacion", s, flags=re.IGNORECASE)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _fiscalia_key(v: str) -> str:
    s = _clean(v).lower()
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _names_from_catalog_ids(id_list, model_cls):
    names = []
    for raw in id_list or []:
        rid = _to_int_or_none(raw)
        if not rid:
            continue
        row = model_cls.query.get(rid)
        if row and getattr(row, "nombre", None):
            names.append(_clean(row.nombre))
    return names


def _derive_tipo_consigna_from_dias(d_fija: int, d_amb: int, d_pers: int) -> str:
    has_f = d_fija > 0
    has_a = d_amb > 0
    has_p = d_pers > 0
    n = sum(1 for x in (has_f, has_a, has_p) if x)
    if n == 0:
        return "indeterminada"
    if n == 1:
        if has_f:
            return "fija"
        if has_a:
            return "ambulatoria"
        return "personalizada"
    return "mixta"


def _ascii_lower_no_accent(s: str) -> str:
    s = _clean(s).lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _slug_tipo_consigna_desde_nombre(nombre: str) -> str:
    s = _ascii_lower_no_accent(nombre)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "tipo")[:30]


def _derive_tipo_consigna_desde_catalogo(
    id_to_dias: dict[int, int], cat_by_id: dict[int, CatalogoTipoConsigna]
) -> str:
    active = [(cid, d) for cid, d in id_to_dias.items() if d and d > 0]
    if not active:
        return "indeterminada"
    if len(active) > 1:
        return "mixta"
    cid = active[0][0]
    cat = cat_by_id.get(cid)
    if not cat:
        return "indeterminada"
    return _slug_tipo_consigna_desde_nombre(cat.nombre)


def _es_tipo_indeterminada_catalogo(nombre: str) -> bool:
    """Tipos cuyo nombre alude a medida indeterminada: Sí/No, no cantidad de días."""
    return "indeterm" in _ascii_lower_no_accent(nombre)


def _orden_tipo_consigna_catalogo(tc: CatalogoTipoConsigna) -> tuple:
    """
    Orden de formulario: ambulatoria → fija → personalizada → indeterminada; el resto al final.
    """
    n = _ascii_lower_no_accent(tc.nombre)
    if "ambulator" in n:
        return (0, n)
    if re.search(r"\bfija\b", n):
        return (1, n)
    if "personal" in n:
        return (2, n)
    if "indeterm" in n:
        return (3, n)
    return (4, n)


def _parse_lat_lng_text(s: str) -> tuple[float | None, float | None]:
    t = _clean(s)
    if not t:
        return None, None
    for sep in [",", ";", "\t"]:
        if sep in t:
            break
    nums = re.findall(r"-?\d+\.?\d*", t)
    if len(nums) >= 2:
        try:
            return float(nums[0]), float(nums[1])
        except Exception:
            return None, None
    return None, None


def _legacy_tres_columnas_desde_catalogo(
    id_to_dias: dict[int, int], cat_by_id: dict[int, CatalogoTipoConsigna]
) -> tuple[int, int, int]:
    """Compatibilidad con columnas dias_fija / dias_ambulatoria / dias_personalizada."""
    lf = la = lp = 0
    for cid, d in id_to_dias.items():
        if d <= 0:
            continue
        cat = cat_by_id.get(cid)
        if not cat or _es_tipo_indeterminada_catalogo(cat.nombre):
            continue
        n = _ascii_lower_no_accent(cat.nombre)
        if "ambulator" in n:
            la += d
        elif "personal" in n:
            lp += d
        elif n == "fija" or n.startswith("fija "):
            lf += d
    return lf, la, lp


def _reemplazar_dias_por_tipo(consigna_id: int, id_to_dias: dict[int, int]) -> None:
    ConsignaDiasPorTipo.query.filter_by(consigna_id=consigna_id).delete(synchronize_session=False)
    for cid, d in id_to_dias.items():
        if d and d > 0:
            db.session.add(ConsignaDiasPorTipo(consigna_id=consigna_id, tipo_catalogo_id=cid, dias=d))


def _file_order_key(filename: str):
    """
    Orden natural para archivos tipo "...Parte_1_de_2..." o similares.
    """
    name = _clean(filename).lower()
    m = re.search(r"(?:parte|part|hoja|pag(?:ina)?)\D{0,8}(\d{1,3})\D{0,8}(?:de|/)\D{0,8}(\d{1,3})", name)
    if m:
        try:
            part = int(m.group(1))
            total = int(m.group(2))
            return (0, total, part, name)
        except Exception:
            pass
    nums = re.findall(r"\d+", name)
    first_num = int(nums[0]) if nums else 9999
    return (1, 9999, first_num, name)


def _parse_date(s: str):
    if not s:
        return None
    try:
        d = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


def _normalize_spaces(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_qr_text_from_image(raw: bytes) -> tuple[str, str]:
    if not qr_decode or not Image:
        return "", ""
    try:
        img = Image.open(io.BytesIO(raw))
        decoded = qr_decode(img)
        for item in decoded:
            payload = _clean(item.data.decode("utf-8", errors="ignore"))
            if payload:
                return payload, "ok"
    except Exception:
        return "", "error"
    return "", "none"


def _extract_ocr_text_from_image(raw: bytes) -> str:
    txt, _ = _extract_ocr_text_from_image_with_error(raw)
    return txt


def _extract_ocr_text_from_image_with_error(raw: bytes) -> tuple[str, str]:
    if not pytesseract or not Image:
        return "", "OCR no disponible (pytesseract/PIL)."
    try:
        if os.path.exists("/usr/bin/tesseract"):
            pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
    except Exception:
        pass
    try:
        img = Image.open(io.BytesIO(raw))
    except Exception as exc:
        return "", f"No se pudo abrir imagen para OCR: {exc}"
    return _ocr_from_pil_with_error(img)


def _extract_qr_text_from_pil_image(img) -> tuple[str, str]:
    if not qr_decode:
        return "", "missing_qr_dependency"
    try:
        decoded = qr_decode(img)
        for item in decoded:
            payload = _clean(item.data.decode("utf-8", errors="ignore"))
            if payload:
                return payload, "ok"
    except Exception:
        return "", "error"
    return "", "none"


def _extract_ocr_text_from_pil_image(img) -> str:
    txt, _ = _ocr_from_pil_with_error(img)
    return txt


def _ocr_from_pil_with_error(img) -> tuple[str, str]:
    if not pytesseract:
        return "", "OCR no disponible (pytesseract)."
    attempts = []
    try:
        attempts.append(img)
        if ImageOps is not None:
            gray = ImageOps.grayscale(img)
            attempts.append(gray)
            attempts.append(ImageOps.autocontrast(gray))
    except Exception:
        pass

    last_err = ""
    best = ""
    for im in attempts:
        # Modo rápido: priorizar spa y cortar cuando el texto ya es suficientemente bueno.
        for lang in ("spa", "spa+eng"):
            try:
                txt = _normalize_spaces(pytesseract.image_to_string(im, lang=lang))
                if len(txt) > len(best):
                    best = txt
                if len(best) >= _OCR_GOOD_ENOUGH_LEN:
                    return best, ""
            except Exception as exc:
                last_err = str(exc)
                continue
    # Fallback de precisión: si quedó muy corto, intentar inglés para OCR difícil.
    if len(best) < 260:
        for im in attempts:
            try:
                txt = _normalize_spaces(pytesseract.image_to_string(im, lang="eng"))
                if len(txt) > len(best):
                    best = txt
            except Exception as exc:
                last_err = str(exc)
                continue
    if best:
        return best, ""
    return "", (last_err or "Tesseract no devolvió texto.")


def _extract_text_from_pdf(raw: bytes) -> str:
    if not PdfReader:
        return ""
    try:
        rd = PdfReader(io.BytesIO(raw))
        parts = []
        for p in rd.pages:
            parts.append(_clean(p.extract_text()))
        return _normalize_spaces("\n".join(parts))
    except Exception:
        return ""


def _render_pdf_pages_to_images(raw: bytes):
    """
    Renderiza páginas de PDF a PIL Images usando PyMuPDF o pdf2image.
    """
    if fitz is not None and Image is not None:
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
            imgs = []
            for page in doc:
                pix = page.get_pixmap(dpi=220, alpha=False)
                mode = "RGB"
                pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                imgs.append(pil)
            return imgs, ""
        except Exception:
            pass

    if convert_from_bytes is not None:
        try:
            return convert_from_bytes(raw, dpi=220), ""
        except Exception:
            pass

    return [], (
        "No hay renderizador de PDF escaneado disponible. Instale PyMuPDF (fitz) "
        "o pdf2image + poppler para OCR en PDFs sin texto."
    )


def _scan_pdf_as_images(raw: bytes) -> tuple[str, str, str, list[str]]:
    """
    Devuelve: (texto_qr_prioritario, texto_ocr, qr_url, advertencias)
    """
    warnings = []
    pages, render_warn = _render_pdf_pages_to_images(raw)
    if render_warn:
        warnings.append(render_warn)
    if not pages:
        return "", "", "", warnings

    qr_parts = []
    ocr_parts = []
    qr_url = ""
    total_pages = len(pages)
    if total_pages > _MAX_PDF_OCR_PAGES:
        warnings.append(
            f"OCR rápido activo: se procesaron {_MAX_PDF_OCR_PAGES} de {total_pages} páginas escaneadas."
        )
    first_batch = pages[:_MAX_PDF_OCR_PAGES]
    for img in first_batch:
        payload, _ = _extract_qr_text_from_pil_image(img)
        if payload:
            resolved, resolved_url = _resolve_qr_payload(payload)
            qr_text = resolved or payload
            if _clean(qr_text):
                qr_parts.append(qr_text)
            if resolved_url:
                qr_url = qr_url or resolved_url

        txt = _extract_ocr_text_from_pil_image(img)
        if _clean(txt):
            ocr_parts.append(txt)

    # Si el lote rápido no alcanza, completar OCR del resto de páginas.
    ocr_joined = _normalize_spaces("\n\n".join(ocr_parts))
    if len(pages) > _MAX_PDF_OCR_PAGES and len(ocr_joined) < 700:
        for img in pages[_MAX_PDF_OCR_PAGES:]:
            txt = _extract_ocr_text_from_pil_image(img)
            if _clean(txt):
                ocr_parts.append(txt)

    return _normalize_spaces("\n\n".join(qr_parts)), _normalize_spaces("\n\n".join(ocr_parts)), qr_url, warnings


def _resolve_qr_payload(qr_payload: str) -> tuple[str, str]:
    payload = _clean(qr_payload)
    if not payload:
        return "", ""
    if payload.lower().startswith("http://") or payload.lower().startswith("https://"):
        if requests is None:
            return "", payload
        try:
            resp = requests.get(payload, timeout=5)
            if resp.ok:
                return _normalize_spaces(resp.text), payload
        except Exception:
            return "", payload
    return payload, ""


def _pick_tipo_medida(text: str) -> str:
    t = text.lower()
    checks = [
        ("consigna fija", "consigna fija"),
        ("consigna ambulatoria", "consigna ambulatoria"),
        ("consigna personalizada", "consigna personalizada"),
        ("prohibición de acercamiento", "prohibición de acercamiento"),
        ("prohibicion de acercamiento", "prohibición de acercamiento"),
        ("prohibición de acercarse", "prohibición de acercamiento"),
        ("prohibicion de acercarse", "prohibición de acercamiento"),
        ("exclusión del hogar", "exclusión del hogar"),
        ("exclusion del hogar", "exclusión del hogar"),
        ("rondas periódicas", "rondas periódicas"),
        ("rondas periodicas", "rondas periódicas"),
    ]
    for k, v in checks:
        if k in t:
            # no return temprano para permitir medidas combinadas
            pass
    found = []
    for k, v in checks:
        if k in t and v not in found:
            found.append(v)
    if not found:
        return ""
    if len(found) == 1:
        return found[0]
    return " + ".join(found[:4])


def _pick_tipo_consigna(text: str) -> str:
    t = (text or "").lower()
    if "consigna policial fija" in t:
        return "fija"
    if re.search(r"rondas?\s+peri[óo]dicas?", t):
        return "ambulatoria"
    if "consigna ambulatoria" in t:
        return "ambulatoria"
    if "consigna fija" in t:
        return "fija"
    if "consigna personalizada" in t:
        return "personalizada"
    if "consigna indeterminada" in t:
        return "indeterminada"
    return ""


def _normalize_dni(v: str) -> str:
    s = _clean(v)
    if not s:
        return ""
    nums = re.findall(r"\d", s)
    if len(nums) < 7:
        return ""
    out = "".join(nums[:8])
    if len(out) == 8:
        return f"{out[:2]}.{out[2:5]}.{out[5:]}"
    return out


def _to_int_or_none(v):
    s = _clean(v)
    if not s:
        return None
    nums = re.findall(r"\d+", s)
    if not nums:
        return None
    try:
        return int(nums[0])
    except Exception:
        return None


def _to_float_or_none(v):
    s = _clean(v).replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _to_input_date(v: str) -> str:
    d = _parse_date(_clean(v))
    return d.strftime("%Y-%m-%d") if d else ""


def _normalize_notificar(v: str, default: str = "no") -> str:
    s = _clean(v).lower()
    if s not in ("si", "no"):
        return default
    return s


def _expediente_key(v: str) -> str:
    """
    Normaliza expediente para comparación robusta entre OCRs ruidosos.
    """
    s = _clean(v).lower()
    if not s:
        return ""
    s = re.sub(r"\bexp(?:ediente|te)?\.?\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _extract_dni_by_context(full: str, person_name: str = "") -> str:
    txt = full or ""
    if person_name:
        # Buscar un DNI cercano al nombre de la persona.
        idx = txt.lower().find(person_name.lower())
        if idx >= 0:
            chunk = txt[max(0, idx - 160): idx + 240]
            m = re.search(r"D\.?\s*N\.?\s*I\.?\s*(?:N[°ºo\*]\s*)?[:\-]?\s*([\d\.\-]{7,16})", chunk, flags=re.IGNORECASE)
            if m:
                return _normalize_dni(m.group(1))
        return ""
    m2 = re.search(r"D\.?\s*N\.?\s*I\.?\s*(?:N[°ºo\*]\s*)?[:\-]?\s*([\d\.\-]{7,16})", txt, flags=re.IGNORECASE)
    if m2:
        return _normalize_dni(m2.group(1))
    return ""


def _first_group(pattern: str, text: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    return _clean(m.group(1))


def _extract_juzgado(full: str) -> str:
    txt = full or ""
    # Intentar extraer denominación completa aun cuando OCR corte en líneas.
    m = re.search(
        r"(JUZGADO[\s\S]{0,180}?(?:NOMINACI[ÓO]N|NOMINACION|N[°º]\s*\d+))",
        txt,
        flags=re.IGNORECASE,
    )
    if m:
        j = _normalize_spaces(m.group(1))
        # cortar posibles colas de códigos/QR
        j = re.split(r"\b(?:Ref\.?|CEDULA|C[ÉE]DULA)\b", j, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        return _smart_cut(j, 220)
    # fallback simple
    return _smart_cut(_first_group(r"(JUZGADO[^\n]+)", txt), 220)


def _extract_caratula(full: str) -> str:
    txt = full or ""
    # Referencia puede romperse en varios saltos de línea.
    m = re.search(
        r"Ref\.?\s*:?\s*([\s\S]{0,420}?)(?:\bCEDULA\b|\bC[ÉE]DULA\b|\n\s*\n|Señor/?a?:)",
        txt,
        flags=re.IGNORECASE,
    )
    if m:
        c = _normalize_spaces(m.group(1))
        m2 = re.search(r"(.+?)\s+CONTRA\s+(.+)", c, flags=re.IGNORECASE)
        if m2:
            left = _normalize_spaces(m2.group(1))
            right = _normalize_spaces(m2.group(2))
            left = re.sub(r"^Expte\.?\s*N[°º\*]?\s*[^-]+-\s*", "", left, flags=re.IGNORECASE).strip()
            seen = []
            for p in re.split(r";|\s+Y\s+", left, flags=re.IGNORECASE):
                pp = _clean_person_name(_smart_cut(p, 140))
                if pp and pp not in seen:
                    seen.append(pp)
            if seen:
                c = f"{'; '.join(seen)} CONTRA {right}"
        return c[:420].strip()
    return _clean(_first_group(r"Ref\.?:\s*(.+)", txt))[:420].strip()


def _extract_victima_from_caratula(caratula: str) -> str:
    c = _clean(caratula)
    if not c:
        return ""
    # Normalizar delimitadores y buscar bloque previo a "CONTRA"
    m = re.search(r"(.+?)\s+CONTRA\s+(.+)", c, flags=re.IGNORECASE)
    if not m:
        return ""
    left = _normalize_spaces(m.group(1))
    left = re.sub(r"^Ref\.?\s*:?\s*", "", left, flags=re.IGNORECASE).strip()
    left = re.sub(r"^Expte\.?\s*N[°º]?\s*[^-]+-\s*", "", left, flags=re.IGNORECASE).strip()
    # quedarse con primer nombre limpio antes de ';'
    first = left.split(";")[0].strip(" -,:")
    return _smart_cut(first, 140)


def _extract_victimas_from_caratula(caratula: str, acusado: str) -> list[str]:
    c = _clean(caratula)
    if not c:
        return []
    m = re.search(r"(.+?)\s+CONTRA\s+(.+)", c, flags=re.IGNORECASE)
    if not m:
        return []
    left = _normalize_spaces(m.group(1))
    left = re.sub(r"^Ref\.?\s*:?\s*", "", left, flags=re.IGNORECASE).strip()
    left = re.sub(r"^Expte\.?\s*N[°º]?\s*[^-]+-\s*", "", left, flags=re.IGNORECASE).strip()
    left = re.sub(r"^[A-Za-z]*\s*-\s*\d+\/\d+\s*-\s*", "", left, flags=re.IGNORECASE).strip()
    parts = [p.strip(" -,:") for p in re.split(r";|\s+Y\s+", left, flags=re.IGNORECASE) if _clean(p)]
    uniq = []
    acusado_l = _clean(acusado).lower()
    for p in parts:
        pp = _clean_person_name(_smart_cut(p, 140))
        if not pp:
            continue
        if not _is_probable_person_name(pp):
            continue
        if acusado_l and _clean(pp).lower() == acusado_l:
            continue
        if pp not in uniq:
            uniq.append(pp)
    return uniq


def _clean_person_name(name: str) -> str:
    s = _clean(name)
    if not s:
        return ""
    s = re.sub(r"^\d+\/\d+\s*-\s*", "", s).strip()
    s = re.sub(r"^Expte\.?\s*N[°º]?\s*[^-]+-\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\bPOR\s+VIOLENCIA\s+FAMILIAR\b.*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\bCONTRA\b.*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\d+\/\d+", "", s).strip()
    s = re.sub(r"\s+", " ", s).strip(" -,;:")
    return s


def _is_probable_person_name(name: str) -> bool:
    n = _clean_person_name(name)
    if not n:
        return False
    low = n.lower()
    blacklist = (
        "los impulsos",
        "disminuir",
        "violencia familiar",
        "denunciante",
        "victima",
        "juzgado",
        "resolucion",
        "notificacion",
        "domicilio",
        "prohibicion",
        "acercarse",
        "acercamiento",
        "reciproca",
        "debera",
        "deberá",
        "hagas saber",
        "ordenar",
    )
    if any(b in low for b in blacklist):
        return False
    toks = [t for t in re.split(r"\s+", n) if t]
    if len(toks) < 2:
        return False
    if len(toks) > 5:
        return False
    if any(re.search(r"\d", t) for t in toks):
        return False
    return True


def _extract_dni_strict_for_name(full: str, person_name: str) -> str:
    txt = full or ""
    nm = _clean_person_name(person_name)
    if not nm:
        return ""
    # Patrón estricto: nombre cercano a DNI, evitando arrastre de otra persona.
    pat = re.compile(
        re.escape(nm) + r"[^.\n,;]{0,90}?D\.?\s*N\.?\s*I\.?\s*(?:N[°ºo\*]\s*)?[:\-]?\s*([\d\.\-]{7,16})",
        flags=re.IGNORECASE,
    )
    m = pat.search(txt)
    if m:
        return _normalize_dni(m.group(1))
    return ""


def _extract_victimas_from_text(full: str, acusado: str) -> list[str]:
    txt = full or ""
    acusado_l = _clean(acusado).lower()
    out = []
    # Patrones de víctimas en frases de prohibición/acercamiento.
    pats = [
        r"EN\s+CONTRA\s+DE\s+([A-ZÁÉÍÓÚÑ ,;]{8,180})",
        r"CONTRA\s+([A-ZÁÉÍÓÚÑ ,;]{8,180})\s*,\s*DEBIENDO",
        r"A\s+LA\s+DENUNCIANTE\s+([A-ZÁÉÍÓÚÑ ,;]{8,180})",
        r"DONDE\s+CONCURRA\s+([A-ZÁÉÍÓÚÑ ,;]{8,220})",
        r"ACERCARSE\s+A\s+([A-Za-zÁÉÍÓÚÑáéíóúñ ,;]{8,220})",
    ]
    for pat in pats:
        for m in re.finditer(pat, txt, flags=re.MULTILINE | re.IGNORECASE):
            groups = [g for g in m.groups() if g]
            for gg in groups:
                block = _normalize_spaces(gg)
                for p in re.split(r";|\s+Y\s+", block, flags=re.IGNORECASE):
                    pp = _clean_person_name(_smart_cut(p.strip(" -,:"), 140))
                    if not pp:
                        continue
                    if not _is_probable_person_name(pp):
                        continue
                    if acusado_l and _clean(pp).lower() == acusado_l:
                        continue
                    if pp not in out:
                        out.append(pp)
    return out


def _extract_acusado_from_caratula(caratula: str) -> str:
    c = _clean(caratula)
    if not c:
        return ""
    m = re.search(r"\s+CONTRA\s+(.+?)(?:\s+POR\s+|$)", c, flags=re.IGNORECASE)
    if not m:
        return ""
    right = _normalize_spaces(m.group(1))
    cand = right.split(";")[0].strip(" -,:")
    cand = _clean_person_name(_smart_cut(cand, 140))
    if _is_probable_person_name(cand):
        return cand
    return ""


def _smart_cut(value: str, max_len: int = 220) -> str:
    s = _clean(value)
    if len(s) <= max_len:
        return s
    # Cortar por delimitadores naturales para evitar basura OCR.
    for sep in (".", ";", ",", " por ", " que ", " en "):
        i = s.lower().find(sep)
        if i > 25:
            return s[:i].strip()
    return s[:max_len].strip()


def _extract_person_after_label(full: str, label_regex: str) -> str:
    m = re.search(label_regex, full, flags=re.IGNORECASE)
    if not m:
        return ""
    tail = full[m.end(): m.end() + 220]
    # Nombre en mayúsculas (2 a 6 palabras) típico en cédulas/oficios.
    mm = re.search(r"([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,6})", tail)
    if mm:
        return _smart_cut(mm.group(1), 120)
    # fallback: hasta fin de línea
    line = tail.splitlines()[0] if tail.splitlines() else tail
    return _smart_cut(line, 120)


def _extract_date_by_context(full: str) -> tuple[str, str]:
    """
    Devuelve (fecha_oficio, fecha_notificacion)
    """
    # 1) Notificación explícita
    fecha_notif = _first_group(r"Constancia de notificaci[oó]n[^\n]*?(?:R\.\s*Fecha\s*[:=]\s*)?(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_notif:
        fecha_notif = _first_group(r"R\.\s*Fecha\s*[:=]\s*\(?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_notif:
        fecha_notif = _first_group(r"notificad[oa][^\n]{0,60}?(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_notif:
        fecha_notif = _first_group(r"de fecha\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_notif:
        fecha_notif = _first_group(r"Salta,\s*(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+de\s+\d{4})", full)

    # 2) Oficio/proveído/firma digital
    fecha_oficio = _first_group(r"prove[ií]do de fecha\s+(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+de\s+\d{4})", full)
    if not fecha_oficio:
        fecha_oficio = _first_group(r"resoluci[oó]n\s+de\s+fecha\s+(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+de\s+\d{4})", full)
    if not fecha_oficio:
        fecha_oficio = _first_group(r"resoluci[oó]n(?:\s+\w+){0,4}\s+de fecha\s+(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+de\s+\d{4})", full)
    if not fecha_oficio:
        fecha_oficio = _first_group(r"(?:prove[ií]do|resoluci[oó]n)[^\n]{0,80}?(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_oficio:
        fecha_oficio = _first_group(r"FIRMADO DIGITALMENTE[^\n]{0,80}?(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_oficio:
        fecha_oficio = _first_group(r"Salta,\s*(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚÑáéíóúñ]+\s+de\s+\d{4})", full)
    if not fecha_oficio:
        fecha_oficio = _first_group(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_notif:
        fecha_notif = _first_group(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)

    # Si solo vino una de las dos, reutilizarla para precarga operativa.
    if fecha_oficio and not fecha_notif:
        fecha_notif = fecha_oficio
    if fecha_notif and not fecha_oficio:
        fecha_oficio = fecha_notif
    return _clean(fecha_oficio), _clean(fecha_notif)


def _extract_medidas_detalle(full: str) -> list[str]:
    medidas = []
    patterns = [
        r"PROHIBICI[ÓO]N DE ACERCAMIENTO[^.]*\.",
        r"ORDENAR RONDAS[^.]*\.",
        r"EXCLUSI[ÓO]N DEL HOGAR[^.]*\.",
        r"CONSIGNA\s+(?:FIJA|AMBULATORIA|PERSONALIZADA)[^.]*\.",
    ]
    for pat in patterns:
        for m in re.findall(pat, full, flags=re.IGNORECASE):
            txt = _smart_cut(m, 220)
            if txt and txt not in medidas:
                medidas.append(txt)

    # Filtro anti-ruido OCR: descartar fragmentos que no parezcan medidas.
    clean = []
    keywords = ("acercamiento", "rondas", "exclus", "consigna", "allanamiento")
    for m in medidas:
        low = m.lower()
        if any(k in low for k in keywords):
            clean.append(m)
    return clean


def _extract_dias_por_consigna(full: str) -> dict:
    txt = full or ""
    out = {"fija": None, "ambulatoria": None, "personalizada": None}
    num_words = {
        "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
        "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
        "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
        "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
        "sesenta": 60, "noventa": 90,
    }

    def _extract_days_value(chunk: str):
        if not chunk:
            return None
        # 1) número explícito
        m_num = re.search(r"\(?\b(\d{1,3})\b\)?\s*d[ií]as", chunk, flags=re.IGNORECASE)
        if m_num:
            return _to_int_or_none(m_num.group(1))
        # 2) número escrito (ej: "diez dias")
        m_word = re.search(r"\b([a-záéíóúñ]{3,15})\b\s*d[ií]as", chunk, flags=re.IGNORECASE)
        if m_word:
            w = _clean(m_word.group(1)).lower()
            return num_words.get(w)
        # 3) formato típico "(10)" sin "días" pegado
        m_par = re.search(r"\((\d{1,3})\)", chunk)
        if m_par:
            return _to_int_or_none(m_par.group(1))
        return None

    def _days_near_keyword(keyword_pat: str):
        for m in re.finditer(keyword_pat, txt, flags=re.IGNORECASE):
            # Limitar al bloque/sentencia para evitar contaminación de otros plazos.
            a = max(txt.rfind(".", 0, m.start()), txt.rfind("\n", 0, m.start()), 0)
            b_dot = txt.find(".", m.end())
            b_nl = txt.find("\n", m.end())
            candidates = [x for x in (b_dot, b_nl) if x != -1]
            b = min(candidates) if candidates else min(len(txt), m.end() + 180)
            chunk = txt[a:b + 1]
            d = _extract_days_value(chunk)
            if d:
                return d
        return None

    pats = {
        "fija": [
            r"CONSIGNA\s+FIJA[^.\n]{0,120}?(\d{1,3})\s*d[ií]as",
            r"(\d{1,3})\s*d[ií]as[^.\n]{0,120}?CONSIGNA\s+FIJA",
            r"CONSIGNA\s+POLICIAL\s+FIJA",
        ],
        "ambulatoria": [
            r"CONSIGNA\s+AMBULATORIA[^.\n]{0,120}?(\d{1,3})\s*d[ií]as",
            r"(\d{1,3})\s*d[ií]as[^.\n]{0,120}?CONSIGNA\s+AMBULATORIA",
            r"RONDAS?\s+PERI[ÓO]DICAS?",
        ],
        "personalizada": [
            r"CONSIGNA\s+PERSONALIZADA[^.\n]{0,120}?(\d{1,3})\s*d[ií]as",
            r"(\d{1,3})\s*d[ií]as[^.\n]{0,120}?CONSIGNA\s+PERSONALIZADA",
        ],
    }
    for k, ls in pats.items():
        for pat in ls:
            m = re.search(pat, txt, flags=re.IGNORECASE)
            if m:
                # Si el patrón trae grupo numérico, usarlo; si no, buscar días cerca.
                if m.lastindex and m.lastindex >= 1 and _clean(m.group(1)):
                    out[k] = _to_int_or_none(m.group(1))
                else:
                    out[k] = _days_near_keyword(pat)
                if out[k]:
                    break

    # Fallbacks operativos:
    # - Si solo hay un total de días y se detecta tipo de consigna único, asignarlo.
    total_dias = _to_int_or_none(_first_group(r"(\d{1,3})\s*d[ií]as", txt))
    tipo_detectado = _pick_tipo_consigna(txt)
    if total_dias:
        if tipo_detectado in out and out[tipo_detectado] is None:
            out[tipo_detectado] = total_dias
        # Si no hay tipo puntual pero hay "rondas", volcar a ambulatoria.
        if out["ambulatoria"] is None and re.search(r"RONDAS?\s+PERI[ÓO]DICAS?", txt, flags=re.IGNORECASE):
            out["ambulatoria"] = total_dias
    return out


def _parse_fields(text: str) -> dict:
    full = text or ""
    expediente = _first_group(r"(EXP[-.\s]*\d+[\/\d\-]*)", full)
    juzgado = _extract_juzgado(full)
    caratula = _extract_caratula(full)
    denunciado = _extract_person_after_label(full, r"Señor/?a?:")
    denunciado = _clean_person_name(denunciado)
    if not _is_probable_person_name(denunciado):
        denunciado = _extract_acusado_from_caratula(caratula)
    victimas = []
    v_from_car = _extract_victimas_from_caratula(caratula, denunciado)
    v_from_txt = _extract_victimas_from_text(full, denunciado)
    for v in v_from_car + v_from_txt:
        vv = _clean_person_name(_smart_cut(v, 140))
        if vv and vv not in victimas:
            victimas.append(vv)
    if not victimas:
        v_single = _extract_person_after_label(full, r"victima\s*[:\-]?")
        v_single = _clean_person_name(v_single)
        if v_single and _is_probable_person_name(v_single) and _clean(v_single).lower() != _clean(denunciado).lower():
            victimas.append(_smart_cut(v_single, 140))
    victima = victimas[0] if victimas else ""
    victima_2 = victimas[1] if len(victimas) > 1 else ""
    victima_3 = victimas[2] if len(victimas) > 2 else ""
    victimas_extra = victimas[3:] if len(victimas) > 3 else []
    dni_denunciado = _extract_dni_strict_for_name(full, denunciado) or _extract_dni_by_context(full, denunciado)
    dni_victima = _extract_dni_strict_for_name(full, victima)
    dni_victima_2 = _extract_dni_strict_for_name(full, victima_2)
    dni_victima_3 = _extract_dni_strict_for_name(full, victima_3)
    # Evitar que víctima herede DNI del acusado por proximidad OCR.
    if dni_victima and dni_denunciado and _normalize_dni(dni_victima) == _normalize_dni(dni_denunciado):
        dni_victima = ""
    if dni_victima_2 and dni_denunciado and _normalize_dni(dni_victima_2) == _normalize_dni(dni_denunciado):
        dni_victima_2 = ""
    if dni_victima_3 and dni_denunciado and _normalize_dni(dni_victima_3) == _normalize_dni(dni_denunciado):
        dni_victima_3 = ""

    dom_den = _first_group(r"Domicilio\s*[:\-]?\s*([^\n]+)", full)
    dom_vic = _first_group(r"domicilio de la victima\s*[:\-]?\s*([^.]+)", full)
    if not dom_vic:
        dom_vic = _first_group(r"sito en\s*([^.]+Cerrillos[^.]*)", full)
    if not dom_vic:
        dom_vic = _first_group(r"domicilio de la v[ií]ctima[^\n]{0,50}?sito en\s*([^\n.]+)", full)
    if not dom_vic:
        dom_vic = _first_group(r"domicilio de la v[ií]ctima[^\n]{0,120}?sito en\s*([^,\n]+(?:,[^,\n]+){0,3})", full)

    dist = _first_group(r"(\d{2,4}\s*metros?)", full)
    dias = _first_group(r"(\d{1,3})\s*d[ií]as", full)
    if not dias:
        dias = _first_group(r"t[eé]rmino de\s+(\d{1,3})", full)
    turnos = _first_group(r"((?:\d+|TRES|DOS|UNO)\s*TURNOS?[^\n,.]*)", full)
    fecha_oficio, fecha_notif = _extract_date_by_context(full)

    medidas = _extract_medidas_detalle(full)
    dias_tipo = _extract_dias_por_consigna(full)

    return {
        "juzgado": _smart_cut(juzgado, 180),
        "expediente": _smart_cut(expediente, 80),
        "caratula": _clean(caratula)[:320],
        "persona_denunciada": _smart_cut(denunciado, 120),
        "victima": _smart_cut(victima, 120),
        "victima_2": _smart_cut(victima_2, 120),
        "victima_3": _smart_cut(victima_3, 120),
        "victimas_adicionales": victimas_extra,
        "domicilio_denunciado": _smart_cut(dom_den, 220),
        "domicilio_victima": _smart_cut(dom_vic, 220),
        "tipo_medida": _pick_tipo_medida(full),
        "tipo_consigna": _pick_tipo_consigna(full),
        "distancia_restriccion": _smart_cut(dist, 40),
        "cantidad_dias": _smart_cut(dias, 12),
        "dias_fija": dias_tipo["fija"] or "",
        "dias_ambulatoria": dias_tipo["ambulatoria"] or "",
        "dias_personalizada": dias_tipo["personalizada"] or "",
        "turnos": _smart_cut(turnos, 80),
        "acusado_notificar": "si",
        "victima_notificar": "no",
        "victima_3_notificar": "no",
        "dni_denunciado": dni_denunciado,
        "dni_victima": dni_victima,
        "dni_victima_2": dni_victima_2,
        "dni_victima_3": dni_victima_3,
        "fecha_oficio": _smart_cut(fecha_oficio, 40),
        "fecha_notificacion": _smart_cut(fecha_notif, 40),
        "observaciones": "",
        "medidas_detalle": medidas,
    }


def _merge_parsed(a: dict, b: dict) -> dict:
    out = dict(a or {})
    prefer_longer = {
        "juzgado",
        "caratula",
        "expediente",
        "persona_denunciada",
        "victima",
        "domicilio_denunciado",
        "domicilio_victima",
    }
    for k, v in (b or {}).items():
        if k == "medidas_detalle":
            prev = out.get(k) or []
            new_vals = v or []
            joined = []
            for x in prev + new_vals:
                if x and x not in joined:
                    joined.append(x)
            out[k] = joined
            continue
        curr = _clean(out.get(k))
        newv = _clean(v)
        if not curr and newv:
            out[k] = v
            continue
        if k in prefer_longer and newv and len(newv) > len(curr) + 8:
            out[k] = v
    return out


def _parsed_score(parsed: dict) -> int:
    if not parsed:
        return 0
    score = 0
    for k, v in parsed.items():
        if k == "medidas_detalle":
            score += len(v or [])
        elif _clean(v):
            score += 1
    return score


def _q_base():
    return ConsignaJudicial.query.filter(ConsignaJudicial.unidad_id == current_user.unidad_id)


def _orden_cronologia_tipo_consigna(cat: CatalogoTipoConsigna) -> tuple:
    """
    Orden de lectura de plazos en cadena: personalizada → fija → ambulatoria → indeterminada; otros al final.
    """
    n = _ascii_lower_no_accent(cat.nombre)
    if "personal" in n:
        return (0, n)
    if re.search(r"\bfija\b", n):
        return (1, n)
    if "ambulator" in n:
        return (2, n)
    if "indeterm" in n:
        return (3, n)
    return (4, n)


def _cronologia_plazos_dias(
    row: ConsignaJudicial, pares: list[tuple[ConsignaDiasPorTipo, CatalogoTipoConsigna]]
) -> list[dict]:
    """
    Tramos consecutivos: personalizada, luego fija, luego ambulatoria (días de carga); indeterminada aparte.
    """
    inicio = row.fecha_notificacion
    if not inicio or not pares:
        return []
    out: list[dict] = []
    cur: date = inicio
    for dp, cat in pares:
        n = _ascii_lower_no_accent(cat.nombre)
        if "indeterm" in n:
            if dp.dias:
                out.append({"modo": "indeterm", "nombre": cat.nombre, "dias": 0})
            continue
        d = int(dp.dias or 0)
        if d <= 0:
            continue
        fin_excl = cur + timedelta(days=d)
        ultimo_dia = fin_excl - timedelta(days=1)
        out.append(
            {
                "modo": "tramo",
                "nombre": cat.nombre,
                "dias": d,
                "desde": cur,
                "hasta": ultimo_dia,
            }
        )
        cur = fin_excl
    return out


def _vencimiento_info(row: ConsignaJudicial, today: date | None = None) -> dict:
    tdy = today or datetime.utcnow().date()
    inicio = row.fecha_notificacion
    dias = row.cantidad_dias
    if not inicio:
        return {"estado": "sin_inicio", "label": "Sin fecha de inicio", "dias_restantes": None, "fecha_vencimiento": None}
    if not dias or dias <= 0:
        return {"estado": "indeterminada", "label": "Sin plazo determinado", "dias_restantes": None, "fecha_vencimiento": None}
    fecha_vto = inicio + timedelta(days=dias)
    restantes = (fecha_vto - tdy).days
    if restantes < 0:
        return {"estado": "vencida", "label": f"Vencida hace {abs(restantes)} día(s)", "dias_restantes": restantes, "fecha_vencimiento": fecha_vto}
    if restantes <= 3:
        return {"estado": "por_vencer", "label": f"Por vencer en {restantes} día(s)", "dias_restantes": restantes, "fecha_vencimiento": fecha_vto}
    return {"estado": "vigente", "label": f"Vigente ({restantes} día(s) restantes)", "dias_restantes": restantes, "fecha_vencimiento": fecha_vto}


@bp.before_request
@login_required
def _before():
    _ensure_schema()


@bp.route("/")
def index():
    if not _can_view():
        abort(403)
    return redirect(url_for("oficios_judiciales.listado"))


@bp.route("/cargar", methods=["GET", "POST"])
def cargar():
    if not _can_upload():
        abort(403)

    if request.method == "POST":
        action = _clean(request.form.get("action"))
        if action == "guardar":
            data_raw = request.form.get("preview_json", "")
            try:
                payload = json.loads(data_raw)
            except Exception:
                flash("No se pudo interpretar la previsualización.", "danger")
                return redirect(url_for("oficios_judiciales.cargar"))

            exp = _clean(payload.get("expediente"))
            juz = _clean(payload.get("juzgado"))
            exp_key = _expediente_key(exp)
            juz_key = _juzgado_key(juz)
            acusado_notificar = _normalize_notificar(payload.get("acusado_notificar"), "si")
            victima_notificar = _normalize_notificar(payload.get("victima_notificar"), "no")
            victima_2_notificar = _normalize_notificar(payload.get("victima_2_notificar"), "no")

            row = None
            fecha_oficio_new = _parse_date(_clean(payload.get("fecha_oficio")))
            if exp_key:
                q = ConsignaJudicial.query.filter(
                    ConsignaJudicial.unidad_id == current_user.unidad_id,
                )
                q = q.filter(ConsignaJudicial.expediente_key == exp_key)
                if juz_key:
                    q = q.filter(ConsignaJudicial.juzgado_key == juz_key)
                row = q.order_by(ConsignaJudicial.id.desc()).first()
                if row is None:
                    # Compatibilidad con datos viejos sin keys persistidas.
                    q_legacy = ConsignaJudicial.query.filter(ConsignaJudicial.unidad_id == current_user.unidad_id)
                    if juz_key:
                        q_legacy = q_legacy.filter(
                            or_(
                                ConsignaJudicial.juzgado_key == juz_key,
                                ConsignaJudicial.juzgado.ilike(f"%{juz}%"),
                            )
                        )
                    candidates = q_legacy.order_by(ConsignaJudicial.id.desc()).limit(300).all()
                    for cand in candidates:
                        if _expediente_key(cand.expediente) == exp_key:
                            row = cand
                            break
            # Fallback: algunos OCR no extraen expediente; consolidar por juzgado + fecha oficio.
            if row is None and (not exp_key) and juz_key and fecha_oficio_new:
                row = (
                    ConsignaJudicial.query.filter(
                        ConsignaJudicial.unidad_id == current_user.unidad_id,
                        ConsignaJudicial.juzgado_key == juz_key,
                        ConsignaJudicial.fecha_oficio == fecha_oficio_new,
                    )
                    .order_by(ConsignaJudicial.id.desc())
                    .first()
                )

            is_new = row is None
            if is_new:
                row = ConsignaJudicial(
                    unidad_id=current_user.unidad_id,
                    creado_por=current_user.id,
                    expediente=exp,
                    expediente_key=exp_key,
                    juzgado=juz,
                    juzgado_key=juz_key,
                    caratula=_clean(payload.get("caratula")),
                    tipo_medida=_clean(payload.get("tipo_medida")),
                    tipo_consigna=_clean(payload.get("tipo_consigna")),
                    fecha_oficio=fecha_oficio_new,
                    fecha_notificacion=_parse_date(_clean(payload.get("fecha_notificacion"))),
                    cantidad_dias=_to_int_or_none(payload.get("cantidad_dias")),
                    dias_fija=_to_int_or_none(payload.get("dias_fija")),
                    dias_ambulatoria=_to_int_or_none(payload.get("dias_ambulatoria")),
                    dias_personalizada=_to_int_or_none(payload.get("dias_personalizada")),
                    acusado_notificar=acusado_notificar,
                    distancia=_clean(payload.get("distancia_restriccion")),
                    turnos=_clean(payload.get("turnos")),
                    estado=_clean(payload.get("estado")) or "activa",
                    observaciones=_clean(payload.get("observaciones")),
                    texto_fuente=_clean(payload.get("texto_fuente")),
                    fuente_principal=_clean(payload.get("fuente_principal")) or "ocr",
                    qr_url=_clean(payload.get("qr_url")),
                    archivo_origen=_clean(payload.get("archivo_origen")),
                )
                db.session.add(row)
                db.session.flush()
            else:
                row.acusado_notificar = acusado_notificar
                row.expediente = row.expediente or exp
                row.expediente_key = row.expediente_key or exp_key
                row.juzgado = row.juzgado or juz
                row.juzgado_key = row.juzgado_key or juz_key
                row.caratula = row.caratula or _clean(payload.get("caratula"))
                row.tipo_medida = row.tipo_medida or _clean(payload.get("tipo_medida"))
                row.tipo_consigna = row.tipo_consigna or _clean(payload.get("tipo_consigna"))
                row.distancia = row.distancia or _clean(payload.get("distancia_restriccion"))
                row.turnos = row.turnos or _clean(payload.get("turnos"))
                row.observaciones = row.observaciones or _clean(payload.get("observaciones"))
                row.texto_fuente = row.texto_fuente or _clean(payload.get("texto_fuente"))
                row.qr_url = row.qr_url or _clean(payload.get("qr_url"))
                row.archivo_origen = row.archivo_origen or _clean(payload.get("archivo_origen"))
                if not row.fecha_oficio:
                    row.fecha_oficio = _parse_date(_clean(payload.get("fecha_oficio")))
                if not row.fecha_notificacion:
                    row.fecha_notificacion = _parse_date(_clean(payload.get("fecha_notificacion")))
                if row.cantidad_dias is None:
                    row.cantidad_dias = _to_int_or_none(payload.get("cantidad_dias"))
                if row.dias_fija is None:
                    row.dias_fija = _to_int_or_none(payload.get("dias_fija"))
                if row.dias_ambulatoria is None:
                    row.dias_ambulatoria = _to_int_or_none(payload.get("dias_ambulatoria"))
                if row.dias_personalizada is None:
                    row.dias_personalizada = _to_int_or_none(payload.get("dias_personalizada"))

            def _add_person_if_new(nombre: str, dni: str, tipo: str, notificar: str):
                nom = _clean(nombre)
                if not nom:
                    return
                dni_n = _normalize_dni(dni)
                dni_k = _digits_only(dni_n)
                nombre_k = _name_key(nom)
                exists = None
                if dni_k:
                    exists = ConsignaPersona.query.filter_by(
                        consigna_id=row.id,
                        tipo=tipo,
                        dni_key=dni_k,
                    ).first()
                if not exists and nombre_k:
                    exists = ConsignaPersona.query.filter_by(
                        consigna_id=row.id,
                        tipo=tipo,
                        nombre_key=nombre_k,
                    ).first()
                exists = ConsignaPersona.query.filter_by(
                    consigna_id=row.id,
                    tipo=tipo,
                    nombre=nom,
                    dni=dni_n,
                ).first() if not exists else exists
                if exists:
                    exists.notificar = _normalize_notificar(notificar, exists.notificar or "no")
                    if dni_n and not _clean(exists.dni):
                        exists.dni = dni_n
                        exists.dni_key = dni_k
                    if nombre_k and not _clean(getattr(exists, "nombre_key", "")):
                        exists.nombre_key = nombre_k
                    return
                db.session.add(
                    ConsignaPersona(
                        consigna_id=row.id,
                        nombre=nom,
                        nombre_key=nombre_k,
                        dni=dni_n,
                        dni_key=dni_k,
                        tipo=tipo,
                        notificar=_normalize_notificar(notificar, "no"),
                    )
                )

            def _add_domicilio_if_new(direccion: str, tipo: str):
                d = _clean(direccion)
                if not d:
                    return
                exists = ConsignaDomicilio.query.filter_by(
                    consigna_id=row.id,
                    tipo=tipo,
                    direccion=d,
                ).first()
                if not exists:
                    db.session.add(ConsignaDomicilio(consigna_id=row.id, direccion=d, tipo=tipo))

            if _clean(payload.get("persona_denunciada")):
                _add_person_if_new(payload.get("persona_denunciada"), payload.get("dni_denunciado"), "denunciado", acusado_notificar)
            if _clean(payload.get("victima")):
                _add_person_if_new(payload.get("victima"), payload.get("dni_victima"), "victima", victima_notificar)
            if _clean(payload.get("victima_2")):
                _add_person_if_new(payload.get("victima_2"), payload.get("dni_victima_2"), "victima", victima_2_notificar)
            if _clean(payload.get("acusado_2")):
                _add_person_if_new(
                    payload.get("acusado_2"),
                    payload.get("dni_acusado_2"),
                    "denunciado",
                    _normalize_notificar(payload.get("acusado_2_notificar"), "si"),
                )
            if _clean(payload.get("victima_3")):
                _add_person_if_new(
                    payload.get("victima_3"),
                    payload.get("dni_victima_3"),
                    "victima",
                    _normalize_notificar(payload.get("victima_3_notificar"), "no"),
                )
            if _clean(payload.get("domicilio_victima_2")):
                _add_domicilio_if_new(payload.get("domicilio_victima_2"), "victima")
            if _clean(payload.get("domicilio_acusado_2")):
                _add_domicilio_if_new(payload.get("domicilio_acusado_2"), "denunciado")
            if _clean(payload.get("domicilio_victima_3")):
                _add_domicilio_if_new(payload.get("domicilio_victima_3"), "victima")
            for ax in (payload.get("acusados_extra") or []):
                if not isinstance(ax, dict):
                    continue
                _add_person_if_new(
                    ax.get("nombre"),
                    ax.get("dni"),
                    "denunciado",
                    _normalize_notificar(ax.get("notificar"), "si"),
                )
                _add_domicilio_if_new(ax.get("domicilio"), "denunciado")
            for vx in (payload.get("victimas_extra_detalle") or []):
                if not isinstance(vx, dict):
                    continue
                _add_person_if_new(
                    vx.get("nombre"),
                    vx.get("dni"),
                    "victima",
                    _normalize_notificar(vx.get("notificar"), "no"),
                )
                _add_domicilio_if_new(vx.get("domicilio"), "victima")
            for vextra in (payload.get("victimas_adicionales") or []):
                if _clean(vextra):
                    _add_person_if_new(vextra, "", "victima", victima_notificar)
            if _clean(payload.get("domicilio_denunciado")):
                _add_domicilio_if_new(payload.get("domicilio_denunciado"), "denunciado")
            if _clean(payload.get("domicilio_victima")):
                _add_domicilio_if_new(payload.get("domicilio_victima"), "victima")
            if _clean(payload.get("tercero_nombre")):
                db.session.add(
                    ConsignaPersona(
                        consigna_id=row.id,
                        nombre=_clean(payload.get("tercero_nombre")),
                        dni=_clean(payload.get("tercero_dni")),
                        tipo="tercero",
                    )
                )
            if _clean(payload.get("tercero_domicilio")):
                db.session.add(
                    ConsignaDomicilio(consigna_id=row.id, direccion=_clean(payload.get("tercero_domicilio")), tipo="tercero")
                )
            for m in (payload.get("medidas_detalle") or []):
                if _clean(m):
                    db.session.add(ConsignaMedidaDetalle(consigna_id=row.id, descripcion=_clean(m)))

            db.session.commit()
            if is_new:
                flash("Consigna judicial guardada correctamente.", "success")
            else:
                flash("Notificación incorporada al oficio existente (sin duplicar expediente).", "success")
            return redirect(url_for("oficios_judiciales.detalle", consigna_id=row.id))

        files = request.files.getlist("archivos")
        if not files:
            flash("Debe seleccionar al menos un archivo.", "warning")
            return redirect(url_for("oficios_judiciales.cargar"))
        files = sorted(files, key=lambda ff: _file_order_key(getattr(ff, "filename", "")))

        full_text_parts = []
        best_source = ""
        qr_url = ""
        archivo_origen = ""
        merged = {}
        processed_files = []
        warnings = []
        detected_fields_set = set()
        if pytesseract is None:
            warnings.append("OCR no disponible: falta dependencia pytesseract.")
        if qr_decode is None:
            warnings.append("Lectura QR no disponible: falta dependencia pyzbar.")
        if PdfReader is None:
            warnings.append("Lectura de texto PDF no disponible: falta dependencia pypdf.")

        for f in files:
            name = _clean(f.filename)
            if not name:
                continue
            raw = f.read()
            if not raw:
                continue
            archivo_origen = archivo_origen or name

            txt_ocr = ""
            txt_qr = ""
            resolved_url = ""
            source_used = ""
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                payload, _ = _extract_qr_text_from_image(raw)
                if payload:
                    resolved, resolved_url = _resolve_qr_payload(payload)
                    txt_qr = resolved or payload
                txt_ocr, ocr_err = _extract_ocr_text_from_image_with_error(raw)
                if ocr_err:
                    warnings.append(f"{name}: OCR imagen con incidencia: {ocr_err}")
                source_used = "QR" if _clean(txt_qr) else "OCR imagen"
                if not _clean(txt_qr) and not _clean(txt_ocr):
                    if pytesseract is None and qr_decode is None:
                        warnings.append(f"{name}: no se pudo leer porque faltan OCR (pytesseract) y QR (pyzbar).")
            elif name.lower().endswith(".pdf"):
                txt_pdf = _extract_text_from_pdf(raw)
                if len(_clean(txt_pdf)) >= _MIN_PDF_TEXT_LEN:
                    txt_ocr = txt_pdf
                    source_used = "PDF texto"
                else:
                    txt_qr_pdf, txt_ocr_pdf, qr_url_pdf, warn_list = _scan_pdf_as_images(raw)
                    if warn_list:
                        warnings.extend([f"{name}: {w}" for w in warn_list])
                    if _clean(txt_qr_pdf):
                        txt_qr = txt_qr_pdf
                        source_used = "QR"
                    elif _clean(txt_ocr_pdf):
                        txt_ocr = txt_ocr_pdf
                        source_used = "OCR PDF escaneado"
                    else:
                        txt_ocr = txt_pdf
                        source_used = "PDF texto"
                    if qr_url_pdf:
                        resolved_url = qr_url_pdf
            else:
                warnings.append(f"{name}: formato no soportado.")
                continue

            src_text = txt_qr if _clean(txt_qr) else txt_ocr
            src_kind = "QR" if _clean(txt_qr) else source_used or "OCR imagen"
            if not best_source and src_kind:
                best_source = src_kind
            parsed_qr = _parse_fields(txt_qr) if _clean(txt_qr) else {}
            parsed_ocr = _parse_fields(txt_ocr) if _clean(txt_ocr) else {}
            score_qr = _parsed_score(parsed_qr)
            score_ocr = _parsed_score(parsed_ocr)

            # QR tiene prioridad cuando es contenido válido/rico; si no, usar OCR.
            qr_is_useful = _clean(txt_qr) and (score_qr >= 2 or len(_clean(txt_qr)) >= 180 or bool(resolved_url))
            primary_text = txt_qr if qr_is_useful else txt_ocr
            primary_kind = "QR" if qr_is_useful else (source_used or "OCR imagen")

            # Consolidar priorizando texto del archivo subido (OCR/PDF) y QR como complemento.
            if _clean(txt_ocr):
                full_text_parts.append(txt_ocr)
                merged = _merge_parsed(merged, parsed_ocr)
            if _clean(txt_qr):
                full_text_parts.append(txt_qr)
                merged = _merge_parsed(merged, parsed_qr)

            if _clean(primary_text):
                for k, v in merged.items():
                    if k == "medidas_detalle":
                        if v:
                            detected_fields_set.add(k)
                    elif _clean(v):
                        detected_fields_set.add(k)
                # Si OCR detecta más campos que QR, reflejar fuente real usada.
                if _clean(txt_qr) and _clean(txt_ocr) and score_ocr > score_qr:
                    primary_kind = "OCR PDF escaneado" if name.lower().endswith(".pdf") and "OCR PDF escaneado" in (source_used or "") else "OCR imagen"
                best_source = primary_kind
                if resolved_url:
                    qr_url = resolved_url
                processed_files.append({"archivo": name, "fuente": primary_kind, "ok": True})
            else:
                processed_files.append({"archivo": name, "fuente": source_used or "sin lectura", "ok": False})
                warnings.append(f"{name}: no se pudo extraer texto útil (OCR/QR).")

        full_text = _normalize_spaces("\n\n".join(full_text_parts))
        if not _clean(full_text):
            warnings.append(
                "No se extrajo texto automáticamente. Complete manualmente los campos y guarde si corresponde."
            )
            full_text = ""

        merged["texto_fuente"] = full_text
        merged["fuente_principal"] = best_source or "OCR imagen"
        merged["qr_url"] = qr_url
        merged["archivo_origen"] = archivo_origen
        merged["estado"] = "activa"
        merged["fecha_oficio"] = _to_input_date(merged.get("fecha_oficio"))
        merged["fecha_notificacion"] = _to_input_date(merged.get("fecha_notificacion"))
        merged["archivos_procesados"] = processed_files
        merged["advertencias"] = warnings
        merged["campos_detectados"] = sorted(detected_fields_set)
        required_fields = [
            "juzgado",
            "expediente",
            "caratula",
            "persona_denunciada",
            "victima",
            "domicilio_denunciado",
            "tipo_medida",
            "fecha_notificacion",
        ]
        merged["campos_vacios"] = [k for k in required_fields if not _clean(merged.get(k))]
        if "medidas_detalle" not in merged:
            merged["medidas_detalle"] = []
        return render_template("oficios_judiciales/preview.html", data=merged, data_json=json.dumps(merged))

    if _clean(request.args.get("manual")) == "1":
        base = {
            "juzgado": "",
            "expediente": "",
            "caratula": "",
            "tipo_medida": "",
            "tipo_consigna": "",
            "fecha_oficio": "",
            "fecha_notificacion": "",
            "persona_denunciada": "",
            "dni_denunciado": "",
            "domicilio_denunciado": "",
            "victima": "",
            "dni_victima": "",
            "domicilio_victima": "",
            "victima_2": "",
            "dni_victima_2": "",
            "domicilio_victima_2": "",
            "acusado_notificar": "si",
            "victima_notificar": "no",
            "victima_2_notificar": "no",
            "victimas_adicionales": [],
            "cantidad_dias": "",
            "dias_fija": "",
            "dias_ambulatoria": "",
            "dias_personalizada": "",
            "turnos": "",
            "observaciones": "",
            "medidas_detalle": [],
            "texto_fuente": "",
            "fuente_principal": "manual",
            "qr_url": "",
            "archivo_origen": "carga_manual",
            "archivos_procesados": [],
            "advertencias": [],
            "campos_detectados": [],
            "campos_vacios": [],
            "estado": "activa",
        }
        return render_template("oficios_judiciales/preview.html", data=base, data_json=json.dumps(base))

    return render_template("oficios_judiciales/cargar.html")


@bp.route("/manual")
def manual_listado():
    if not _can_view():
        abort(403)
    estados = [e for e in request.args.getlist("estado") if e in ("activa", "finalizada")]
    qtxt = _clean(request.args.get("q"))
    fecha_desde = _parse_date(_clean(request.args.get("fecha_desde")))
    fecha_hasta = _parse_date(_clean(request.args.get("fecha_hasta")))
    tipos_sel = [_clean(x) for x in request.args.getlist("tipo_consigna") if _clean(x)]
    juzgados_sel = [_clean(x) for x in request.args.getlist("juzgado") if _clean(x)]
    medidas_sel = [_clean(x) for x in request.args.getlist("tipo_medida") if _clean(x)]
    fiscalias_sel = [_clean(x) for x in request.args.getlist("fiscalia") if _clean(x)]
    barrios_sel = [_clean(x) for x in request.args.getlist("barrio") if _clean(x)]

    q = _q_base().filter(ConsignaJudicial.fuente_principal == "manual")
    if estados:
        q = q.filter(ConsignaJudicial.estado.in_(estados))
    catalogo_tipos = sorted(
        CatalogoTipoConsigna.query.filter_by(activo=True).all(),
        key=_orden_cronologia_tipo_consigna,
    )
    tipo_slug_to_ids = {}
    for tc in catalogo_tipos:
        slug = _slug_tipo_consigna_desde_nombre(tc.nombre)
        tipo_slug_to_ids.setdefault(slug, []).append(tc.id)

    if tipos_sel:
        conds = []
        ids_cats = []
        for ts in tipos_sel:
            ids_cats.extend(tipo_slug_to_ids.get(ts, []))
        if ids_cats:
            sq_tipo = (
                db.session.query(ConsignaDiasPorTipo.consigna_id)
                .filter(
                    ConsignaDiasPorTipo.tipo_catalogo_id.in_(ids_cats),
                    ConsignaDiasPorTipo.dias > 0,
                )
                .subquery()
            )
            conds.append(ConsignaJudicial.id.in_(sq_tipo))
        if "mixta" in tipos_sel:
            conds.append(ConsignaJudicial.tipo_consigna == "mixta")
        if "indeterminada" in tipos_sel:
            conds.append(ConsignaJudicial.tipo_consigna == "indeterminada")
        if conds:
            q = q.filter(or_(*conds))
    if juzgados_sel:
        q = q.filter(or_(*[ConsignaJudicial.juzgado.ilike(f"%{v}%") for v in juzgados_sel]))
    if medidas_sel:
        q = q.filter(or_(*[ConsignaJudicial.tipo_medida.ilike(f"%{v}%") for v in medidas_sel]))
    if fiscalias_sel:
        q = q.filter(or_(*[ConsignaJudicial.fiscalia.ilike(f"%{v}%") for v in fiscalias_sel]))
    if barrios_sel:
        sq_bar = (
            db.session.query(ConsignaDomicilio.consigna_id)
            .filter(or_(*[ConsignaDomicilio.barrio_nombre.ilike(f"%{b}%") for b in barrios_sel]))
            .subquery()
        )
        q = q.filter(ConsignaJudicial.id.in_(sq_bar))
    if fecha_desde:
        q = q.filter(ConsignaJudicial.fecha_notificacion >= fecha_desde)
    if fecha_hasta:
        q = q.filter(ConsignaJudicial.fecha_notificacion <= fecha_hasta)
    if qtxt:
        pat = f"%{qtxt}%"
        eq = _expediente_key(qtxt)
        sq_per = (
            db.session.query(ConsignaPersona.consigna_id)
            .filter(or_(ConsignaPersona.nombre.ilike(pat), ConsignaPersona.dni.ilike(pat)))
            .subquery()
        )
        sq_dom = (
            db.session.query(ConsignaDomicilio.consigna_id)
            .filter(
                or_(
                    ConsignaDomicilio.direccion.ilike(pat),
                    ConsignaDomicilio.barrio_nombre.ilike(pat),
                )
            )
            .subquery()
        )
        q = q.filter(
            or_(
                ConsignaJudicial.expediente_key == eq if eq else false(),
                ConsignaJudicial.expediente.ilike(pat),
                ConsignaJudicial.caratula.ilike(pat),
                ConsignaJudicial.juzgado.ilike(pat),
                ConsignaJudicial.tipo_medida.ilike(pat),
                ConsignaJudicial.tipo_consigna.ilike(pat),
                ConsignaJudicial.fiscalia.ilike(pat),
                ConsignaJudicial.seps_ingreso.ilike(pat),
                ConsignaJudicial.seps_salida.ilike(pat),
                ConsignaJudicial.id.in_(sq_per),
                ConsignaJudicial.id.in_(sq_dom),
            )
        )

    page = max(1, _to_int_or_none(request.args.get("page")) or 1)
    per_page = max(10, min(100, _to_int_or_none(request.args.get("per_page")) or 25))
    today = datetime.utcnow().date()

    def _estado_operativo(r: ConsignaJudicial) -> str:
        if _clean(r.estado).lower() == "finalizada":
            return "finalizada"
        inicio = r.fecha_notificacion
        dias = int(r.cantidad_dias or 0)
        if inicio and dias > 0:
            vto = inicio + timedelta(days=dias)
            if vto <= today:
                return "finalizada"
        return "activa"

    rows_all = q.order_by(ConsignaJudicial.created_at.desc()).all()
    if estados:
        estados_set = set(estados)
        rows_all = [r for r in rows_all if _estado_operativo(r) in estados_set]

    total_rows = len(rows_all)
    total_pages = max(1, (total_rows + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    rows = rows_all[start:end]
    row_ids = [r.id for r in rows]
    personas_map = {}
    domicilios_map = {}
    persona_domicilio_map = {}
    coords_map = {}
    progreso_map = {}
    etapa_actual_map = {}
    estado_operativo_map = {}
    if row_ids:
        pers = (
            ConsignaPersona.query.filter(ConsignaPersona.consigna_id.in_(row_ids))
            .order_by(ConsignaPersona.id.asc())
            .all()
        )
        for p in pers:
            bag = personas_map.setdefault(p.consigna_id, {"victima": None, "denunciado": None})
            if p.tipo == "victima" and bag["victima"] is None:
                bag["victima"] = p
            elif p.tipo == "denunciado" and bag["denunciado"] is None:
                bag["denunciado"] = p
        doms = (
            ConsignaDomicilio.query.filter(ConsignaDomicilio.consigna_id.in_(row_ids))
            .order_by(ConsignaDomicilio.id.asc())
            .all()
        )
        for d in doms:
            if d.consigna_id not in domicilios_map:
                domicilios_map[d.consigna_id] = d
            if d.latitud is not None and d.longitud is not None and d.consigna_id not in coords_map:
                coords_map[d.consigna_id] = (d.latitud, d.longitud)

        doms_by_cons_tipo = {}
        for d in doms:
            key = (d.consigna_id, _clean(d.tipo).lower())
            doms_by_cons_tipo.setdefault(key, []).append(d)
        used_dom_ids = set()
        for r in rows:
            items = []
            plist = [p for p in pers if p.consigna_id == r.id]
            for p in plist:
                pt = _clean(p.tipo).lower()
                cand = doms_by_cons_tipo.get((r.id, pt), []) or doms_by_cons_tipo.get((r.id, "victima"), []) or []
                chosen = None
                for d in cand:
                    if d.id not in used_dom_ids:
                        chosen = d
                        break
                if not chosen:
                    for d in doms:
                        if d.consigna_id == r.id and d.id not in used_dom_ids:
                            chosen = d
                            break
                if chosen:
                    used_dom_ids.add(chosen.id)
                items.append({"persona": p, "domicilio": chosen})
            persona_domicilio_map[r.id] = items
        for r in rows:
            total = int(r.cantidad_dias or 0)
            estado_operativo_map[r.id] = _estado_operativo(r)
            if r.fecha_notificacion and total > 0:
                trans = max(0, (today - r.fecha_notificacion).days)
                if trans > total:
                    trans = total
                progreso_map[r.id] = {"transcurridos": trans, "total": total}
            else:
                progreso_map[r.id] = {"transcurridos": 0, "total": total}

        dias_pairs = (
            db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
            .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
            .filter(ConsignaDiasPorTipo.consigna_id.in_(row_ids))
            .all()
        )
        dias_por_consigna = {}
        for dp, cat in dias_pairs:
            dias_por_consigna.setdefault(dp.consigna_id, []).append((dp, cat))

        for r in rows:
            pares = dias_por_consigna.get(r.id, [])
            pares.sort(key=lambda p: _orden_cronologia_tipo_consigna(p[1]))
            trans = progreso_map.get(r.id, {}).get("transcurridos", 0)
            has_indet = False
            tramos = []
            for dp, cat in pares:
                n = _ascii_lower_no_accent(cat.nombre)
                if "indeterm" in n:
                    has_indet = bool(dp.dias)
                    continue
                d = int(dp.dias or 0)
                if d > 0:
                    tramos.append((cat.nombre, d, n))

            etapa = {"slug": "indeterminada", "nombre": "Indeterminada", "icono": "bi-infinity", "pos": 0, "total": 0}
            if tramos:
                acc = 0
                chosen = tramos[-1]
                chosen_idx = len(tramos) - 1
                for idx, t in enumerate(tramos):
                    acc += t[1]
                    if trans < acc:
                        chosen = t
                        chosen_idx = idx
                        break
                n = chosen[2]
                if "fija" in n:
                    etapa = {"slug": "fija", "nombre": "Fija", "icono": "bi-anchor-fill", "pos": chosen_idx + 1, "total": len(tramos)}
                elif "ambulator" in n:
                    etapa = {"slug": "ambulatoria", "nombre": "Ambulatoria", "icono": "bi-car-front-fill", "pos": chosen_idx + 1, "total": len(tramos)}
                elif "personal" in n:
                    etapa = {"slug": "personalizada", "nombre": "Personalizada", "icono": "bi-person-circle", "pos": chosen_idx + 1, "total": len(tramos)}
                else:
                    etapa = {"slug": _slug_tipo_consigna_desde_nombre(chosen[0]), "nombre": chosen[0], "icono": "bi-dot", "pos": chosen_idx + 1, "total": len(tramos)}
            elif has_indet:
                etapa = {"slug": "indeterminada", "nombre": "Indeterminada", "icono": "bi-infinity", "pos": 0, "total": 0}
            elif (r.tipo_consigna or "") == "fija":
                etapa = {"slug": "fija", "nombre": "Fija", "icono": "bi-anchor-fill", "pos": 0, "total": 0}
            elif (r.tipo_consigna or "") == "ambulatoria":
                etapa = {"slug": "ambulatoria", "nombre": "Ambulatoria", "icono": "bi-car-front-fill", "pos": 0, "total": 0}
            elif (r.tipo_consigna or "") == "personalizada":
                etapa = {"slug": "personalizada", "nombre": "Personalizada", "icono": "bi-person-circle", "pos": 0, "total": 0}
            etapa_actual_map[r.id] = etapa

    tipos_consigna = []
    seen_tipos = set()
    for tc in catalogo_tipos:
        slug = _slug_tipo_consigna_desde_nombre(tc.nombre)
        if slug in seen_tipos:
            continue
        tipos_consigna.append({"value": slug, "label": tc.nombre})
        seen_tipos.add(slug)
    for extra in ("mixta",):
        if extra not in seen_tipos:
            tipos_consigna.append({"value": extra, "label": extra.title()})
    juzgados_opts = [x.nombre for x in CatalogoJuzgado.query.filter_by(activo=True).order_by(CatalogoJuzgado.nombre.asc()).all()]
    medidas_opts = [x.nombre for x in CatalogoTipoMedida.query.filter_by(activo=True).order_by(CatalogoTipoMedida.nombre.asc()).all()]
    fiscalias_opts = [x.nombre for x in CatalogoFiscalia.query.filter_by(activo=True).order_by(CatalogoFiscalia.nombre.asc()).all()]
    barrios_opts = [x.nombre for x in CatalogoBarrio.query.filter_by(activo=True).order_by(CatalogoBarrio.nombre.asc()).all()]

    args_multi = request.args.to_dict(flat=False)
    args_multi.pop("page", None)
    args_multi.pop("per_page", None)

    def _page_url(n: int) -> str:
        data = {k: list(v) for k, v in args_multi.items()}
        data["page"] = [str(n)]
        data["per_page"] = [str(per_page)]
        return f"{url_for('oficios_judiciales.manual_listado')}?{urlencode(data, doseq=True)}"

    pagination = {
        "page": page,
        "per_page": per_page,
        "total_rows": total_rows,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_url": _page_url(page - 1) if page > 1 else None,
        "next_url": _page_url(page + 1) if page < total_pages else None,
    }

    return render_template(
        "oficios_judiciales/manual_listado.html",
        rows=rows,
        selected=request.args,
        tipos_consigna=tipos_consigna,
        juzgados_opts=juzgados_opts,
        medidas_opts=medidas_opts,
        fiscalias_opts=fiscalias_opts,
        barrios_opts=barrios_opts,
        personas_map=personas_map,
        domicilios_map=domicilios_map,
        persona_domicilio_map=persona_domicilio_map,
        coords_map=coords_map,
        progreso_map=progreso_map,
        etapa_actual_map=etapa_actual_map,
        estado_operativo_map=estado_operativo_map,
        pagination=pagination,
    )


@bp.route("/manual/dashboard")
def manual_dashboard():
    if not _can_view():
        abort(403)
    base = _q_base().filter(ConsignaJudicial.fuente_principal == "manual")
    total = base.count()
    activas = base.filter(ConsignaJudicial.estado == "activa").count()
    finalizadas = base.filter(ConsignaJudicial.estado == "finalizada").count()
    por_tipo = (
        base.with_entities(ConsignaJudicial.tipo_consigna, func.count(ConsignaJudicial.id))
        .group_by(ConsignaJudicial.tipo_consigna)
        .order_by(func.count(ConsignaJudicial.id).desc())
        .all()
    )
    por_barrio = (
        db.session.query(ConsignaDomicilio.barrio_nombre, func.count(ConsignaDomicilio.id))
        .join(ConsignaJudicial, ConsignaJudicial.id == ConsignaDomicilio.consigna_id)
        .filter(
            ConsignaJudicial.unidad_id == current_user.unidad_id,
            ConsignaJudicial.fuente_principal == "manual",
            ConsignaDomicilio.barrio_nombre.isnot(None),
            ConsignaDomicilio.barrio_nombre != "",
        )
        .group_by(ConsignaDomicilio.barrio_nombre)
        .order_by(func.count(ConsignaDomicilio.id).desc())
        .limit(15)
        .all()
    )
    return render_template(
        "oficios_judiciales/manual_dashboard.html",
        total=total,
        activas=activas,
        finalizadas=finalizadas,
        por_tipo=por_tipo,
        por_barrio=por_barrio,
    )


@bp.route("/manual/mapa")
def manual_mapa():
    if not _can_view():
        abort(403)
    estado = _clean(request.args.get("estado")) or "activa"
    tipo_consigna = _clean(request.args.get("tipo_consigna"))
    barrio = _clean(request.args.get("barrio"))
    q = (
        db.session.query(ConsignaJudicial, ConsignaDomicilio)
        .join(ConsignaDomicilio, ConsignaDomicilio.consigna_id == ConsignaJudicial.id)
        .filter(
            ConsignaJudicial.unidad_id == current_user.unidad_id,
            ConsignaJudicial.fuente_principal == "manual",
            ConsignaDomicilio.latitud.isnot(None),
            ConsignaDomicilio.longitud.isnot(None),
        )
    )
    if estado == "activa":
        q = q.filter(ConsignaJudicial.estado == "activa")
    elif estado == "finalizada":
        q = q.filter(ConsignaJudicial.estado == "finalizada")
    if tipo_consigna:
        q = q.filter(ConsignaJudicial.tipo_consigna == tipo_consigna)
    if barrio:
        q = q.filter(ConsignaDomicilio.barrio_nombre == barrio)
    rows = q.order_by(ConsignaJudicial.id.desc()).limit(1000).all()
    points = []
    for r, d in rows:
        points.append(
            {
                "id": r.id,
                "expediente": r.expediente,
                "tipo_consigna": r.tipo_consigna,
                "estado": r.estado,
                "barrio": d.barrio_nombre or "",
                "direccion": d.direccion or "",
                "lat": d.latitud,
                "lng": d.longitud,
                "detalle_url": url_for("oficios_judiciales.detalle", consigna_id=r.id),
            }
        )
    tipos_consigna = [r[0] for r in _q_base().with_entities(ConsignaJudicial.tipo_consigna).distinct().all() if r[0]]
    barrios = [r[0] for r in db.session.query(ConsignaDomicilio.barrio_nombre).filter(ConsignaDomicilio.barrio_nombre.isnot(None), ConsignaDomicilio.barrio_nombre != "").distinct().order_by(ConsignaDomicilio.barrio_nombre.asc()).all() if r[0]]
    return render_template(
        "oficios_judiciales/manual_mapa.html",
        points_json=json.dumps(points),
        tipos_consigna=tipos_consigna,
        barrios=barrios,
        selected=request.args,
    )


@bp.route("/manual/reincidencias")
def manual_reincidencias():
    if not _can_view():
        abort(403)
    qtxt = _clean(request.args.get("q"))
    rows = []
    detalle = []
    if qtxt:
        rows = (
            db.session.query(
                ConsignaPersona.nombre,
                ConsignaPersona.dni,
                func.count(ConsignaPersona.id).label("n"),
            )
            .join(ConsignaJudicial, ConsignaJudicial.id == ConsignaPersona.consigna_id)
            .filter(
                ConsignaJudicial.unidad_id == current_user.unidad_id,
                ConsignaJudicial.fuente_principal == "manual",
                or_(ConsignaPersona.nombre.ilike(f"%{qtxt}%"), ConsignaPersona.dni.ilike(f"%{qtxt}%")),
            )
            .group_by(ConsignaPersona.nombre, ConsignaPersona.dni)
            .having(func.count(ConsignaPersona.id) > 1)
            .order_by(func.count(ConsignaPersona.id).desc())
            .limit(100)
            .all()
        )
        detalle = (
            db.session.query(
                ConsignaPersona.nombre,
                ConsignaPersona.dni,
                ConsignaJudicial.id,
                ConsignaJudicial.expediente,
                ConsignaJudicial.tipo_consigna,
                ConsignaJudicial.estado,
                ConsignaJudicial.fecha_notificacion,
            )
            .join(ConsignaJudicial, ConsignaJudicial.id == ConsignaPersona.consigna_id)
            .filter(
                ConsignaJudicial.unidad_id == current_user.unidad_id,
                ConsignaJudicial.fuente_principal == "manual",
                or_(ConsignaPersona.nombre.ilike(f"%{qtxt}%"), ConsignaPersona.dni.ilike(f"%{qtxt}%")),
            )
            .order_by(ConsignaJudicial.fecha_notificacion.desc().nullslast(), ConsignaJudicial.id.desc())
            .limit(300)
            .all()
        )
    return render_template("oficios_judiciales/manual_reincidencias.html", rows=rows, detalle=detalle, selected=request.args)


@bp.route("/manual/nuevo", methods=["GET", "POST"])
def manual_nuevo():
    if not _can_upload():
        abort(403)
    _ensure_schema()
    juzgados = CatalogoJuzgado.query.filter_by(activo=True).order_by(CatalogoJuzgado.nombre.asc()).all()
    tipos_medida = CatalogoTipoMedida.query.filter_by(activo=True).order_by(CatalogoTipoMedida.nombre.asc()).all()
    fiscalias = CatalogoFiscalia.query.filter_by(activo=True).order_by(CatalogoFiscalia.nombre.asc()).all()
    barrios = CatalogoBarrio.query.filter_by(activo=True).order_by(CatalogoBarrio.nombre.asc()).all()
    tipos_consigna_catalogo = sorted(
        CatalogoTipoConsigna.query.filter_by(activo=True).all(),
        key=_orden_tipo_consigna_catalogo,
    )
    if request.method == "POST":
        exp = _clean(request.form.get("expediente"))
        caratula = _clean(request.form.get("caratula"))
        estado = "activa"
        tel_contacto = _clean(request.form.get("telefono_contacto"))
        seps_ingreso = _clean(request.form.get("seps_ingreso"))
        seps_salida = _clean(request.form.get("seps_salida"))
        juz_n = _names_from_catalog_ids(request.form.getlist("juzgado_id"), CatalogoJuzgado)
        tm_n = _names_from_catalog_ids(request.form.getlist("tipo_medida_id"), CatalogoTipoMedida)
        fis_n = _names_from_catalog_ids(request.form.getlist("fiscalia_id"), CatalogoFiscalia)
        juz = " · ".join(juz_n) if juz_n else ""
        tipo_medida = " · ".join(tm_n) if tm_n else ""
        fiscalia = " · ".join(fis_n) if fis_n else ""
        cat_by_id = {c.id: c for c in tipos_consigna_catalogo}
        id_to_dias: dict[int, int] = {}
        for tc in tipos_consigna_catalogo:
            v = _to_int_or_none(request.form.get(f"dias_por_tipo_{tc.id}"))
            d = 0 if v is None else max(0, v)
            if _es_tipo_indeterminada_catalogo(tc.nombre):
                d = 1 if d else 0
            id_to_dias[tc.id] = d
        cantidad_dias = 0
        for tc in tipos_consigna_catalogo:
            d = id_to_dias.get(tc.id, 0)
            if _es_tipo_indeterminada_catalogo(tc.nombre):
                continue
            cantidad_dias += d
        tipo_consigna = _derive_tipo_consigna_desde_catalogo(id_to_dias, cat_by_id)
        d_fija, d_amb, d_pers = _legacy_tres_columnas_desde_catalogo(id_to_dias, cat_by_id)
        exp_key = _expediente_key(exp)
        juz_key = _juzgado_key(juz) if juz else ""

        row = None
        if exp_key:
            q = ConsignaJudicial.query.filter(
                ConsignaJudicial.unidad_id == current_user.unidad_id,
                ConsignaJudicial.expediente_key == exp_key,
                ConsignaJudicial.fuente_principal == "manual",
            )
            if juz_key:
                q = q.filter(ConsignaJudicial.juzgado_key == juz_key)
            row = q.order_by(ConsignaJudicial.id.desc()).first()

        is_new = row is None
        if is_new:
            row = ConsignaJudicial(
                unidad_id=current_user.unidad_id,
                creado_por=current_user.id,
                expediente=exp,
                expediente_key=exp_key,
                juzgado=juz,
                juzgado_key=juz_key,
                caratula=caratula,
                tipo_medida=tipo_medida,
                tipo_consigna=tipo_consigna,
                fiscalia=fiscalia,
                fiscalia_key=_fiscalia_key(fiscalia) if fiscalia else "",
                telefono_contacto=tel_contacto,
                seps_ingreso=seps_ingreso or None,
                seps_salida=seps_salida or None,
                fecha_oficio=None,
                fecha_notificacion=_parse_date(_clean(request.form.get("fecha_notificacion"))),
                cantidad_dias=cantidad_dias if cantidad_dias else None,
                dias_fija=d_fija if d_fija else None,
                dias_ambulatoria=d_amb if d_amb else None,
                dias_personalizada=d_pers if d_pers else None,
                estado=estado,
                fuente_principal="manual",
                archivo_origen="carga_manual",
            )
            db.session.add(row)
            db.session.flush()
        else:
            row.juzgado = juz or row.juzgado
            row.juzgado_key = juz_key or row.juzgado_key
            row.caratula = caratula or row.caratula
            row.tipo_medida = tipo_medida or row.tipo_medida
            row.tipo_consigna = tipo_consigna
            row.fiscalia = fiscalia or row.fiscalia
            row.fiscalia_key = _fiscalia_key(fiscalia) if fiscalia else (row.fiscalia_key or "")
            row.telefono_contacto = tel_contacto or row.telefono_contacto
            row.seps_ingreso = seps_ingreso or None
            row.seps_salida = seps_salida or None
            row.cantidad_dias = cantidad_dias or None
            row.dias_fija = d_fija or None
            row.dias_ambulatoria = d_amb or None
            row.dias_personalizada = d_pers or None
            row.fecha_notificacion = _parse_date(_clean(request.form.get("fecha_notificacion"))) or row.fecha_notificacion
            row.estado = "activa"

        def _add_person_manual(nombre, dni, tipo, notificar):
            nom = _clean(nombre)
            if not nom:
                return
            dni_n = _normalize_dni(dni)
            dni_k = _digits_only(dni_n)
            nom_k = _name_key(nom)
            exists = None
            if dni_k:
                exists = ConsignaPersona.query.filter_by(consigna_id=row.id, tipo=tipo, dni_key=dni_k).first()
            if not exists and nom_k:
                exists = ConsignaPersona.query.filter_by(consigna_id=row.id, tipo=tipo, nombre_key=nom_k).first()
            if exists:
                exists.notificar = _normalize_notificar(notificar, exists.notificar or "no")
                return
            db.session.add(
                ConsignaPersona(
                    consigna_id=row.id,
                    nombre=nom,
                    nombre_key=nom_k,
                    dni=dni_n,
                    dni_key=dni_k,
                    tipo=tipo,
                    notificar=_normalize_notificar(notificar, "no"),
                )
            )

        def _add_domicilio_manual(direccion, tipo, lat, lng, barrio_id):
            d = _clean(direccion)
            if not d:
                return
            lat_f = _to_float_or_none(lat)
            lng_f = _to_float_or_none(lng)
            b_id = _to_int_or_none(barrio_id)
            b_row = CatalogoBarrio.query.get(b_id) if b_id else None
            exists = ConsignaDomicilio.query.filter_by(consigna_id=row.id, tipo=tipo, direccion=d).first()
            if exists:
                if exists.latitud is None:
                    exists.latitud = lat_f
                if exists.longitud is None:
                    exists.longitud = lng_f
                if b_row and not _clean(exists.barrio_nombre):
                    exists.barrio_codigo = _clean(b_row.codigo)
                    exists.barrio_nombre = _clean(b_row.nombre)
                return
            db.session.add(
                ConsignaDomicilio(
                    consigna_id=row.id,
                    direccion=d,
                    tipo=tipo,
                    barrio_codigo=_clean(b_row.codigo) if b_row else "",
                    barrio_nombre=_clean(b_row.nombre) if b_row else "",
                    latitud=lat_f,
                    longitud=lng_f,
                )
            )

        p_nombres = request.form.getlist("persona_nombre[]")
        p_dnis = request.form.getlist("persona_dni[]")
        p_tipos = request.form.getlist("persona_tipo[]")
        p_noti = request.form.getlist("persona_notificar[]")
        p_dom = request.form.getlist("persona_domicilio[]")
        p_latlng = request.form.getlist("persona_latlng[]")
        p_barrio = request.form.getlist("persona_barrio_id[]")
        total = max(
            len(p_nombres),
            len(p_dnis),
            len(p_tipos),
            len(p_noti),
            len(p_dom),
            len(p_latlng),
            len(p_barrio),
        )
        for i in range(total):
            nombre = p_nombres[i] if i < len(p_nombres) else ""
            dni = p_dnis[i] if i < len(p_dnis) else ""
            tipo = _clean(p_tipos[i] if i < len(p_tipos) else "victima") or "victima"
            noti = p_noti[i] if i < len(p_noti) else "no"
            dom = p_dom[i] if i < len(p_dom) else ""
            lat = lng = ""
            if i < len(p_latlng):
                la, ln = _parse_lat_lng_text(p_latlng[i])
                if la is not None:
                    lat = str(la)
                if ln is not None:
                    lng = str(ln)
            barr = p_barrio[i] if i < len(p_barrio) else ""
            _add_person_manual(nombre, dni, tipo, noti)
            _add_domicilio_manual(dom, tipo, lat, lng, barr)

        _reemplazar_dias_por_tipo(row.id, id_to_dias)
        db.session.commit()
        flash("Consigna manual guardada.", "success")
        return redirect(url_for("oficios_judiciales.detalle", consigna_id=row.id))
    return render_template(
        "oficios_judiciales/manual_form.html",
        juzgados=juzgados,
        tipos_medida=tipos_medida,
        fiscalias=fiscalias,
        barrios=barrios,
        tipos_consigna_catalogo=tipos_consigna_catalogo,
    )


@bp.route("/catalogos", methods=["GET", "POST"])
def catalogos():
    if not _can_upload():
        abort(403)
    _ensure_schema()
    action = _clean(request.form.get("catalog_action"))
    if request.method == "POST":
        mostrar_ok = True
        if action == "add_juzgado":
            nombre = _clean(request.form.get("nombre"))
            if nombre and not CatalogoJuzgado.query.filter_by(nombre=nombre).first():
                db.session.add(CatalogoJuzgado(nombre=nombre, clave=_juzgado_key(nombre), activo=True))
                db.session.commit()
        elif action == "add_tipo_medida":
            nombre = _clean(request.form.get("nombre"))
            if nombre and not CatalogoTipoMedida.query.filter_by(nombre=nombre).first():
                db.session.add(CatalogoTipoMedida(nombre=nombre, activo=True))
                db.session.commit()
        elif action == "add_tipo_consigna":
            nombre = _clean(request.form.get("nombre"))
            if nombre and not CatalogoTipoConsigna.query.filter_by(nombre=nombre).first():
                db.session.add(CatalogoTipoConsigna(nombre=nombre, activo=True))
                db.session.commit()
        elif action == "add_fiscalia":
            nombre = _clean(request.form.get("nombre"))
            if nombre and not CatalogoFiscalia.query.filter_by(nombre=nombre).first():
                db.session.add(CatalogoFiscalia(nombre=nombre, clave=_fiscalia_key(nombre), activo=True))
                db.session.commit()
        elif action == "import_barrios_json":
            try:
                json_path = os.path.abspath(os.path.join(current_app.root_path, "..", "barrios.json"))
                if os.path.exists(json_path):
                    with open(json_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    _import_barrios_desde_geojson(payload)
                else:
                    mostrar_ok = False
                    flash("No se encontró barrios.json en el servidor (/opt/sioc/barrios.json). Subí el archivo abajo.", "warning")
            except Exception:
                db.session.rollback()
                mostrar_ok = False
                flash("No se pudo importar desde barrios.json del servidor.", "danger")
        elif action == "import_barrios_json_upload":
            up = request.files.get("barrios_json")
            if up and _clean(up.filename):
                try:
                    raw = up.read().decode("utf-8")
                    payload = json.loads(raw)
                    _import_barrios_desde_geojson(payload)
                except Exception:
                    db.session.rollback()
                    mostrar_ok = False
                    flash("Archivo JSON inválido o no es GeoJSON esperado.", "danger")
        elif action == "import_barrios_excel":
            f = request.files.get("barrios_excel")
            if f and _clean(f.filename):
                try:
                    import pandas as pd  # lazy import

                    df = pd.read_excel(f)
                    cols = {str(c).strip().lower(): c for c in df.columns}
                    c_cod = cols.get("barrios")
                    c_nom = cols.get("barrios_nombre")
                    c_dep = cols.get("dependencia")
                    c_dep_nom = cols.get("dependencia_nombre")
                    if c_nom is not None:
                        for _, r in df.iterrows():
                            nom = _clean(r.get(c_nom))
                            if not nom:
                                continue
                            codigo = _clean(r.get(c_cod)) if c_cod is not None else ""
                            depc = _clean(r.get(c_dep)) if c_dep is not None else ""
                            depn = _clean(r.get(c_dep_nom)) if c_dep_nom is not None else ""
                            b = CatalogoBarrio.query.filter_by(nombre=nom).first()
                            if not b:
                                db.session.add(
                                    CatalogoBarrio(
                                        nombre=nom,
                                        codigo=codigo or None,
                                        dependencia_codigo=depc or None,
                                        dependencia_nombre=depn or None,
                                        activo=True,
                                    )
                                )
                            else:
                                if codigo and not _clean(b.codigo):
                                    b.codigo = codigo
                                if depc and not _clean(b.dependencia_codigo):
                                    b.dependencia_codigo = depc
                                if depn and not _clean(b.dependencia_nombre):
                                    b.dependencia_nombre = depn
                        db.session.commit()
                except Exception:
                    db.session.rollback()
        elif action == "edit_juzgado":
            rid = _to_int_or_none(request.form.get("item_id"))
            nombre = _clean(request.form.get("nombre"))
            row = CatalogoJuzgado.query.get(rid) if rid else None
            if row and nombre:
                dup = CatalogoJuzgado.query.filter(
                    CatalogoJuzgado.id != row.id, func.lower(CatalogoJuzgado.nombre) == nombre.lower()
                ).first()
                if dup:
                    flash("Ya existe un juzgado con ese nombre.", "warning")
                else:
                    row.nombre = nombre
                    row.clave = _juzgado_key(nombre)
                    db.session.commit()
        elif action == "delete_juzgado":
            rid = _to_int_or_none(request.form.get("item_id"))
            row = CatalogoJuzgado.query.get(rid) if rid else None
            if row:
                db.session.delete(row)
                db.session.commit()
        elif action == "edit_tipo_medida":
            rid = _to_int_or_none(request.form.get("item_id"))
            nombre = _clean(request.form.get("nombre"))
            row = CatalogoTipoMedida.query.get(rid) if rid else None
            if row and nombre:
                dup = CatalogoTipoMedida.query.filter(
                    CatalogoTipoMedida.id != row.id, func.lower(CatalogoTipoMedida.nombre) == nombre.lower()
                ).first()
                if dup:
                    flash("Ya existe ese tipo de medida.", "warning")
                else:
                    row.nombre = nombre
                    db.session.commit()
        elif action == "delete_tipo_medida":
            rid = _to_int_or_none(request.form.get("item_id"))
            row = CatalogoTipoMedida.query.get(rid) if rid else None
            if row:
                db.session.delete(row)
                db.session.commit()
        elif action == "edit_tipo_consigna":
            rid = _to_int_or_none(request.form.get("item_id"))
            nombre = _clean(request.form.get("nombre"))
            row = CatalogoTipoConsigna.query.get(rid) if rid else None
            if row and nombre:
                dup = CatalogoTipoConsigna.query.filter(
                    CatalogoTipoConsigna.id != row.id, func.lower(CatalogoTipoConsigna.nombre) == nombre.lower()
                ).first()
                if dup:
                    flash("Ya existe ese tipo de consigna.", "warning")
                else:
                    row.nombre = nombre
                    db.session.commit()
        elif action == "delete_tipo_consigna":
            rid = _to_int_or_none(request.form.get("item_id"))
            row = CatalogoTipoConsigna.query.get(rid) if rid else None
            if row:
                db.session.delete(row)
                db.session.commit()
        elif action == "edit_fiscalia":
            rid = _to_int_or_none(request.form.get("item_id"))
            nombre = _clean(request.form.get("nombre"))
            row = CatalogoFiscalia.query.get(rid) if rid else None
            if row and nombre:
                dup = CatalogoFiscalia.query.filter(
                    CatalogoFiscalia.id != row.id, func.lower(CatalogoFiscalia.nombre) == nombre.lower()
                ).first()
                if dup:
                    flash("Ya existe esa fiscalía.", "warning")
                else:
                    row.nombre = nombre
                    row.clave = _fiscalia_key(nombre)
                    db.session.commit()
        elif action == "delete_fiscalia":
            rid = _to_int_or_none(request.form.get("item_id"))
            row = CatalogoFiscalia.query.get(rid) if rid else None
            if row:
                db.session.delete(row)
                db.session.commit()
        elif action == "edit_barrio":
            rid = _to_int_or_none(request.form.get("item_id"))
            nombre = _clean(request.form.get("nombre"))
            row = CatalogoBarrio.query.get(rid) if rid else None
            if row and nombre:
                dup = CatalogoBarrio.query.filter(
                    CatalogoBarrio.id != row.id, func.lower(CatalogoBarrio.nombre) == nombre.lower()
                ).first()
                if dup:
                    flash("Ya existe un barrio con ese nombre.", "warning")
                else:
                    row.nombre = nombre
                    row.codigo = _clean(request.form.get("codigo")) or None
                    row.dependencia_codigo = _clean(request.form.get("dependencia_codigo")) or None
                    row.dependencia_nombre = _clean(request.form.get("dependencia_nombre")) or None
                    db.session.commit()
        elif action == "delete_barrio":
            rid = _to_int_or_none(request.form.get("item_id"))
            row = CatalogoBarrio.query.get(rid) if rid else None
            if row:
                db.session.delete(row)
                db.session.commit()
        if mostrar_ok:
            flash("Catálogo actualizado.", "success")
        return redirect(url_for("oficios_judiciales.catalogos"))
    juzgados = CatalogoJuzgado.query.order_by(CatalogoJuzgado.nombre.asc()).all()
    tipos_medida = CatalogoTipoMedida.query.order_by(CatalogoTipoMedida.nombre.asc()).all()
    tipos_consigna = CatalogoTipoConsigna.query.order_by(CatalogoTipoConsigna.nombre.asc()).all()
    fiscalias = CatalogoFiscalia.query.order_by(CatalogoFiscalia.nombre.asc()).all()
    barrios = CatalogoBarrio.query.order_by(CatalogoBarrio.nombre.asc()).all()
    return render_template(
        "oficios_judiciales/catalogos.html",
        juzgados=juzgados,
        tipos_medida=tipos_medida,
        tipos_consigna=tipos_consigna,
        fiscalias=fiscalias,
        barrios=barrios,
    )


@bp.route("/listado")
def listado():
    if not _can_view():
        abort(403)
    q = _q_base()

    tipo = _clean(request.args.get("tipo"))
    tipo_consigna = _clean(request.args.get("tipo_consigna"))
    juzgado = _clean(request.args.get("juzgado"))
    persona = _clean(request.args.get("persona"))
    qtxt = _clean(request.args.get("q"))
    fdesde = _parse_date(_clean(request.args.get("fecha_desde")))
    fhasta = _parse_date(_clean(request.args.get("fecha_hasta")))

    if tipo:
        q = q.filter(ConsignaJudicial.tipo_medida == tipo)
    if tipo_consigna:
        q = q.filter(ConsignaJudicial.tipo_consigna == tipo_consigna)
    if juzgado:
        jk = _juzgado_key(juzgado)
        if jk:
            q = q.filter(or_(ConsignaJudicial.juzgado_key == jk, ConsignaJudicial.juzgado.ilike(f"%{juzgado}%")))
        else:
            q = q.filter(ConsignaJudicial.juzgado.ilike(f"%{juzgado}%"))
    if qtxt:
        pat = f"%{qtxt}%"
        eq = _expediente_key(qtxt)
        q = q.filter(
            or_(
                ConsignaJudicial.expediente_key == eq if eq else false(),
                ConsignaJudicial.expediente.ilike(pat),
                ConsignaJudicial.caratula.ilike(pat),
                ConsignaJudicial.observaciones.ilike(pat),
            )
        )
    if fdesde:
        q = q.filter(ConsignaJudicial.fecha_notificacion >= fdesde)
    if fhasta:
        q = q.filter(ConsignaJudicial.fecha_notificacion <= fhasta)
    if persona:
        persona_key = _name_key(persona)
        dni_key = _digits_only(persona)
        q = q.join(ConsignaPersona, ConsignaPersona.consigna_id == ConsignaJudicial.id).filter(
            or_(
                ConsignaPersona.nombre_key == persona_key if persona_key else false(),
                ConsignaPersona.dni_key == dni_key if dni_key else false(),
                ConsignaPersona.nombre.ilike(f"%{persona}%"),
                ConsignaPersona.dni.ilike(f"%{persona}%"),
            )
        )

    rows = q.order_by(ConsignaJudicial.created_at.desc()).limit(300).all()
    tipos = [r[0] for r in _q_base().with_entities(ConsignaJudicial.tipo_medida).distinct().all() if r[0]]
    tipos_consigna = [r[0] for r in _q_base().with_entities(ConsignaJudicial.tipo_consigna).distinct().all() if r[0]]
    venc = {r.id: _vencimiento_info(r) for r in rows}
    return render_template("oficios_judiciales/listado.html", rows=rows, tipos=tipos, tipos_consigna=tipos_consigna, venc=venc, selected=request.args)


@bp.route("/alertas")
def alertas():
    if not _can_view():
        abort(403)
    rows = _q_base().order_by(ConsignaJudicial.fecha_notificacion.desc(), ConsignaJudicial.id.desc()).limit(500).all()
    cards = []
    for r in rows:
        info = _vencimiento_info(r)
        cards.append({"row": r, "venc": info})
    vencidas = [x for x in cards if x["venc"]["estado"] == "vencida"]
    por_vencer = [x for x in cards if x["venc"]["estado"] == "por_vencer"]
    vigentes = [x for x in cards if x["venc"]["estado"] == "vigente"]
    indeterminadas = [x for x in cards if x["venc"]["estado"] in ("indeterminada", "sin_inicio")]
    return render_template(
        "oficios_judiciales/alertas.html",
        vencidas=vencidas,
        por_vencer=por_vencer,
        vigentes=vigentes,
        indeterminadas=indeterminadas,
    )


@bp.route("/detalle/<int:consigna_id>")
def detalle(consigna_id: int):
    if not _can_view():
        abort(403)
    _ensure_schema()
    row = _q_base().filter(ConsignaJudicial.id == consigna_id).first_or_404()
    venc = _vencimiento_info(row)
    dias_por_tipo_detalle = (
        db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
        .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
        .filter(ConsignaDiasPorTipo.consigna_id == consigna_id)
        .all()
    )
    dias_por_tipo_detalle.sort(key=lambda p: _orden_cronologia_tipo_consigna(p[1]))
    cronologia_plazos = _cronologia_plazos_dias(row, dias_por_tipo_detalle)
    if not cronologia_plazos and row.fecha_notificacion and (row.dias_personalizada or row.dias_fija or row.dias_ambulatoria):
        cur = row.fecha_notificacion
        for label, d in (
            ("Personalizada", row.dias_personalizada or 0),
            ("Fija", row.dias_fija or 0),
            ("Ambulatoria", row.dias_ambulatoria or 0),
        ):
            if d <= 0:
                continue
            fin_excl = cur + timedelta(days=d)
            ultimo = fin_excl - timedelta(days=1)
            cronologia_plazos.append(
                {
                    "modo": "tramo",
                    "nombre": label,
                    "dias": d,
                    "desde": cur,
                    "hasta": ultimo,
                }
            )
            cur = fin_excl
    volver_url = (
        url_for("oficios_judiciales.manual_listado")
        if (row.fuente_principal or "") == "manual"
        else url_for("oficios_judiciales.listado")
    )
    return render_template(
        "oficios_judiciales/detalle.html",
        row=row,
        venc=venc,
        dias_por_tipo_detalle=dias_por_tipo_detalle,
        cronologia_plazos=cronologia_plazos,
        volver_url=volver_url,
    )


@bp.route("/export.csv")
def export_csv():
    if not _can_export():
        abort(403)
    q = _q_base().order_by(ConsignaJudicial.created_at.desc())
    out = io.StringIO()
    import csv
    w = csv.writer(out)
    w.writerow(["id", "expediente", "juzgado", "tipo_medida", "tipo_consigna", "fecha_notificacion", "cantidad_dias", "dias_fija", "dias_ambulatoria", "dias_personalizada", "estado", "caratula"])
    for r in q.yield_per(300):
        w.writerow(
            [
                r.id,
                r.expediente or "",
                r.juzgado or "",
                r.tipo_medida or "",
                r.tipo_consigna or "",
                r.fecha_notificacion.isoformat() if r.fecha_notificacion else "",
                r.cantidad_dias or "",
                r.dias_fija or "",
                r.dias_ambulatoria or "",
                r.dias_personalizada or "",
                r.estado or "",
                r.caratula or "",
            ]
        )
    return Response(
        out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=oficios_judiciales.csv"},
    )


@bp.route("/export.xlsx")
def export_xlsx():
    if not _can_export():
        abort(403)
    rows = []
    for r in _q_base().order_by(ConsignaJudicial.created_at.desc()).yield_per(300):
        rows.append(
            {
                "id": r.id,
                "expediente": r.expediente,
                "juzgado": r.juzgado,
                "tipo_medida": r.tipo_medida,
                "tipo_consigna": r.tipo_consigna,
                "fecha_notificacion": r.fecha_notificacion,
                "cantidad_dias": r.cantidad_dias,
                "dias_fija": r.dias_fija,
                "dias_ambulatoria": r.dias_ambulatoria,
                "dias_personalizada": r.dias_personalizada,
                "estado": r.estado,
                "caratula": r.caratula,
            }
        )
    bio = io.BytesIO()
    pd.DataFrame(rows).to_excel(bio, index=False)
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=oficios_judiciales.xlsx"},
    )


@bp.route("/export.pdf")
def export_pdf():
    if not _can_export():
        abort(403)
    if not canvas:
        flash("Exportar PDF requiere reportlab instalado en el servidor.", "warning")
        return redirect(url_for("oficios_judiciales.listado"))
    rows = _q_base().order_by(ConsignaJudicial.created_at.desc()).limit(200).all()
    bio = io.BytesIO()
    c = canvas.Canvas(bio, pagesize=A4)
    w, h = A4
    y = h - 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "SIOC - Listado Oficios Judiciales")
    y -= 22
    c.setFont("Helvetica", 9)
    c.drawString(40, y, f"Emitido: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC")
    y -= 18
    for r in rows:
        line = f"#{r.id} | {r.expediente or '-'} | {r.tipo_medida or '-'} | Inicio: {r.fecha_notificacion or '-'} | {r.juzgado or '-'}"
        c.drawString(40, y, line[:125])
        y -= 14
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 9)
            y = h - 40
    c.save()
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=oficios_judiciales.pdf"},
    )


@bp.route("/api/reincidencia")
def api_reincidencia():
    if not _can_view():
        abort(403)
    q = _clean(request.args.get("q"))
    if not q:
        return Response(json.dumps([]), mimetype="application/json")
    rows = (
        db.session.query(
            ConsignaPersona.nombre,
            ConsignaPersona.dni,
            func.count(ConsignaPersona.id).label("n"),
        )
        .join(ConsignaJudicial, ConsignaJudicial.id == ConsignaPersona.consigna_id)
        .filter(
            ConsignaJudicial.unidad_id == current_user.unidad_id,
            or_(ConsignaPersona.nombre.ilike(f"%{q}%"), ConsignaPersona.dni.ilike(f"%{q}%")),
        )
        .group_by(ConsignaPersona.nombre, ConsignaPersona.dni)
        .having(func.count(ConsignaPersona.id) > 1)
        .order_by(func.count(ConsignaPersona.id).desc())
        .limit(40)
        .all()
    )
    out = [{"nombre": r[0], "dni": r[1], "cantidad": int(r[2])} for r in rows]
    return Response(json.dumps(out), mimetype="application/json")


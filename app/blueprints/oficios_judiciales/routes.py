from __future__ import annotations

import io
import json
import os
import re
import unicodedata
from urllib.parse import urlencode
from datetime import datetime, timedelta, date

import pandas as pd
from flask import Response, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import false, func, inspect, or_, text
from sqlalchemy.orm import joinedload

from app.blueprints.oficios_judiciales import bp
from app.extensions import db
from app.models.oficios_judiciales import (
    CatalogoBarrio,
    CatalogoEstadoExpediente,
    CatalogoFiscalia,
    CatalogoJuzgado,
    CatalogoMotivoIndeterminada,
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
        CatalogoMotivoIndeterminada,
        CatalogoEstadoExpediente,
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
    if "motivo_indeterminada_id" not in cols:
        db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN motivo_indeterminada_id INT NULL"))
        db.session.commit()
    if "estado_expediente_id" not in cols:
        try:
            db.session.execute(text("ALTER TABLE oficios_consignas ADD COLUMN estado_expediente_id INT NULL"))
            db.session.commit()
        except Exception:
            current_app.logger.exception("No se pudo agregar estado_expediente_id en oficios_consignas")
            db.session.rollback()
    # Ajustes de longitudes/texto para campos extensos.
    # Nota: 191 evita errores de índice en MySQL/MariaDB con utf8mb4.
    try:
        cons_cols = {c.get("name"): c for c in insp.get_columns(ConsignaJudicial.__tablename__)}
        exp_col = cons_cols.get("expediente")
        exp_len = getattr(exp_col.get("type"), "length", None) if exp_col else None
        if exp_col and exp_len is not None and int(exp_len) < 191:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN expediente VARCHAR(191) NULL"))
            db.session.commit()
        expk_col = cons_cols.get("expediente_key")
        expk_len = getattr(expk_col.get("type"), "length", None) if expk_col else None
        if expk_col and expk_len is not None and int(expk_len) < 191:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN expediente_key VARCHAR(191) NULL"))
            db.session.commit()
        car_col = cons_cols.get("caratula")
        car_type = str(car_col.get("type")).lower() if car_col else ""
        if car_col and ("char" in car_type or "varchar" in car_type):
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN caratula TEXT NULL"))
            db.session.commit()
        tcol = cons_cols.get("tipo_medida")
        tlen = getattr(tcol.get("type"), "length", None) if tcol else None
        if tcol and tlen is not None and int(tlen) < 191:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN tipo_medida VARCHAR(191) NULL"))
            db.session.commit()
        tel_col = cons_cols.get("telefono_contacto")
        tel_len = getattr(tel_col.get("type"), "length", None) if tel_col else None
        if tel_col and tel_len is not None and int(tel_len) < 120:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN telefono_contacto VARCHAR(120) NULL"))
            db.session.commit()
        seps_in_col = cons_cols.get("seps_ingreso")
        seps_in_len = getattr(seps_in_col.get("type"), "length", None) if seps_in_col else None
        if seps_in_col and seps_in_len is not None and int(seps_in_len) < 128:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN seps_ingreso VARCHAR(128) NULL"))
            db.session.commit()
        seps_out_col = cons_cols.get("seps_salida")
        seps_out_len = getattr(seps_out_col.get("type"), "length", None) if seps_out_col else None
        if seps_out_col and seps_out_len is not None and int(seps_out_len) < 128:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN seps_salida VARCHAR(128) NULL"))
            db.session.commit()
        turn_col = cons_cols.get("turnos")
        turn_len = getattr(turn_col.get("type"), "length", None) if turn_col else None
        if turn_col and turn_len is not None and int(turn_len) < 255:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN turnos VARCHAR(255) NULL"))
            db.session.commit()
        orig_col = cons_cols.get("archivo_origen")
        orig_len = getattr(orig_col.get("type"), "length", None) if orig_col else None
        if orig_col and orig_len is not None and int(orig_len) < 500:
            db.session.execute(text("ALTER TABLE oficios_consignas MODIFY COLUMN archivo_origen VARCHAR(500) NULL"))
            db.session.commit()
    except Exception:
        current_app.logger.exception("No se pudieron ampliar campos extensos en oficios_consignas")
        db.session.rollback()
    try:
        tm_cols = {c.get("name"): c for c in insp.get_columns(CatalogoTipoMedida.__tablename__)}
        ncol = tm_cols.get("nombre")
        nlen = getattr(ncol.get("type"), "length", None) if ncol else None
        if ncol and nlen is not None and int(nlen) < 191:
            db.session.execute(text("ALTER TABLE oficios_catalogo_tipos_medida MODIFY COLUMN nombre VARCHAR(191) NOT NULL"))
            db.session.commit()
    except Exception:
        current_app.logger.exception("No se pudo ampliar oficios_catalogo_tipos_medida.nombre a 191")
        db.session.rollback()
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
    try:
        if CatalogoEstadoExpediente.query.count() == 0:
            for nombre, bloq in (
                ("Archivo", True),
                ("Desestimada", True),
                ("Providencia judicial", True),
            ):
                db.session.add(CatalogoEstadoExpediente(nombre=nombre, bloquea_cumplimiento=bloq, activo=True))
            db.session.commit()
    except Exception:
        current_app.logger.exception("Seed CatalogoEstadoExpediente")
        db.session.rollback()
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
    _ensure_schema()
    return ConsignaJudicial.query.filter(ConsignaJudicial.unidad_id == current_user.unidad_id)


def _manual_estado_operativo(
    row: ConsignaJudicial,
    today: date | None = None,
    *,
    cat_row: CatalogoEstadoExpediente | None = None,
) -> str:
    cr = cat_row
    if cr is None and getattr(row, "estado_expediente_id", None):
        cr = db.session.get(CatalogoEstadoExpediente, row.estado_expediente_id)
    if cr and getattr(cr, "bloquea_cumplimiento", False):
        return "sin_tramite"
    tdy = today or datetime.utcnow().date()
    if _clean(row.estado).lower() == "finalizada":
        return "finalizada"
    inicio = row.fecha_notificacion
    dias = int(row.cantidad_dias or 0)
    if inicio and dias > 0:
        vto = inicio + timedelta(days=dias)
        if vto <= tdy:
            return "finalizada"
    return "activa"


def _catalogo_estado_map(rows: list) -> dict[int, CatalogoEstadoExpediente]:
    eids = {r.estado_expediente_id for r in rows if getattr(r, "estado_expediente_id", None)}
    if not eids:
        return {}
    return {c.id: c for c in CatalogoEstadoExpediente.query.filter(CatalogoEstadoExpediente.id.in_(eids)).all()}


def _manual_compute_trans_dias(row: ConsignaJudicial, today: date | None = None) -> int:
    tdy = today or datetime.utcnow().date()
    total = int(row.cantidad_dias or 0)
    if not row.fecha_notificacion or total <= 0:
        return 0
    trans = max(0, (tdy - row.fecha_notificacion).days)
    return min(trans, total)


def _manual_etapa_slug_desde_pares(r: ConsignaJudicial, pares_raw: list, trans: int) -> str:
    pares = list(pares_raw)
    pares.sort(key=lambda p: _orden_cronologia_tipo_consigna(p[1]))
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
    if tramos:
        acc = 0
        chosen = tramos[-1]
        for t in tramos:
            acc += t[1]
            if trans < acc:
                chosen = t
                break
        n = chosen[2]
        if "fija" in n:
            return "fija"
        if "ambulator" in n:
            return "ambulatoria"
        if "personal" in n:
            return "personalizada"
        return "mixta"
    if has_indet:
        return "indeterminada"
    tc = _clean(r.tipo_consigna).lower()
    if tc in {"fija", "ambulatoria", "personalizada", "indeterminada", "mixta"}:
        return tc
    return "indeterminada"


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
    if getattr(row, "estado_expediente_id", None):
        st = db.session.get(CatalogoEstadoExpediente, row.estado_expediente_id)
        if st and st.bloquea_cumplimiento:
            return {
                "estado": "sin_cumplimiento",
                "label": f"Sin cumplimiento operativo ({st.nombre})",
                "dias_restantes": None,
                "fecha_vencimiento": None,
            }
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


def _manual_filter_options():
    catalogo_tipos = sorted(CatalogoTipoConsigna.query.filter_by(activo=True).all(), key=_orden_cronologia_tipo_consigna)
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
    return {
        "catalogo_tipos": catalogo_tipos,
        "tipos_consigna": tipos_consigna,
        "juzgados_opts": [x.nombre for x in CatalogoJuzgado.query.filter_by(activo=True).order_by(CatalogoJuzgado.nombre.asc()).all()],
        "medidas_opts": [x.nombre for x in CatalogoTipoMedida.query.filter_by(activo=True).order_by(CatalogoTipoMedida.nombre.asc()).all()],
        "fiscalias_opts": [x.nombre for x in CatalogoFiscalia.query.filter_by(activo=True).order_by(CatalogoFiscalia.nombre.asc()).all()],
        "barrios_opts": [x.nombre for x in CatalogoBarrio.query.filter_by(activo=True).order_by(CatalogoBarrio.nombre.asc()).all()],
    }


def _manual_apply_filters_query():
    opts = _manual_filter_options()
    catalogo_tipos = opts["catalogo_tipos"]
    estados = [e for e in request.args.getlist("estado") if e in ("activa", "finalizada", "sin_tramite", "sin_trámite")]
    estados = ["sin_tramite" if e == "sin_trámite" else e for e in estados]
    qtxt = _clean(request.args.get("q"))
    tipos_sel = [_clean(x) for x in request.args.getlist("tipo_consigna") if _clean(x)]
    juzgados_sel = [_clean(x) for x in request.args.getlist("juzgado") if _clean(x)]
    medidas_sel = [_clean(x) for x in request.args.getlist("tipo_medida") if _clean(x)]
    fiscalias_sel = [_clean(x) for x in request.args.getlist("fiscalia") if _clean(x)]
    barrios_sel = [_clean(x) for x in request.args.getlist("barrio") if _clean(x)]
    fecha_desde = _parse_date(_clean(request.args.get("fecha_desde")))
    fecha_hasta = _parse_date(_clean(request.args.get("fecha_hasta")))

    q = _q_base().filter(ConsignaJudicial.fuente_principal == "manual")
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
                .filter(ConsignaDiasPorTipo.tipo_catalogo_id.in_(ids_cats), ConsignaDiasPorTipo.dias > 0)
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
        sq_per = db.session.query(ConsignaPersona.consigna_id).filter(or_(ConsignaPersona.nombre.ilike(pat), ConsignaPersona.dni.ilike(pat))).subquery()
        sq_dom = db.session.query(ConsignaDomicilio.consigna_id).filter(or_(ConsignaDomicilio.direccion.ilike(pat), ConsignaDomicilio.barrio_nombre.ilike(pat))).subquery()
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
    return q, estados, opts


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
    q, estados, opts = _manual_apply_filters_query()
    catalogo_tipos = opts["catalogo_tipos"]

    page = max(1, _to_int_or_none(request.args.get("page")) or 1)
    per_page = max(10, min(100, _to_int_or_none(request.args.get("per_page")) or 25))
    today = datetime.utcnow().date()

    estados_efectivos = estados or ["activa"]
    rows_all = q.order_by(ConsignaJudicial.created_at.desc()).all()
    cat_estado_map = _catalogo_estado_map(rows_all)
    estados_set = set(estados_efectivos)
    rows_all = [
        r
        for r in rows_all
        if _manual_estado_operativo(r, cat_row=cat_estado_map.get(r.estado_expediente_id)) in estados_set
    ]

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
            estado_operativo_map[r.id] = _manual_estado_operativo(
                r, cat_row=cat_estado_map.get(r.estado_expediente_id)
            )
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
            cumplidas = []
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
                acc2 = 0
                for t in tramos:
                    acc2 += t[1]
                    if trans >= acc2:
                        cumplidas.append(t[0])
                n = chosen[2]
                if "fija" in n:
                    etapa = {"slug": "fija", "nombre": "Fija", "icono": "bi-anchor-fill", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
                elif "ambulator" in n:
                    etapa = {"slug": "ambulatoria", "nombre": "Ambulatoria", "icono": "bi-car-front-fill", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
                elif "personal" in n:
                    etapa = {"slug": "personalizada", "nombre": "Personalizada", "icono": "bi-person-circle", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
                else:
                    etapa = {"slug": _slug_tipo_consigna_desde_nombre(chosen[0]), "nombre": chosen[0], "icono": "bi-dot", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
            elif has_indet:
                etapa = {"slug": "indeterminada", "nombre": "Indeterminada", "icono": "bi-infinity", "pos": 0, "total": 0, "cumplidas": []}
            elif (r.tipo_consigna or "") == "fija":
                etapa = {"slug": "fija", "nombre": "Fija", "icono": "bi-anchor-fill", "pos": 0, "total": 0, "cumplidas": []}
            elif (r.tipo_consigna or "") == "ambulatoria":
                etapa = {"slug": "ambulatoria", "nombre": "Ambulatoria", "icono": "bi-car-front-fill", "pos": 0, "total": 0, "cumplidas": []}
            elif (r.tipo_consigna or "") == "personalizada":
                etapa = {"slug": "personalizada", "nombre": "Personalizada", "icono": "bi-person-circle", "pos": 0, "total": 0, "cumplidas": []}
            if estado_operativo_map.get(r.id) == "finalizada" and tramos:
                etapa["cumplidas"] = [t[0] for t in tramos]
            etapa_actual_map[r.id] = etapa

    args_multi = request.args.to_dict(flat=False)
    args_multi.pop("page", None)
    args_multi.pop("per_page", None)
    export_url = url_for("oficios_judiciales.manual_export_xlsx")
    if args_multi:
        export_url = f"{export_url}?{urlencode(args_multi, doseq=True)}"
    args_estad = {k: list(v) for k, v in args_multi.items()}
    args_estad["year"] = [str(datetime.utcnow().year)]
    export_estad_url = url_for("oficios_judiciales.manual_export_estadistico_anual")
    if args_estad:
        export_estad_url = f"{export_estad_url}?{urlencode(args_estad, doseq=True)}"

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
        tipos_consigna=opts["tipos_consigna"],
        juzgados_opts=opts["juzgados_opts"],
        medidas_opts=opts["medidas_opts"],
        fiscalias_opts=opts["fiscalias_opts"],
        barrios_opts=opts["barrios_opts"],
        personas_map=personas_map,
        domicilios_map=domicilios_map,
        persona_domicilio_map=persona_domicilio_map,
        coords_map=coords_map,
        progreso_map=progreso_map,
        etapa_actual_map=etapa_actual_map,
        estado_operativo_map=estado_operativo_map,
        pagination=pagination,
        export_url=export_url,
        export_estad_url=export_estad_url,
        can_delete_superadmin=_is_superadmin(),
    )


@bp.route("/manual/<int:consigna_id>/eliminar", methods=["POST"])
def manual_eliminar(consigna_id: int):
    if not _is_superadmin():
        abort(403)
    row = (
        ConsignaJudicial.query.filter(
            ConsignaJudicial.id == consigna_id,
            ConsignaJudicial.unidad_id == current_user.unidad_id,
            ConsignaJudicial.fuente_principal == "manual",
        ).first()
    )
    if not row:
        flash("No se encontró la consigna a eliminar.", "warning")
        return redirect(url_for("oficios_judiciales.manual_listado"))
    db.session.delete(row)
    db.session.commit()
    flash("Consigna eliminada correctamente.", "success")
    return redirect(url_for("oficios_judiciales.manual_listado"))


@bp.route("/manual/export.xlsx")
def manual_export_xlsx():
    if not (_can_export() or _can_view()):
        abort(403)
    q, estados, _opts = _manual_apply_filters_query()
    rows = q.order_by(ConsignaJudicial.created_at.desc()).all()
    cat_estado_map = _catalogo_estado_map(rows)
    estados_efectivos = estados or ["activa"]
    est_set = set(estados_efectivos)
    rows = [
        r
        for r in rows
        if _manual_estado_operativo(r, cat_row=cat_estado_map.get(r.estado_expediente_id)) in est_set
    ]
    if not rows:
        bio = io.BytesIO()
        pd.DataFrame(
            [
                {
                    "id": None,
                    "expediente": "",
                    "seps_ingreso": "",
                    "seps_salida": "",
                    "caratula": "",
                    "juzgado": "",
                    "fiscalia": "",
                    "tipo_medida": "",
                    "fecha_notificacion": "",
                    "fecha_oficio": "",
                    "dias_total": 0,
                    "estado_operativo": "",
                    "estado_expediente": "",
                    "etapa_actual": "",
                    "progreso": "",
                    "personas": "",
                    "domicilios": "",
                    "barrios": "",
                    "coords": "",
                }
            ]
        ).iloc[0:0].to_excel(bio, index=False)
        bio.seek(0)
        return Response(
            bio.read(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=consignas_filtradas_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"},
        )

    row_ids = [r.id for r in rows]
    pers = (
        ConsignaPersona.query.filter(ConsignaPersona.consigna_id.in_(row_ids))
        .order_by(ConsignaPersona.consigna_id.asc(), ConsignaPersona.id.asc())
        .all()
    )
    doms = (
        ConsignaDomicilio.query.filter(ConsignaDomicilio.consigna_id.in_(row_ids))
        .order_by(ConsignaDomicilio.consigna_id.asc(), ConsignaDomicilio.id.asc())
        .all()
    )
    dias_pairs = (
        db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
        .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
        .filter(ConsignaDiasPorTipo.consigna_id.in_(row_ids))
        .all()
    )
    personas_map: dict[int, list[ConsignaPersona]] = {}
    for p in pers:
        personas_map.setdefault(p.consigna_id, []).append(p)
    domicilios_map: dict[int, list[ConsignaDomicilio]] = {}
    for d in doms:
        domicilios_map.setdefault(d.consigna_id, []).append(d)
    dias_map: dict[int, list[tuple[ConsignaDiasPorTipo, CatalogoTipoConsigna]]] = {}
    for dp, cat in dias_pairs:
        dias_map.setdefault(dp.consigna_id, []).append((dp, cat))

    out_rows = []
    today = datetime.utcnow().date()
    for r in rows:
        total = int(r.cantidad_dias or 0)
        trans = 0
        if r.fecha_notificacion and total > 0:
            trans = max(0, (today - r.fecha_notificacion).days)
            if trans > total:
                trans = total
        etapa_nombre = "Indeterminada"
        pares = list(dias_map.get(r.id, []))
        pares.sort(key=lambda p: _orden_cronologia_tipo_consigna(p[1]))
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
        if tramos:
            acc = 0
            chosen = tramos[-1]
            for t in tramos:
                acc += t[1]
                if trans < acc:
                    chosen = t
                    break
            n = chosen[2]
            if "fija" in n:
                etapa_nombre = "Fija"
            elif "ambulator" in n:
                etapa_nombre = "Ambulatoria"
            elif "personal" in n:
                etapa_nombre = "Personalizada"
            else:
                etapa_nombre = _clean(chosen[0]) or "Indeterminada"
        elif has_indet:
            etapa_nombre = "Indeterminada"
        else:
            tc = _clean(r.tipo_consigna).lower()
            if tc == "fija":
                etapa_nombre = "Fija"
            elif tc == "ambulatoria":
                etapa_nombre = "Ambulatoria"
            elif tc == "personalizada":
                etapa_nombre = "Personalizada"
            elif tc == "indeterminada":
                etapa_nombre = "Indeterminada"
        personas_txt = " | ".join(
            [
                f"{(_clean(p.tipo) or 'persona').title()}: {_clean(p.nombre) or '—'} ({_clean(p.dni) or 'SIN DNI'})"
                for p in personas_map.get(r.id, [])
            ]
        )
        doms_row = domicilios_map.get(r.id, [])
        domicilios_txt = " | ".join([_clean(d.direccion) for d in doms_row if _clean(d.direccion)])
        barrios_txt = " | ".join([_clean(d.barrio_nombre) for d in doms_row if _clean(d.barrio_nombre)])
        coords_txt = " | ".join(
            [f"{d.latitud}, {d.longitud}" for d in doms_row if d.latitud is not None and d.longitud is not None]
        )
        ee = cat_estado_map.get(r.estado_expediente_id) if r.estado_expediente_id else None
        out_rows.append(
            {
                "id": r.id,
                "expediente": r.expediente or "",
                "seps_ingreso": r.seps_ingreso or "",
                "seps_salida": r.seps_salida or "",
                "caratula": r.caratula or "",
                "juzgado": r.juzgado or "",
                "fiscalia": r.fiscalia or "",
                "tipo_medida": r.tipo_medida or "",
                "fecha_notificacion": r.fecha_notificacion,
                "fecha_oficio": r.fecha_oficio,
                "dias_total": total,
                "estado_expediente": ee.nombre if ee else "",
                "estado_operativo": _manual_estado_operativo(r, cat_row=ee),
                "etapa_actual": etapa_nombre,
                "motivo_indeterminada": (r.motivo_indeterminada.nombre if getattr(r, "motivo_indeterminada", None) else ""),
                "progreso": f"{trans}/{total}" if total > 0 else "0/0",
                "personas": personas_txt,
                "domicilios": domicilios_txt,
                "barrios": barrios_txt,
                "coords": coords_txt,
            }
        )
    bio = io.BytesIO()
    pd.DataFrame(out_rows).to_excel(bio, index=False)
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=consignas_filtradas_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"},
    )


@bp.route("/manual/export-estadistico-anual.xlsx")
def manual_export_estadistico_anual():
    """
    Matriz mensual (ENE–DIC) estilo informe policial: totales y reparto víctima/acusado por etapa.
    Respeta los mismos filtros que el listado (búsqueda, barrio, fechas, etc.), pero siempre por año civil de fecha de notificación.
    """
    if not (_can_export() or _can_view()):
        abort(403)
    year = _to_int_or_none(request.args.get("year")) or datetime.utcnow().year
    q, _est, _opts = _manual_apply_filters_query()
    rows = q.all()
    cats = _catalogo_estado_map(rows)
    rows_y = [r for r in rows if r.fecha_notificacion and r.fecha_notificacion.year == year]
    meses = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
    if not rows_y:
        bio = io.BytesIO()
        pd.DataFrame([{"Rubro": "", **{m: "" for m in meses}, "TOTAL": ""}]).iloc[0:0].to_excel(bio, index=False)
        bio.seek(0)
        return Response(
            bio.read(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=estadistico_consignas_{year}_vacio_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
            },
        )

    ids = [r.id for r in rows_y]
    pers = ConsignaPersona.query.filter(ConsignaPersona.consigna_id.in_(ids)).all()
    pers_map: dict[int, list] = {}
    for p in pers:
        pers_map.setdefault(p.consigna_id, []).append(p)
    dias_pairs = (
        db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
        .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
        .filter(ConsignaDiasPorTipo.consigna_id.in_(ids))
        .all()
    )
    dias_map: dict[int, list] = {}
    for dp, cat in dias_pairs:
        dias_map.setdefault(dp.consigna_id, []).append((dp, cat))

    rubros: dict[str, dict[str, int]] = {}

    def bump(label: str, month: int, n: int = 1):
        if label not in rubros:
            rubros[label] = {m: 0 for m in meses}
            rubros[label]["TOTAL"] = 0
        rubros[label][meses[month - 1]] += n
        rubros[label]["TOTAL"] += n

    today = datetime.utcnow().date()
    for r in rows_y:
        m = int(r.fecha_notificacion.month)
        op = _manual_estado_operativo(r, cat_row=cats.get(r.estado_expediente_id))
        bump("Total cargadas (por mes de fecha notificación)", m)
        if op == "sin_tramite":
            bump("Sin cumplimiento judicial (estado expediente)", m)
            continue
        bump("Con cumplimiento operativo", m)
        trans = _manual_compute_trans_dias(r, today)
        slug = _manual_etapa_slug_desde_pares(r, dias_map.get(r.id, []), trans)
        plist = pers_map.get(r.id, [])
        has_v = any(_clean(x.tipo).lower() == "victima" for x in plist)
        has_a = any(_clean(x.tipo).lower() == "denunciado" for x in plist)
        if has_v:
            if slug == "fija":
                bump("Víctimas — Fija", m)
            elif slug == "ambulatoria":
                bump("Víctimas — Ambulatoria", m)
            elif slug == "personalizada":
                bump("Víctimas — Personalizada", m)
            elif slug in ("indeterminada", "mixta"):
                bump("Víctimas — Indeterminada / mixta", m)
        if has_a:
            if slug == "fija":
                bump("Acusados — Fija", m)
            elif slug == "ambulatoria":
                bump("Acusados — Ambulatoria", m)
            elif slug == "personalizada":
                bump("Acusados — Personalizada", m)
            elif slug in ("indeterminada", "mixta"):
                bump("Acusados — Indeterminada / mixta", m)

    order = [
        "Total cargadas (por mes de fecha notificación)",
        "Sin cumplimiento judicial (estado expediente)",
        "Con cumplimiento operativo",
        "Víctimas — Fija",
        "Víctimas — Ambulatoria",
        "Víctimas — Personalizada",
        "Víctimas — Indeterminada / mixta",
        "Acusados — Fija",
        "Acusados — Ambulatoria",
        "Acusados — Personalizada",
        "Acusados — Indeterminada / mixta",
    ]
    out_list = []
    for lab in order:
        if lab not in rubros:
            continue
        row = {"Rubro / indicador": lab, **{mm: int(rubros[lab][mm]) for mm in meses}, "TOTAL": int(rubros[lab]["TOTAL"])}
        out_list.append(row)
    for lab, data in rubros.items():
        if lab in order:
            continue
        out_list.append({"Rubro / indicador": lab, **{mm: int(data[mm]) for mm in meses}, "TOTAL": int(data["TOTAL"])})

    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame(out_list).to_excel(writer, sheet_name=f"Consignas {year}", index=False)
        pd.DataFrame(
            [
                {
                    "Nota": "Los totales usan la fecha de notificación de cada consigna. "
                    "«Sin cumplimiento judicial» corresponde a estados del expediente marcados en catálogo como que bloquean cumplimiento."
                }
            ]
        ).to_excel(writer, sheet_name="Leyenda", index=False)
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=estadistico_consignas_{year}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
        },
    )


@bp.route("/manual/dashboard")
def manual_dashboard():
    if not _can_view():
        abort(403)
    base, estados, opts = _manual_apply_filters_query()
    rows = base.all()
    cats = _catalogo_estado_map(rows)
    if estados:
        est_set = set(estados)
        rows = [r for r in rows if _manual_estado_operativo(r, cat_row=cats.get(r.estado_expediente_id)) in est_set]
    total = len(rows)
    activas = len([r for r in rows if _manual_estado_operativo(r, cat_row=cats.get(r.estado_expediente_id)) == "activa"])
    finalizadas = len([r for r in rows if _manual_estado_operativo(r, cat_row=cats.get(r.estado_expediente_id)) == "finalizada"])
    sin_tramite_n = len([r for r in rows if _manual_estado_operativo(r, cat_row=cats.get(r.estado_expediente_id)) == "sin_tramite"])
    by_tipo = {}
    by_mes = {}
    by_fecha = {}
    by_juzgado = {}
    by_fiscalia = {}
    by_estado = {"Activa": 0, "Finalizada": 0, "Sin trámite judicial": 0}
    row_ids = [r.id for r in rows]
    dias_por_consigna = {}
    if row_ids:
        dias_pairs = (
            db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
            .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
            .filter(ConsignaDiasPorTipo.consigna_id.in_(row_ids))
            .all()
        )
        for dp, cat in dias_pairs:
            dias_por_consigna.setdefault(dp.consigna_id, []).append((dp, cat))

    def _etapa_dashboard(r: ConsignaJudicial) -> str:
        pares = list(dias_por_consigna.get(r.id, []))
        pares.sort(key=lambda p: _orden_cronologia_tipo_consigna(p[1]))
        today = datetime.utcnow().date()
        total = int(r.cantidad_dias or 0)
        trans = 0
        if r.fecha_notificacion and total > 0:
            trans = max(0, (today - r.fecha_notificacion).days)
            if trans > total:
                trans = total
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
        if tramos:
            acc = 0
            chosen = tramos[-1]
            for t in tramos:
                acc += t[1]
                if trans < acc:
                    chosen = t
                    break
            n = chosen[2]
            if "fija" in n:
                return "fija"
            if "ambulator" in n:
                return "ambulatoria"
            if "personal" in n:
                return "personalizada"
            return _clean(chosen[0]).lower() or "indeterminada"
        if has_indet:
            return "indeterminada"
        tc = _clean(r.tipo_consigna).lower()
        if tc in {"fija", "ambulatoria", "personalizada", "indeterminada"}:
            return tc
        # Evita mostrar "mixta" como categoría en dashboard.
        if tc == "mixta":
            return "indeterminada"
        return tc or "indeterminada"

    for r in rows:
        op = _manual_estado_operativo(r, cat_row=cats.get(r.estado_expediente_id))
        if op == "sin_tramite":
            by_tipo["sin_tramite"] = by_tipo.get("sin_tramite", 0) + 1
        else:
            t = _etapa_dashboard(r)
            by_tipo[t] = by_tipo.get(t, 0) + 1
        j = _clean(r.juzgado) or "—"
        by_juzgado[j] = by_juzgado.get(j, 0) + 1
        f = _clean(r.fiscalia) or "—"
        by_fiscalia[f] = by_fiscalia.get(f, 0) + 1
        if op == "sin_tramite":
            by_estado["Sin trámite judicial"] = by_estado.get("Sin trámite judicial", 0) + 1
        elif op == "activa":
            by_estado["Activa"] = by_estado.get("Activa", 0) + 1
        else:
            by_estado["Finalizada"] = by_estado.get("Finalizada", 0) + 1
        dt = r.fecha_notificacion or (r.created_at.date() if r.created_at else None)
        if dt:
            mk = f"{dt.year:04d}-{dt.month:02d}"
            by_mes[mk] = by_mes.get(mk, 0) + 1
            dk = dt.strftime("%Y-%m-%d")
            by_fecha[dk] = by_fecha.get(dk, 0) + 1
    tipo_labels = {
        "ambulatoria": "Ambulatoria",
        "fija": "Fija",
        "personalizada": "Personalizada",
        "indeterminada": "Indeterminada",
        "sin_tramite": "Sin trámite judicial",
    }
    por_tipo = [
        (tipo_labels.get(k, _clean(k).title() or "Indeterminada"), int(v))
        for k, v in sorted(by_tipo.items(), key=lambda x: x[1], reverse=True)
    ]
    por_tipo_slug_map = {tipo_labels.get(k, _clean(k).title() or "Indeterminada"): k for k in by_tipo.keys()}
    por_mes = sorted(by_mes.items(), key=lambda x: x[0])
    por_fecha = sorted(by_fecha.items(), key=lambda x: x[0])
    por_juzgado = [(k, int(v)) for k, v in sorted(by_juzgado.items(), key=lambda x: x[1], reverse=True)]
    por_fiscalia = [(k, int(v)) for k, v in sorted(by_fiscalia.items(), key=lambda x: x[1], reverse=True)]
    por_estado = [(k, int(v)) for k, v in by_estado.items()]
    ids = [r.id for r in rows] or [-1]
    por_barrio_q = (
        db.session.query(ConsignaDomicilio.barrio_nombre, func.count(ConsignaDomicilio.id))
        .join(ConsignaJudicial, ConsignaJudicial.id == ConsignaDomicilio.consigna_id)
        .filter(
            ConsignaJudicial.unidad_id == current_user.unidad_id,
            ConsignaJudicial.fuente_principal == "manual",
            ConsignaJudicial.id.in_(ids),
            ConsignaDomicilio.barrio_nombre.isnot(None),
            ConsignaDomicilio.barrio_nombre != "",
        )
        .group_by(ConsignaDomicilio.barrio_nombre)
        .order_by(func.count(ConsignaDomicilio.id).desc())
        .all()
    )
    por_barrio = [(_clean(r[0]), int(r[1])) for r in por_barrio_q if _clean(r[0])]
    today = datetime.utcnow().date()
    cur_month_key = f"{today.year:04d}-{today.month:02d}"
    prev_year = today.year if today.month > 1 else today.year - 1
    prev_month = today.month - 1 if today.month > 1 else 12
    prev_month_key = f"{prev_year:04d}-{prev_month:02d}"
    total_mes_actual = int(by_mes.get(cur_month_key, 0))
    total_mes_anterior = int(by_mes.get(prev_month_key, 0))
    if total_mes_anterior > 0:
        variacion_mensual_pct = round(((total_mes_actual - total_mes_anterior) / total_mes_anterior) * 100.0, 1)
    elif total_mes_actual > 0:
        variacion_mensual_pct = 100.0
    else:
        variacion_mensual_pct = 0.0
    return render_template(
        "oficios_judiciales/manual_dashboard.html",
        total=total,
        activas=activas,
        finalizadas=finalizadas,
        sin_tramite_n=sin_tramite_n,
        total_mes_actual=total_mes_actual,
        total_mes_anterior=total_mes_anterior,
        variacion_mensual_pct=variacion_mensual_pct,
        cur_month_key=cur_month_key,
        prev_month_key=prev_month_key,
        por_tipo=por_tipo,
        por_tipo_slug_map=por_tipo_slug_map,
        por_mes=por_mes,
        por_fecha=por_fecha,
        por_estado=por_estado,
        por_juzgado=por_juzgado,
        por_fiscalia=por_fiscalia,
        por_barrio=por_barrio,
        selected=request.args,
        tipos_consigna=opts["tipos_consigna"],
        juzgados_opts=opts["juzgados_opts"],
        medidas_opts=opts["medidas_opts"],
        fiscalias_opts=opts["fiscalias_opts"],
        barrios_opts=opts["barrios_opts"],
    )


@bp.route("/manual/mapa")
def manual_mapa():
    if not _can_view():
        abort(403)
    base, estados, opts = _manual_apply_filters_query()
    estados_efectivos = estados or ["activa"]
    base_rows = base.all()
    cat_estado_map = _catalogo_estado_map(base_rows)
    est_set = set(estados_efectivos)
    base_rows = [
        r
        for r in base_rows
        if _manual_estado_operativo(r, cat_row=cat_estado_map.get(r.estado_expediente_id)) in est_set
    ]
    allowed_ids = [r.id for r in base_rows] or [-1]
    q = (
        db.session.query(ConsignaJudicial, ConsignaDomicilio)
        .join(ConsignaDomicilio, ConsignaDomicilio.consigna_id == ConsignaJudicial.id)
        .filter(
            ConsignaJudicial.unidad_id == current_user.unidad_id,
            ConsignaJudicial.fuente_principal == "manual",
            ConsignaJudicial.id.in_(allowed_ids),
            ConsignaDomicilio.latitud.isnot(None),
            ConsignaDomicilio.longitud.isnot(None),
        )
    )
    rows = q.order_by(ConsignaJudicial.id.desc()).limit(1000).all()
    consigna_ids = [r.id for r, _ in rows]
    dias_por_consigna = {}
    if consigna_ids:
        dias_pairs = (
            db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
            .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
            .filter(ConsignaDiasPorTipo.consigna_id.in_(consigna_ids))
            .all()
        )
        for dp, cat in dias_pairs:
            dias_por_consigna.setdefault(dp.consigna_id, []).append((dp, cat))

    def _etapa_slug_mapa(r: ConsignaJudicial) -> str:
        pares = list(dias_por_consigna.get(r.id, []))
        pares.sort(key=lambda p: _orden_cronologia_tipo_consigna(p[1]))
        today = datetime.utcnow().date()
        total = int(r.cantidad_dias or 0)
        trans = 0
        if r.fecha_notificacion and total > 0:
            trans = max(0, (today - r.fecha_notificacion).days)
            if trans > total:
                trans = total
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
        if tramos:
            acc = 0
            chosen = tramos[-1]
            for t in tramos:
                acc += t[1]
                if trans < acc:
                    chosen = t
                    break
            n = chosen[2]
            if "fija" in n:
                return "fija"
            if "ambulator" in n:
                return "ambulatoria"
            if "personal" in n:
                return "personalizada"
            return _slug_tipo_consigna_desde_nombre(chosen[0]) or "indeterminada"
        if has_indet:
            return "indeterminada"
        tc = _clean(r.tipo_consigna).lower()
        if tc in {"fija", "ambulatoria", "personalizada", "indeterminada"}:
            return tc
        return "indeterminada"

    points = []
    for r, d in rows:
        etapa_slug = _etapa_slug_mapa(r)
        tipo_label = {
            "fija": "Fija",
            "ambulatoria": "Ambulatoria",
            "personalizada": "Personalizada",
            "indeterminada": "Indeterminada",
        }.get(etapa_slug, etapa_slug.title())
        points.append(
            {
                "id": r.id,
                "expediente": r.expediente,
                "tipo_consigna": tipo_label,
                "tipo_slug": etapa_slug,
                "estado": _manual_estado_operativo(r, cat_row=cat_estado_map.get(r.estado_expediente_id)),
                "barrio": d.barrio_nombre or "",
                "direccion": d.direccion or "",
                "lat": d.latitud,
                "lng": d.longitud,
                "detalle_url": url_for("oficios_judiciales.detalle", consigna_id=r.id),
            }
        )
    return render_template(
        "oficios_judiciales/manual_mapa.html",
        points_json=json.dumps(points),
        tipos_consigna=opts["tipos_consigna"],
        juzgados_opts=opts["juzgados_opts"],
        medidas_opts=opts["medidas_opts"],
        fiscalias_opts=opts["fiscalias_opts"],
        barrios_opts=opts["barrios_opts"],
        selected=request.args,
    )


@bp.route("/manual/reincidencias")
def manual_reincidencias():
    if not _can_view():
        abort(403)
    base, estados, opts = _manual_apply_filters_query()
    estados_efectivos = estados or ["activa"]
    base_rows = base.all()
    cat_estado_map = _catalogo_estado_map(base_rows)
    est_set = set(estados_efectivos)
    base_rows = [
        r
        for r in base_rows
        if _manual_estado_operativo(r, cat_row=cat_estado_map.get(r.estado_expediente_id)) in est_set
    ]
    allowed_ids = [r.id for r in base_rows] or [-1]
    qtxt = _clean(request.args.get("q"))
    persona_sel = _clean(request.args.get("persona_key"))
    pers_rows = (
        db.session.query(ConsignaPersona, ConsignaJudicial)
        .join(ConsignaJudicial, ConsignaJudicial.id == ConsignaPersona.consigna_id)
        .filter(
            ConsignaJudicial.unidad_id == current_user.unidad_id,
            ConsignaJudicial.fuente_principal == "manual",
            ConsignaJudicial.id.in_(allowed_ids),
        )
        .order_by(
            ConsignaJudicial.fecha_notificacion.is_(None),
            ConsignaJudicial.fecha_notificacion.desc(),
            ConsignaJudicial.id.desc(),
        )
        .all()
    )
    grupos = {}
    for p, cj in pers_rows:
        nombre = _clean(p.nombre)
        dni = _clean(p.dni)
        dni_norm = _digits_only(dni)
        if not nombre and not dni:
            continue
        key = f"dni:{dni_norm}" if dni_norm else f"nom:{_ascii_lower_no_accent(nombre)}"
        g = grupos.setdefault(
            key,
            {
                "persona_key": key,
                "nombre": nombre,
                "dni": dni,
                "dni_norm": dni_norm,
                "n": 0,
                "activa": 0,
                "finalizada": 0,
                "last_fecha": None,
                "items": [],
            },
        )
        g["n"] += 1
        est = _manual_estado_operativo(cj, cat_row=cat_estado_map.get(cj.estado_expediente_id))
        if est == "activa":
            g["activa"] += 1
        else:
            g["finalizada"] += 1
        fnot = cj.fecha_notificacion
        if fnot and (g["last_fecha"] is None or fnot > g["last_fecha"]):
            g["last_fecha"] = fnot
        g["items"].append(
            {
                "nombre": nombre,
                "dni": dni,
                "id": cj.id,
                "expediente": cj.expediente,
                "tipo_consigna": cj.tipo_consigna,
                "estado": est,
                "fecha_notificacion": cj.fecha_notificacion,
            }
        )
        if not g["nombre"] and nombre:
            g["nombre"] = nombre
        if not g["dni"] and dni:
            g["dni"] = dni

    coincidencias = [g for g in grupos.values() if g["n"] > 1]
    if qtxt:
        qn = _ascii_lower_no_accent(qtxt)
        qd = _digits_only(qtxt)
        coincidencias = [
            g
            for g in coincidencias
            if qn in _ascii_lower_no_accent(g.get("nombre", ""))
            or qn in _ascii_lower_no_accent(g.get("dni", ""))
            or (qd and qd in _digits_only(g.get("dni", "")))
        ]
    coincidencias.sort(
        key=lambda g: (
            int(g.get("n", 0)),
            int(g.get("activa", 0)),
            g.get("last_fecha") or date.min,
        ),
        reverse=True,
    )
    coincidencias = coincidencias[:200]
    if not persona_sel and coincidencias:
        persona_sel = coincidencias[0]["persona_key"]
    detalle = []
    persona_resumen = None
    detalle_points = []
    for g in coincidencias:
        if g.get("persona_key") == persona_sel:
            detalle = list(g.get("items", []))
            total = int(g.get("n", 0))
            activas = int(g.get("activa", 0))
            finalizadas = int(g.get("finalizada", 0))
            if activas > 0 and finalizadas > 0:
                estado_txt = "tiene historial mixto (activas y finalizadas)"
            elif activas > 0:
                estado_txt = "tiene consignas activas en curso"
            else:
                estado_txt = "solo tiene consignas finalizadas"
            persona_resumen = {
                "nombre": g.get("nombre") or "Sin nombre",
                "dni": g.get("dni") or "",
                "total": total,
                "activas": activas,
                "finalizadas": finalizadas,
                "estado_txt": estado_txt,
            }
            break
    if detalle:
        detalle_by_id = {int(d.get("id")): d for d in detalle if d.get("id")}
        dom_rows = (
            db.session.query(ConsignaDomicilio)
            .filter(
                ConsignaDomicilio.consigna_id.in_(list(detalle_by_id.keys())),
                ConsignaDomicilio.latitud.isnot(None),
                ConsignaDomicilio.longitud.isnot(None),
            )
            .all()
        )
        for d in dom_rows:
            ref = detalle_by_id.get(int(d.consigna_id))
            if not ref:
                continue
            detalle_points.append(
                {
                    "id": int(d.consigna_id),
                    "expediente": ref.get("expediente") or "",
                    "tipo_consigna": ref.get("tipo_consigna") or "",
                    "estado": ref.get("estado") or "",
                    "barrio": d.barrio_nombre or "",
                    "direccion": d.direccion or "",
                    "lat": d.latitud,
                    "lng": d.longitud,
                    "detalle_url": url_for("oficios_judiciales.detalle", consigna_id=d.consigna_id),
                }
            )
    return render_template(
        "oficios_judiciales/manual_reincidencias.html",
        rows=coincidencias,
        detalle=detalle,
        persona_resumen=persona_resumen,
        detalle_points_json=json.dumps(detalle_points),
        persona_sel=persona_sel,
        selected=request.args,
        tipos_consigna=opts["tipos_consigna"],
        juzgados_opts=opts["juzgados_opts"],
        medidas_opts=opts["medidas_opts"],
        fiscalias_opts=opts["fiscalias_opts"],
        barrios_opts=opts["barrios_opts"],
    )


@bp.route("/manual/autofill", methods=["POST"])
def manual_autofill():
    if not _can_upload():
        abort(403)
    files = request.files.getlist("archivos")
    files = [f for f in files if _clean(getattr(f, "filename", ""))]
    if not files:
        return jsonify({"ok": False, "error": "Debe seleccionar al menos un archivo."}), 400
    files = sorted(files, key=lambda ff: _file_order_key(getattr(ff, "filename", "")))

    merged = {}
    warnings = []
    for f in files:
        name = _clean(f.filename)
        raw = f.read()
        if not raw:
            continue
        txt_ocr = ""
        txt_qr = ""
        if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            payload, _ = _extract_qr_text_from_image(raw)
            if payload:
                resolved, _u = _resolve_qr_payload(payload)
                txt_qr = resolved or payload
            txt_ocr, _err = _extract_ocr_text_from_image_with_error(raw)
        elif name.lower().endswith(".pdf"):
            txt_pdf = _extract_text_from_pdf(raw)
            if len(_clean(txt_pdf)) >= _MIN_PDF_TEXT_LEN:
                txt_ocr = txt_pdf
            else:
                txt_qr_pdf, txt_ocr_pdf, _qr_url_pdf, warn_list = _scan_pdf_as_images(raw)
                if warn_list:
                    warnings.extend([f"{name}: {w}" for w in warn_list])
                txt_qr = txt_qr_pdf
                txt_ocr = txt_ocr_pdf or txt_pdf
        else:
            warnings.append(f"{name}: formato no soportado.")
            continue
        parsed_qr = _parse_fields(txt_qr) if _clean(txt_qr) else {}
        parsed_ocr = _parse_fields(txt_ocr) if _clean(txt_ocr) else {}
        if _parsed_score(parsed_ocr) > _parsed_score(parsed_qr):
            merged = _merge_parsed(merged, parsed_ocr)
            merged = _merge_parsed(merged, parsed_qr)
        else:
            merged = _merge_parsed(merged, parsed_qr)
            merged = _merge_parsed(merged, parsed_ocr)

    if not merged:
        return jsonify({"ok": False, "error": "No se pudo extraer información útil del archivo."}), 400

    personas = []

    def _add_person(nombre, dni, tipo, domicilio):
        nom = _clean(nombre)
        dd = _clean(dni)
        dom = _clean(domicilio)
        if not nom and not dd and not dom:
            return
        personas.append(
            {
                "nombre": nom,
                "dni": dd,
                "tipo": "denunciado" if _clean(tipo).lower() == "denunciado" else "victima",
                "domicilio": dom,
                "notificar": "si" if _clean(tipo).lower() == "denunciado" else "no",
            }
        )

    _add_person(
        merged.get("persona_denunciada"),
        merged.get("dni_denunciado"),
        "denunciado",
        merged.get("domicilio_denunciado"),
    )
    _add_person(
        merged.get("victima"),
        merged.get("dni_victima"),
        "victima",
        merged.get("domicilio_victima"),
    )
    _add_person(
        merged.get("victima_2"),
        merged.get("dni_victima_2"),
        "victima",
        merged.get("domicilio_victima_2"),
    )
    _add_person(
        merged.get("acusado_2"),
        merged.get("dni_acusado_2"),
        "denunciado",
        merged.get("domicilio_acusado_2"),
    )
    _add_person(
        merged.get("victima_3"),
        merged.get("dni_victima_3"),
        "victima",
        merged.get("domicilio_victima_3"),
    )
    for ax in merged.get("acusados_extra") or []:
        if isinstance(ax, dict):
            _add_person(ax.get("nombre"), ax.get("dni"), "denunciado", ax.get("domicilio"))
    for vx in merged.get("victimas_extra_detalle") or []:
        if isinstance(vx, dict):
            _add_person(vx.get("nombre"), vx.get("dni"), "victima", vx.get("domicilio"))

    data = {
        "expediente": _clean(merged.get("expediente")),
        "caratula": _clean(merged.get("caratula")),
        "juzgado": _clean(merged.get("juzgado")),
        "tipo_medida": _clean(merged.get("tipo_medida")),
        "fiscalia": _clean(merged.get("fiscalia")),
        "fecha_notificacion": _to_input_date(merged.get("fecha_notificacion")),
        "personas": personas,
        "warnings": warnings,
    }
    return jsonify({"ok": True, "data": data})


@bp.route("/manual/nuevo", methods=["GET", "POST"])
def manual_nuevo():
    if not _can_view():
        abort(403)
    _ensure_schema()
    juzgados = CatalogoJuzgado.query.filter_by(activo=True).order_by(CatalogoJuzgado.nombre.asc()).all()
    tipos_medida = CatalogoTipoMedida.query.filter_by(activo=True).order_by(CatalogoTipoMedida.nombre.asc()).all()
    fiscalias = CatalogoFiscalia.query.filter_by(activo=True).order_by(CatalogoFiscalia.nombre.asc()).all()
    motivos_indeterminada = (
        CatalogoMotivoIndeterminada.query.filter_by(activo=True).order_by(CatalogoMotivoIndeterminada.nombre.asc()).all()
    )
    estados_expediente = (
        CatalogoEstadoExpediente.query.filter_by(activo=True).order_by(CatalogoEstadoExpediente.nombre.asc()).all()
    )
    barrios = CatalogoBarrio.query.filter_by(activo=True).order_by(CatalogoBarrio.nombre.asc()).all()
    tipos_consigna_catalogo = sorted(
        CatalogoTipoConsigna.query.filter_by(activo=True).all(),
        key=_orden_tipo_consigna_catalogo,
    )
    edit_id = _to_int_or_none(request.form.get("edit_id") or request.args.get("edit_id"))
    row_edit = None
    if edit_id:
        row_edit = ConsignaJudicial.query.filter_by(
            id=edit_id, unidad_id=current_user.unidad_id, fuente_principal="manual"
        ).first()
    if request.method == "POST":
        ee_id = _to_int_or_none(request.form.get("estado_expediente_id"))
        ee_row = CatalogoEstadoExpediente.query.filter_by(id=ee_id, activo=True).first() if ee_id else None
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
        motivo_indeterminada_id = _to_int_or_none(request.form.get("motivo_indeterminada_id"))
        id_to_dias: dict[int, int] = {}
        has_indeterminada = False
        for tc in tipos_consigna_catalogo:
            v = _to_int_or_none(request.form.get(f"dias_por_tipo_{tc.id}"))
            d = 0 if v is None else max(0, v)
            if _es_tipo_indeterminada_catalogo(tc.nombre):
                d = 1 if d else 0
                has_indeterminada = has_indeterminada or bool(d)
            id_to_dias[tc.id] = d
        if has_indeterminada:
            # Regla de negocio: si es indeterminada, no pueden coexistir tramos en días.
            for tc in tipos_consigna_catalogo:
                if not _es_tipo_indeterminada_catalogo(tc.nombre):
                    id_to_dias[tc.id] = 0
        cantidad_dias = 0
        for tc in tipos_consigna_catalogo:
            d = id_to_dias.get(tc.id, 0)
            if _es_tipo_indeterminada_catalogo(tc.nombre):
                continue
            cantidad_dias += d
        tipo_consigna = "indeterminada" if has_indeterminada else _derive_tipo_consigna_desde_catalogo(id_to_dias, cat_by_id)
        d_fija, d_amb, d_pers = (0, 0, 0) if has_indeterminada else _legacy_tres_columnas_desde_catalogo(id_to_dias, cat_by_id)
        exp_key = _expediente_key(exp)
        juz_key = _juzgado_key(juz) if juz else ""

        row = row_edit
        if row is None and exp_key:
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
                motivo_indeterminada_id=motivo_indeterminada_id if has_indeterminada else None,
                estado_expediente_id=ee_row.id if ee_row else None,
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
            row.motivo_indeterminada_id = motivo_indeterminada_id if has_indeterminada else None
            row.estado_expediente_id = ee_row.id if ee_row else None
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

        if row_edit:
            ConsignaPersona.query.filter_by(consigna_id=row.id).delete(synchronize_session=False)
            ConsignaDomicilio.query.filter_by(consigna_id=row.id).delete(synchronize_session=False)
            ConsignaMedidaDetalle.query.filter_by(consigna_id=row.id).delete(synchronize_session=False)

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
        flash("Consigna manual actualizada." if row_edit else "Consigna manual guardada.", "success")
        return redirect(url_for("oficios_judiciales.detalle", consigna_id=row.id))

    form_data = {}
    selected_juzgado_ids = []
    selected_tipo_medida_ids = []
    selected_fiscalia_ids = []
    dias_por_tipo_prefill = {}
    personas_prefill = []
    if row_edit:
        form_data = {
            "expediente": row_edit.expediente or "",
            "caratula": row_edit.caratula or "",
            "fecha_notificacion": row_edit.fecha_notificacion.isoformat() if row_edit.fecha_notificacion else "",
            "telefono_contacto": row_edit.telefono_contacto or "",
            "seps_ingreso": row_edit.seps_ingreso or "",
            "seps_salida": row_edit.seps_salida or "",
            "motivo_indeterminada_id": row_edit.motivo_indeterminada_id or "",
            "estado_expediente_id": row_edit.estado_expediente_id or "",
        }
        def _split_names(v):
            return [x.strip() for x in _clean(v).split("·") if _clean(x)]
        jn = set(_split_names(row_edit.juzgado))
        tn = set(_split_names(row_edit.tipo_medida))
        fn = set(_split_names(row_edit.fiscalia))
        selected_juzgado_ids = [j.id for j in juzgados if _clean(j.nombre) in jn]
        selected_tipo_medida_ids = [t.id for t in tipos_medida if _clean(t.nombre) in tn]
        selected_fiscalia_ids = [f.id for f in fiscalias if _clean(f.nombre) in fn]
        for dp, cat in (
            db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
            .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
            .filter(ConsignaDiasPorTipo.consigna_id == row_edit.id)
            .all()
        ):
            dias_por_tipo_prefill[dp.tipo_catalogo_id] = int(dp.dias or 0)
        pers = ConsignaPersona.query.filter_by(consigna_id=row_edit.id).order_by(ConsignaPersona.id.asc()).all()
        doms = ConsignaDomicilio.query.filter_by(consigna_id=row_edit.id).order_by(ConsignaDomicilio.id.asc()).all()
        dom_by_tipo = {}
        for d in doms:
            dom_by_tipo.setdefault(_clean(d.tipo).lower(), []).append(d)
        for p in pers:
            pt = _clean(p.tipo).lower()
            cand = (dom_by_tipo.get(pt) or dom_by_tipo.get("victima") or [])
            dsel = cand[0] if cand else None
            personas_prefill.append(
                {
                    "nombre": p.nombre or "",
                    "dni": p.dni or "",
                    "tipo": "denunciado" if pt == "denunciado" else "victima",
                    "notificar": p.notificar or ("si" if pt == "denunciado" else "no"),
                    "domicilio": dsel.direccion if dsel else "",
                    "latlng": f"{dsel.latitud}, {dsel.longitud}" if dsel and dsel.latitud is not None and dsel.longitud is not None else "",
                    "barrio_id": "",
                }
            )
    return render_template(
        "oficios_judiciales/manual_form.html",
        juzgados=juzgados,
        tipos_medida=tipos_medida,
        fiscalias=fiscalias,
        barrios=barrios,
        motivos_indeterminada=motivos_indeterminada,
        tipos_consigna_catalogo=tipos_consigna_catalogo,
        edit_id=(row_edit.id if row_edit else ""),
        form_data=form_data,
        selected_juzgado_ids=selected_juzgado_ids,
        selected_tipo_medida_ids=selected_tipo_medida_ids,
        selected_fiscalia_ids=selected_fiscalia_ids,
        dias_por_tipo_prefill=dias_por_tipo_prefill,
        personas_prefill=personas_prefill,
        estados_expediente=estados_expediente,
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
        elif action == "add_motivo_indeterminada":
            nombre = _clean(request.form.get("nombre"))
            if nombre and not CatalogoMotivoIndeterminada.query.filter_by(nombre=nombre).first():
                db.session.add(CatalogoMotivoIndeterminada(nombre=nombre, activo=True))
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
        elif action == "edit_motivo_indeterminada":
            rid = _to_int_or_none(request.form.get("item_id"))
            nombre = _clean(request.form.get("nombre"))
            row = CatalogoMotivoIndeterminada.query.get(rid) if rid else None
            if row and nombre:
                dup = CatalogoMotivoIndeterminada.query.filter(
                    CatalogoMotivoIndeterminada.id != row.id,
                    func.lower(CatalogoMotivoIndeterminada.nombre) == nombre.lower(),
                ).first()
                if dup:
                    flash("Ya existe ese motivo de indeterminada.", "warning")
                else:
                    row.nombre = nombre
                    db.session.commit()
        elif action == "delete_motivo_indeterminada":
            rid = _to_int_or_none(request.form.get("item_id"))
            row = CatalogoMotivoIndeterminada.query.get(rid) if rid else None
            if row:
                db.session.delete(row)
                db.session.commit()
        elif action == "add_estado_expediente":
            nombre = _clean(request.form.get("nombre"))
            bloq = request.form.get("bloquea_cumplimiento") == "1"
            if nombre and not CatalogoEstadoExpediente.query.filter(func.lower(CatalogoEstadoExpediente.nombre) == nombre.lower()).first():
                db.session.add(CatalogoEstadoExpediente(nombre=nombre, bloquea_cumplimiento=bloq, activo=True))
                db.session.commit()
        elif action == "edit_estado_expediente":
            rid = _to_int_or_none(request.form.get("item_id"))
            nombre = _clean(request.form.get("nombre"))
            bloq = request.form.get("bloquea_cumplimiento") == "1"
            row = CatalogoEstadoExpediente.query.get(rid) if rid else None
            if row and nombre:
                dup = CatalogoEstadoExpediente.query.filter(
                    CatalogoEstadoExpediente.id != row.id, func.lower(CatalogoEstadoExpediente.nombre) == nombre.lower()
                ).first()
                if dup:
                    flash("Ya existe ese estado de expediente.", "warning")
                else:
                    row.nombre = nombre
                    row.bloquea_cumplimiento = bloq
                    db.session.commit()
        elif action == "delete_estado_expediente":
            rid = _to_int_or_none(request.form.get("item_id"))
            row = CatalogoEstadoExpediente.query.get(rid) if rid else None
            if row:
                ConsignaJudicial.query.filter_by(estado_expediente_id=row.id).update(
                    {ConsignaJudicial.estado_expediente_id: None}, synchronize_session=False
                )
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
    motivos_indeterminada = CatalogoMotivoIndeterminada.query.order_by(CatalogoMotivoIndeterminada.nombre.asc()).all()
    estados_expediente = CatalogoEstadoExpediente.query.order_by(CatalogoEstadoExpediente.nombre.asc()).all()
    barrios = CatalogoBarrio.query.order_by(CatalogoBarrio.nombre.asc()).all()
    return render_template(
        "oficios_judiciales/catalogos.html",
        juzgados=juzgados,
        tipos_medida=tipos_medida,
        tipos_consigna=tipos_consigna,
        fiscalias=fiscalias,
        motivos_indeterminada=motivos_indeterminada,
        estados_expediente=estados_expediente,
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
    row = (
        _q_base()
        .options(joinedload(ConsignaJudicial.estado_expediente), joinedload(ConsignaJudicial.motivo_indeterminada))
        .filter(ConsignaJudicial.id == consigna_id)
        .first_or_404()
    )
    venc = _vencimiento_info(row)
    dias_por_tipo_detalle = (
        db.session.query(ConsignaDiasPorTipo, CatalogoTipoConsigna)
        .join(CatalogoTipoConsigna, ConsignaDiasPorTipo.tipo_catalogo_id == CatalogoTipoConsigna.id)
        .filter(ConsignaDiasPorTipo.consigna_id == consigna_id)
        .all()
    )
    dias_por_tipo_detalle.sort(key=lambda p: _orden_cronologia_tipo_consigna(p[1]))
    cronologia_plazos = _cronologia_plazos_dias(row, dias_por_tipo_detalle)
    rango_por_tipo = {}
    for t in cronologia_plazos:
        if t.get("modo") == "tramo":
            rango_por_tipo[_clean(t.get("nombre"))] = {
                "desde": t.get("desde"),
                "hasta": t.get("hasta"),
            }
    today = datetime.utcnow().date()
    total = int(row.cantidad_dias or 0)
    if row.fecha_notificacion and total > 0:
        trans = max(0, (today - row.fecha_notificacion).days)
        if trans > total:
            trans = total
    else:
        trans = 0
    progreso_detalle = {"transcurridos": trans, "total": total}

    estado_operativo = _manual_estado_operativo(row, cat_row=row.estado_expediente)

    has_indet = False
    tramos = []
    for dp, cat in dias_por_tipo_detalle:
        n = _ascii_lower_no_accent(cat.nombre)
        if "indeterm" in n:
            has_indet = bool(dp.dias)
            continue
        d = int(dp.dias or 0)
        if d > 0:
            tramos.append((cat.nombre, d, n))
    etapa_actual = {"slug": "indeterminada", "nombre": "Indeterminada", "icono": "bi-infinity", "pos": 0, "total": 0, "cumplidas": []}
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
        cumplidas = []
        acc2 = 0
        for t in tramos:
            acc2 += t[1]
            if trans >= acc2:
                cumplidas.append(t[0])
        n = chosen[2]
        if "fija" in n:
            etapa_actual = {"slug": "fija", "nombre": "Fija", "icono": "bi-anchor-fill", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
        elif "ambulator" in n:
            etapa_actual = {"slug": "ambulatoria", "nombre": "Ambulatoria", "icono": "bi-car-front-fill", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
        elif "personal" in n:
            etapa_actual = {"slug": "personalizada", "nombre": "Personalizada", "icono": "bi-person-circle", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
        else:
            etapa_actual = {"slug": _slug_tipo_consigna_desde_nombre(chosen[0]), "nombre": chosen[0], "icono": "bi-dot", "pos": chosen_idx + 1, "total": len(tramos), "cumplidas": cumplidas}
    elif has_indet:
        etapa_actual = {"slug": "indeterminada", "nombre": "Indeterminada", "icono": "bi-infinity", "pos": 0, "total": 0, "cumplidas": []}
    if estado_operativo == "finalizada" and tramos:
        etapa_actual["cumplidas"] = [t[0] for t in tramos]

    personas = row.personas.order_by(ConsignaPersona.id.asc()).all()
    domicilios = row.domicilios.order_by(ConsignaDomicilio.id.asc()).all()
    doms_by_tipo = {}
    for d in domicilios:
        key = _clean(d.tipo).lower()
        doms_by_tipo.setdefault(key, []).append(d)
    used_dom_ids = set()
    persona_domicilio = []
    for p in personas:
        pt = _clean(p.tipo).lower()
        cand = doms_by_tipo.get(pt, []) or doms_by_tipo.get("victima", [])
        chosen = None
        for d in cand:
            if d.id not in used_dom_ids:
                chosen = d
                break
        if not chosen:
            for d in domicilios:
                if d.id not in used_dom_ids:
                    chosen = d
                    break
        if chosen:
            used_dom_ids.add(chosen.id)
        persona_domicilio.append({"persona": p, "domicilio": chosen})
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
        estado_expediente_nombre=(row.estado_expediente.nombre if row.estado_expediente else ""),
        venc=venc,
        dias_por_tipo_detalle=dias_por_tipo_detalle,
        cronologia_plazos=cronologia_plazos,
        rango_por_tipo=rango_por_tipo,
        volver_url=volver_url,
        etapa_actual=etapa_actual,
        progreso_detalle=progreso_detalle,
        estado_operativo=estado_operativo,
        persona_domicilio=persona_domicilio,
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


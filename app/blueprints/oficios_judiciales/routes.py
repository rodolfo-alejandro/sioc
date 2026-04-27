from __future__ import annotations

import io
import json
import re
from datetime import datetime

import pandas as pd
from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, inspect, or_

from app.blueprints.oficios_judiciales import bp
from app.extensions import db
from app.models.oficios_judiciales import (
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
    from PIL import Image
except Exception:
    pytesseract = None
    Image = None

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
_MIN_PDF_TEXT_LEN = 120


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
    for model in (ConsignaJudicial, ConsignaPersona, ConsignaDomicilio, ConsignaMedidaDetalle):
        if model.__tablename__ not in existing:
            model.__table__.create(bind=db.engine)
    _schema_checked = True


def _clean(v):
    if v is None:
        return ""
    return str(v).strip()


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
    if not pytesseract or not Image:
        return ""
    try:
        img = Image.open(io.BytesIO(raw))
        txt = pytesseract.image_to_string(img, lang="spa")
        return _normalize_spaces(txt)
    except Exception:
        return ""


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
    if not pytesseract:
        return ""
    try:
        txt = pytesseract.image_to_string(img, lang="spa")
        return _normalize_spaces(txt)
    except Exception:
        return ""


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
    for img in pages:
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

    return _normalize_spaces("\n\n".join(qr_parts)), _normalize_spaces("\n\n".join(ocr_parts)), qr_url, warnings


def _resolve_qr_payload(qr_payload: str) -> tuple[str, str]:
    payload = _clean(qr_payload)
    if not payload:
        return "", ""
    if payload.lower().startswith("http://") or payload.lower().startswith("https://"):
        if requests is None:
            return "", payload
        try:
            resp = requests.get(payload, timeout=12)
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
        ("exclusión del hogar", "exclusión del hogar"),
        ("exclusion del hogar", "exclusión del hogar"),
        ("rondas periódicas", "rondas periódicas"),
        ("rondas periodicas", "rondas periódicas"),
    ]
    for k, v in checks:
        if k in t:
            return v
    return ""


def _first_group(pattern: str, text: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    return _clean(m.group(1))


def _parse_fields(text: str) -> dict:
    full = text or ""
    expediente = _first_group(r"(EXP[-.\s]*\d+[\/\d\-]*)", full)
    juzgado = _first_group(r"(JUZGADO[^\n]+)", full)
    caratula = _first_group(r"Ref\.?:\s*(.+)", full)
    denunciado = _first_group(r"Señor/?a?:\s*([^\n]+)", full)
    victima = _first_group(r"victima\s*[:\-]?\s*([^\n]+)", full)
    dom_den = _first_group(r"Domicilio\s*[:\-]?\s*([^\n]+)", full)
    dom_vic = _first_group(r"domicilio de la victima\s*[:\-]?\s*([^\n]+)", full)
    dist = _first_group(r"(\d{2,4}\s*metros?)", full)
    dias = _first_group(r"(\d{1,3})\s*d[ií]as", full)
    turnos = _first_group(r"(\d+\s*turnos?[^\n,.]*)", full)
    fecha_oficio = _first_group(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}).{0,30}JUEZ|JUEZA|Secretar", full)
    fecha_notif = _first_group(r"notificad[oa].{0,40}?(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)
    if not fecha_notif:
        fecha_notif = _first_group(r"Constancia de notificación.*?(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", full)

    medidas = []
    for pat in [
        r"PROHIBICI[ÓO]N DE ACERCAMIENTO[^.]*\.",
        r"ORDENAR RONDAS[^.]*\.",
        r"EXCLUSI[ÓO]N DEL HOGAR[^.]*\.",
        r"consigna[^.]*\.",
    ]:
        for m in re.findall(pat, full, flags=re.IGNORECASE):
            txt = _clean(m)
            if txt and txt not in medidas:
                medidas.append(txt)

    return {
        "juzgado": juzgado,
        "expediente": expediente,
        "caratula": caratula,
        "persona_denunciada": denunciado,
        "victima": victima,
        "domicilio_denunciado": dom_den,
        "domicilio_victima": dom_vic,
        "tipo_medida": _pick_tipo_medida(full),
        "distancia_restriccion": dist,
        "cantidad_dias": dias,
        "turnos": turnos,
        "fecha_oficio": fecha_oficio,
        "fecha_notificacion": fecha_notif,
        "observaciones": "",
        "medidas_detalle": medidas,
    }


def _merge_parsed(a: dict, b: dict) -> dict:
    out = dict(a or {})
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
        if not _clean(out.get(k)) and _clean(v):
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

            row = ConsignaJudicial(
                unidad_id=current_user.unidad_id,
                creado_por=current_user.id,
                expediente=_clean(payload.get("expediente")),
                juzgado=_clean(payload.get("juzgado")),
                caratula=_clean(payload.get("caratula")),
                tipo_medida=_clean(payload.get("tipo_medida")),
                fecha_oficio=_parse_date(_clean(payload.get("fecha_oficio"))),
                fecha_notificacion=_parse_date(_clean(payload.get("fecha_notificacion"))),
                cantidad_dias=int(payload.get("cantidad_dias") or 0) if str(payload.get("cantidad_dias") or "").isdigit() else None,
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

            if _clean(payload.get("persona_denunciada")):
                db.session.add(
                    ConsignaPersona(
                        consigna_id=row.id,
                        nombre=_clean(payload.get("persona_denunciada")),
                        dni=_clean(payload.get("dni_denunciado")),
                        tipo="denunciado",
                    )
                )
            if _clean(payload.get("victima")):
                db.session.add(
                    ConsignaPersona(
                        consigna_id=row.id,
                        nombre=_clean(payload.get("victima")),
                        dni=_clean(payload.get("dni_victima")),
                        tipo="victima",
                    )
                )
            if _clean(payload.get("domicilio_denunciado")):
                db.session.add(
                    ConsignaDomicilio(consigna_id=row.id, direccion=_clean(payload.get("domicilio_denunciado")), tipo="denunciado")
                )
            if _clean(payload.get("domicilio_victima")):
                db.session.add(
                    ConsignaDomicilio(consigna_id=row.id, direccion=_clean(payload.get("domicilio_victima")), tipo="victima")
                )
            for m in (payload.get("medidas_detalle") or []):
                if _clean(m):
                    db.session.add(ConsignaMedidaDetalle(consigna_id=row.id, descripcion=_clean(m)))

            db.session.commit()
            flash("Consigna judicial guardada correctamente.", "success")
            return redirect(url_for("oficios_judiciales.detalle", consigna_id=row.id))

        files = request.files.getlist("archivos")
        if not files:
            flash("Debe seleccionar al menos un archivo.", "warning")
            return redirect(url_for("oficios_judiciales.cargar"))

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
                txt_ocr = _extract_ocr_text_from_image(raw)
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

            # Siempre consolidar ambas fuentes cuando existan para no perder datos.
            if _clean(txt_qr):
                full_text_parts.append(txt_qr)
                merged = _merge_parsed(merged, parsed_qr)
            if _clean(txt_ocr):
                full_text_parts.append(txt_ocr)
                merged = _merge_parsed(merged, parsed_ocr)

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

    return render_template("oficios_judiciales/cargar.html")


@bp.route("/listado")
def listado():
    if not _can_view():
        abort(403)
    q = _q_base()

    tipo = _clean(request.args.get("tipo"))
    juzgado = _clean(request.args.get("juzgado"))
    persona = _clean(request.args.get("persona"))
    qtxt = _clean(request.args.get("q"))
    fdesde = _parse_date(_clean(request.args.get("fecha_desde")))
    fhasta = _parse_date(_clean(request.args.get("fecha_hasta")))

    if tipo:
        q = q.filter(ConsignaJudicial.tipo_medida == tipo)
    if juzgado:
        q = q.filter(ConsignaJudicial.juzgado.ilike(f"%{juzgado}%"))
    if qtxt:
        pat = f"%{qtxt}%"
        q = q.filter(
            or_(
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
        q = q.join(ConsignaPersona, ConsignaPersona.consigna_id == ConsignaJudicial.id).filter(
            or_(
                ConsignaPersona.nombre.ilike(f"%{persona}%"),
                ConsignaPersona.dni.ilike(f"%{persona}%"),
            )
        )

    rows = q.order_by(ConsignaJudicial.created_at.desc()).limit(300).all()
    tipos = [r[0] for r in _q_base().with_entities(ConsignaJudicial.tipo_medida).distinct().all() if r[0]]
    return render_template("oficios_judiciales/listado.html", rows=rows, tipos=tipos, selected=request.args)


@bp.route("/detalle/<int:consigna_id>")
def detalle(consigna_id: int):
    if not _can_view():
        abort(403)
    row = _q_base().filter(ConsignaJudicial.id == consigna_id).first_or_404()
    return render_template("oficios_judiciales/detalle.html", row=row)


@bp.route("/export.csv")
def export_csv():
    if not _can_export():
        abort(403)
    q = _q_base().order_by(ConsignaJudicial.created_at.desc())
    out = io.StringIO()
    import csv
    w = csv.writer(out)
    w.writerow(["id", "expediente", "juzgado", "tipo_medida", "fecha_notificacion", "estado", "caratula"])
    for r in q.yield_per(300):
        w.writerow(
            [
                r.id,
                r.expediente or "",
                r.juzgado or "",
                r.tipo_medida or "",
                r.fecha_notificacion.isoformat() if r.fecha_notificacion else "",
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
                "fecha_notificacion": r.fecha_notificacion,
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


"""
Almacenamiento de archivos (PDF/imagen) adjuntos a consignas judiciales.
"""
from __future__ import annotations

import mimetypes
import os
import shutil
import uuid
from datetime import datetime

from flask import current_app
from werkzeug.utils import secure_filename

from app.models.oficios_judiciales import ConsignaArchivo, ConsignaJudicial

ARCHIVO_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png", "webp"})


def upload_root() -> str:
    base = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
    if not os.path.isabs(base):
        base = os.path.join(current_app.root_path, base)
    return base


def consigna_dir(unidad_id: int, consigna_id: int) -> str:
    return os.path.join(upload_root(), "oficios_consignas", str(unidad_id), str(consigna_id))


def staging_dir(staging_id: str) -> str:
    return os.path.join(upload_root(), "oficios_consignas", "_staging", staging_id)


def allowed_archivo(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ARCHIVO_EXTENSIONS


def _safe_stored_name(original: str) -> str:
    clean = secure_filename(original) or "archivo"
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:8]
    if "." in clean:
        base, ext = clean.rsplit(".", 1)
        return f"{ts}_{short}_{base}.{ext.lower()}"
    return f"{ts}_{short}_{clean}"


def _max_bytes() -> int:
    return int(current_app.config.get("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))


def _validate_raw(raw: bytes, original_filename: str) -> None:
    if not raw:
        raise ValueError("El archivo está vacío.")
    if len(raw) > _max_bytes():
        raise ValueError("Archivo demasiado grande.")
    if not allowed_archivo(original_filename):
        raise ValueError("Formato no permitido. Use PDF, JPG, PNG o WEBP.")


def abs_path(ruta_relativa: str) -> str:
    return os.path.join(upload_root(), ruta_relativa.replace("/", os.sep))


def save_staging_file(raw: bytes, original_filename: str, staging_id: str) -> dict:
    _validate_raw(raw, original_filename)
    d = staging_dir(staging_id)
    os.makedirs(d, exist_ok=True)
    stored = _safe_stored_name(original_filename)
    with open(os.path.join(d, stored), "wb") as fh:
        fh.write(raw)
    rel = f"oficios_consignas/_staging/{staging_id}/{stored}"
    mime = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
    return {
        "stored_name": stored,
        "nombre_original": original_filename,
        "ruta_relativa": rel,
        "mime_type": mime,
        "size_bytes": len(raw),
    }


def persist_staged_archivos(
    staging_id: str,
    staging_entries: list[dict],
    consigna: ConsignaJudicial,
    user_id: int | None,
    origen: str = "ocr",
) -> list[ConsignaArchivo]:
    if not staging_id or not staging_entries:
        return []
    dest = consigna_dir(consigna.unidad_id, consigna.id)
    os.makedirs(dest, exist_ok=True)
    src_root = staging_dir(staging_id)
    out: list[ConsignaArchivo] = []
    for entry in staging_entries:
        stored = entry.get("stored_name")
        if not stored:
            continue
        src = os.path.join(src_root, stored)
        if not os.path.isfile(src):
            continue
        dest_name = stored
        dest_path = os.path.join(dest, dest_name)
        if os.path.exists(dest_path):
            dest_name = _safe_stored_name(entry.get("nombre_original") or stored)
            dest_path = os.path.join(dest, dest_name)
        shutil.move(src, dest_path)
        rel = f"oficios_consignas/{consigna.unidad_id}/{consigna.id}/{dest_name}"
        out.append(
            ConsignaArchivo(
                consigna_id=consigna.id,
                unidad_id=consigna.unidad_id,
                subido_por=user_id,
                nombre_original=entry.get("nombre_original") or stored,
                nombre_almacenado=dest_name,
                ruta_relativa=rel,
                mime_type=entry.get("mime_type") or mimetypes.guess_type(dest_name)[0],
                size_bytes=entry.get("size_bytes") or os.path.getsize(dest_path),
                origen=origen,
            )
        )
    if os.path.isdir(src_root):
        shutil.rmtree(src_root, ignore_errors=True)
    return out


def save_consigna_archivo(
    raw: bytes,
    original_filename: str,
    consigna: ConsignaJudicial,
    user_id: int | None,
    origen: str = "detalle",
) -> ConsignaArchivo:
    _validate_raw(raw, original_filename)
    dest = consigna_dir(consigna.unidad_id, consigna.id)
    os.makedirs(dest, exist_ok=True)
    stored = _safe_stored_name(original_filename)
    dest_path = os.path.join(dest, stored)
    with open(dest_path, "wb") as fh:
        fh.write(raw)
    rel = f"oficios_consignas/{consigna.unidad_id}/{consigna.id}/{stored}"
    return ConsignaArchivo(
        consigna_id=consigna.id,
        unidad_id=consigna.unidad_id,
        subido_por=user_id,
        nombre_original=original_filename,
        nombre_almacenado=stored,
        ruta_relativa=rel,
        mime_type=mimetypes.guess_type(original_filename)[0] or "application/octet-stream",
        size_bytes=len(raw),
        origen=origen,
    )


def delete_archivo_record(archivo: ConsignaArchivo) -> None:
    path = abs_path(archivo.ruta_relativa)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass

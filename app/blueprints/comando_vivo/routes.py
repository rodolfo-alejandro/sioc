"""
Rutas Centro de Comando / Operativos en vivo (piloto GPS + audio).
"""
from __future__ import annotations

import os
import secrets
import string
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, text

from app.blueprints.comando_vivo import bp
from app.extensions import csrf, db
from app.models.comando_vivo import (
    ComandoAudioClip,
    ComandoGpsPing,
    ComandoOperativo,
    ComandoParticipante,
    ComandoVideoClip,
)
from app.services.rbac import require_permission

# Sin señal si no hay ping en este intervalo
OFFLINE_SECONDS = 90
# Media reciente = "transmitiendo"
AUDIO_LIVE_SECONDS = 12
VIDEO_LIVE_SECONDS = 15
# Retener pings recientes para traza corta en mapa
TRACE_LIMIT = 80
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 2 MB por clip
MAX_VIDEO_BYTES = 6 * 1024 * 1024  # 6 MB por clip
# Clips no retenidos se borran tras este tiempo (solo en vivo)
EPHEMERAL_KEEP_SECONDS = 180


def _clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _ensure_column(table: str, column: str, ddl: str) -> None:
    from sqlalchemy import inspect

    insp = inspect(db.engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column not in cols:
        db.session.execute(text(f"ALTER TABLE {table} {ddl}"))
        db.session.commit()


def _ensure_tables():
    from sqlalchemy import inspect

    insp = inspect(db.engine)
    needed = {
        "comando_operativos",
        "comando_participantes",
        "comando_gps_pings",
        "comando_audio_clips",
        "comando_video_clips",
    }
    existing = set(insp.get_table_names())
    if not needed.issubset(existing):
        db.create_all()

    _ensure_column("comando_participantes", "last_audio_at", "ADD COLUMN last_audio_at DATETIME NULL")
    _ensure_column("comando_participantes", "last_video_at", "ADD COLUMN last_video_at DATETIME NULL")
    _ensure_column("comando_operativos", "grabar_gps", "ADD COLUMN grabar_gps TINYINT(1) NOT NULL DEFAULT 1")
    _ensure_column("comando_operativos", "grabar_audio", "ADD COLUMN grabar_audio TINYINT(1) NOT NULL DEFAULT 1")
    _ensure_column("comando_operativos", "grabar_video", "ADD COLUMN grabar_video TINYINT(1) NOT NULL DEFAULT 1")
    _ensure_column("comando_operativos", "audio_clip_sec", "ADD COLUMN audio_clip_sec INT NOT NULL DEFAULT 4")
    _ensure_column("comando_operativos", "video_clip_sec", "ADD COLUMN video_clip_sec INT NOT NULL DEFAULT 3")
    _ensure_column("comando_operativos", "gps_interval_sec", "ADD COLUMN gps_interval_sec INT NOT NULL DEFAULT 5")
    _ensure_column("comando_gps_pings", "retenido", "ADD COLUMN retenido TINYINT(1) NOT NULL DEFAULT 1")
    _ensure_column("comando_audio_clips", "retenido", "ADD COLUMN retenido TINYINT(1) NOT NULL DEFAULT 1")
    _ensure_column("comando_video_clips", "retenido", "ADD COLUMN retenido TINYINT(1) NOT NULL DEFAULT 1")


def _op_config(op: ComandoOperativo) -> dict:
    return {
        "grabar_gps": bool(getattr(op, "grabar_gps", True)),
        "grabar_audio": bool(getattr(op, "grabar_audio", True)),
        "grabar_video": bool(getattr(op, "grabar_video", True)),
        "audio_clip_sec": int(getattr(op, "audio_clip_sec", None) or 4),
        "video_clip_sec": int(getattr(op, "video_clip_sec", None) or 3),
        "gps_interval_sec": int(getattr(op, "gps_interval_sec", None) or 5),
    }


def _delete_clip_file(rel_path: str) -> None:
    try:
        upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "instance/uploads")).resolve()
        path = (upload_root / rel_path).resolve()
        if str(path).startswith(str(upload_root)) and path.is_file():
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _purge_ephemeral(op_id: int) -> None:
    """Borra GPS/audio/video no retenidos más viejos que EPHEMERAL_KEEP_SECONDS."""
    cutoff = datetime.utcnow() - timedelta(seconds=EPHEMERAL_KEEP_SECONDS)
    for clip in ComandoAudioClip.query.filter(
        ComandoAudioClip.operativo_id == op_id,
        ComandoAudioClip.retenido.is_(False),
        ComandoAudioClip.created_at < cutoff,
    ).limit(200).all():
        _delete_clip_file(clip.rel_path)
        db.session.delete(clip)
    for clip in ComandoVideoClip.query.filter(
        ComandoVideoClip.operativo_id == op_id,
        ComandoVideoClip.retenido.is_(False),
        ComandoVideoClip.created_at < cutoff,
    ).limit(200).all():
        _delete_clip_file(clip.rel_path)
        db.session.delete(clip)
    ComandoGpsPing.query.filter(
        ComandoGpsPing.operativo_id == op_id,
        ComandoGpsPing.retenido.is_(False),
        ComandoGpsPing.created_at < cutoff,
    ).delete(synchronize_session=False)
    db.session.commit()


def _storage_stats(op_id: int) -> dict:
    return {
        "gps_retenidos": ComandoGpsPing.query.filter_by(operativo_id=op_id, retenido=True).count(),
        "audio_retenidos": ComandoAudioClip.query.filter_by(operativo_id=op_id, retenido=True).count(),
        "video_retenidos": ComandoVideoClip.query.filter_by(operativo_id=op_id, retenido=True).count(),
        "audio_efimeros": ComandoAudioClip.query.filter_by(operativo_id=op_id, retenido=False).count(),
        "video_efimeros": ComandoVideoClip.query.filter_by(operativo_id=op_id, retenido=False).count(),
    }


def _media_dir(op_id: int, part_id: int, kind: str = "media") -> Path:
    base = Path(current_app.config.get("UPLOAD_FOLDER", "instance/uploads"))
    d = base / "comando_vivo" / str(op_id) / str(part_id) / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audio_dir(op_id: int, part_id: int) -> Path:
    return _media_dir(op_id, part_id, "audio")


def _video_dir(op_id: int, part_id: int) -> Path:
    return _media_dir(op_id, part_id, "video")


def _gen_codigo(n: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    # Evitar confusiones 0/O I/1
    alphabet = alphabet.replace("0", "").replace("O", "").replace("1", "").replace("I", "")
    for _ in range(30):
        code = "".join(secrets.choice(alphabet) for _ in range(n))
        if not ComandoOperativo.query.filter_by(codigo=code).first():
            return code
    return secrets.token_hex(4).upper()[:n]


def _can_view_op(op: ComandoOperativo) -> bool:
    if not current_user.is_authenticated:
        return False
    if op.unidad_id != current_user.unidad_id:
        return False
    return current_user.has_permission("COMANDO_VIVO_VIEW") or current_user.has_permission(
        "COMANDO_VIVO_MANAGE"
    )


def _participante_from_token(token: str) -> ComandoParticipante | None:
    if not token:
        return None
    return ComandoParticipante.query.filter_by(token=token).first()


def _mark_offline(participantes: list[ComandoParticipante]) -> None:
    cutoff = datetime.utcnow() - timedelta(seconds=OFFLINE_SECONDS)
    for p in participantes:
        if p.estado == "panico":
            continue
        if not p.last_seen_at or p.last_seen_at < cutoff:
            if p.estado != "offline":
                p.estado = "offline"


def _serialize_participante(p: ComandoParticipante) -> dict:
    audio_vivo = False
    video_vivo = False
    if p.last_audio_at:
        audio_vivo = (datetime.utcnow() - p.last_audio_at).total_seconds() <= AUDIO_LIVE_SECONDS
    if p.last_video_at:
        video_vivo = (datetime.utcnow() - p.last_video_at).total_seconds() <= VIDEO_LIVE_SECONDS
    return {
        "id": p.id,
        "alias": p.alias,
        "estado": p.estado,
        "lat": p.last_lat,
        "lon": p.last_lon,
        "accuracy": p.last_accuracy,
        "battery": p.last_battery,
        "last_seen_at": p.last_seen_at.isoformat() + "Z" if p.last_seen_at else None,
        "last_audio_at": p.last_audio_at.isoformat() + "Z" if p.last_audio_at else None,
        "last_video_at": p.last_video_at.isoformat() + "Z" if p.last_video_at else None,
        "audio_vivo": audio_vivo,
        "video_vivo": video_vivo,
    }


# ─── Web centro de comando ───────────────────────────────────────────────────


@bp.route("/")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def listado():
    _ensure_tables()
    activos = (
        ComandoOperativo.query.filter_by(unidad_id=current_user.unidad_id, estado="activo")
        .order_by(ComandoOperativo.created_at.desc())
        .all()
    )
    cerrados = (
        ComandoOperativo.query.filter_by(unidad_id=current_user.unidad_id, estado="cerrado")
        .order_by(ComandoOperativo.closed_at.desc())
        .limit(30)
        .all()
    )
    counts = {}
    if activos:
        ids = [o.id for o in activos]
        rows = (
            db.session.query(ComandoParticipante.operativo_id, func.count(ComandoParticipante.id))
            .filter(ComandoParticipante.operativo_id.in_(ids))
            .group_by(ComandoParticipante.operativo_id)
            .all()
        )
        counts = {r[0]: r[1] for r in rows}
    return render_template(
        "comando_vivo/listado.html",
        activos=activos,
        cerrados=cerrados,
        counts=counts,
        can_manage=current_user.has_permission("COMANDO_VIVO_MANAGE"),
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
@require_permission("COMANDO_VIVO_MANAGE")
def nuevo():
    _ensure_tables()
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        tipo = (request.form.get("tipo") or "").strip() or None
        notas = (request.form.get("notas") or "").strip() or None
        if not nombre:
            flash("Indicá un nombre para el operativo.", "warning")
            return render_template("comando_vivo/nuevo.html")
        op = ComandoOperativo(
            unidad_id=current_user.unidad_id,
            creado_por=current_user.id,
            nombre=nombre,
            tipo=tipo,
            notas=notas,
            codigo=_gen_codigo(),
            estado="activo",
        )
        db.session.add(op)
        db.session.commit()
        flash(f"Operativo creado. Código para el personal: {op.codigo}", "success")
        return redirect(url_for("comando_vivo.mapa", op_id=op.id))
    return render_template("comando_vivo/nuevo.html")


@bp.route("/<int:op_id>/mapa")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def mapa(op_id: int):
    _ensure_tables()
    op = ComandoOperativo.query.get_or_404(op_id)
    if not _can_view_op(op):
        flash("No tenés acceso a este operativo.", "warning")
        return redirect(url_for("comando_vivo.listado"))
    cfg = _op_config(op)
    return render_template(
        "comando_vivo/mapa.html",
        op=op,
        cfg=cfg,
        stats=_storage_stats(op.id),
        can_manage=current_user.has_permission("COMANDO_VIVO_MANAGE"),
        positions_url=url_for("comando_vivo.api_posiciones", op_id=op.id),
        audio_lista_url=url_for("comando_vivo.api_audio_lista", op_id=op.id),
        video_lista_url=url_for("comando_vivo.api_video_lista", op_id=op.id),
        config_url=url_for("comando_vivo.api_config", op_id=op.id),
        offline_seconds=OFFLINE_SECONDS,
    )


@bp.route("/<int:op_id>/cerrar", methods=["POST"])
@login_required
@require_permission("COMANDO_VIVO_MANAGE")
def cerrar(op_id: int):
    _ensure_tables()
    op = ComandoOperativo.query.get_or_404(op_id)
    if not _can_view_op(op):
        flash("Sin acceso.", "warning")
        return redirect(url_for("comando_vivo.listado"))
    op.estado = "cerrado"
    op.closed_at = datetime.utcnow()
    db.session.commit()
    flash("Operativo cerrado.", "info")
    return redirect(url_for("comando_vivo.listado"))


@bp.route("/api/config/<int:op_id>", methods=["GET", "POST"])
@login_required
def api_config(op_id: int):
    """Ver / actualizar grabación y lapsos del operativo."""
    _ensure_tables()
    op = ComandoOperativo.query.get_or_404(op_id)
    if not _can_view_op(op):
        return jsonify({"error": "forbidden"}), 403

    if request.method == "GET":
        return jsonify({"ok": True, "config": _op_config(op), "stats": _storage_stats(op.id)})

    if not current_user.has_permission("COMANDO_VIVO_MANAGE"):
        return jsonify({"error": "forbidden"}), 403
    if op.estado != "activo":
        return jsonify({"ok": False, "error": "operativo_cerrado"}), 409

    data = request.get_json(silent=True) or {}

    def _bool(key, current):
        if key not in data:
            return current
        v = data.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        return str(v).strip().lower() in ("1", "true", "si", "yes", "on")

    op.grabar_gps = _bool("grabar_gps", op.grabar_gps)
    op.grabar_audio = _bool("grabar_audio", op.grabar_audio)
    op.grabar_video = _bool("grabar_video", op.grabar_video)
    op.audio_clip_sec = _clamp_int(data.get("audio_clip_sec", op.audio_clip_sec), 3, 20, 4)
    op.video_clip_sec = _clamp_int(data.get("video_clip_sec", op.video_clip_sec), 2, 15, 3)
    op.gps_interval_sec = _clamp_int(data.get("gps_interval_sec", op.gps_interval_sec), 3, 30, 5)
    db.session.commit()
    return jsonify({"ok": True, "config": _op_config(op), "stats": _storage_stats(op.id)})


# ─── App de campo (PWA) ──────────────────────────────────────────────────────


@bp.route("/app")
def app_campo():
    """Página móvil: unirse con código + enviar GPS. No requiere login SIOC."""
    _ensure_tables()
    return render_template("comando_vivo/app.html")


# ─── API JSON ────────────────────────────────────────────────────────────────


@bp.route("/api/posiciones/<int:op_id>")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def api_posiciones(op_id: int):
    _ensure_tables()
    op = ComandoOperativo.query.get_or_404(op_id)
    if not _can_view_op(op):
        return jsonify({"error": "forbidden"}), 403

    _purge_ephemeral(op.id)
    participantes = ComandoParticipante.query.filter_by(operativo_id=op.id).all()
    _mark_offline(participantes)
    db.session.commit()

    panicos = (
        ComandoGpsPing.query.filter_by(operativo_id=op.id, evento="panico")
        .order_by(ComandoGpsPing.created_at.desc())
        .limit(20)
        .all()
    )
    online = sum(1 for p in participantes if p.estado == "online")
    panico_n = sum(1 for p in participantes if p.estado == "panico")

    return jsonify(
        {
            "operativo": {
                "id": op.id,
                "nombre": op.nombre,
                "codigo": op.codigo,
                "estado": op.estado,
            },
            "config": _op_config(op),
            "stats": _storage_stats(op.id),
            "resumen": {
                "total": len(participantes),
                "online": online,
                "panico": panico_n,
                "offline": len(participantes) - online - panico_n,
            },
            "participantes": [_serialize_participante(p) for p in participantes],
            "panicos": [
                {
                    "participante_id": x.participante_id,
                    "lat": x.lat,
                    "lon": x.lon,
                    "created_at": x.created_at.isoformat() + "Z",
                }
                for x in panicos
            ],
            "server_time": datetime.utcnow().isoformat() + "Z",
            "offline_seconds": OFFLINE_SECONDS,
        }
    )


@bp.route("/api/traza/<int:participante_id>")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def api_traza(participante_id: int):
    _ensure_tables()
    p = ComandoParticipante.query.get_or_404(participante_id)
    op = p.operativo
    if not _can_view_op(op):
        return jsonify({"error": "forbidden"}), 403
    rows = (
        ComandoGpsPing.query.filter_by(participante_id=p.id)
        .order_by(ComandoGpsPing.created_at.desc())
        .limit(TRACE_LIMIT)
        .all()
    )
    rows = list(reversed(rows))
    return jsonify(
        {
            "participante_id": p.id,
            "alias": p.alias,
            "puntos": [
                {
                    "lat": r.lat,
                    "lon": r.lon,
                    "evento": r.evento,
                    "created_at": r.created_at.isoformat() + "Z",
                }
                for r in rows
            ],
        }
    )


@bp.route("/api/join", methods=["POST"])
@csrf.exempt
def api_join():
    """Unirse a un operativo activo con código + alias (celular)."""
    _ensure_tables()
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or request.form.get("codigo") or "").strip().upper()
    alias = (data.get("alias") or request.form.get("alias") or "").strip()
    device_id = (data.get("device_id") or request.form.get("device_id") or "").strip() or None

    if not codigo or not alias:
        return jsonify({"ok": False, "error": "codigo_y_alias_requeridos"}), 400

    op = ComandoOperativo.query.filter_by(codigo=codigo, estado="activo").first()
    if not op:
        return jsonify({"ok": False, "error": "codigo_invalido_o_cerrado"}), 404

    # Reusar participante si mismo device_id en este operativo
    part = None
    if device_id:
        part = ComandoParticipante.query.filter_by(
            operativo_id=op.id, device_id=device_id
        ).first()

    if part:
        part.alias = alias[:120]
        part.estado = "online"
        part.last_seen_at = datetime.utcnow()
    else:
        part = ComandoParticipante(
            operativo_id=op.id,
            alias=alias[:120],
            device_id=device_id,
            token=secrets.token_urlsafe(32),
            estado="online",
            last_seen_at=datetime.utcnow(),
        )
        db.session.add(part)

    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "token": part.token,
            "participante_id": part.id,
            "operativo": {
                "id": op.id,
                "nombre": op.nombre,
                "codigo": op.codigo,
            },
            "config": _op_config(op),
        }
    )


def _ingest_ping(evento: str = "ping"):
    _ensure_tables()
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    part = _participante_from_token(token)
    if not part:
        return jsonify({"ok": False, "error": "token_invalido"}), 401

    op = part.operativo
    if op.estado != "activo":
        return jsonify({"ok": False, "error": "operativo_cerrado"}), 409

    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "coords_invalidas"}), 400

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"ok": False, "error": "coords_fuera_rango"}), 400

    def _opt_float(key):
        v = data.get(key)
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    accuracy = _opt_float("accuracy")
    speed = _opt_float("speed")
    heading = _opt_float("heading")
    battery = _opt_float("battery")

    # Posición en vivo siempre; retenido=True guarda historial (pánico siempre retenido)
    retenido = bool(getattr(op, "grabar_gps", True)) or evento == "panico"
    ping = ComandoGpsPing(
        operativo_id=op.id,
        participante_id=part.id,
        lat=lat,
        lon=lon,
        accuracy=accuracy,
        speed=speed,
        heading=heading,
        battery=battery,
        evento=evento,
        retenido=retenido,
    )
    db.session.add(ping)

    part.last_lat = lat
    part.last_lon = lon
    part.last_accuracy = accuracy
    part.last_battery = battery
    part.last_seen_at = datetime.utcnow()
    if evento == "panico":
        part.estado = "panico"
    elif part.estado != "panico":
        part.estado = "online"

    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "evento": evento,
            "estado": part.estado,
            "config": _op_config(op),
        }
    )


@bp.route("/api/ping", methods=["POST"])
@csrf.exempt
def api_ping():
    return _ingest_ping("ping")


@bp.route("/api/panico", methods=["POST"])
@csrf.exempt
def api_panico():
    return _ingest_ping("panico")


@bp.route("/api/ok", methods=["POST"])
@csrf.exempt
def api_ok():
    """Quitar estado pánico (efectivo confirma que está bien)."""
    _ensure_tables()
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    part = _participante_from_token(token)
    if not part:
        return jsonify({"ok": False, "error": "token_invalido"}), 401
    part.estado = "online"
    part.last_seen_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "estado": part.estado})


# ─── Audio ───────────────────────────────────────────────────────────────────


@bp.route("/api/audio", methods=["POST"])
@csrf.exempt
def api_audio_upload():
    """Sube un clip corto (webm/ogg/mp4) desde la app de campo."""
    _ensure_tables()
    token = (request.form.get("token") or "").strip()
    part = _participante_from_token(token)
    if not part:
        return jsonify({"ok": False, "error": "token_invalido"}), 401

    op = part.operativo
    if op.estado != "activo":
        return jsonify({"ok": False, "error": "operativo_cerrado"}), 409

    f = request.files.get("audio")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "audio_requerido"}), 400

    raw = f.read()
    if not raw:
        return jsonify({"ok": False, "error": "audio_vacio"}), 400
    if len(raw) > MAX_AUDIO_BYTES:
        return jsonify({"ok": False, "error": "audio_muy_grande"}), 413

    mime = (f.mimetype or request.form.get("mime") or "audio/webm").split(";")[0].strip()
    allowed = {
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/mpeg",
        "audio/wav",
        "video/webm",  # algunos browsers mandan webm como video/*
    }
    if mime not in allowed:
        # Aceptar si la extensión parece audio
        if not any(x in mime for x in ("webm", "ogg", "mp4", "mpeg", "wav")):
            return jsonify({"ok": False, "error": "mime_no_soportado", "mime": mime}), 400

    ext = "webm"
    if "ogg" in mime:
        ext = "ogg"
    elif "mp4" in mime or "mpeg" in mime:
        ext = "m4a"
    elif "wav" in mime:
        ext = "wav"

    duration_ms = None
    try:
        duration_ms = int(request.form.get("duration_ms") or 0) or None
    except (TypeError, ValueError):
        duration_ms = None

    fname = f"{uuid.uuid4().hex}.{ext}"
    dest_dir = _audio_dir(op.id, part.id)
    dest = dest_dir / fname
    dest.write_bytes(raw)

    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "instance/uploads")).resolve()
    rel = str(dest.resolve().relative_to(upload_root)).replace("\\", "/")

    retenido = bool(getattr(op, "grabar_audio", True))
    clip = ComandoAudioClip(
        operativo_id=op.id,
        participante_id=part.id,
        rel_path=rel,
        mime="audio/webm" if "webm" in mime else mime,
        size_bytes=len(raw),
        duration_ms=duration_ms,
        retenido=retenido,
    )
    db.session.add(clip)
    part.last_audio_at = datetime.utcnow()
    part.last_seen_at = datetime.utcnow()
    if part.estado != "panico":
        part.estado = "online"
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "clip_id": clip.id,
            "retenido": retenido,
            "url": url_for("comando_vivo.api_audio_file", clip_id=clip.id),
            "config": _op_config(op),
        }
    )


@bp.route("/api/audio/lista/<int:op_id>")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def api_audio_lista(op_id: int):
    """Lista clips nuevos (para escucha casi en vivo en el mapa)."""
    _ensure_tables()
    op = ComandoOperativo.query.get_or_404(op_id)
    if not _can_view_op(op):
        return jsonify({"error": "forbidden"}), 403

    after_id = request.args.get("after_id", type=int) or 0
    part_id = request.args.get("participante_id", type=int)

    q = ComandoAudioClip.query.filter(
        ComandoAudioClip.operativo_id == op.id,
        ComandoAudioClip.id > after_id,
    )
    if part_id:
        q = q.filter(ComandoAudioClip.participante_id == part_id)

    rows = q.order_by(ComandoAudioClip.id.asc()).limit(40).all()
    return jsonify(
        {
            "clips": [
                {
                    "id": c.id,
                    "participante_id": c.participante_id,
                    "mime": c.mime,
                    "duration_ms": c.duration_ms,
                    "created_at": c.created_at.isoformat() + "Z",
                    "url": url_for("comando_vivo.api_audio_file", clip_id=c.id),
                }
                for c in rows
            ]
        }
    )


@bp.route("/api/audio/<int:clip_id>")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def api_audio_file(clip_id: int):
    _ensure_tables()
    clip = ComandoAudioClip.query.get_or_404(clip_id)
    op = clip.operativo
    if not _can_view_op(op):
        return jsonify({"error": "forbidden"}), 403

    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "instance/uploads")).resolve()
    path = (upload_root / clip.rel_path).resolve()
    if not str(path).startswith(str(upload_root)) or not path.is_file():
        return jsonify({"error": "archivo_no_encontrado"}), 404

    return send_file(
        path,
        mimetype=clip.mime or "audio/webm",
        as_attachment=False,
        download_name=os.path.basename(path),
        conditional=True,
    )


# ─── Video ───────────────────────────────────────────────────────────────────


@bp.route("/api/video", methods=["POST"])
@csrf.exempt
def api_video_upload():
    """Sube un clip corto de video (webm/mp4) desde la app de campo."""
    _ensure_tables()
    token = (request.form.get("token") or "").strip()
    part = _participante_from_token(token)
    if not part:
        return jsonify({"ok": False, "error": "token_invalido"}), 401

    op = part.operativo
    if op.estado != "activo":
        return jsonify({"ok": False, "error": "operativo_cerrado"}), 409

    f = request.files.get("video")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "video_requerido"}), 400

    raw = f.read()
    if not raw:
        return jsonify({"ok": False, "error": "video_vacio"}), 400
    if len(raw) > MAX_VIDEO_BYTES:
        return jsonify({"ok": False, "error": "video_muy_grande"}), 413

    mime = (f.mimetype or request.form.get("mime") or "video/webm").split(";")[0].strip()
    if not any(x in mime for x in ("webm", "mp4", "ogg", "quicktime")):
        return jsonify({"ok": False, "error": "mime_no_soportado", "mime": mime}), 400

    ext = "webm"
    if "mp4" in mime or "quicktime" in mime:
        ext = "mp4"
    elif "ogg" in mime:
        ext = "ogv"

    duration_ms = None
    try:
        duration_ms = int(request.form.get("duration_ms") or 0) or None
    except (TypeError, ValueError):
        duration_ms = None

    fname = f"{uuid.uuid4().hex}.{ext}"
    dest = _video_dir(op.id, part.id) / fname
    dest.write_bytes(raw)

    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "instance/uploads")).resolve()
    rel = str(dest.resolve().relative_to(upload_root)).replace("\\", "/")

    retenido = bool(getattr(op, "grabar_video", True))
    clip = ComandoVideoClip(
        operativo_id=op.id,
        participante_id=part.id,
        rel_path=rel,
        mime="video/webm" if "webm" in mime else mime,
        size_bytes=len(raw),
        duration_ms=duration_ms,
        retenido=retenido,
    )
    db.session.add(clip)
    now = datetime.utcnow()
    part.last_video_at = now
    part.last_audio_at = now  # el video suele traer audio
    part.last_seen_at = now
    if part.estado != "panico":
        part.estado = "online"
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "clip_id": clip.id,
            "retenido": retenido,
            "url": url_for("comando_vivo.api_video_file", clip_id=clip.id),
            "config": _op_config(op),
        }
    )


@bp.route("/api/video/lista/<int:op_id>")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def api_video_lista(op_id: int):
    _ensure_tables()
    op = ComandoOperativo.query.get_or_404(op_id)
    if not _can_view_op(op):
        return jsonify({"error": "forbidden"}), 403

    after_id = request.args.get("after_id", type=int) or 0
    part_id = request.args.get("participante_id", type=int)

    q = ComandoVideoClip.query.filter(
        ComandoVideoClip.operativo_id == op.id,
        ComandoVideoClip.id > after_id,
    )
    if part_id:
        q = q.filter(ComandoVideoClip.participante_id == part_id)

    rows = q.order_by(ComandoVideoClip.id.asc()).limit(30).all()
    return jsonify(
        {
            "clips": [
                {
                    "id": c.id,
                    "participante_id": c.participante_id,
                    "mime": c.mime,
                    "duration_ms": c.duration_ms,
                    "created_at": c.created_at.isoformat() + "Z",
                    "url": url_for("comando_vivo.api_video_file", clip_id=c.id),
                }
                for c in rows
            ]
        }
    )


@bp.route("/api/video/<int:clip_id>")
@login_required
@require_permission("COMANDO_VIVO_VIEW")
def api_video_file(clip_id: int):
    _ensure_tables()
    clip = ComandoVideoClip.query.get_or_404(clip_id)
    op = clip.operativo
    if not _can_view_op(op):
        return jsonify({"error": "forbidden"}), 403

    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "instance/uploads")).resolve()
    path = (upload_root / clip.rel_path).resolve()
    if not str(path).startswith(str(upload_root)) or not path.is_file():
        return jsonify({"error": "archivo_no_encontrado"}), 404

    return send_file(
        path,
        mimetype=clip.mime or "video/webm",
        as_attachment=False,
        download_name=os.path.basename(path),
        conditional=True,
    )

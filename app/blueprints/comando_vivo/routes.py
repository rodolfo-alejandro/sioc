"""
Rutas Centro de Comando / Operativos en vivo (piloto GPS).
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from app.blueprints.comando_vivo import bp
from app.extensions import csrf, db
from app.models.comando_vivo import ComandoGpsPing, ComandoOperativo, ComandoParticipante
from app.services.rbac import require_permission

# Sin señal si no hay ping en este intervalo
OFFLINE_SECONDS = 90
# Retener pings recientes para traza corta en mapa
TRACE_LIMIT = 80


def _ensure_tables():
    from sqlalchemy import inspect

    insp = inspect(db.engine)
    needed = {
        "comando_operativos",
        "comando_participantes",
        "comando_gps_pings",
    }
    existing = set(insp.get_table_names())
    if not needed.issubset(existing):
        db.create_all()


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
    return {
        "id": p.id,
        "alias": p.alias,
        "estado": p.estado,
        "lat": p.last_lat,
        "lon": p.last_lon,
        "accuracy": p.last_accuracy,
        "battery": p.last_battery,
        "last_seen_at": p.last_seen_at.isoformat() + "Z" if p.last_seen_at else None,
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
    return render_template(
        "comando_vivo/mapa.html",
        op=op,
        can_manage=current_user.has_permission("COMANDO_VIVO_MANAGE"),
        positions_url=url_for("comando_vivo.api_posiciones", op_id=op.id),
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

    participantes = ComandoParticipante.query.filter_by(operativo_id=op.id).all()
    _mark_offline(participantes)
    db.session.commit()

    panicos = (
        ComandoGpsPing.query.filter_by(operativo_id=op.id, evento="panico")
        .order_by(ComandoGpsPing.created_at.desc())
        .limit(20)
        .all()
    )

    return jsonify(
        {
            "operativo": {
                "id": op.id,
                "nombre": op.nombre,
                "codigo": op.codigo,
                "estado": op.estado,
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
    return jsonify({"ok": True, "evento": evento, "estado": part.estado})


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

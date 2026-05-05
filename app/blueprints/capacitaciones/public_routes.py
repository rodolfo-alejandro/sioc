"""Rutas públicas (sin login): asistencia por enlace/QR por momento."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from app.models.capacitaciones import EventoCapacitacion, MomentoAsistencia
from app.services.capacitaciones import (
    ensure_capacitaciones_db,
    qr_svg_response_for_url,
    registrar_asistencia,
)

bp_public = Blueprint(
    "capacitaciones_public",
    __name__,
    url_prefix="/capacitaciones",
)


@bp_public.before_request
def _ensure_db():
    ensure_capacitaciones_db()


@bp_public.route("/p/asistencia/<string:token>", methods=["GET", "POST"])
def marcar_asistencia(token: str):
    if not token or len(token) > 64:
        abort(404)
    mo = MomentoAsistencia.query.filter_by(token_publico=token.strip()).first()
    if not mo:
        abort(404)
    ev = EventoCapacitacion.query.get(mo.evento_id)
    if not ev:
        abort(404)

    if request.method == "POST":
        dni = (request.form.get("dni") or "").strip()
        _, msg_code = registrar_asistencia(ev, mo, dni, (mo.codigo_validacion or "").strip(), request)
        msgs = {
            "ok": ("Asistencia registrada correctamente.", "success"),
            "dni_no_inscripto": ("DNI no figura entre los inscriptos de este evento.", "warning"),
            "codigo_incorrecto": ("No se pudo validar el acceso. Contactá a la organización.", "danger"),
            "fuera_horario": ("Fuera del horario permitido para este momento.", "warning"),
            "ya_registrado": ("Ya estaba registrada tu asistencia para este momento.", "info"),
            "momento_inactivo": ("Este momento de asistencia no está activo.", "warning"),
        }
        text, cat = msgs.get(msg_code, ("No se pudo registrar la asistencia.", "danger"))
        flash(text, cat)
        return redirect(url_for("capacitaciones_public.marcar_asistencia", token=token))

    return render_template(
        "capacitaciones/asistencia_publica.html",
        ev=ev,
        mo=mo,
    )


@bp_public.route("/p/asistencia/<string:token>/qr.svg")
def marcar_asistencia_qr(token: str):
    if not token or len(token) > 64:
        abort(404)
    mo = MomentoAsistencia.query.filter_by(token_publico=token.strip()).first()
    if not mo:
        abort(404)
    full = _abs_url_for_marcar(token)
    return qr_svg_response_for_url(full)


def _abs_url_for_marcar(token: str) -> str:
    return request.url_root.rstrip("/") + url_for("capacitaciones_public.marcar_asistencia", token=token)

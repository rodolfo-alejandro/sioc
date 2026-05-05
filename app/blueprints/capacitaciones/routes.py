"""Rutas del módulo Capacitaciones."""

from __future__ import annotations

import io
from datetime import datetime, time as dt_time

import pandas as pd
from flask import (
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.blueprints.capacitaciones import bp
from app.extensions import db
from app.models.capacitaciones import (
    EventoCapacitacion,
    InscriptoEvento,
    MomentoAsistencia,
    PadronDrogas,
    RegistroAsistencia,
)
from app.services.capacitaciones import (
    build_reporte_dataframe,
    ensure_capacitaciones_db,
    export_dataframe_inscriptos,
    generate_codigo_momento,
    generate_token_publico_unique,
    importar_inscriptos_evento,
    importar_padron_drogas,
    normalize_dni,
    registrar_asistencia,
    resultado_final_asistencia,
)


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("CAPACITACIONES_VIEW")


def _can_admin() -> bool:
    return _is_superadmin() or current_user.has_permission("CAPACITACIONES_ADMIN")


def _can_asistencia() -> bool:
    return _is_superadmin() or current_user.has_permission("CAPACITACIONES_ASISTENCIA")


def _ensure_cap_tables():
    """Crea tablas del módulo y columnas auxiliares (token público por momento)."""
    ensure_capacitaciones_db()


@bp.before_request
@login_required
def _req_login():
    _ensure_cap_tables()
    if not (_can_view() or _can_admin() or _can_asistencia()):
        abort(403)


@bp.route("/")
def index():
    if not (_can_view() or _can_admin() or _can_asistencia()):
        abort(403)
    eventos = (
        EventoCapacitacion.query.filter_by(unidad_id=current_user.unidad_id)
        .order_by(EventoCapacitacion.creado_en.desc())
        .limit(200)
        .all()
    )
    n_padron = PadronDrogas.query.filter_by(activo=True).count() if (_can_view() or _can_admin()) else 0
    return render_template(
        "capacitaciones/index.html",
        eventos=eventos,
        n_padron=n_padron,
        can_admin=_can_admin(),
        can_view=_can_view(),
        can_asistencia=_can_asistencia(),
    )


# —— Padrón ——


@bp.route("/padron")
def padron_listado():
    if not (_can_view() or _can_admin()):
        abort(403)
    q = PadronDrogas.query
    buscar = (request.args.get("q") or "").strip()
    if buscar:
        bk, _ = normalize_dni(buscar)
        if bk:
            q = q.filter(
                or_(
                    PadronDrogas.dni_key == bk,
                    PadronDrogas.dni.ilike(f"%{buscar}%"),
                )
            )
        else:
            pat = f"%{buscar}%"
            q = q.filter(
                or_(
                    PadronDrogas.apellido.ilike(pat),
                    PadronDrogas.nombre.ilike(pat),
                    PadronDrogas.legajo.ilike(pat),
                    PadronDrogas.dependencia.ilike(pat),
                )
            )
    dep = (request.args.get("dependencia") or "").strip()
    if dep:
        q = q.filter(PadronDrogas.dependencia.ilike(f"%{dep}%"))
    grado = (request.args.get("grado") or "").strip()
    if grado:
        q = q.filter(PadronDrogas.grado.ilike(f"%{grado}%"))
    act = request.args.get("activo")
    if act == "1":
        q = q.filter(PadronDrogas.activo.is_(True))
    elif act == "0":
        q = q.filter(PadronDrogas.activo.is_(False))
    rows = q.order_by(PadronDrogas.apellido.asc(), PadronDrogas.nombre.asc()).limit(500).all()
    return render_template(
        "capacitaciones/padron_listado.html",
        rows=rows,
        can_import=_can_admin(),
    )


@bp.route("/padron/<int:persona_id>")
def padron_detalle(persona_id: int):
    if not (_can_view() or _can_admin()):
        abort(403)
    p = PadronDrogas.query.get_or_404(persona_id)
    return render_template("capacitaciones/padron_detalle.html", p=p)


@bp.route("/padron/importar", methods=["GET", "POST"])
def padron_importar():
    if not _can_admin():
        abort(403)
    if request.method == "POST":
        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccioná un archivo CSV o XLSX.", "warning")
            return redirect(url_for("capacitaciones.padron_importar"))
        es_completo = request.form.get("es_padron_completo") == "1"
        try:
            stats = importar_padron_drogas(f, f.filename, es_completo)
            flash(
                f"Importación finalizada. Leídos: {stats['leidos']}, insertados: {stats['insertados']}, "
                f"actualizados: {stats['actualizados']}, inválidos: {stats['invalidos']}, "
                f"desactivados: {stats['desactivados']}.",
                "success",
            )
        except Exception as e:
            flash(f"Error al importar: {e}", "danger")
        return redirect(url_for("capacitaciones.padron_listado"))
    return render_template("capacitaciones/padron_importar.html")


# —— Eventos ——


def _get_evento_or_404(eid: int) -> EventoCapacitacion:
    ev = EventoCapacitacion.query.filter_by(id=eid, unidad_id=current_user.unidad_id).first()
    if not ev:
        abort(404)
    return ev


@bp.route("/eventos/nuevo", methods=["GET", "POST"])
def evento_nuevo():
    if not _can_admin():
        abort(403)
    if request.method == "POST":
        ev = EventoCapacitacion(
            titulo=(request.form.get("titulo") or "").strip() or "Sin título",
            descripcion=(request.form.get("descripcion") or "").strip() or None,
            tipo_evento=(request.form.get("tipo_evento") or "").strip() or None,
            modalidad=(request.form.get("modalidad") or "").strip() or None,
            fecha=_parse_date(request.form.get("fecha")),
            hora_inicio=_parse_time(request.form.get("hora_inicio")),
            hora_fin=_parse_time(request.form.get("hora_fin")),
            lugar=(request.form.get("lugar") or "").strip() or None,
            enlace_virtual=(request.form.get("enlace_virtual") or "").strip() or None,
            estado=(request.form.get("estado") or "planificado").strip(),
            unidad_id=current_user.unidad_id,
            creado_por_id=current_user.id,
            creado_en=datetime.utcnow(),
        )
        db.session.add(ev)
        db.session.commit()
        flash("Evento creado.", "success")
        return redirect(url_for("capacitaciones.evento_detalle", evento_id=ev.id))
    return render_template("capacitaciones/evento_form.html", evento=None)


@bp.route("/eventos/<int:evento_id>")
def evento_detalle(evento_id: int):
    if not (_can_view() or _can_admin() or _can_asistencia()):
        abort(403)
    ev = _get_evento_or_404(evento_id)
    momentos = (
        MomentoAsistencia.query.filter_by(evento_id=ev.id).order_by(MomentoAsistencia.orden.asc(), MomentoAsistencia.id.asc()).all()
    )
    n_ins = InscriptoEvento.query.filter_by(evento_id=ev.id).count()
    return render_template(
        "capacitaciones/evento_detalle.html",
        ev=ev,
        momentos=momentos,
        n_ins=n_ins,
        can_admin=_can_admin(),
        can_asistencia=_can_asistencia(),
    )


@bp.route("/eventos/<int:evento_id>/editar", methods=["GET", "POST"])
def evento_editar(evento_id: int):
    if not _can_admin():
        abort(403)
    ev = _get_evento_or_404(evento_id)
    if request.method == "POST":
        ev.titulo = (request.form.get("titulo") or "").strip() or ev.titulo
        ev.descripcion = (request.form.get("descripcion") or "").strip() or None
        ev.tipo_evento = (request.form.get("tipo_evento") or "").strip() or None
        ev.modalidad = (request.form.get("modalidad") or "").strip() or None
        ev.fecha = _parse_date(request.form.get("fecha"))
        ev.hora_inicio = _parse_time(request.form.get("hora_inicio"))
        ev.hora_fin = _parse_time(request.form.get("hora_fin"))
        ev.lugar = (request.form.get("lugar") or "").strip() or None
        ev.enlace_virtual = (request.form.get("enlace_virtual") or "").strip() or None
        ev.estado = (request.form.get("estado") or ev.estado).strip()
        db.session.commit()
        flash("Cambios guardados.", "success")
        return redirect(url_for("capacitaciones.evento_detalle", evento_id=ev.id))
    return render_template("capacitaciones/evento_form.html", evento=ev)


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_time(s: str | None):
    if not s:
        return None
    try:
        parts = s.strip().split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return dt_time(h, m)
    except Exception:
        return None


# —— Inscriptos ——


@bp.route("/eventos/<int:evento_id>/inscriptos")
def inscriptos_listado(evento_id: int):
    if not (_can_view() or _can_admin()):
        abort(403)
    ev = _get_evento_or_404(evento_id)
    filtro = (request.args.get("estado_validacion") or "").strip()
    q = InscriptoEvento.query.filter_by(evento_id=ev.id)
    if filtro:
        q = q.filter_by(estado_validacion=filtro)
    rows = q.order_by(InscriptoEvento.apellido_nombre.asc()).limit(2000).all()
    return render_template(
        "capacitaciones/inscriptos_listado.html",
        ev=ev,
        rows=rows,
        can_admin=_can_admin(),
    )


@bp.route("/eventos/<int:evento_id>/inscriptos/importar", methods=["GET", "POST"])
def inscriptos_importar(evento_id: int):
    if not _can_admin():
        abort(403)
    ev = _get_evento_or_404(evento_id)
    if request.method == "POST":
        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Seleccioná un archivo.", "warning")
            return redirect(url_for("capacitaciones.inscriptos_importar", evento_id=ev.id))
        try:
            stats = importar_inscriptos_evento(ev.id, f, f.filename)
            flash(
                f"Importación: total filas {stats['total']}, insertados/actualizados: "
                f"{stats['insertados']}/{stats['actualizados']}, Drogas: {stats['validado_drogas']}, "
                f"externos: {stats['externo']}, inválidos: {stats['dni_invalido']}, duplicados (omitidos): {stats['duplicado']}.",
                "success",
            )
        except Exception as e:
            flash(f"Error: {e}", "danger")
        return redirect(url_for("capacitaciones.inscriptos_listado", evento_id=ev.id))
    return render_template("capacitaciones/inscriptos_importar.html", ev=ev)


# —— Momentos ——


@bp.route("/eventos/<int:evento_id>/momentos/nuevo", methods=["GET", "POST"])
def momento_nuevo(evento_id: int):
    if not _can_admin():
        abort(403)
    ev = _get_evento_or_404(evento_id)
    if request.method == "POST":
        mx = MomentoAsistencia.query.filter_by(evento_id=ev.id).count()
        mo = MomentoAsistencia(
            evento_id=ev.id,
            nombre=(request.form.get("nombre") or "Momento").strip(),
            tipo=(request.form.get("tipo") or "personalizado").strip(),
            codigo_validacion=(request.form.get("codigo") or "").strip().upper() or generate_codigo_momento(),
            token_publico=generate_token_publico_unique(),
            fecha_apertura=_parse_dt(request.form.get("fecha_apertura")),
            fecha_cierre=_parse_dt(request.form.get("fecha_cierre")),
            activo=request.form.get("activo") == "1",
            orden=int(request.form.get("orden") or mx + 1),
        )
        db.session.add(mo)
        db.session.commit()
        flash("Momento creado.", "success")
        return redirect(url_for("capacitaciones.evento_detalle", evento_id=ev.id))
    return render_template("capacitaciones/momento_form.html", ev=ev, momento=None)


@bp.route("/momentos/<int:momento_id>/editar", methods=["GET", "POST"])
def momento_editar(momento_id: int):
    if not _can_admin():
        abort(403)
    mo = MomentoAsistencia.query.get_or_404(momento_id)
    ev = _get_evento_or_404(mo.evento_id)
    if request.method == "POST":
        mo.nombre = (request.form.get("nombre") or mo.nombre).strip()
        mo.tipo = (request.form.get("tipo") or mo.tipo).strip()
        mo.codigo_validacion = (request.form.get("codigo") or mo.codigo_validacion).strip().upper()
        mo.fecha_apertura = _parse_dt(request.form.get("fecha_apertura"))
        mo.fecha_cierre = _parse_dt(request.form.get("fecha_cierre"))
        mo.activo = request.form.get("activo") == "1"
        mo.orden = int(request.form.get("orden") or mo.orden)
        if request.form.get("regenerar_token_publico") == "1":
            mo.token_publico = generate_token_publico_unique(exclude_momento_id=mo.id)
        elif not (mo.token_publico or "").strip():
            mo.token_publico = generate_token_publico_unique(exclude_momento_id=mo.id)
        db.session.commit()
        flash("Momento actualizado.", "success")
        return redirect(url_for("capacitaciones.evento_detalle", evento_id=ev.id))
    return render_template("capacitaciones/momento_form.html", ev=ev, momento=mo)


def _parse_dt(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    return None


# —— Asistencia ——


@bp.route("/eventos/<int:evento_id>/asistencia", methods=["GET", "POST"])
def asistencia(evento_id: int):
    if not _can_asistencia():
        abort(403)
    ev = _get_evento_or_404(evento_id)
    momentos = (
        MomentoAsistencia.query.filter_by(evento_id=ev.id).order_by(MomentoAsistencia.orden.asc(), MomentoAsistencia.id.asc()).all()
    )
    msg_code = None
    ok = False
    if request.method == "POST":
        mid = request.form.get("momento_id", type=int)
        dni = request.form.get("dni", "")
        codigo = request.form.get("codigo", "")
        mo = MomentoAsistencia.query.filter_by(id=mid, evento_id=ev.id).first() if mid else None
        if not mo:
            flash("Seleccioná un momento válido.", "danger")
        else:
            ok, msg_code = registrar_asistencia(ev, mo, dni, codigo, request)
            msgs = {
                "ok": ("Asistencia registrada correctamente.", "success"),
                "dni_no_inscripto": ("DNI no figura entre los inscriptos de este evento.", "warning"),
                "codigo_incorrecto": ("Código incorrecto.", "danger"),
                "fuera_horario": ("Fuera del horario permitido para este momento.", "warning"),
                "ya_registrado": ("Ya estaba registrada la asistencia para este momento.", "info"),
                "momento_inactivo": ("Este momento no está activo.", "warning"),
            }
            text, cat = msgs.get(msg_code, ("No se pudo registrar.", "danger"))
            flash(text, cat)
    return render_template(
        "capacitaciones/asistencia.html",
        ev=ev,
        momentos=momentos,
        last_ok=ok,
        last_code=msg_code,
    )


# —— Reporte ——


@bp.route("/eventos/<int:evento_id>/reporte")
def reporte(evento_id: int):
    if not (_can_view() or _can_admin() or _can_asistencia()):
        abort(403)
    ev = _get_evento_or_404(evento_id)
    momentos = (
        MomentoAsistencia.query.filter_by(evento_id=ev.id).order_by(MomentoAsistencia.orden.asc(), MomentoAsistencia.id.asc()).all()
    )
    ins_list = (
        InscriptoEvento.query.options(joinedload(InscriptoEvento.padron_ref))
        .filter_by(evento_id=ev.id)
        .all()
    )
    regs = {
        (r.inscripto_id, r.momento_id)
        for r in RegistroAsistencia.query.filter(
            RegistroAsistencia.evento_id == ev.id,
            RegistroAsistencia.valido.is_(True),
            RegistroAsistencia.inscripto_id.isnot(None),
        ).all()
    }
    filas = []
    for ins in sorted(ins_list, key=lambda x: (x.apellido_nombre or "", x.id)):
        row = {"ins": ins, "checks": {}, "resultado": resultado_final_asistencia(ins, momentos)}
        for m in momentos:
            row["checks"][m.id] = (ins.id, m.id) in regs
        filas.append(row)
    total = len(ins_list)
    n_drogas = sum(1 for x in ins_list if x.pertenece_drogas)
    n_ext = sum(1 for x in ins_list if x.estado_validacion == "externo")
    n_pres = sum(1 for f in filas if f["resultado"] == "PRESENTE")
    n_aus = sum(1 for f in filas if f["resultado"] == "AUSENTE")
    return render_template(
        "capacitaciones/reporte.html",
        ev=ev,
        momentos=momentos,
        filas=filas,
        total=total,
        n_drogas=n_drogas,
        n_ext=n_ext,
        n_pres=n_pres,
        n_aus=n_aus,
        can_export=_can_admin(),
    )


# —— Exportaciones ——


def _df_response(df: pd.DataFrame, name: str, as_csv: bool) -> Response:
    bio = io.BytesIO()
    if as_csv:
        df.to_csv(bio, index=False, encoding="utf-8-sig")
        bio.seek(0)
        return Response(
            bio.read(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={name}.csv"},
        )
    df.to_excel(bio, index=False, engine="openpyxl")
    bio.seek(0)
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={name}.xlsx"},
    )


@bp.route("/eventos/<int:evento_id>/export/inscriptos")
def export_inscriptos(evento_id: int):
    if not _can_admin():
        abort(403)
    ev = _get_evento_or_404(evento_id)
    solo = (request.args.get("solo") or "").strip() or None
    df = export_dataframe_inscriptos(ev.id, solo)
    fmt = (request.args.get("fmt") or "xlsx").lower()
    return _df_response(df, f"inscriptos_evento_{ev.id}", as_csv=fmt == "csv")


@bp.route("/eventos/<int:evento_id>/export/reporte")
def export_reporte(evento_id: int):
    if not _can_admin():
        abort(403)
    ev = _get_evento_or_404(evento_id)
    momentos = (
        MomentoAsistencia.query.filter_by(evento_id=ev.id).order_by(MomentoAsistencia.orden.asc(), MomentoAsistencia.id.asc()).all()
    )
    df = build_reporte_dataframe(ev, momentos)
    fmt = (request.args.get("fmt") or "xlsx").lower()
    return _df_response(df, f"asistencia_evento_{ev.id}", as_csv=fmt == "csv")

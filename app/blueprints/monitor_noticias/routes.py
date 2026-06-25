"""
Monitor de Noticias: bandeja, búsqueda manual, temas y fuentes.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

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
from sqlalchemy import inspect

from app.blueprints.monitor_noticias import bp
from app.blueprints.monitor_noticias import services
from app.extensions import db
from app.models.monitor_noticias import FuenteNoticia, Noticia, TemaNoticia

_schema_checked = False

_TEMAS_SEED = [
    {
        "nombre": "Droga - Resultados",
        "palabras_clave": "secuestro de droga, allanamiento, narcomenudeo, cocaína, marihuana, detenidos droga, incautación, dosis de droga, microtráfico",
        "palabras_excluir": "fútbol, mundial",
    },
    {
        "nombre": "Droga - Problemáticas",
        "palabras_clave": "consumo de drogas, adicciones, búnker, venta de droga, narcotráfico, narcomenudeo, droga en barrios",
        "palabras_excluir": "fútbol, mundial",
    },
]


def _clean(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ""


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("MONITOR_NOTICIAS_VIEW")


def _can_manage() -> bool:
    return _is_superadmin() or current_user.has_permission("MONITOR_NOTICIAS_MANAGE")


def _can_export() -> bool:
    return _is_superadmin() or current_user.has_permission("MONITOR_NOTICIAS_EXPORT")


def _ensure_schema():
    global _schema_checked
    if _schema_checked:
        return
    insp = inspect(db.engine)
    existing = set(insp.get_table_names())
    for model in (TemaNoticia, FuenteNoticia, Noticia):
        if model.__tablename__ not in existing:
            model.__table__.create(bind=db.engine)
    _schema_checked = True


def _seed_inicial():
    """Crea, una sola vez por unidad, la fuente Google News y los temas de droga."""
    uid = current_user.unidad_id
    if not FuenteNoticia.query.filter_by(unidad_id=uid).first():
        db.session.add(
            FuenteNoticia(
                unidad_id=uid,
                creado_por=current_user.id,
                nombre="Google News (Salta)",
                tipo="google_news",
                url=None,
                activo=True,
            )
        )
    if not TemaNoticia.query.filter_by(unidad_id=uid).first():
        for t in _TEMAS_SEED:
            db.session.add(
                TemaNoticia(
                    unidad_id=uid,
                    creado_por=current_user.id,
                    nombre=t["nombre"],
                    palabras_clave=t["palabras_clave"],
                    palabras_excluir=t["palabras_excluir"],
                    region="Salta",
                    activo=True,
                )
            )
    db.session.commit()


@bp.before_request
@login_required
def _gate():
    if not _can_view():
        abort(403)
    _ensure_schema()


def _base_noticias():
    return Noticia.query.filter(Noticia.unidad_id == current_user.unidad_id)


@bp.route("/")
def bandeja():
    _seed_inicial()
    q = _base_noticias()

    tema_id = _clean(request.args.get("tema"))
    estado = _clean(request.args.get("estado"))
    medio = _clean(request.args.get("medio"))
    texto = _clean(request.args.get("q"))

    if tema_id.isdigit():
        q = q.filter(Noticia.tema_id == int(tema_id))
    if estado in ("nueva", "relevante", "descartada"):
        q = q.filter(Noticia.estado == estado)
    if medio:
        q = q.filter(Noticia.medio.ilike(f"%{medio}%"))
    if texto:
        q = q.filter(Noticia.titulo.ilike(f"%{texto}%"))

    noticias = q.order_by(
        Noticia.publicado_en.desc().nullslast(),
        Noticia.created_at.desc(),
    ).limit(500).all()

    temas = TemaNoticia.query.filter_by(unidad_id=current_user.unidad_id).order_by(TemaNoticia.nombre).all()
    medios = [
        m[0]
        for m in db.session.query(Noticia.medio)
        .filter(Noticia.unidad_id == current_user.unidad_id, Noticia.medio.isnot(None))
        .distinct()
        .order_by(Noticia.medio)
        .all()
        if m[0]
    ]

    contadores = {
        "nueva": _base_noticias().filter(Noticia.estado == "nueva").count(),
        "relevante": _base_noticias().filter(Noticia.estado == "relevante").count(),
        "descartada": _base_noticias().filter(Noticia.estado == "descartada").count(),
    }

    return render_template(
        "monitor_noticias/bandeja.html",
        noticias=noticias,
        temas=temas,
        medios=medios,
        contadores=contadores,
        selected={"tema": tema_id, "estado": estado, "medio": medio, "q": texto},
        can_manage=_can_manage(),
        can_export=_can_export(),
        dep_faltantes=services.dependencias_faltantes(),
    )


@bp.route("/buscar", methods=["POST"])
def buscar():
    if not _can_manage():
        abort(403)
    faltan = services.dependencias_faltantes()
    if faltan:
        flash(f"Faltan dependencias en el servidor: {', '.join(faltan)}. Instalá con pip install -r requirements.txt.", "danger")
        return redirect(url_for("monitor_noticias.bandeja"))

    uid = current_user.unidad_id
    tema_id = _clean(request.form.get("tema_id"))
    temas_q = TemaNoticia.query.filter_by(unidad_id=uid, activo=True)
    if tema_id.isdigit():
        temas_q = temas_q.filter(TemaNoticia.id == int(tema_id))
    temas = temas_q.all()
    if not temas:
        flash("No hay temas activos para buscar. Creá uno en la pestaña Temas.", "warning")
        return redirect(url_for("monitor_noticias.bandeja"))

    fuentes = FuenteNoticia.query.filter_by(unidad_id=uid, activo=True).all()
    if not fuentes:
        flash("No hay fuentes activas. Activá al menos Google News en la pestaña Fuentes.", "warning")
        return redirect(url_for("monitor_noticias.bandeja"))

    total_nuevas = 0
    total_dup = 0
    for tema in temas:
        try:
            candidatos = services.recolectar_para_tema(tema, fuentes)
        except Exception as e:
            flash(f"Error al buscar el tema «{tema.nombre}»: {e}", "danger")
            continue
        for item in candidatos:
            existe = (
                _base_noticias()
                .filter(Noticia.link_hash == item["link_hash"])
                .first()
            )
            if existe:
                total_dup += 1
                continue
            db.session.add(
                Noticia(
                    unidad_id=uid,
                    tema_id=tema.id,
                    titulo=item["titulo"][:600],
                    link=item["link"][:1000],
                    link_hash=item["link_hash"],
                    medio=(item.get("medio") or "")[:200] or None,
                    resumen=item.get("resumen") or None,
                    publicado_en=item.get("publicado_en"),
                    estado="nueva",
                    fuente_origen=item.get("fuente_origen"),
                )
            )
            total_nuevas += 1
    db.session.commit()
    flash(
        f"Búsqueda completada: {total_nuevas} noticia(s) nueva(s), {total_dup} ya existían.",
        "success" if total_nuevas else "info",
    )
    return redirect(url_for("monitor_noticias.bandeja"))


@bp.route("/noticia/<int:noticia_id>/estado", methods=["POST"])
def cambiar_estado(noticia_id: int):
    if not _can_manage():
        abort(403)
    n = _base_noticias().filter(Noticia.id == noticia_id).first_or_404()
    nuevo = _clean(request.form.get("estado"))
    if nuevo not in ("nueva", "relevante", "descartada"):
        abort(400)
    n.estado = nuevo
    db.session.commit()
    return redirect(request.referrer or url_for("monitor_noticias.bandeja"))


# ---------------------- Temas ----------------------

@bp.route("/temas")
def temas():
    _seed_inicial()
    rows = TemaNoticia.query.filter_by(unidad_id=current_user.unidad_id).order_by(TemaNoticia.nombre).all()
    return render_template("monitor_noticias/temas.html", temas=rows, can_manage=_can_manage())


@bp.route("/temas/guardar", methods=["POST"])
def temas_guardar():
    if not _can_manage():
        abort(403)
    tid = _clean(request.form.get("id"))
    nombre = _clean(request.form.get("nombre"))
    if not nombre:
        flash("El nombre del tema es obligatorio.", "warning")
        return redirect(url_for("monitor_noticias.temas"))
    if tid.isdigit():
        row = TemaNoticia.query.filter_by(unidad_id=current_user.unidad_id, id=int(tid)).first_or_404()
    else:
        row = TemaNoticia(unidad_id=current_user.unidad_id, creado_por=current_user.id)
        db.session.add(row)
    row.nombre = nombre[:120]
    row.palabras_clave = _clean(request.form.get("palabras_clave"))
    row.palabras_excluir = _clean(request.form.get("palabras_excluir"))
    row.region = _clean(request.form.get("region")) or "Salta"
    row.activo = request.form.get("activo") == "1"
    db.session.commit()
    flash("Tema guardado.", "success")
    return redirect(url_for("monitor_noticias.temas"))


@bp.route("/temas/<int:tema_id>/eliminar", methods=["POST"])
def temas_eliminar(tema_id: int):
    if not _can_manage():
        abort(403)
    row = TemaNoticia.query.filter_by(unidad_id=current_user.unidad_id, id=tema_id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    flash("Tema eliminado.", "success")
    return redirect(url_for("monitor_noticias.temas"))


# ---------------------- Fuentes ----------------------

@bp.route("/fuentes")
def fuentes():
    _seed_inicial()
    rows = FuenteNoticia.query.filter_by(unidad_id=current_user.unidad_id).order_by(FuenteNoticia.nombre).all()
    return render_template("monitor_noticias/fuentes.html", fuentes=rows, can_manage=_can_manage())


@bp.route("/fuentes/guardar", methods=["POST"])
def fuentes_guardar():
    if not _can_manage():
        abort(403)
    fid = _clean(request.form.get("id"))
    nombre = _clean(request.form.get("nombre"))
    tipo = _clean(request.form.get("tipo")) or "rss"
    if tipo not in ("google_news", "rss"):
        tipo = "rss"
    url = _clean(request.form.get("url"))
    if not nombre:
        flash("El nombre de la fuente es obligatorio.", "warning")
        return redirect(url_for("monitor_noticias.fuentes"))
    if tipo == "rss" and not url:
        flash("Una fuente RSS necesita la URL del feed.", "warning")
        return redirect(url_for("monitor_noticias.fuentes"))
    if fid.isdigit():
        row = FuenteNoticia.query.filter_by(unidad_id=current_user.unidad_id, id=int(fid)).first_or_404()
    else:
        row = FuenteNoticia(unidad_id=current_user.unidad_id, creado_por=current_user.id)
        db.session.add(row)
    row.nombre = nombre[:150]
    row.tipo = tipo
    row.url = url[:500] if tipo == "rss" else None
    row.activo = request.form.get("activo") == "1"
    db.session.commit()
    flash("Fuente guardada.", "success")
    return redirect(url_for("monitor_noticias.fuentes"))


@bp.route("/fuentes/<int:fuente_id>/eliminar", methods=["POST"])
def fuentes_eliminar(fuente_id: int):
    if not _can_manage():
        abort(403)
    row = FuenteNoticia.query.filter_by(unidad_id=current_user.unidad_id, id=fuente_id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    flash("Fuente eliminada.", "success")
    return redirect(url_for("monitor_noticias.fuentes"))


# ---------------------- Export ----------------------

@bp.route("/export.xlsx")
def export_xlsx():
    if not _can_export():
        abort(403)
    import openpyxl

    q = _base_noticias()
    estado = _clean(request.args.get("estado"))
    if estado in ("nueva", "relevante", "descartada"):
        q = q.filter(Noticia.estado == estado)
    tema_id = _clean(request.args.get("tema"))
    if tema_id.isdigit():
        q = q.filter(Noticia.tema_id == int(tema_id))
    rows = q.order_by(Noticia.publicado_en.desc().nullslast(), Noticia.created_at.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Noticias"
    ws.append(["Fecha", "Medio", "Tema", "Estado", "Título", "Link", "Resumen"])
    for n in rows:
        ws.append(
            [
                n.publicado_en.strftime("%d/%m/%Y %H:%M") if n.publicado_en else "",
                n.medio or "",
                n.tema.nombre if n.tema else "",
                n.estado,
                n.titulo,
                n.link,
                n.resumen or "",
            ]
        )
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    fname = f"monitor_noticias_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

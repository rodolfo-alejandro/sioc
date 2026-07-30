"""
Monitor de Noticias: bandeja, búsqueda manual, temas y fuentes.
"""
from __future__ import annotations

from datetime import datetime, timedelta
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

PROVINCIAS_AR = [
    "Buenos Aires", "CABA", "Catamarca", "Chaco", "Chubut", "Córdoba",
    "Corrientes", "Entre Ríos", "Formosa", "Jujuy", "La Pampa", "La Rioja",
    "Mendoza", "Misiones", "Neuquén", "Río Negro", "Salta", "San Juan",
    "San Luis", "Santa Cruz", "Santa Fe", "Santiago del Estero",
    "Tierra del Fuego", "Tucumán",
]

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

# Fuentes oficiales de Salta (se crean si faltan, aunque ya exista Google News)
_FUENTES_OFICIALES_SEED = [
    {
        "nombre": "Prensa Policía de Salta - DROGAS",
        "tipo": "rss",
        "url": "https://prensa.policiadesalta.gob.ar/?feed=rss2&cat=40",
    },
    {
        "nombre": "Ministerio de Seguridad - Salta",
        "tipo": "html_site",
        "url": "https://www.salta.gob.ar/organismos/ministerio-de-seguridad-6",
    },
]


def _clean(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ""


def _parse_date(s: str):
    s = _clean(s)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


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
    """Crea, una sola vez por unidad, Google News, temas de droga y fuentes oficiales."""
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
    for fo in _FUENTES_OFICIALES_SEED:
        existe = FuenteNoticia.query.filter_by(unidad_id=uid, nombre=fo["nombre"]).first()
        if not existe:
            db.session.add(
                FuenteNoticia(
                    unidad_id=uid,
                    creado_por=current_user.id,
                    nombre=fo["nombre"],
                    tipo=fo["tipo"],
                    url=fo["url"],
                    activo=True,
                )
            )
        elif fo["tipo"] == "rss" and existe.url and "cat=51" in existe.url:
            # Corrección: DROGAS es cat=40 (51 era DIC)
            existe.url = fo["url"]
            existe.tipo = fo["tipo"]
            existe.activo = True
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
    fecha_desde = _clean(request.args.get("fecha_desde"))
    fecha_hasta = _clean(request.args.get("fecha_hasta"))
    dias = _clean(request.args.get("dias"))

    if tema_id.isdigit():
        q = q.filter(Noticia.tema_id == int(tema_id))
    if estado in ("nueva", "relevante", "descartada"):
        q = q.filter(Noticia.estado == estado)
    if medio:
        q = q.filter(Noticia.medio.ilike(f"%{medio}%"))
    if texto:
        q = q.filter(Noticia.titulo.ilike(f"%{texto}%"))

    if dias.isdigit() and int(dias) > 0:
        q = q.filter(Noticia.publicado_en >= datetime.utcnow() - timedelta(days=int(dias)))
    else:
        d1 = _parse_date(fecha_desde)
        d2 = _parse_date(fecha_hasta)
        if d1:
            q = q.filter(Noticia.publicado_en >= datetime(d1.year, d1.month, d1.day))
        if d2:
            q = q.filter(Noticia.publicado_en <= datetime(d2.year, d2.month, d2.day, 23, 59, 59))

    noticias = q.order_by(
        Noticia.publicado_en.desc(),
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

    fuentes_oficiales = (
        FuenteNoticia.query.filter_by(unidad_id=current_user.unidad_id, activo=True)
        .filter(FuenteNoticia.tipo.in_(("rss", "html_site")))
        .order_by(FuenteNoticia.nombre)
        .all()
    )

    return render_template(
        "monitor_noticias/bandeja.html",
        noticias=noticias,
        temas=temas,
        medios=medios,
        fuentes_oficiales=fuentes_oficiales,
        contadores=contadores,
        selected={
            "tema": tema_id,
            "estado": estado,
            "medio": medio,
            "q": texto,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "dias": dias,
        },
        provincias=PROVINCIAS_AR,
        can_manage=_can_manage(),
        can_export=_can_export(),
        dep_faltantes=services.dependencias_faltantes(),
    )


def _guardar_candidatos(uid: int, tema_id, candidatos: list[dict]) -> tuple[int, int]:
    nuevas = 0
    dup = 0
    for item in candidatos:
        existe = _base_noticias().filter(Noticia.link_hash == item["link_hash"]).first()
        if existe:
            dup += 1
            continue
        db.session.add(
            Noticia(
                unidad_id=uid,
                tema_id=tema_id,
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
        nuevas += 1
    db.session.commit()
    return nuevas, dup


@bp.route("/buscar-libre", methods=["POST"])
def buscar_libre():
    if not _can_manage():
        abort(403)
    faltan = services.dependencias_faltantes()
    if faltan:
        flash(f"Faltan dependencias en el servidor: {', '.join(faltan)}. Instalá con pip install -r requirements.txt.", "danger")
        return redirect(url_for("monitor_noticias.bandeja"))

    texto = _clean(request.form.get("q_libre"))
    if not texto:
        flash("Escribí al menos una palabra para la búsqueda libre.", "warning")
        return redirect(url_for("monitor_noticias.bandeja"))
    regiones = [_clean(r) for r in request.form.getlist("regiones") if _clean(r)]
    region = ", ".join(regiones)
    dias_libre = _clean(request.form.get("dias_libre"))
    dias_int = int(dias_libre) if dias_libre.isdigit() and int(dias_libre) > 0 else None

    uid = current_user.unidad_id
    fuentes = FuenteNoticia.query.filter_by(unidad_id=uid, activo=True, tipo="google_news").all()
    if not fuentes:
        fuentes = [FuenteNoticia(unidad_id=uid, nombre="Google News", tipo="google_news", activo=True)]

    tema_tmp = TemaNoticia(
        unidad_id=uid,
        nombre="Búsqueda libre",
        palabras_clave=texto,
        palabras_excluir="",
        region=region,
        activo=True,
    )
    try:
        candidatos = services.recolectar_para_tema(tema_tmp, fuentes, dias=dias_int)
    except Exception as e:
        flash(f"Error en la búsqueda libre: {e}", "danger")
        return redirect(url_for("monitor_noticias.bandeja"))

    nuevas, dup = _guardar_candidatos(uid, None, candidatos)
    flash(
        f"Búsqueda «{texto}»: {nuevas} noticia(s) nueva(s), {dup} ya existían.",
        "success" if nuevas else "info",
    )
    return redirect(url_for("monitor_noticias.bandeja", dias=dias_libre or None))


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
        n, d = _guardar_candidatos(uid, tema.id, candidatos)
        total_nuevas += n
        total_dup += d
    flash(
        f"Búsqueda completada: {total_nuevas} noticia(s) nueva(s), {total_dup} ya existían.",
        "success" if total_nuevas else "info",
    )
    return redirect(url_for("monitor_noticias.bandeja"))


@bp.route("/buscar-oficiales", methods=["POST"])
def buscar_oficiales():
    """Recolecta noticias de fuentes oficiales (Policía RSS + Ministerio HTML) por período."""
    if not _can_manage():
        abort(403)
    faltan = services.dependencias_faltantes()
    if faltan:
        flash(f"Faltan dependencias en el servidor: {', '.join(faltan)}. Instalá con pip install -r requirements.txt.", "danger")
        return redirect(url_for("monitor_noticias.bandeja"))

    _seed_inicial()
    uid = current_user.unidad_id
    d1 = _parse_date(request.form.get("fecha_desde"))
    d2 = _parse_date(request.form.get("fecha_hasta"))
    dias_raw = _clean(request.form.get("dias_oficial"))
    dias_int = int(dias_raw) if dias_raw.isdigit() and int(dias_raw) > 0 else None

    if not d1 and not d2 and not dias_int:
        flash("Indicá un período (fechas o últimos N días) para las fuentes oficiales.", "warning")
        return redirect(url_for("monitor_noticias.bandeja"))

    tema_id = _clean(request.form.get("tema_id"))
    temas_q = TemaNoticia.query.filter_by(unidad_id=uid, activo=True)
    if tema_id.isdigit():
        temas_q = temas_q.filter(TemaNoticia.id == int(tema_id))
    temas = temas_q.all()
    if not temas:
        # Tema temporal genérico droga para filtrar Ministerio
        temas = [
            TemaNoticia(
                unidad_id=uid,
                nombre="Oficiales - Droga",
                palabras_clave="droga, cocaína, marihuana, narcotráfico, narcomenudeo, allanamiento, secuestro, dosis, estupefacientes",
                palabras_excluir="",
                region="Salta",
                activo=True,
            )
        ]

    fuentes_q = FuenteNoticia.query.filter_by(unidad_id=uid, activo=True).filter(
        FuenteNoticia.tipo.in_(("rss", "html_site"))
    )
    # Opcional: limitar a una sola fuente oficial (policía / ministerio)
    fuente_ids = [x for x in request.form.getlist("fuente_ids") if str(x).isdigit()]
    if fuente_ids:
        fuentes_q = fuentes_q.filter(FuenteNoticia.id.in_([int(x) for x in fuente_ids]))
    fuentes = fuentes_q.all()
    if not fuentes:
        flash("No hay fuentes oficiales activas. Abrí la pestaña Fuentes o dejá marcadas Policía/Ministerio.", "warning")
        return redirect(url_for("monitor_noticias.bandeja"))

    total_nuevas = 0
    total_dup = 0
    for tema in temas:
        try:
            candidatos = services.recolectar_para_tema(
                tema,
                fuentes,
                dias=dias_int,
                fecha_desde=d1,
                fecha_hasta=d2,
                solo_oficiales=True,
            )
        except Exception as e:
            flash(f"Error al buscar oficiales («{tema.nombre}»): {e}", "danger")
            continue
        tid = getattr(tema, "id", None)
        n, d = _guardar_candidatos(uid, tid, candidatos)
        total_nuevas += n
        total_dup += d

    periodo = ""
    if d1 or d2:
        periodo = f" del {d1 or '…'} al {d2 or '…'}"
    elif dias_int:
        periodo = f" (últimos {dias_int} días)"
    flash(
        f"Fuentes oficiales{periodo}: {total_nuevas} noticia(s) nueva(s), {total_dup} ya existían.",
        "success" if total_nuevas else "info",
    )
    redirect_args = {}
    if dias_int:
        redirect_args["dias"] = dias_int
    else:
        if d1:
            redirect_args["fecha_desde"] = d1.isoformat()
        if d2:
            redirect_args["fecha_hasta"] = d2.isoformat()
    return redirect(url_for("monitor_noticias.bandeja", **redirect_args))


@bp.route("/limpiar", methods=["POST"])
def limpiar():
    if not _can_manage():
        abort(403)
    modo = _clean(request.form.get("modo"))
    q = _base_noticias()
    if modo == "descartadas":
        q = q.filter(Noticia.estado == "descartada")
    elif modo == "no_relevantes":
        q = q.filter(Noticia.estado != "relevante")
    elif modo == "todas":
        pass
    else:
        flash("Acción de limpieza no válida.", "warning")
        return redirect(url_for("monitor_noticias.bandeja"))
    n = q.delete(synchronize_session=False)
    db.session.commit()
    flash(f"Se eliminaron {n} noticia(s).", "success")
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
    if tipo not in ("google_news", "rss", "html_site"):
        tipo = "rss"
    url = _clean(request.form.get("url"))
    if not nombre:
        flash("El nombre de la fuente es obligatorio.", "warning")
        return redirect(url_for("monitor_noticias.fuentes"))
    if tipo in ("rss", "html_site") and not url:
        flash("RSS y sitios HTML necesitan una URL.", "warning")
        return redirect(url_for("monitor_noticias.fuentes"))
    if fid.isdigit():
        row = FuenteNoticia.query.filter_by(unidad_id=current_user.unidad_id, id=int(fid)).first_or_404()
    else:
        row = FuenteNoticia(unidad_id=current_user.unidad_id, creado_por=current_user.id)
        db.session.add(row)
    row.nombre = nombre[:150]
    row.tipo = tipo
    row.url = url[:500] if tipo in ("rss", "html_site") else None
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
    medio = _clean(request.args.get("medio"))
    if medio:
        q = q.filter(Noticia.medio.ilike(f"%{medio}%"))
    texto = _clean(request.args.get("q"))
    if texto:
        q = q.filter(Noticia.titulo.ilike(f"%{texto}%"))
    dias = _clean(request.args.get("dias"))
    if dias.isdigit() and int(dias) > 0:
        q = q.filter(Noticia.publicado_en >= datetime.utcnow() - timedelta(days=int(dias)))
    else:
        d1 = _parse_date(request.args.get("fecha_desde"))
        d2 = _parse_date(request.args.get("fecha_hasta"))
        if d1:
            q = q.filter(Noticia.publicado_en >= datetime(d1.year, d1.month, d1.day))
        if d2:
            q = q.filter(Noticia.publicado_en <= datetime(d2.year, d2.month, d2.day, 23, 59, 59))
    rows = q.order_by(Noticia.publicado_en.desc(), Noticia.created_at.desc()).all()

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

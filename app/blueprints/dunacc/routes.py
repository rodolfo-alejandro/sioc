"""
Módulo DUNACC: subir planillas Excel, listar/geo­rreferenciar registros y verlos en mapa.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from io import BytesIO
from urllib.parse import urlencode

from flask import (
    Response,
    abort,
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
from sqlalchemy import inspect, or_
from werkzeug.utils import secure_filename

from app.blueprints.dunacc import bp
from app.blueprints.dunacc import services
from app.extensions import db
from app.models.dunacc import (
    FUENTE_LABELS,
    DunaccComisariaAlias,
    DunaccLote,
    DunaccLoteCompartido,
    DunaccRegistro,
)
from app.models.unidad import Unidad

_schema_checked = False

_ALLOWED_EXT = {".xlsx", ".xlsm"}


def _is_superadmin() -> bool:
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _can_view() -> bool:
    return _is_superadmin() or current_user.has_permission("DUNACC_VIEW")


def _can_manage() -> bool:
    return _is_superadmin() or current_user.has_permission("DUNACC_MANAGE")


def _can_export() -> bool:
    return _is_superadmin() or current_user.has_permission("DUNACC_EXPORT")


def _clean(v) -> str:
    return v.strip() if isinstance(v, str) else ""


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


def _ensure_schema():
    global _schema_checked
    if _schema_checked:
        return
    try:
        insp = inspect(db.engine)
        existing = set(insp.get_table_names())
        for model in (DunaccLote, DunaccRegistro, DunaccLoteCompartido, DunaccComisariaAlias):
            if model.__tablename__ not in existing:
                model.__table__.create(bind=db.engine)
        # Columnas agregadas luego de la creación inicial (multi-fuente).
        nuevas_cols = {
            "dunacc_lotes": [("fuente", "VARCHAR(20) NOT NULL DEFAULT 'DUNACC'")],
            "dunacc_registros": [
                ("fuente", "VARCHAR(20) NOT NULL DEFAULT 'DUNACC'"),
                ("ddp", "VARCHAR(40)"),
                ("comisaria_norm", "VARCHAR(255)"),
            ],
            "dunacc_comisaria_alias": [
                ("ddp", "VARCHAR(40)"),
            ],
        }
        agrego_comisaria = False
        for tabla, cols in nuevas_cols.items():
            try:
                presentes = {c["name"] for c in insp.get_columns(tabla)}
            except Exception:
                presentes = set()
            for nombre, ddl in cols:
                if nombre not in presentes:
                    db.session.execute(
                        db.text(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {ddl}")
                    )
                    if nombre == "comisaria_norm":
                        agrego_comisaria = True
        db.session.commit()
        if agrego_comisaria:
            _backfill_comisaria_norm()
        _schema_checked = True
    except Exception:
        db.session.rollback()


def _backfill_comisaria_norm():
    """Calcula comisaria_norm (y DDP embebido) para los registros ya existentes."""
    try:
        rows = (
            db.session.query(DunaccRegistro)
            .filter(DunaccRegistro.comisaria_norm.is_(None), DunaccRegistro.dependencia.isnot(None))
            .all()
        )
        for r in rows:
            r.comisaria_norm = services.normalizar_comisaria(r.dependencia)[1]
            if not r.ddp and r.dependencia:
                m = re.search(r"ddp\s*n?\s*(\d+)", r.dependencia, re.IGNORECASE)
                if m:
                    r.ddp = f"DDP{m.group(1)}"
        db.session.commit()
    except Exception:
        db.session.rollback()


@bp.before_request
@login_required
def _gate():
    if not _can_view():
        abort(403)
    _ensure_schema()


def _shared_lote_ids():
    """IDs de planillas (lotes) compartidas con el área del usuario actual."""
    rows = (
        db.session.query(DunaccLoteCompartido.lote_id)
        .filter(DunaccLoteCompartido.unidad_destino_id == current_user.unidad_id)
        .all()
    )
    return [r[0] for r in rows]


def _base_registros():
    """Registros de mi área + los de planillas compartidas conmigo."""
    shared = _shared_lote_ids()
    cond = DunaccRegistro.unidad_id == current_user.unidad_id
    if shared:
        cond = or_(cond, DunaccRegistro.lote_id.in_(shared))
    return DunaccRegistro.query.filter(cond)


def _lotes_info():
    """Devuelve (lotes_info, todas_las_planillas) propias + compartidas conmigo."""
    own_lotes = (
        DunaccLote.query.filter_by(unidad_id=current_user.unidad_id)
        .order_by(DunaccLote.created_at.desc())
        .all()
    )
    shared_ids = _shared_lote_ids()
    shared_lotes = []
    if shared_ids:
        shared_lotes = (
            DunaccLote.query.filter(DunaccLote.id.in_(shared_ids))
            .order_by(DunaccLote.created_at.desc())
            .all()
        )
    share_counts = {}
    if own_lotes:
        for lid, cnt in (
            db.session.query(DunaccLoteCompartido.lote_id, db.func.count())
            .filter(DunaccLoteCompartido.lote_id.in_([l.id for l in own_lotes]))
            .group_by(DunaccLoteCompartido.lote_id)
            .all()
        ):
            share_counts[lid] = cnt
    lotes_info = [
        {"lote": l, "propio": True, "owner": None, "shares": share_counts.get(l.id, 0)}
        for l in own_lotes
    ] + [
        {"lote": l, "propio": False, "owner": (l.unidad.nombre if l.unidad else "Otra área"), "shares": 0}
        for l in shared_lotes
    ]
    return lotes_info, own_lotes + shared_lotes


def _opciones_comisaria_ddp():
    """Listas ordenadas de comisarías normalizadas y DDP accesibles para filtros."""
    shared = _shared_lote_ids()
    cond = DunaccRegistro.unidad_id == current_user.unidad_id
    if shared:
        cond = or_(cond, DunaccRegistro.lote_id.in_(shared))
    comisarias = [
        r[0]
        for r in db.session.query(DunaccRegistro.comisaria_norm)
        .filter(cond, DunaccRegistro.comisaria_norm.isnot(None))
        .distinct()
        .order_by(DunaccRegistro.comisaria_norm)
        .all()
        if r[0]
    ]
    ddps = [
        r[0]
        for r in db.session.query(DunaccRegistro.ddp)
        .filter(cond, DunaccRegistro.ddp.isnot(None))
        .distinct()
        .order_by(DunaccRegistro.ddp)
        .all()
        if r[0]
    ]
    return comisarias, ddps


def _alias_map():
    """Diccionario {origen: canonico} del catálogo de comisarías de mi área."""
    return {
        a.origen: a.canonico
        for a in DunaccComisariaAlias.query.filter_by(unidad_id=current_user.unidad_id).all()
    }


def _ddp_map():
    """Diccionario {comisaria_canonica: ddp} asignados manualmente en el catálogo."""
    return {
        a.canonico: a.ddp
        for a in DunaccComisariaAlias.query.filter(
            DunaccComisariaAlias.unidad_id == current_user.unidad_id,
            DunaccComisariaAlias.ddp.isnot(None),
        ).all()
        if a.ddp
    }


def _upload_dir(unidad_id=None) -> str:
    base_dir = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(current_app.root_path, base_dir)
    target = os.path.join(base_dir, "dunacc", str(unidad_id or current_user.unidad_id))
    os.makedirs(target, exist_ok=True)
    return target


# ---------------------- Listado ----------------------

@bp.route("/")
def listado():
    q = _base_registros()

    texto = _clean(request.args.get("q"))
    dependencia = _clean(request.args.get("dependencia"))
    comisaria = _clean(request.args.get("comisaria"))
    ddp = _clean(request.args.get("ddp"))
    caratula = _clean(request.args.get("caratula"))
    anio = _clean(request.args.get("anio"))
    geo = _clean(request.args.get("geo"))  # con | sin
    lote = _clean(request.args.get("lote"))
    fuente = _clean(request.args.get("fuente"))
    fecha_desde = _clean(request.args.get("fecha_desde"))
    fecha_hasta = _clean(request.args.get("fecha_hasta"))

    q = _aplicar_filtros(q, request.args)

    page = max(1, request.args.get("page", type=int) or 1)
    per_page = min(200, max(10, request.args.get("per_page", type=int) or 50))
    total_filtrado = q.count()
    pages = max(1, (total_filtrado + per_page - 1) // per_page)
    if page > pages:
        page = pages
    registros = (
        q.order_by(DunaccRegistro.fecha.desc(), DunaccRegistro.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    args_no_page = request.args.to_dict(flat=False)
    args_no_page.pop("page", None)
    qs_no_page = urlencode(args_no_page, doseq=True)

    total = _base_registros().count()
    sin_coords = _base_registros().filter(
        or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None))
    ).count()
    anios = [
        r[0]
        for r in db.session.query(DunaccRegistro.anio)
        .filter(DunaccRegistro.unidad_id == current_user.unidad_id, DunaccRegistro.anio.isnot(None))
        .distinct()
        .order_by(DunaccRegistro.anio.desc())
        .all()
        if r[0]
    ]
    lotes_info, all_lotes = _lotes_info()
    comisarias, ddps = _opciones_comisaria_ddp()

    return render_template(
        "dunacc/listado.html",
        registros=registros,
        total=total,
        total_filtrado=total_filtrado,
        page=page,
        per_page=per_page,
        pages=pages,
        qs_no_page=qs_no_page,
        sin_coords=sin_coords,
        con_coords=total - sin_coords,
        anios=anios,
        lotes_info=lotes_info,
        lotes=all_lotes,
        fuentes=FUENTE_LABELS,
        comisarias=comisarias,
        ddps=ddps,
        selected={
            "q": texto,
            "dependencia": dependencia,
            "comisaria": comisaria,
            "ddp": ddp,
            "caratula": caratula,
            "anio": anio,
            "geo": geo,
            "lote": lote,
            "fuente": fuente,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
        },
        can_manage=_can_manage(),
        can_export=_can_export(),
        dep_faltantes=services.dependencias_faltantes(),
    )


def _aplicar_filtros(q, args):
    """Aplica los filtros comunes (texto, dependencia, carátula, año, geo, planilla, fechas)."""
    texto = _clean(args.get("q"))
    if texto:
        like = f"%{texto}%"
        q = q.filter(or_(
            DunaccRegistro.caratula.ilike(like),
            DunaccRegistro.lugar.ilike(like),
            DunaccRegistro.dependencia.ilike(like),
            DunaccRegistro.informante.ilike(like),
            DunaccRegistro.acusado.ilike(like),
            DunaccRegistro.numero_ap.ilike(like),
            DunaccRegistro.relato.ilike(like),
        ))
    dependencia = _clean(args.get("dependencia"))
    if dependencia:
        q = q.filter(DunaccRegistro.dependencia.ilike(f"%{dependencia}%"))
    comisaria = _clean(args.get("comisaria"))
    if comisaria:
        q = q.filter(DunaccRegistro.comisaria_norm == comisaria)
    ddp = _clean(args.get("ddp"))
    if ddp:
        q = q.filter(DunaccRegistro.ddp == ddp)
    caratula = _clean(args.get("caratula"))
    if caratula:
        q = q.filter(DunaccRegistro.caratula.ilike(f"%{caratula}%"))
    anio = _clean(args.get("anio"))
    if anio.isdigit():
        q = q.filter(DunaccRegistro.anio == int(anio))
    geo = _clean(args.get("geo"))
    if geo == "con":
        q = q.filter(DunaccRegistro.lat.isnot(None), DunaccRegistro.lon.isnot(None))
    elif geo == "sin":
        q = q.filter(or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None)))
    lote = _clean(args.get("lote"))
    if lote.isdigit():
        q = q.filter(DunaccRegistro.lote_id == int(lote))
    fuente = _clean(args.get("fuente"))
    if fuente in FUENTE_LABELS:
        q = q.filter(DunaccRegistro.fuente == fuente)
    d1 = _parse_date(args.get("fecha_desde"))
    d2 = _parse_date(args.get("fecha_hasta"))
    if d1:
        q = q.filter(DunaccRegistro.fecha >= d1)
    if d2:
        q = q.filter(DunaccRegistro.fecha <= d2)
    return q


@bp.route("/patrones")
def patrones():
    registros = _aplicar_filtros(_base_registros(), request.args).all()

    dow_labels = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    mes_labels = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    dow = [0] * 7
    horas = [0] * 24
    meses = [0] * 12
    anios = {}
    deps = {}
    ddps = {}
    cars = {}
    fuentes_cnt = {}
    con_hora = 0
    con_fecha = 0
    textos = []
    for r in registros:
        if r.fecha:
            con_fecha += 1
            dow[r.fecha.weekday()] += 1
            meses[r.fecha.month - 1] += 1
        if r.anio:
            anios[r.anio] = anios.get(r.anio, 0) + 1
        h = services.hora_a_int(r.hora)
        if h is not None:
            horas[h] += 1
            con_hora += 1
        # Agrupar por comisaría normalizada (cae a la dependencia cruda si falta).
        comi = r.comisaria_norm or (r.dependencia.strip() if r.dependencia else None)
        if comi:
            deps[comi] = deps.get(comi, 0) + 1
        if r.ddp:
            ddps[r.ddp] = ddps.get(r.ddp, 0) + 1
        if r.caratula:
            c = r.caratula.strip()
            cars[c] = cars.get(c, 0) + 1
        fl = r.fuente_label
        fuentes_cnt[fl] = fuentes_cnt.get(fl, 0) + 1
        textos.append(f"{r.caratula or ''} {r.relato or ''}")

    deps_orden = sorted(deps.items(), key=lambda x: x[1], reverse=True)
    ddps_orden = sorted(ddps.items(), key=lambda x: (int(re.sub(r"\D", "", x[0]) or 0)))
    cars_orden = sorted(cars.items(), key=lambda x: x[1], reverse=True)
    anios_orden = sorted(anios.items())

    # Picos
    dia_pico = dow_labels[dow.index(max(dow))] if con_fecha else "-"
    hora_pico = f"{horas.index(max(horas)):02d}:00" if con_hora else "-"

    texto_an = services.analizar_texto(textos, top=30)

    # Listas para los filtros
    anios_filtro = [
        r[0]
        for r in db.session.query(DunaccRegistro.anio)
        .filter(DunaccRegistro.unidad_id == current_user.unidad_id, DunaccRegistro.anio.isnot(None))
        .distinct()
        .order_by(DunaccRegistro.anio.desc())
        .all()
        if r[0]
    ]
    _, all_lotes = _lotes_info()
    comisarias_filtro, ddps_filtro = _opciones_comisaria_ddp()
    fuentes_orden = sorted(fuentes_cnt.items(), key=lambda x: x[1], reverse=True)

    charts = {
        "dow": {"labels": dow_labels, "values": dow},
        "horas": {"labels": [f"{h:02d}" for h in range(24)], "values": horas},
        "meses": {"labels": mes_labels, "values": meses},
        "anios": {"labels": [str(a) for a, _ in anios_orden], "values": [c for _, c in anios_orden]},
        "deps": {"labels": [d for d, _ in deps_orden[:20]], "values": [c for _, c in deps_orden[:20]]},
        "ddps": {"labels": [d for d, _ in ddps_orden], "values": [n for _, n in ddps_orden]},
        "cars": {"labels": [c for c, _ in cars_orden[:15]], "values": [n for _, n in cars_orden[:15]]},
        "fuentes": {"labels": [f for f, _ in fuentes_orden], "values": [n for _, n in fuentes_orden]},
    }

    return render_template(
        "dunacc/patrones.html",
        charts=charts,
        deps_tabla=deps_orden,
        texto=texto_an,
        total=len(registros),
        dia_pico=dia_pico,
        hora_pico=hora_pico,
        n_dependencias=len(deps),
        anios=anios_filtro,
        lotes=all_lotes,
        fuentes=FUENTE_LABELS,
        comisarias=comisarias_filtro,
        ddps_opts=ddps_filtro,
        selected={
            "q": _clean(request.args.get("q")),
            "dependencia": _clean(request.args.get("dependencia")),
            "comisaria": _clean(request.args.get("comisaria")),
            "ddp": _clean(request.args.get("ddp")),
            "caratula": _clean(request.args.get("caratula")),
            "anio": _clean(request.args.get("anio")),
            "geo": _clean(request.args.get("geo")),
            "lote": _clean(request.args.get("lote")),
            "fuente": _clean(request.args.get("fuente")),
            "fecha_desde": _clean(request.args.get("fecha_desde")),
            "fecha_hasta": _clean(request.args.get("fecha_hasta")),
        },
    )


@bp.route("/planillas")
def planillas():
    lotes_info, _ = _lotes_info()
    return render_template(
        "dunacc/planillas.html",
        lotes_info=lotes_info,
        can_manage=_can_manage(),
    )


# ---------------------- Catálogo de comisarías ----------------------

@bp.route("/comisarias")
def comisarias():
    rows = (
        db.session.query(
            DunaccRegistro.comisaria_norm,
            db.func.count(DunaccRegistro.id),
        )
        .filter(
            DunaccRegistro.unidad_id == current_user.unidad_id,
            DunaccRegistro.comisaria_norm.isnot(None),
        )
        .group_by(DunaccRegistro.comisaria_norm)
        .order_by(DunaccRegistro.comisaria_norm)
        .all()
    )
    # Variantes crudas (dependencia) y DDPs por cada comisaría normalizada.
    variantes = {}
    ddps_comi = {}
    for norm, dep, ddp in (
        db.session.query(
            DunaccRegistro.comisaria_norm, DunaccRegistro.dependencia, DunaccRegistro.ddp
        )
        .filter(
            DunaccRegistro.unidad_id == current_user.unidad_id,
            DunaccRegistro.comisaria_norm.isnot(None),
        )
        .distinct()
        .all()
    ):
        if dep:
            variantes.setdefault(norm, set()).add(dep)
        if ddp:
            ddps_comi.setdefault(norm, set()).add(ddp)
    comis = [
        {
            "nombre": norm,
            "registros": n,
            "variantes": sorted(variantes.get(norm, [])),
            "ddps": sorted(ddps_comi.get(norm, [])),
        }
        for norm, n in rows
    ]
    return render_template(
        "dunacc/comisarias.html",
        comisarias=comis,
        nombres=[c["nombre"] for c in comis],
        can_manage=_can_manage(),
    )


@bp.route("/comisarias/fusionar", methods=["POST"])
def comisarias_fusionar():
    if not _can_manage():
        abort(403)
    origenes = [o for o in request.form.getlist("origenes") if _clean(o)]
    destino = _clean(request.form.get("destino"))
    if not origenes or not destino:
        flash("Elegí al menos una comisaría de origen y un nombre destino.", "warning")
        return redirect(url_for("dunacc.comisarias"))

    actualizados = 0
    for origen in origenes:
        if origen == destino:
            continue
        n = (
            DunaccRegistro.query.filter(
                DunaccRegistro.unidad_id == current_user.unidad_id,
                DunaccRegistro.comisaria_norm == origen,
            ).update({"comisaria_norm": destino}, synchronize_session=False)
        )
        actualizados += n
        # Guardar/actualizar el alias para futuras importaciones.
        alias = DunaccComisariaAlias.query.filter_by(
            unidad_id=current_user.unidad_id, origen=origen
        ).first()
        if alias:
            alias.canonico = destino
        else:
            db.session.add(DunaccComisariaAlias(
                unidad_id=current_user.unidad_id, origen=origen, canonico=destino
            ))
        # Reapuntar alias previos que apuntaban al origen ahora renombrado.
        DunaccComisariaAlias.query.filter_by(
            unidad_id=current_user.unidad_id, canonico=origen
        ).update({"canonico": destino}, synchronize_session=False)
    db.session.commit()
    flash(f"{actualizados} registro(s) reasignado(s) a «{destino}».", "success")
    return redirect(url_for("dunacc.comisarias"))


@bp.route("/comisarias/asignar-ddp", methods=["POST"])
def comisarias_ddp():
    if not _can_manage():
        abort(403)
    origenes = [o for o in request.form.getlist("origenes") if _clean(o)]
    ddp_raw = _clean(request.form.get("ddp"))
    if not origenes or not ddp_raw:
        flash("Elegí al menos una comisaría y un DDP.", "warning")
        return redirect(url_for("dunacc.comisarias"))
    # Normalizar el DDP a formato "DDP<n>".
    m = re.search(r"(\d+)", ddp_raw)
    ddp = f"DDP{m.group(1)}" if m else ddp_raw.upper().replace(" ", "")

    actualizados = 0
    for nombre in origenes:
        n = (
            DunaccRegistro.query.filter(
                DunaccRegistro.unidad_id == current_user.unidad_id,
                DunaccRegistro.comisaria_norm == nombre,
            ).update({"ddp": ddp}, synchronize_session=False)
        )
        actualizados += n
        # Persistir el DDP para futuras importaciones (alias canónico = mismo nombre).
        alias = DunaccComisariaAlias.query.filter_by(
            unidad_id=current_user.unidad_id, origen=nombre
        ).first()
        if alias:
            alias.ddp = ddp
            if not alias.canonico:
                alias.canonico = nombre
        else:
            db.session.add(DunaccComisariaAlias(
                unidad_id=current_user.unidad_id, origen=nombre, canonico=nombre, ddp=ddp
            ))
    db.session.commit()
    flash(f"{ddp} asignado a {len(origenes)} comisaría(s) ({actualizados} registro(s)).", "success")
    return redirect(url_for("dunacc.comisarias"))


# ---------------------- Coincidencias DUNACC <-> 911 ----------------------

@bp.route("/coincidencias")
def coincidencias():
    dias_tol = min(7, max(0, request.args.get("dias", type=int) if request.args.get("dias") is not None else 1))
    umbral_pct = min(80, max(5, request.args.get("umbral", type=int) or 18))
    fecha_desde = _clean(request.args.get("fecha_desde"))
    fecha_hasta = _clean(request.args.get("fecha_hasta"))

    base = _base_registros()
    d1 = _parse_date(fecha_desde)
    d2 = _parse_date(fecha_hasta)
    if d1:
        base = base.filter(DunaccRegistro.fecha >= d1)
    if d2:
        base = base.filter(DunaccRegistro.fecha <= d2)

    dunacc_regs = base.filter(DunaccRegistro.fuente == "DUNACC").all()
    cco_regs = base.filter(DunaccRegistro.fuente == "CCO911").all()

    pares = services.buscar_coincidencias(
        dunacc_regs, cco_regs, dias_tol=dias_tol, umbral=umbral_pct / 100.0
    )

    return render_template(
        "dunacc/coincidencias.html",
        pares=pares,
        n_dunacc=len(dunacc_regs),
        n_cco=len(cco_regs),
        selected={
            "dias": dias_tol,
            "umbral": umbral_pct,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
        },
    )


# ---------------------- Subir / importar ----------------------

@bp.route("/subir", methods=["GET", "POST"])
def subir():
    if not _can_manage():
        abort(403)

    if request.method == "GET":
        return render_template(
            "dunacc/subir.html",
            dep_faltantes=services.dependencias_faltantes(),
        )

    faltan = services.dependencias_faltantes()
    if faltan:
        flash(f"Faltan dependencias en el servidor: {', '.join(faltan)}.", "danger")
        return redirect(url_for("dunacc.subir"))

    f = request.files.get("archivo")
    if not f or not f.filename:
        flash("Seleccioná un archivo Excel.", "warning")
        return redirect(url_for("dunacc.subir"))

    nombre_original = f.filename
    ext = os.path.splitext(secure_filename(nombre_original) or "x")[1].lower()
    if ext not in _ALLOWED_EXT:
        flash("Formato no permitido. Subí un archivo .xlsx.", "warning")
        return redirect(url_for("dunacc.subir"))

    omitir_dup = request.form.get("omitir_duplicados") == "1"

    # Guardar archivo en disco.
    safe = secure_filename(nombre_original) or "planilla.xlsx"
    stored = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe}"
    path = os.path.join(_upload_dir(), stored)
    f.save(path)

    sha1 = hashlib.sha1()
    with open(path, "rb") as rf:
        for chunk in iter(lambda: rf.read(8192), b""):
            sha1.update(chunk)

    try:
        registros, advertencias = services.importar_excel(path)
    except Exception as e:
        try:
            os.remove(path)
        except Exception:
            pass
        flash(f"No se pudo leer el Excel: {e}", "danger")
        return redirect(url_for("dunacc.subir"))

    if not registros:
        try:
            os.remove(path)
        except Exception:
            pass
        msg = "No se detectaron filas para importar."
        if advertencias:
            msg += " " + " ".join(advertencias)
        flash(msg, "warning")
        return redirect(url_for("dunacc.subir"))

    # Aplicar catálogo de comisarías (fusiones manuales) a los nombres normalizados.
    alias = _alias_map()
    if alias:
        for reg in registros:
            cn = reg.get("comisaria_norm")
            if cn and cn in alias:
                reg["comisaria_norm"] = alias[cn]
    # Aplicar DDP asignado manualmente a cada comisaría (si la fila no trae DDP).
    ddp_por_comisaria = _ddp_map()
    if ddp_por_comisaria:
        for reg in registros:
            if not reg.get("ddp"):
                cn = reg.get("comisaria_norm")
                if cn and cn in ddp_por_comisaria:
                    reg["ddp"] = ddp_por_comisaria[cn]

    # Fuente predominante de la planilla (DUNACC denuncias o CCO911 llamadas).
    fuentes = [r.get("fuente") for r in registros if r.get("fuente")]
    fuente_lote = max(set(fuentes), key=fuentes.count) if fuentes else "DUNACC"

    lote = DunaccLote(
        unidad_id=current_user.unidad_id,
        user_id=current_user.id,
        nombre_archivo=stored,
        nombre_original=nombre_original[:255],
        sha1=sha1.hexdigest(),
        size_bytes=os.path.getsize(path),
        total_registros=0,
        fuente=fuente_lote,
    )
    db.session.add(lote)
    db.session.flush()

    nuevos = 0
    duplicados = 0
    existentes = set()
    if omitir_dup:
        existentes = {
            h[0]
            for h in db.session.query(DunaccRegistro.dedupe_hash)
            .filter(DunaccRegistro.unidad_id == current_user.unidad_id)
            .all()
            if h[0]
        }

    vistos_en_lote = set()
    for reg in registros:
        h = reg.get("dedupe_hash")
        if omitir_dup and h and (h in existentes or h in vistos_en_lote):
            duplicados += 1
            continue
        if h:
            vistos_en_lote.add(h)
        db.session.add(DunaccRegistro(
            unidad_id=current_user.unidad_id,
            lote_id=lote.id,
            user_id=current_user.id,
            fuente=reg.get("fuente") or fuente_lote,
            numero=reg.get("numero"),
            numero_ap=reg.get("numero_ap"),
            dependencia=reg.get("dependencia"),
            comisaria_norm=reg.get("comisaria_norm"),
            ddp=reg.get("ddp"),
            caratula=reg.get("caratula"),
            fecha=reg.get("fecha"),
            hora=reg.get("hora"),
            lugar=reg.get("lugar"),
            informante=reg.get("informante"),
            acusado=reg.get("acusado"),
            relato=reg.get("relato"),
            anio=reg.get("anio"),
            lat=reg.get("lat"),
            lon=reg.get("lon"),
            geo_origen=reg.get("geo_origen"),
            dedupe_hash=h,
        ))
        nuevos += 1

    lote.total_registros = nuevos
    db.session.commit()

    sin_coords = sum(1 for reg in registros if reg.get("lat") is None or reg.get("lon") is None)
    partes = [f"{nuevos} registro(s) importado(s)"]
    if duplicados:
        partes.append(f"{duplicados} duplicado(s) omitido(s)")
    if sin_coords:
        partes.append(f"{sin_coords} sin coordenadas (cargalas desde el listado)")
    flash(". ".join(partes) + ".", "success")
    for adv in advertencias:
        flash(adv, "info")
    return redirect(url_for("dunacc.listado", geo="sin" if sin_coords else None))


# ---------------------- Coordenadas ----------------------

@bp.route("/registro/<int:registro_id>")
def registro_detalle(registro_id: int):
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()
    return render_template("dunacc/detalle.html", reg=reg, can_manage=_can_manage())


@bp.route("/registro/<int:registro_id>/coords", methods=["GET", "POST"])
def registro_coords(registro_id: int):
    if not _can_manage():
        abort(403)
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()

    if request.method == "GET":
        # Sugerencia inicial para el mapa: registros vecinos ya geolocalizados.
        ref = _base_registros().filter(
            DunaccRegistro.lat.isnot(None), DunaccRegistro.lon.isnot(None)
        ).first()
        centro = {"lat": ref.lat, "lon": ref.lon} if ref else {"lat": -24.7859, "lon": -65.4114}
        return render_template("dunacc/coords.html", reg=reg, centro=centro)

    lat = services._parse_float(request.form.get("lat"))
    lon = services._parse_float(request.form.get("lon"))
    if lat is None or lon is None:
        # Permite pegar "lat, lon" en un solo campo.
        lat, lon = services._parse_coords(request.form.get("coords"))
    if not services._coords_validas(lat, lon):
        flash("Coordenadas inválidas. Revisá latitud y longitud.", "warning")
        return redirect(url_for("dunacc.registro_coords", registro_id=reg.id))

    reg.lat = lat
    reg.lon = lon
    reg.geo_origen = _clean(request.form.get("origen")) or "manual"
    db.session.commit()
    flash("Coordenadas guardadas.", "success")
    siguiente = request.form.get("siguiente") == "1"
    if siguiente:
        prox = _base_registros().filter(
            or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None))
        ).order_by(DunaccRegistro.fecha.desc()).first()
        if prox:
            return redirect(url_for("dunacc.registro_coords", registro_id=prox.id))
        flash("¡No quedan registros sin coordenadas!", "info")
    return redirect(url_for("dunacc.listado"))


@bp.route("/registro/<int:registro_id>/quitar-coords", methods=["POST"])
def registro_quitar_coords(registro_id: int):
    if not _can_manage():
        abort(403)
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()
    reg.lat = None
    reg.lon = None
    reg.geo_origen = None
    db.session.commit()
    flash("Coordenadas quitadas.", "success")
    return redirect(request.referrer or url_for("dunacc.listado"))


@bp.route("/registro/<int:registro_id>/eliminar", methods=["POST"])
def registro_eliminar(registro_id: int):
    if not _can_manage():
        abort(403)
    reg = _base_registros().filter(DunaccRegistro.id == registro_id).first_or_404()
    if reg.unidad_id != current_user.unidad_id:
        flash("Solo el área dueña de la planilla puede eliminar registros.", "warning")
        return redirect(request.referrer or url_for("dunacc.listado"))
    db.session.delete(reg)
    db.session.commit()
    flash("Registro eliminado.", "success")
    return redirect(request.referrer or url_for("dunacc.listado"))


@bp.route("/api/geocodificar")
def api_geocodificar():
    if not _can_manage():
        return jsonify({"ok": False, "error": "sin_permiso"}), 403
    consulta = _clean(request.args.get("q"))
    if not consulta:
        return jsonify({"ok": False, "error": "consulta_vacia"}), 400
    res = services.geocodificar(consulta)
    if not res:
        return jsonify({"ok": False, "error": "sin_resultados"}), 404
    return jsonify({"ok": True, **res})


# ---------------------- Mapa ----------------------

@bp.route("/mapa")
def mapa():
    q = _base_registros().filter(
        DunaccRegistro.lat.isnot(None), DunaccRegistro.lon.isnot(None)
    )
    q = _aplicar_filtros(q, request.args)
    anio = _clean(request.args.get("anio"))
    dependencia = _clean(request.args.get("dependencia"))
    comisaria = _clean(request.args.get("comisaria"))
    ddp = _clean(request.args.get("ddp"))
    caratula = _clean(request.args.get("caratula"))
    lote = _clean(request.args.get("lote"))
    fuente = _clean(request.args.get("fuente"))

    puntos = []
    for r in q.limit(3000).all():
        puntos.append({
            "id": r.id,
            "lat": r.lat,
            "lng": r.lon,
            "fuente": r.fuente or "DUNACC",
            "fuente_label": r.fuente_label,
            "caratula": r.caratula or "-",
            "fecha": r.fecha.strftime("%d/%m/%Y") if r.fecha else "-",
            "dependencia": r.dependencia or "-",
            "lugar": (r.lugar or "-")[:200],
            "numero_ap": r.numero_ap or "-",
        })

    anios = [
        r[0]
        for r in db.session.query(DunaccRegistro.anio)
        .filter(DunaccRegistro.unidad_id == current_user.unidad_id, DunaccRegistro.anio.isnot(None))
        .distinct()
        .order_by(DunaccRegistro.anio.desc())
        .all()
        if r[0]
    ]
    sin_coords = _base_registros().filter(
        or_(DunaccRegistro.lat.is_(None), DunaccRegistro.lon.is_(None))
    ).count()
    shared_ids = _shared_lote_ids()
    lote_cond = DunaccLote.unidad_id == current_user.unidad_id
    if shared_ids:
        lote_cond = or_(lote_cond, DunaccLote.id.in_(shared_ids))
    lotes = DunaccLote.query.filter(lote_cond).order_by(DunaccLote.created_at.desc()).all()
    comisarias, ddps = _opciones_comisaria_ddp()

    return render_template(
        "dunacc/mapa.html",
        puntos=puntos,
        anios=anios,
        lotes=lotes,
        fuentes=FUENTE_LABELS,
        comisarias=comisarias,
        ddps=ddps,
        sin_coords=sin_coords,
        selected={
            "anio": anio,
            "dependencia": dependencia,
            "comisaria": comisaria,
            "ddp": ddp,
            "caratula": caratula,
            "lote": lote,
            "fuente": fuente,
        },
    )


# ---------------------- Lotes (archivos) ----------------------

def _lote_accesible(lote_id: int):
    """Devuelve el lote si es de mi área o está compartido conmigo; si no, 404."""
    lote = DunaccLote.query.filter_by(id=lote_id).first_or_404()
    if lote.unidad_id == current_user.unidad_id:
        return lote
    if lote.id in _shared_lote_ids():
        return lote
    abort(404)


@bp.route("/lote/<int:lote_id>/descargar")
def lote_descargar(lote_id: int):
    lote = _lote_accesible(lote_id)
    path = os.path.join(_upload_dir(lote.unidad_id), lote.nombre_archivo)
    if not os.path.exists(path):
        flash("El archivo original ya no está disponible en el servidor.", "warning")
        return redirect(url_for("dunacc.listado"))
    return send_file(path, as_attachment=True, download_name=lote.nombre_original or lote.nombre_archivo)


@bp.route("/lote/<int:lote_id>/compartir", methods=["GET", "POST"])
def lote_compartir(lote_id: int):
    if not _can_manage():
        abort(403)
    lote = DunaccLote.query.filter_by(id=lote_id, unidad_id=current_user.unidad_id).first_or_404()

    if request.method == "POST":
        seleccionadas = {
            int(x) for x in request.form.getlist("unidades") if str(x).isdigit()
        }
        seleccionadas.discard(current_user.unidad_id)
        actuales = {
            c.unidad_destino_id: c
            for c in DunaccLoteCompartido.query.filter_by(lote_id=lote.id).all()
        }
        # Agregar nuevas
        for uid in seleccionadas - set(actuales):
            db.session.add(DunaccLoteCompartido(
                lote_id=lote.id,
                unidad_destino_id=uid,
                compartido_por=current_user.id,
            ))
        # Quitar las que ya no están
        for uid in set(actuales) - seleccionadas:
            db.session.delete(actuales[uid])
        db.session.commit()
        flash("Compartición actualizada.", "success")
        return redirect(url_for("dunacc.listado"))

    unidades = (
        Unidad.query.filter(Unidad.activo.is_(True), Unidad.id != current_user.unidad_id)
        .order_by(Unidad.nombre)
        .all()
    )
    compartidas = {
        c.unidad_destino_id for c in DunaccLoteCompartido.query.filter_by(lote_id=lote.id).all()
    }
    return render_template(
        "dunacc/compartir.html",
        lote=lote,
        unidades=unidades,
        compartidas=compartidas,
    )


@bp.route("/lote/<int:lote_id>/eliminar", methods=["POST"])
def lote_eliminar(lote_id: int):
    if not _can_manage():
        abort(403)
    lote = DunaccLote.query.filter_by(id=lote_id, unidad_id=current_user.unidad_id).first_or_404()
    borrar_registros = request.form.get("borrar_registros") == "1"
    if borrar_registros:
        DunaccRegistro.query.filter_by(lote_id=lote.id, unidad_id=current_user.unidad_id).delete(
            synchronize_session=False
        )
    else:
        DunaccRegistro.query.filter_by(lote_id=lote.id, unidad_id=current_user.unidad_id).update(
            {DunaccRegistro.lote_id: None}, synchronize_session=False
        )
    try:
        path = os.path.join(_upload_dir(), lote.nombre_archivo)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    db.session.delete(lote)
    db.session.commit()
    flash("Lote eliminado." + (" Sus registros también se eliminaron." if borrar_registros else " Los registros se conservaron."), "success")
    return redirect(url_for("dunacc.listado"))


# ---------------------- Export ----------------------

@bp.route("/export.xlsx")
def export_xlsx():
    if not _can_export():
        abort(403)
    import openpyxl

    q = _aplicar_filtros(_base_registros(), request.args)

    rows = q.order_by(DunaccRegistro.fecha.desc(), DunaccRegistro.created_at.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DUNACC"
    ws.append([
        "Fuente", "N°", "N° AP", "Dependencia", "DDP", "Carátula", "Fecha", "Hora", "Lugar",
        "Informante", "Acusado", "Breve relato", "Latitud", "Longitud", "Año",
    ])
    for r in rows:
        ws.append([
            r.fuente_label,
            r.numero or "",
            r.numero_ap or "",
            r.dependencia or "",
            r.ddp or "",
            r.caratula or "",
            r.fecha.strftime("%d/%m/%Y") if r.fecha else "",
            r.hora or "",
            r.lugar or "",
            r.informante or "",
            r.acusado or "",
            r.relato or "",
            r.lat if r.lat is not None else "",
            r.lon if r.lon is not None else "",
            r.anio or "",
        ])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    fname = f"dunacc_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        bio.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

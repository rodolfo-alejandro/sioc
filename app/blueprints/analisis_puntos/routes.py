import hashlib
import json
import os
from datetime import datetime

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text
from sqlalchemy.sql import and_, exists, or_
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app.blueprints.analisis_puntos import bp
from app.blueprints.analisis_puntos.services import procesar_fuente_voz, procesar_fuente_gprs
from app.extensions import db
from app.models.analisis_puntos import (
    AnalisisPuntoCaso,
    AnalisisPuntoCasoCompartido,
    AnalisisPuntoCasoMapaPunto,
    AnalisisPuntoCelda,
    AnalisisPuntoEvento,
    AnalisisPuntoFuente,
    AnalisisPuntoCasoSujeto,
    AnalisisPuntoCasoNumero,
    AnalisisPuntoTitular,
)
from app.models.sabana_llamadas import CargaLlamada, Sujeto, SujetoNumero


_ap_schema_checked = False


def _migrate_legacy_caso_fuentes_notas():
    """Copia notas desde ap_caso_fuentes hacia ap_fuentes.relaciones_nota (idempotente)."""
    try:
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        if "ap_fuentes" not in tables or "ap_caso_fuentes" not in tables:
            return
        cols = {c.get("name") for c in insp.get_columns("ap_fuentes")}
        if "relaciones_nota" not in cols:
            return
        db.session.execute(
            text(
                """
                UPDATE ap_fuentes f
                INNER JOIN ap_caso_fuentes cf ON cf.fuente_id = f.id
                SET f.relaciones_nota = LEFT(TRIM(cf.nota), 500)
                WHERE (f.relaciones_nota IS NULL OR f.relaciones_nota = '')
                  AND cf.nota IS NOT NULL
                  AND CHAR_LENGTH(TRIM(cf.nota)) > 0
                """
            )
        )
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _permiso():
    return current_user.has_permission("SABANA_LLAMADAS_VIEW") or current_user.has_permission("SABANA_LLAMADAS_UPLOAD")


def _is_superadmin():
    try:
        return current_user.has_role("SUPERADMIN")
    except Exception:
        return False


def _caso_access_predicate():
    if _is_superadmin():
        return True
    owned = (AnalisisPuntoCaso.user_id == current_user.id)
    shared_case = exists().where(and_(
        AnalisisPuntoCasoCompartido.caso_id == AnalisisPuntoCaso.id,
        AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
    ))
    return or_(owned, shared_case)


def _casos_query_accessible():
    q = AnalisisPuntoCaso.query.filter(AnalisisPuntoCaso.unidad_id == current_user.unidad_id)
    pred = _caso_access_predicate()
    if pred is not True:
        q = q.filter(pred)
    return q


def _fuentes_query_accessible():
    q = AnalisisPuntoFuente.query.filter(AnalisisPuntoFuente.unidad_id == current_user.unidad_id)
    if _is_superadmin():
        return q
    shared_case = exists().where(and_(
        AnalisisPuntoCasoCompartido.caso_id == AnalisisPuntoFuente.caso_id,
        AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
    ))
    return q.filter(or_(AnalisisPuntoFuente.user_id == current_user.id, shared_case))


def _parse_fuente_processing_detail(fuente):
    """
    error_detail puede ser:
    - JSON con {"processing_summary": {...}} tras procesamiento OK
    - texto plano si hubo excepción al procesar
    """
    raw = fuente.error_detail
    if not raw or not str(raw).strip():
        return None, None
    s = str(raw).strip()
    try:
        j = json.loads(s)
        if isinstance(j, dict) and j.get("processing_summary"):
            return j.get("processing_summary"), None
    except Exception:
        pass
    return None, s


def _ensure_analisis_schema():
    global _ap_schema_checked
    if _ap_schema_checked:
        return
    try:
        insp = inspect(db.engine)
        if "ap_casos" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_casos (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    unidad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    codigo VARCHAR(64) NOT NULL,
                    titulo VARCHAR(255) NOT NULL,
                    descripcion TEXT NULL,
                    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_casos_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT fk_ap_casos_user FOREIGN KEY (user_id) REFERENCES users(id),
                    CONSTRAINT uq_ap_casos_unidad_codigo UNIQUE (unidad_id, codigo)
                )
            """))
        if "ap_fuentes" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_fuentes (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    caso_id INTEGER NOT NULL,
                    unidad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    source_type VARCHAR(20) NOT NULL,
                    operadora VARCHAR(30) NULL,
                    nombre_archivo VARCHAR(255) NOT NULL,
                    sha256 VARCHAR(128) NULL,
                    mime_type VARCHAR(120) NULL,
                    size_bytes INTEGER NULL,
                    date_from DATETIME NULL,
                    date_to DATETIME NULL,
                    upload_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    error_detail TEXT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_fuentes_caso FOREIGN KEY (caso_id) REFERENCES ap_casos(id),
                    CONSTRAINT fk_ap_fuentes_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT fk_ap_fuentes_user FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
        else:
            try:
                cols = {c.get("name") for c in insp.get_columns("ap_fuentes")}
                if "operadora" not in cols:
                    db.session.execute(text("ALTER TABLE ap_fuentes ADD COLUMN operadora VARCHAR(30) NULL"))
                if "relaciones_nota" not in cols:
                    db.session.execute(text("ALTER TABLE ap_fuentes ADD COLUMN relaciones_nota VARCHAR(500) NULL"))
            except Exception:
                pass
        if "ap_celdas" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_celdas (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    unidad_id INTEGER NOT NULL,
                    cell_code VARCHAR(100) NOT NULL,
                    address VARCHAR(255) NULL,
                    locality VARCHAR(200) NULL,
                    province VARCHAR(200) NULL,
                    lat FLOAT NULL,
                    lon FLOAT NULL,
                    coverage_radius_m INTEGER NULL,
                    azimuth_deg INTEGER NULL,
                    aperture_h_deg INTEGER NULL,
                    aperture_v_deg INTEGER NULL,
                    metadata_json TEXT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_celdas_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT uq_ap_celdas_unidad_code UNIQUE (unidad_id, cell_code)
                )
            """))
        if "ap_eventos" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_eventos (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    caso_id INTEGER NOT NULL,
                    fuente_id INTEGER NOT NULL,
                    unidad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    source_type VARCHAR(20) NOT NULL,
                    event_dt DATETIME NULL,
                    event_date VARCHAR(10) NULL,
                    event_hour VARCHAR(2) NULL,
                    origin_msisdn VARCHAR(64) NULL,
                    target_msisdn VARCHAR(64) NULL,
                    imei VARCHAR(64) NULL,
                    imsi VARCHAR(64) NULL,
                    event_type VARCHAR(50) NULL,
                    duration_sec INTEGER NULL,
                    bytes_up BIGINT NULL,
                    bytes_down BIGINT NULL,
                    cell_id INTEGER NULL,
                    raw_cell_code VARCHAR(100) NULL,
                    distance_to_cell_m INTEGER NULL,
                    inside_filter_radius BOOLEAN NULL,
                    raw_payload_json TEXT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_eventos_caso FOREIGN KEY (caso_id) REFERENCES ap_casos(id),
                    CONSTRAINT fk_ap_eventos_fuente FOREIGN KEY (fuente_id) REFERENCES ap_fuentes(id),
                    CONSTRAINT fk_ap_eventos_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT fk_ap_eventos_user FOREIGN KEY (user_id) REFERENCES users(id),
                    CONSTRAINT fk_ap_eventos_celda FOREIGN KEY (cell_id) REFERENCES ap_celdas(id)
                )
            """))
        if "ap_titulares" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_titulares (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    caso_id INTEGER NOT NULL,
                    fuente_id INTEGER NULL,
                    unidad_id INTEGER NOT NULL,
                    msisdn VARCHAR(64) NOT NULL,
                    holder_name VARCHAR(255) NULL,
                    doc_number VARCHAR(64) NULL,
                    service_type VARCHAR(100) NULL,
                    market_type VARCHAR(100) NULL,
                    billing_address VARCHAR(255) NULL,
                    contact_phone VARCHAR(64) NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_titulares_caso FOREIGN KEY (caso_id) REFERENCES ap_casos(id),
                    CONSTRAINT fk_ap_titulares_fuente FOREIGN KEY (fuente_id) REFERENCES ap_fuentes(id),
                    CONSTRAINT fk_ap_titulares_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT uq_ap_titulares_caso_msisdn UNIQUE (caso_id, msisdn)
                )
            """))
        if "ap_caso_sujetos" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_caso_sujetos (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    caso_id INTEGER NOT NULL,
                    sujeto_id INTEGER NOT NULL,
                    unidad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    nota VARCHAR(255) NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_caso_sujetos_caso FOREIGN KEY (caso_id) REFERENCES ap_casos(id),
                    CONSTRAINT fk_ap_caso_sujetos_sujeto FOREIGN KEY (sujeto_id) REFERENCES sabana_sujetos(id),
                    CONSTRAINT fk_ap_caso_sujetos_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT fk_ap_caso_sujetos_user FOREIGN KEY (user_id) REFERENCES users(id),
                    CONSTRAINT uq_ap_caso_sujetos UNIQUE (caso_id, sujeto_id)
                )
            """))
        if "ap_caso_fuentes" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_caso_fuentes (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    caso_id INTEGER NOT NULL,
                    fuente_id INTEGER NOT NULL,
                    unidad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    nota VARCHAR(255) NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_caso_fuentes_caso FOREIGN KEY (caso_id) REFERENCES ap_casos(id),
                    CONSTRAINT fk_ap_caso_fuentes_fuente FOREIGN KEY (fuente_id) REFERENCES ap_fuentes(id),
                    CONSTRAINT fk_ap_caso_fuentes_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT fk_ap_caso_fuentes_user FOREIGN KEY (user_id) REFERENCES users(id),
                    CONSTRAINT uq_ap_caso_fuentes UNIQUE (caso_id, fuente_id)
                )
            """))
        if "ap_caso_numeros" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_caso_numeros (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    caso_id INTEGER NOT NULL,
                    unidad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    msisdn VARCHAR(64) NOT NULL,
                    sujeto_id INTEGER NULL,
                    fuente_id INTEGER NULL,
                    nota VARCHAR(255) NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_caso_numeros_caso FOREIGN KEY (caso_id) REFERENCES ap_casos(id),
                    CONSTRAINT fk_ap_caso_numeros_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT fk_ap_caso_numeros_user FOREIGN KEY (user_id) REFERENCES users(id),
                    CONSTRAINT fk_ap_caso_numeros_sujeto FOREIGN KEY (sujeto_id) REFERENCES sabana_sujetos(id),
                    CONSTRAINT fk_ap_caso_numeros_fuente FOREIGN KEY (fuente_id) REFERENCES ap_fuentes(id),
                    CONSTRAINT uq_ap_caso_numeros UNIQUE (caso_id, msisdn, sujeto_id, fuente_id)
                )
            """))
        if "ap_caso_mapa_puntos" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_caso_mapa_puntos (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    caso_id INTEGER NOT NULL,
                    unidad_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    lat DOUBLE NOT NULL,
                    lon DOUBLE NOT NULL,
                    tipo VARCHAR(40) NOT NULL,
                    etiqueta VARCHAR(120) NULL,
                    nota TEXT NULL,
                    origen_contexto VARCHAR(20) NULL,
                    icono VARCHAR(40) NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    CONSTRAINT fk_ap_cmap_puntos_caso FOREIGN KEY (caso_id) REFERENCES ap_casos(id),
                    CONSTRAINT fk_ap_cmap_puntos_unidad FOREIGN KEY (unidad_id) REFERENCES unidades(id),
                    CONSTRAINT fk_ap_cmap_puntos_user FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
        if "ap_casos_compartidos" not in insp.get_table_names():
            db.session.execute(text("""
                CREATE TABLE ap_casos_compartidos (
                    caso_id INTEGER NOT NULL,
                    shared_with_user_id INTEGER NOT NULL,
                    shared_by_user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    PRIMARY KEY (caso_id, shared_with_user_id)
                )
            """))

        # Indexes de lookup frecuentes
        def ensure_index(table_name, index_name, ddl):
            try:
                idxs = insp.get_indexes(table_name)
                if any((ix.get("name") or "").lower() == index_name.lower() for ix in idxs):
                    return
            except Exception:
                return
            db.session.execute(text(ddl))

        ensure_index("ap_fuentes", "idx_ap_fuentes_caso", "CREATE INDEX idx_ap_fuentes_caso ON ap_fuentes(caso_id)")
        ensure_index("ap_eventos", "idx_ap_eventos_caso_dt", "CREATE INDEX idx_ap_eventos_caso_dt ON ap_eventos(caso_id, event_dt)")
        ensure_index("ap_eventos", "idx_ap_eventos_caso_origin", "CREATE INDEX idx_ap_eventos_caso_origin ON ap_eventos(caso_id, origin_msisdn)")
        ensure_index("ap_eventos", "idx_ap_eventos_caso_target", "CREATE INDEX idx_ap_eventos_caso_target ON ap_eventos(caso_id, target_msisdn)")
        ensure_index("ap_eventos", "idx_ap_eventos_caso_cell", "CREATE INDEX idx_ap_eventos_caso_cell ON ap_eventos(caso_id, cell_id)")
        ensure_index("ap_caso_sujetos", "idx_ap_caso_sujetos_caso", "CREATE INDEX idx_ap_caso_sujetos_caso ON ap_caso_sujetos(caso_id)")
        ensure_index("ap_caso_sujetos", "idx_ap_caso_sujetos_sujeto", "CREATE INDEX idx_ap_caso_sujetos_sujeto ON ap_caso_sujetos(sujeto_id)")
        ensure_index("ap_caso_fuentes", "idx_ap_caso_fuentes_caso", "CREATE INDEX idx_ap_caso_fuentes_caso ON ap_caso_fuentes(caso_id)")
        ensure_index("ap_caso_numeros", "idx_ap_caso_numeros_caso", "CREATE INDEX idx_ap_caso_numeros_caso ON ap_caso_numeros(caso_id)")
        ensure_index("ap_caso_numeros", "idx_ap_caso_numeros_msisdn", "CREATE INDEX idx_ap_caso_numeros_msisdn ON ap_caso_numeros(msisdn)")
        ensure_index("ap_caso_mapa_puntos", "idx_ap_caso_mapa_puntos_caso", "CREATE INDEX idx_ap_caso_mapa_puntos_caso ON ap_caso_mapa_puntos(caso_id)")
        ensure_index("ap_casos_compartidos", "idx_ap_casos_compartidos_shared_with", "CREATE INDEX idx_ap_casos_compartidos_shared_with ON ap_casos_compartidos(shared_with_user_id)")

        # Columnas idempotentes en ap_casos
        try:
            tables = set(insp.get_table_names())
            if "ap_casos" in tables:
                cols = {c.get("name") for c in insp.get_columns("ap_casos")}
                if "referencia_carpeta" not in cols:
                    db.session.execute(text("ALTER TABLE ap_casos ADD COLUMN referencia_carpeta VARCHAR(120) NULL"))
                if "fecha_referencia" not in cols:
                    db.session.execute(text("ALTER TABLE ap_casos ADD COLUMN fecha_referencia DATE NULL"))
        except Exception:
            pass

        try:
            tables = set(insp.get_table_names())
            if "ap_caso_mapa_puntos" in tables:
                cols = {c.get("name") for c in insp.get_columns("ap_caso_mapa_puntos")}
                if "icono" not in cols:
                    db.session.execute(text("ALTER TABLE ap_caso_mapa_puntos ADD COLUMN icono VARCHAR(40) NULL"))
        except Exception:
            pass

        db.session.commit()
    except Exception:
        db.session.rollback()
        return
    _ap_schema_checked = True


@bp.before_request
@login_required
def _before_request():
    _ensure_analisis_schema()
    _migrate_legacy_caso_fuentes_notas()


@bp.route("/")
def index():
    if not _permiso():
        flash("No tiene permiso para acceder a Casos.", "warning")
        return redirect(url_for("core.dashboard"))
    casos = _casos_query_accessible().order_by(AnalisisPuntoCaso.created_at.desc()).limit(50).all()
    return render_template(
        "analisis_puntos/index.html",
        casos=casos,
    )


@bp.route("/casos", methods=["POST"])
def crear_caso():
    if not _permiso():
        flash("No tiene permiso para crear casos.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    titulo = (request.form.get("titulo") or "").strip()
    descripcion = (request.form.get("descripcion") or "").strip()
    referencia_carpeta = (request.form.get("referencia_carpeta") or "").strip() or None
    fecha_raw = (request.form.get("fecha_referencia") or "").strip()
    fecha_referencia = None
    if fecha_raw:
        try:
            fecha_referencia = datetime.strptime(fecha_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("La fecha de referencia no es válida.", "warning")
            return redirect(url_for("analisis_puntos.index"))

    if not titulo:
        flash("Debe indicar un título para el caso.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    codigo = f"CASO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    caso = AnalisisPuntoCaso(
        unidad_id=current_user.unidad_id,
        user_id=current_user.id,
        codigo=codigo,
        titulo=titulo,
        descripcion=descripcion or None,
        referencia_carpeta=referencia_carpeta,
        fecha_referencia=fecha_referencia,
        estado="ACTIVO",
    )
    db.session.add(caso)
    db.session.commit()
    flash("Caso creado. Ya puede cargar archivos y vincular sujetos desde Sabana de Llamadas.", "success")
    return redirect(url_for("analisis_puntos.index"))


@bp.route("/casos/<int:caso_id>/relaciones")
def caso_relaciones(caso_id):
    if not _permiso():
        flash("No tiene permiso para ver relaciones del caso.", "warning")
        return redirect(url_for("core.dashboard"))
    from app.blueprints.sabana_llamadas.routes import _ensure_sabana_schema

    _ensure_sabana_schema()
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    sujetos = Sujeto.query.filter(Sujeto.unidad_id == current_user.unidad_id).order_by(Sujeto.apodo, Sujeto.nombre, Sujeto.dni).limit(300).all()
    fuentes = AnalisisPuntoFuente.query.filter_by(caso_id=caso.id, unidad_id=current_user.unidad_id).order_by(AnalisisPuntoFuente.created_at.desc()).all()
    links_suj = AnalisisPuntoCasoSujeto.query.filter_by(caso_id=caso.id, unidad_id=current_user.unidad_id).order_by(AnalisisPuntoCasoSujeto.created_at.desc()).all()
    links_num = AnalisisPuntoCasoNumero.query.filter_by(caso_id=caso.id, unidad_id=current_user.unidad_id).order_by(AnalisisPuntoCasoNumero.created_at.desc()).all()

    cargas_caso = (
        CargaLlamada.query.filter_by(caso_id=caso.id, unidad_id=current_user.unidad_id)
        .options(joinedload(CargaLlamada.sujeto))
        .order_by(CargaLlamada.created_at.desc())
        .all()
    )

    # Sujetos: vínculos explícitos + los deducidos de cargas de sábana con sujeto
    explicit_suj_ids = {l.sujeto_id for l in links_suj}
    sujeto_filas = [{"kind": "explicit", "link": l} for l in links_suj]
    cargas_por_sujeto = {}
    for cg in cargas_caso:
        if cg.sujeto_id:
            cargas_por_sujeto[cg.sujeto_id] = cargas_por_sujeto.get(cg.sujeto_id, 0) + 1
    for sid, cnt in sorted(cargas_por_sujeto.items(), key=lambda x: x[0]):
        if sid in explicit_suj_ids:
            continue
        s = Sujeto.query.filter_by(id=sid, unidad_id=current_user.unidad_id).first()
        if s:
            sujeto_filas.append({"kind": "sabana", "sujeto": s, "n_cargas": cnt})

    # Archivos: record (nota en ap_fuentes.relaciones_nota) + sábana (nota en sabana_cargas.relaciones_nota)
    archivo_filas = []
    for f in fuentes:
        archivo_filas.append({"kind": "record", "fuente": f})
    for cg in cargas_caso:
        archivo_filas.append({"kind": "sabana", "carga": cg})

    def _archivo_sort_key(r):
        if r["kind"] == "record":
            return r["fuente"].created_at or datetime.min
        return r["carga"].created_at or datetime.min

    archivo_filas.sort(key=_archivo_sort_key, reverse=True)

    # Números: solo manuales (caso) + explícitos del sujeto (sin titulares automáticos)
    manual_msisdn = {(ln.msisdn or "").strip() for ln in links_num if (ln.msisdn or "").strip()}
    numero_filas = [{"kind": "manual", "link": l} for l in links_num]
    seen_msisdn = set(manual_msisdn)
    # Si un sujeto está asociado al caso, se incorporan sus números explícitos (sabana_sujeto_numeros)
    sujetos_del_caso_ids = set(explicit_suj_ids) | set(cargas_por_sujeto.keys())
    if sujetos_del_caso_ids:
        sujetos_vinculados = {
            s.id: s for s in Sujeto.query.filter(
                Sujeto.unidad_id == current_user.unidad_id,
                Sujeto.id.in_(list(sujetos_del_caso_ids))
            ).all()
        }
        nums_sujeto = (
            SujetoNumero.query
            .filter(
                SujetoNumero.unidad_id == current_user.unidad_id,
                SujetoNumero.sujeto_id.in_(list(sujetos_del_caso_ids)),
            )
            .order_by(SujetoNumero.numero.asc())
            .all()
        )
        for sn in nums_sujeto:
            n = (sn.numero or "").strip()
            if not n or n in seen_msisdn:
                continue
            seen_msisdn.add(n)
            numero_filas.append({
                "kind": "sujeto_numero",
                "msisdn": n,
                "sujeto": sujetos_vinculados.get(sn.sujeto_id),
                "sujeto_id": sn.sujeto_id,
                "nota": (sn.notas or "").strip() or None,
            })

    mapa_puntos = (
        AnalisisPuntoCasoMapaPunto.query.options(joinedload(AnalisisPuntoCasoMapaPunto.user))
        .filter_by(caso_id=caso.id, unidad_id=current_user.unidad_id)
        .order_by(AnalisisPuntoCasoMapaPunto.created_at.desc())
        .all()
    )

    return render_template(
        "analisis_puntos/caso_relaciones.html",
        caso=caso,
        sujetos=sujetos,
        fuentes=fuentes,
        cargas_caso=cargas_caso,
        links_sujetos=links_suj,
        links_numeros=links_num,
        sujeto_filas=sujeto_filas,
        archivo_filas=archivo_filas,
        numero_filas=numero_filas,
        mapa_puntos=mapa_puntos,
    )


@bp.route("/casos/<int:caso_id>/relaciones/sujetos", methods=["POST"])
def caso_relaciones_sujetos_add(caso_id):
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    sujeto_id = request.form.get("sujeto_id", type=int)
    nota = (request.form.get("nota") or "").strip() or None
    if not sujeto_id:
        flash("Debe seleccionar un sujeto.", "warning")
        return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    sujeto = Sujeto.query.filter_by(id=sujeto_id, unidad_id=current_user.unidad_id).first()
    if not sujeto:
        flash("Sujeto inválido para esta unidad.", "warning")
        return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    ex = AnalisisPuntoCasoSujeto.query.filter_by(caso_id=caso.id, sujeto_id=sujeto.id).first()
    if ex:
        flash("Ese sujeto ya está vinculado al caso.", "info")
    else:
        db.session.add(AnalisisPuntoCasoSujeto(caso_id=caso.id, sujeto_id=sujeto.id, unidad_id=current_user.unidad_id, user_id=current_user.id, nota=nota))
        db.session.commit()
        flash("Sujeto vinculado al caso.", "success")
    return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))


@bp.route("/casos/<int:caso_id>/relaciones/sujetos/<int:link_id>/eliminar", methods=["POST"])
def caso_relaciones_sujetos_del(caso_id, link_id):
    link = AnalisisPuntoCasoSujeto.query.filter_by(id=link_id, caso_id=caso_id, unidad_id=current_user.unidad_id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    flash("Vínculo caso-sujeto eliminado.", "success")
    return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso_id))


@bp.route("/casos/<int:caso_id>/relaciones/mapa-puntos/<int:punto_id>/eliminar", methods=["POST"])
def caso_relaciones_mapa_punto_del(caso_id, punto_id):
    """Elimina un punto de referencia geográfico del caso (misma regla que el mapa)."""
    if not _permiso():
        flash("No tiene permiso.", "warning")
        return redirect(url_for("core.dashboard"))
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    p = AnalisisPuntoCasoMapaPunto.query.filter_by(
        id=punto_id, caso_id=caso.id, unidad_id=current_user.unidad_id
    ).first_or_404()
    db.session.delete(p)
    db.session.commit()
    flash("Punto de referencia eliminado del mapa.", "success")
    return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso_id))


@bp.route("/casos/<int:caso_id>/relaciones/archivo-record-nota", methods=["POST"])
def caso_relaciones_record_nota(caso_id):
    """Nota de relaciones en el propio registro ap_fuentes (misma lógica que sábana en sabana_cargas)."""
    if not _permiso():
        flash("No tiene permiso.", "warning")
        return redirect(url_for("core.dashboard"))
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    fuente_id = request.form.get("fuente_id", type=int)
    raw = (request.form.get("nota") or "").strip()
    nota = raw or None
    if not fuente_id:
        flash("Debe seleccionar un archivo record (VOZ/GPRS).", "warning")
        return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    fuente = AnalisisPuntoFuente.query.filter_by(id=fuente_id, caso_id=caso.id, unidad_id=current_user.unidad_id).first()
    if not fuente:
        flash("Archivo record inválido para este caso.", "warning")
        return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    if nota and len(nota) > 500:
        nota = nota[:500]
    fuente.relaciones_nota = nota
    db.session.commit()
    flash("Nota guardada." if nota else "Nota eliminada.", "success")
    return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))


@bp.route("/casos/<int:caso_id>/relaciones/cargas-sabana", methods=["POST"])
def caso_relaciones_carga_sabana_nota(caso_id):
    """Nota opcional en relaciones para una carga de sábana del caso (columna relaciones_nota)."""
    if not _permiso():
        flash("No tiene permiso.", "warning")
        return redirect(url_for("core.dashboard"))
    from app.blueprints.sabana_llamadas.routes import _ensure_sabana_schema

    _ensure_sabana_schema()
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    carga_id = request.form.get("carga_id", type=int)
    nota = (request.form.get("nota") or "").strip() or None
    if not carga_id:
        flash("Debe seleccionar una carga de sábana.", "warning")
        return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    carga = CargaLlamada.query.filter_by(id=carga_id, caso_id=caso.id, unidad_id=current_user.unidad_id).first()
    if not carga:
        flash("Carga inválida o no pertenece a este caso.", "warning")
        return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    carga.relaciones_nota = nota
    db.session.commit()
    flash("Nota guardada para la carga de sábana." if nota else "Nota de la carga eliminada.", "success")
    return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))


@bp.route("/casos/<int:caso_id>/relaciones/numeros", methods=["POST"])
def caso_relaciones_numeros_add(caso_id):
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    msisdn = (request.form.get("msisdn") or "").strip()
    sujeto_id = request.form.get("sujeto_id", type=int)
    fuente_id = request.form.get("fuente_id", type=int)
    nota = (request.form.get("nota") or "").strip() or None
    if not msisdn:
        flash("Debe informar un número.", "warning")
        return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    if sujeto_id:
        sujeto = Sujeto.query.filter_by(id=sujeto_id, unidad_id=current_user.unidad_id).first()
        if not sujeto:
            flash("Sujeto inválido.", "warning")
            return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    if fuente_id:
        fuente = AnalisisPuntoFuente.query.filter_by(id=fuente_id, caso_id=caso.id, unidad_id=current_user.unidad_id).first()
        if not fuente:
            flash("Fuente inválida.", "warning")
            return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))
    ex = AnalisisPuntoCasoNumero.query.filter_by(caso_id=caso.id, msisdn=msisdn, sujeto_id=sujeto_id, fuente_id=fuente_id).first()
    if ex:
        flash("Ese número ya está vinculado con la misma combinación.", "info")
    else:
        db.session.add(AnalisisPuntoCasoNumero(
            caso_id=caso.id,
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            msisdn=msisdn,
            sujeto_id=sujeto_id,
            fuente_id=fuente_id,
            nota=nota,
        ))
        db.session.commit()
        flash("Número vinculado al caso.", "success")
    return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso.id))


@bp.route("/casos/<int:caso_id>/relaciones/numeros/<int:link_id>/eliminar", methods=["POST"])
def caso_relaciones_numeros_del(caso_id, link_id):
    link = AnalisisPuntoCasoNumero.query.filter_by(id=link_id, caso_id=caso_id, unidad_id=current_user.unidad_id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    flash("Vínculo caso-número eliminado.", "success")
    return redirect(url_for("analisis_puntos.caso_relaciones", caso_id=caso_id))


@bp.route("/casos/<int:caso_id>/upload", methods=["POST"])
def upload_archivo(caso_id):
    if not _permiso():
        flash("No tiene permiso para subir archivos.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    source_type = (request.form.get("source_type") or "").strip().upper()
    if source_type not in {"VOZ", "GPRS"}:
        flash("Tipo de fuente inválido. Use VOZ o GPRS.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    f = request.files.get("archivo")
    if not f or not f.filename:
        flash("Debe seleccionar un archivo.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    filename = secure_filename(f.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in {".xlsx", ".xls", ".csv"}:
        flash("Formato no permitido. Use .xlsx, .xls o .csv.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    base_dir = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(current_app.root_path, base_dir)
    target_dir = os.path.join(base_dir, "analisis_puntos", str(current_user.unidad_id), str(caso.id))
    os.makedirs(target_dir, exist_ok=True)
    safe_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
    path = os.path.join(target_dir, safe_name)
    f.save(path)

    sha256 = hashlib.sha256()
    with open(path, "rb") as rf:
        for chunk in iter(lambda: rf.read(8192), b""):
            sha256.update(chunk)

    src = AnalisisPuntoFuente(
        caso_id=caso.id,
        unidad_id=current_user.unidad_id,
        user_id=current_user.id,
        source_type=source_type,
        nombre_archivo=safe_name,
        sha256=sha256.hexdigest(),
        mime_type=f.mimetype,
        size_bytes=os.path.getsize(path),
        upload_status="PENDING",
    )
    db.session.add(src)
    db.session.commit()

    flash("Archivo subido. Siguiente paso: procesar parser VOZ/GPRS.", "success")
    return redirect(url_for("analisis_puntos.index"))


@bp.route("/fuentes/<int:fuente_id>")
def fuente_detalle(fuente_id):
    if not _permiso():
        flash("No tiene permiso para ver el detalle de la fuente.", "warning")
        return redirect(url_for("core.dashboard"))
    fuente = _fuentes_query_accessible().options(joinedload(AnalisisPuntoFuente.caso)).filter(AnalisisPuntoFuente.id == fuente_id).first_or_404()
    summary, err_text = _parse_fuente_processing_detail(fuente)
    try:
        n_eventos_db = AnalisisPuntoEvento.query.filter_by(fuente_id=fuente.id).count()
    except Exception:
        n_eventos_db = None
    return render_template(
        "analisis_puntos/fuente_detalle.html",
        fuente=fuente,
        processing_summary=summary,
        error_text=err_text,
        n_eventos_db=n_eventos_db,
    )


@bp.route("/fuentes/<int:fuente_id>/procesar", methods=["POST"])
def procesar_fuente(fuente_id):
    if not _permiso():
        flash("No tiene permiso para procesar archivos.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    fuente = _fuentes_query_accessible().filter(AnalisisPuntoFuente.id == fuente_id).first_or_404()

    base_dir = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(current_app.root_path, base_dir)
    path = os.path.join(base_dir, "analisis_puntos", str(current_user.unidad_id), str(fuente.caso_id), fuente.nombre_archivo)

    try:
        if fuente.source_type == "VOZ":
            res = procesar_fuente_voz(fuente, path)
            total = int((res or {}).get("eventos_importados", 0))
            omit = int((res or {}).get("filas_omitidas_total", 0))
            leidas = int((res or {}).get("filas_trafico_leidas", total + omit))
            flash(f"Procesamiento VOZ completado. Eventos: {total} (filas leídas: {leidas}, omitidas vacías: {omit}).", "success")
        else:
            res = procesar_fuente_gprs(fuente, path)
            total = int((res or {}).get("eventos_importados", 0))
            omit = int((res or {}).get("filas_omitidas_total", 0))
            leidas = int((res or {}).get("filas_trafico_leidas", total + omit))
            flash(f"Procesamiento GPRS completado. Eventos: {total} (filas leídas: {leidas}, omitidas vacías: {omit}).", "success")
    except Exception as e:
        try:
            fuente.upload_status = "ERROR"
            fuente.error_detail = str(e)
            db.session.add(fuente)
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f"Error procesando fuente: {e}", "danger")
        return redirect(url_for("analisis_puntos.fuente_detalle", fuente_id=fuente.id))

    return redirect(url_for("analisis_puntos.fuente_detalle", fuente_id=fuente.id))


@bp.route("/fuentes/<int:fuente_id>/eliminar", methods=["POST"])
def fuente_eliminar(fuente_id):
    """Elimina una fuente record y sus registros dependientes."""
    if not current_user.has_permission("SABANA_LLAMADAS_UPLOAD"):
        flash("Sin permiso para eliminar archivos.", "warning")
        return redirect(url_for("sabana_llamadas.cargas_list"))

    fuente = _fuentes_query_accessible().filter(AnalisisPuntoFuente.id == fuente_id).first_or_404()

    # Borrado de datos asociados para evitar restricciones FK.
    AnalisisPuntoCasoNumero.query.filter_by(fuente_id=fuente.id).delete(synchronize_session=False)
    AnalisisPuntoTitular.query.filter_by(fuente_id=fuente.id).delete(synchronize_session=False)
    AnalisisPuntoEvento.query.filter_by(fuente_id=fuente.id).delete(synchronize_session=False)
    try:
        db.session.execute(text("DELETE FROM ap_caso_fuentes WHERE fuente_id = :fid"), {"fid": fuente.id})
    except Exception:
        pass
    db.session.delete(fuente)
    db.session.commit()

    # Limpieza best-effort del archivo físico.
    try:
        base_dir = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(current_app.root_path, base_dir)
        path = os.path.join(base_dir, "analisis_puntos", str(current_user.unidad_id), str(fuente.caso_id), fuente.nombre_archivo)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    flash("Record eliminado correctamente.", "success")
    return redirect(url_for("sabana_llamadas.cargas_list"))


@bp.route("/casos/<int:caso_id>/mapa")
def mapa_caso(caso_id):
    """
    Compatibilidad: antes servía el mapa solo-record (Leaflet en este blueprint).
    El mapa único vive en Sabana de Llamadas con modo record + caso precargado.
    """
    if not _permiso():
        flash("No tiene permiso para ver el mapa.", "warning")
        return redirect(url_for("analisis_puntos.index"))
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first_or_404()
    return redirect(url_for("sabana_llamadas.mapa", modo="record", caso_id=caso.id))


@bp.route("/api/casos/<int:caso_id>/mapa-data")
def api_mapa_data(caso_id):
    if not _permiso():
        return jsonify({"ok": False, "error": "sin_permiso"}), 403
    caso = _casos_query_accessible().filter(AnalisisPuntoCaso.id == caso_id).first()
    if not caso:
        return jsonify({"ok": False, "error": "caso_no_encontrado"}), 404

    source_type = (request.args.get("source_type") or "").strip().upper()
    max_m = request.args.get("max_m", type=int)
    if max_m is not None and max_m < 0:
        max_m = None

    q = (
        db.session.query(
            AnalisisPuntoEvento.id,
            AnalisisPuntoEvento.event_dt,
            AnalisisPuntoEvento.origin_msisdn,
            AnalisisPuntoEvento.target_msisdn,
            AnalisisPuntoEvento.imei,
            AnalisisPuntoEvento.imsi,
            AnalisisPuntoEvento.event_type,
            AnalisisPuntoEvento.duration_sec,
            AnalisisPuntoEvento.raw_cell_code,
            AnalisisPuntoCelda.id.label("celda_id"),
            AnalisisPuntoCelda.cell_code,
            AnalisisPuntoCelda.locality,
            AnalisisPuntoCelda.province,
            AnalisisPuntoCelda.lat,
            AnalisisPuntoCelda.lon,
            AnalisisPuntoCelda.coverage_radius_m,
        )
        .outerjoin(AnalisisPuntoCelda, AnalisisPuntoEvento.cell_id == AnalisisPuntoCelda.id)
        .filter(AnalisisPuntoEvento.caso_id == caso.id)
    )
    if source_type in {"VOZ", "GPRS"}:
        q = q.filter(AnalisisPuntoEvento.source_type == source_type)

    rows = q.order_by(AnalisisPuntoEvento.event_dt.asc().nullsfirst()).all()

    celdas = {}
    eventos = []
    for r in rows:
        if r.celda_id and r.lat is not None and r.lon is not None:
            key = str(r.celda_id)
            if key not in celdas:
                radius_full = int(r.coverage_radius_m or 0)
                radius_draw = radius_full
                if max_m is not None and radius_full > 0:
                    radius_draw = min(radius_full, max_m)
                celdas[key] = {
                    "id": r.celda_id,
                    "cell_code": r.cell_code,
                    "locality": r.locality,
                    "province": r.province,
                    "lat": r.lat,
                    "lon": r.lon,
                    "radius_full_m": radius_full,
                    "radius_draw_m": radius_draw if radius_draw > 0 else (max_m or 200),
                    "event_count": 0,
                }
            celdas[key]["event_count"] += 1

        eventos.append({
            "id": r.id,
            "event_dt": r.event_dt.isoformat() if r.event_dt else None,
            "origin": r.origin_msisdn,
            "target": r.target_msisdn,
            "imei": r.imei,
            "imsi": r.imsi,
            "event_type": r.event_type,
            "duration_sec": r.duration_sec,
            "cell_code": r.cell_code or r.raw_cell_code,
            "distance_m": 0,  # Placeholder: el record fuente no trae coordenada puntual del impacto.
        })

    return jsonify({
        "ok": True,
        "caso": {"id": caso.id, "codigo": caso.codigo, "titulo": caso.titulo},
        "summary": {
            "total_eventos": len(eventos),
            "total_celdas": len(celdas),
            "max_m": max_m,
            "source_type": source_type or "ALL",
        },
        "celdas": list(celdas.values()),
        "eventos": eventos[:1500],
    })

import hashlib
import os
from datetime import datetime

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text
from werkzeug.utils import secure_filename

from app.blueprints.analisis_puntos import bp
from app.blueprints.analisis_puntos.services import procesar_fuente_voz
from app.extensions import db
from app.models.analisis_puntos import AnalisisPuntoCaso, AnalisisPuntoCelda, AnalisisPuntoEvento, AnalisisPuntoFuente


_ap_schema_checked = False


def _permiso():
    return current_user.has_permission("SABANA_LLAMADAS_VIEW") or current_user.has_permission("SABANA_LLAMADAS_UPLOAD")


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
        db.session.commit()
    except Exception:
        db.session.rollback()
        return
    _ap_schema_checked = True


@bp.before_request
@login_required
def _before_request():
    _ensure_analisis_schema()


@bp.route("/")
def index():
    if not _permiso():
        flash("No tiene permiso para acceder a Análisis de Puntos.", "warning")
        return redirect(url_for("core.dashboard"))
    casos = (
        AnalisisPuntoCaso.query
        .filter(AnalisisPuntoCaso.unidad_id == current_user.unidad_id)
        .order_by(AnalisisPuntoCaso.created_at.desc())
        .limit(30)
        .all()
    )
    return render_template("analisis_puntos/index.html", casos=casos)


@bp.route("/casos", methods=["POST"])
def crear_caso():
    if not _permiso():
        flash("No tiene permiso para crear casos.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    titulo = (request.form.get("titulo") or "").strip()
    descripcion = (request.form.get("descripcion") or "").strip()
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
        estado="ACTIVO",
    )
    db.session.add(caso)
    db.session.commit()
    flash("Caso creado. Ya puede subir VOZ o GPRS.", "success")
    return redirect(url_for("analisis_puntos.index"))


@bp.route("/casos/<int:caso_id>/upload", methods=["POST"])
def upload_archivo(caso_id):
    if not _permiso():
        flash("No tiene permiso para subir archivos.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    caso = AnalisisPuntoCaso.query.filter_by(id=caso_id, unidad_id=current_user.unidad_id).first_or_404()
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


@bp.route("/fuentes/<int:fuente_id>/procesar", methods=["POST"])
def procesar_fuente(fuente_id):
    if not _permiso():
        flash("No tiene permiso para procesar archivos.", "warning")
        return redirect(url_for("analisis_puntos.index"))

    fuente = (
        AnalisisPuntoFuente.query
        .filter(AnalisisPuntoFuente.id == fuente_id, AnalisisPuntoFuente.unidad_id == current_user.unidad_id)
        .first_or_404()
    )

    base_dir = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
    path = os.path.join(base_dir, "analisis_puntos", str(current_user.unidad_id), str(fuente.caso_id), fuente.nombre_archivo)
    if not os.path.isabs(path):
        path = os.path.join(current_app.root_path, path)

    try:
        if fuente.source_type == "VOZ":
            total = procesar_fuente_voz(fuente, path)
            flash(f"Procesamiento VOZ completado. Eventos cargados: {total}.", "success")
        else:
            flash("Procesamiento GPRS aún no implementado en este paso.", "info")
    except Exception as e:
        try:
            fuente.upload_status = "ERROR"
            fuente.error_detail = str(e)
            db.session.add(fuente)
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f"Error procesando fuente: {e}", "danger")

    return redirect(url_for("analisis_puntos.index"))


@bp.route("/casos/<int:caso_id>/mapa")
def mapa_caso(caso_id):
    if not _permiso():
        flash("No tiene permiso para ver el mapa.", "warning")
        return redirect(url_for("analisis_puntos.index"))
    caso = AnalisisPuntoCaso.query.filter_by(id=caso_id, unidad_id=current_user.unidad_id).first_or_404()
    return render_template("analisis_puntos/mapa.html", caso=caso)


@bp.route("/api/casos/<int:caso_id>/mapa-data")
def api_mapa_data(caso_id):
    if not _permiso():
        return jsonify({"ok": False, "error": "sin_permiso"}), 403
    caso = AnalisisPuntoCaso.query.filter_by(id=caso_id, unidad_id=current_user.unidad_id).first()
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

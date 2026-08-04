"""
Rutas del módulo Sabana de Llamadas
"""
import os
import io
from collections import defaultdict
import zipfile
import hashlib
import mimetypes
import json
import math
import html
import urllib.request
import unicodedata
import time
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, send_from_directory, send_file
from flask_login import login_required, current_user
from sqlalchemy import func, or_, inspect, text, tuple_, literal, case
from sqlalchemy.sql import exists, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import aliased, joinedload
from werkzeug.utils import secure_filename

from app.blueprints.sabana_llamadas import bp
from app.blueprints.sabana_llamadas.forms import (
    UploadGPRSForm,
    UploadVOZForm,
    SujetoForm,
    SujetoNuevoForm,
    VincularCargaForm,
)
from app.blueprints.sabana_llamadas.services import (
    procesar_archivo_gprs,
    procesar_archivo_voz,
    guardar_imagen_sujeto,
)
from app.blueprints.sabana_llamadas.claro_import import procesar_archivo_claro
from app.blueprints.sabana_llamadas.movistar_import import procesar_archivo_movistar
from app.blueprints.analisis_puntos.claro_record import procesar_record_claro
from app.extensions import db
from app.models.sabana_llamadas import (
    Sujeto,
    CargaLlamada,
    CargaLlamadaCompartida,
    SujetoCompartido,
    SujetoNumero,
    DatoTecnico,
    ResultadoTraficoGPRS,
    ResultadoTraficoVOZ,
    SabanaImpactoNota,
)
from app.models.analisis_puntos import (
    AnalisisPuntoCaso,
    AnalisisPuntoCasoCompartido,
    AnalisisPuntoCasoMapaPunto,
    AnalisisPuntoCasoSujeto,
    AnalisisPuntoCelda,
    AnalisisPuntoEvento,
    AnalisisPuntoFuente,
)
from app.blueprints.analisis_puntos.services import procesar_fuente_voz, procesar_fuente_gprs
from app.models.persona import Persona
from app.models.user import User
from app.models.unidad import Unidad


def _permiso():
    if not current_user.has_permission('SABANA_LLAMADAS_VIEW') and not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        return False
    return True


def _is_superadmin():
    try:
        return current_user.has_role('SUPERADMIN')
    except Exception:
        return False


def _carga_access_predicate():
    """
    Devuelve un filtro SQLAlchemy para aplicar sobre CargaLlamada:
    - dueño (user_id) o
    - compartida explícitamente (carga) o
    - compartida por sujeto (sujeto_id)
    """
    if _is_superadmin():
        return True
    owned = (CargaLlamada.user_id == current_user.id)
    shared_carga = exists().where(and_(
        CargaLlamadaCompartida.carga_id == CargaLlamada.id,
        CargaLlamadaCompartida.shared_with_user_id == current_user.id,
    ))
    shared_suj = exists().where(and_(
        SujetoCompartido.sujeto_id == CargaLlamada.sujeto_id,
        SujetoCompartido.shared_with_user_id == current_user.id,
    ))
    shared_case = exists().where(and_(
        AnalisisPuntoCasoCompartido.caso_id == CargaLlamada.caso_id,
        AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
    ))
    return or_(owned, shared_carga, shared_suj, shared_case)


def _sujeto_access_predicate():
    """
    Acceso a Sujeto:
    - dueño (user_id) o
    - compartido explícitamente (sujeto) o
    - tiene alguna carga compartida al usuario
    """
    if _is_superadmin():
        return True
    owned = (Sujeto.user_id == current_user.id)
    shared_suj = exists().where(and_(
        SujetoCompartido.sujeto_id == Sujeto.id,
        SujetoCompartido.shared_with_user_id == current_user.id,
    ))
    shared_via_carga = exists().where(and_(
        CargaLlamada.id == CargaLlamadaCompartida.carga_id,
        CargaLlamada.sujeto_id == Sujeto.id,
        CargaLlamadaCompartida.shared_with_user_id == current_user.id,
    ))
    shared_via_case = exists().where(and_(
        CargaLlamada.sujeto_id == Sujeto.id,
        CargaLlamada.caso_id == AnalisisPuntoCasoCompartido.caso_id,
        AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
    ))
    return or_(owned, shared_suj, shared_via_carga, shared_via_case)


def _cargas_query_accessible():
    q = CargaLlamada.query.filter(CargaLlamada.unidad_id == current_user.unidad_id)
    pred = _carga_access_predicate()
    if pred is not True:
        q = q.filter(pred)
    return q


def _sujetos_query_accessible():
    q = Sujeto.query.filter(Sujeto.unidad_id == current_user.unidad_id)
    pred = _sujeto_access_predicate()
    if pred is not True:
        q = q.filter(pred)
    return q


def _assert_owner_or_404(obj):
    if _is_superadmin():
        return obj
    if not obj or getattr(obj, 'user_id', None) != current_user.id:
        # no revelar existencia
        from flask import abort
        abort(404)
    return obj


def _parse_sabana_processing_detail(carga):
    raw = getattr(carga, 'processing_detail', None)
    if not raw or not str(raw).strip():
        return None
    try:
        j = json.loads(str(raw))
        return j if isinstance(j, dict) else None
    except Exception:
        return None


def _haversine_m(lat1, lon1, lat2, lon2):
    """Distancia aproximada entre dos puntos geográficos en metros."""
    try:
        r = 6371000.0
        p1 = math.radians(float(lat1))
        p2 = math.radians(float(lat2))
        dp = math.radians(float(lat2) - float(lat1))
        dl = math.radians(float(lon2) - float(lon1))
        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * (math.sin(dl / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return r * c
    except Exception:
        return None


def _bearing_deg(lat1, lon1, lat2, lon2):
    """Rumbo inicial desde (lat1,lon1) hacia (lat2,lon2), grados [0, 360)."""
    try:
        φ1 = math.radians(float(lat1))
        φ2 = math.radians(float(lat2))
        dλ = math.radians(float(lon2) - float(lon1))
        y = math.sin(dλ) * math.cos(φ2)
        x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(dλ)
        brng = math.degrees(math.atan2(y, x))
        return (brng + 360.0) % 360.0
    except Exception:
        return None


def _smallest_angle_diff_deg(a, b):
    """Diferencia angular mínima entre dos rumbos en grados [0, 180]."""
    try:
        d = (float(a) - float(b) + 540.0) % 360.0 - 180.0
        return abs(d)
    except Exception:
        return 180.0


_REF_GEO_MODE_DESC = {
    'centro': 'Distancia del punto de referencia al centro de antena ≤ radio de búsqueda.',
    'disco': 'El punto de referencia cae dentro del disco de cobertura (radio en BD de la celda). Si no hay radio en BD, se usa el mismo criterio que «centro».',
    'sector': 'Criterio de disco y además el punto debe caer en el sector de azimut (abertura horizontal en BD; por defecto 60° si falta). Sin azimut en BD se aplica solo el disco.',
}


def _ref_punto_in_celda_geom(ref_la, ref_lo, cel, perimetro_m, mode):
    """
    Decide si el punto de referencia se considera «cubierto» por la celda según el modo.

    mode:
      - centro: Haversine(ref, torre) ≤ perimetro_m
      - disco: Haversine ≤ coverage_radius_m si hay radio en BD; si no, igual que centro
      - sector: igual que disco para el alcance; si hay azimut, el rumbo torre→ref debe
        estar dentro de ± mitad de abertura horizontal (default 60° total como el mapa)

    Returns:
      (incluir: bool, dist_ref_torre_m: int | None)
    """
    if cel is None or cel.lat is None or cel.lon is None:
        return False, None
    tla, tlo = float(cel.lat), float(cel.lon)
    d = _haversine_m(ref_la, ref_lo, tla, tlo)
    if d is None:
        return False, None
    d_int = int(round(d))

    try:
        r_cov = int(cel.coverage_radius_m or 0)
    except Exception:
        r_cov = 0
    try:
        ap_full = float(cel.aperture_h_deg) if cel.aperture_h_deg is not None else 60.0
    except Exception:
        ap_full = 60.0
    if ap_full <= 0:
        ap_full = 60.0
    half_ap = ap_full / 2.0

    mode = (mode or 'centro').strip().lower()
    if mode not in ('centro', 'disco', 'sector'):
        mode = 'centro'

    def _in_alcance_disco_o_centro():
        """Disco si hay radio BD; si no, tope por perimetro_m (búsqueda)."""
        if r_cov > 0:
            return d <= float(r_cov)
        return d <= float(perimetro_m)

    if mode == 'centro':
        if d > float(perimetro_m):
            return False, d_int
        return True, d_int

    if mode == 'disco':
        if not _in_alcance_disco_o_centro():
            return False, d_int
        return True, d_int

    # sector
    if not _in_alcance_disco_o_centro():
        return False, d_int
    az = getattr(cel, 'azimuth_deg', None)
    if az is None:
        return True, d_int
    try:
        azf = float(az) % 360.0
    except Exception:
        return True, d_int
    brg = _bearing_deg(tla, tlo, ref_la, ref_lo)
    if brg is None:
        return True, d_int
    if _smallest_angle_diff_deg(brg, azf) > half_ap:
        return False, d_int
    return True, d_int


_sabana_schema_checked = False


def _ensure_sabana_schema():
    """
    Este proyecto no incluye migrations; para cambios pequeños del módulo Sabana
    agregamos columnas faltantes de forma idempotente.
    """
    global _sabana_schema_checked
    if _sabana_schema_checked:
        return
    _sabana_schema_checked = True
    try:
        insp = inspect(db.engine)

        def ensure_col(table, col_name, ddl):
            cols = {c.get('name') for c in insp.get_columns(table)}
            if col_name not in cols:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
                return True
            return False

        def ensure_index(table, idx_name, ddl_sql):
            try:
                existing = {i.get('name') for i in insp.get_indexes(table) if i.get('name')}
            except Exception:
                existing = set()
            if idx_name in existing:
                return False
            try:
                db.session.execute(text(ddl_sql))
                return True
            except Exception:
                return False

        def ensure_table(table_name, ddl_sql):
            try:
                tables = set(insp.get_table_names())
            except Exception:
                tables = set()
            if table_name in tables:
                return False
            try:
                db.session.execute(text(ddl_sql))
                return True
            except Exception:
                return False

        changed = False
        # GPRS tráfico
        changed = ensure_col('sabana_trafico_gprs', 'numero', "numero VARCHAR(64) NULL") or changed
        changed = ensure_col('sabana_trafico_gprs', 'extras', "extras TEXT NULL") or changed
        # VOZ tráfico
        changed = ensure_col('sabana_trafico_voz', 'numero', "numero VARCHAR(64) NULL") or changed
        changed = ensure_col('sabana_trafico_voz', 'extras', "extras TEXT NULL") or changed
        # Datos técnicos
        changed = ensure_col('sabana_datos_tecnicos', 'extras', "extras TEXT NULL") or changed
        # Cargas
        changed = ensure_col('sabana_cargas', 'criterio_busqueda', "criterio_busqueda TEXT NULL") or changed
        changed = ensure_col('sabana_cargas', 'operadora', "operadora VARCHAR(30) NULL") or changed
        changed = ensure_col('sabana_cargas', 'processing_detail', "processing_detail TEXT NULL") or changed
        changed = ensure_col('sabana_cargas', 'caso_id', "caso_id INT NULL") or changed
        changed = ensure_col('sabana_cargas', 'relaciones_nota', "relaciones_nota VARCHAR(500) NULL") or changed
        changed = ensure_col('sabana_cargas', 'sha256', "sha256 VARCHAR(128) NULL") or changed
        changed = ensure_col('sabana_cargas', 'size_bytes', "size_bytes INT NULL") or changed

        # Índices: siempre intentamos crearlos si faltan (sin spamear errores por request).
        idx_changed = False
        idx_changed = ensure_index('sabana_trafico_gprs', 'idx_sabana_trafico_gprs_numero',
                                   "CREATE INDEX idx_sabana_trafico_gprs_numero ON sabana_trafico_gprs (numero)") or idx_changed
        idx_changed = ensure_index('sabana_trafico_gprs', 'idx_sabana_trafico_gprs_imei',
                                   "CREATE INDEX idx_sabana_trafico_gprs_imei ON sabana_trafico_gprs (imei)") or idx_changed
        idx_changed = ensure_index('sabana_trafico_voz', 'idx_sabana_trafico_voz_imei',
                                   "CREATE INDEX idx_sabana_trafico_voz_imei ON sabana_trafico_voz (imei)") or idx_changed

        # Para mapa/impactos/ruta (clave por celda y filtro por fecha/hora)
        idx_changed = ensure_index('sabana_trafico_gprs', 'idx_sabana_trafico_gprs_carga_celda',
                                   "CREATE INDEX idx_sabana_trafico_gprs_carga_celda ON sabana_trafico_gprs (carga_id, celda)") or idx_changed
        idx_changed = ensure_index('sabana_trafico_voz', 'idx_sabana_trafico_voz_carga_celda',
                                   "CREATE INDEX idx_sabana_trafico_voz_carga_celda ON sabana_trafico_voz (carga_id, celda_id)") or idx_changed
        idx_changed = ensure_index('sabana_trafico_gprs', 'idx_sabana_trafico_gprs_fecha_hora',
                                   "CREATE INDEX idx_sabana_trafico_gprs_fecha_hora ON sabana_trafico_gprs (fecha, hora)") or idx_changed
        idx_changed = ensure_index('sabana_trafico_voz', 'idx_sabana_trafico_voz_fecha_hora',
                                   "CREATE INDEX idx_sabana_trafico_voz_fecha_hora ON sabana_trafico_voz (fecha, hora)") or idx_changed

        # Datos técnicos (celdas)
        idx_changed = ensure_index('sabana_datos_tecnicos', 'idx_sabana_datos_tecnicos_carga_celda',
                                   "CREATE INDEX idx_sabana_datos_tecnicos_carga_celda ON sabana_datos_tecnicos (carga_id, celda_id)") or idx_changed
        idx_changed = ensure_index('sabana_datos_tecnicos', 'idx_sabana_datos_tecnicos_tipo',
                                   "CREATE INDEX idx_sabana_datos_tecnicos_tipo ON sabana_datos_tecnicos (tipo)") or idx_changed
        # Útil para resolver coordenadas por celda (misma u otra carga)
        idx_changed = ensure_index('sabana_datos_tecnicos', 'idx_sabana_datos_tecnicos_tipo_celda',
                                   "CREATE INDEX idx_sabana_datos_tecnicos_tipo_celda ON sabana_datos_tecnicos (tipo, celda_id)") or idx_changed
        idx_changed = ensure_index('sabana_datos_tecnicos', 'idx_sabana_datos_tecnicos_celda_prov',
                                   "CREATE INDEX idx_sabana_datos_tecnicos_celda_prov ON sabana_datos_tecnicos (celda_prov)") or idx_changed
        idx_changed = ensure_index('sabana_datos_tecnicos', 'idx_sabana_datos_tecnicos_celda_loc',
                                   "CREATE INDEX idx_sabana_datos_tecnicos_celda_loc ON sabana_datos_tecnicos (celda_loc)") or idx_changed
        idx_changed = ensure_index('sabana_cargas', 'idx_sabana_cargas_caso_id',
                                   "CREATE INDEX idx_sabana_cargas_caso_id ON sabana_cargas (caso_id)") or idx_changed

        # Tablas para compartir (privacidad por usuario + share explícito)
        tbl_changed = False
        tbl_changed = ensure_table(
            'sabana_cargas_compartidas',
            """
            CREATE TABLE sabana_cargas_compartidas (
                carga_id INTEGER NOT NULL,
                shared_with_user_id INTEGER NOT NULL,
                shared_by_user_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (carga_id, shared_with_user_id)
            )
            """
        ) or tbl_changed
        tbl_changed = ensure_table(
            'sabana_sujetos_compartidos',
            """
            CREATE TABLE sabana_sujetos_compartidos (
                sujeto_id INTEGER NOT NULL,
                shared_with_user_id INTEGER NOT NULL,
                shared_by_user_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (sujeto_id, shared_with_user_id)
            )
            """
        ) or tbl_changed
        tbl_changed = ensure_table(
            'ap_casos_compartidos',
            """
            CREATE TABLE ap_casos_compartidos (
                caso_id INTEGER NOT NULL,
                shared_with_user_id INTEGER NOT NULL,
                shared_by_user_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (caso_id, shared_with_user_id)
            )
            """
        ) or tbl_changed

        # Índices de lookup para shares (PK ya asegura unicidad)
        idx_changed = ensure_index('sabana_cargas_compartidas', 'idx_sabana_cargas_compartidas_shared_with',
                                   "CREATE INDEX idx_sabana_cargas_compartidas_shared_with ON sabana_cargas_compartidas (shared_with_user_id)") or idx_changed
        idx_changed = ensure_index('sabana_sujetos_compartidos', 'idx_sabana_sujetos_compartidos_shared_with',
                                   "CREATE INDEX idx_sabana_sujetos_compartidos_shared_with ON sabana_sujetos_compartidos (shared_with_user_id)") or idx_changed
        idx_changed = ensure_index('ap_casos_compartidos', 'idx_ap_casos_compartidos_shared_with',
                                   "CREATE INDEX idx_ap_casos_compartidos_shared_with ON ap_casos_compartidos (shared_with_user_id)") or idx_changed

        tbl_changed = ensure_table(
            'ap_caso_mapa_puntos',
            """
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
                updated_at DATETIME NOT NULL
            )
            """
        ) or tbl_changed
        idx_changed = ensure_index('ap_caso_mapa_puntos', 'idx_ap_caso_mapa_puntos_caso',
                                   "CREATE INDEX idx_ap_caso_mapa_puntos_caso ON ap_caso_mapa_puntos (caso_id)") or idx_changed
        try:
            if 'ap_caso_mapa_puntos' in set(insp.get_table_names()):
                changed = ensure_col('ap_caso_mapa_puntos', 'icono', "icono VARCHAR(40) NULL") or changed
        except Exception:
            pass

        # Compatibilidad cruzada con módulo de Records:
        # si el modelo de ap_fuentes incluye "operadora", asegurar columna aunque
        # el usuario navegue solo por /sabana-llamadas y nunca abra /analisis-puntos.
        try:
            tables = set(insp.get_table_names())
            if 'ap_fuentes' in tables:
                changed = ensure_col('ap_fuentes', 'operadora', "operadora VARCHAR(30) NULL") or changed
        except Exception:
            pass

        if changed or idx_changed or tbl_changed:
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


@bp.before_request
@login_required
def require_login():
    _ensure_sabana_schema()


@bp.route('/')
def index():
    if not _permiso():
        flash('No tiene permiso para acceder a Sabana de Llamadas.', 'warning')
        return redirect(url_for('core.dashboard'))
    # Mostrar algunas cargas recientes para tener a la vista los archivos subidos
    cargas_recientes = _cargas_query_accessible() \
        .options(joinedload(CargaLlamada.caso), joinedload(CargaLlamada.sujeto)) \
        .order_by(CargaLlamada.created_at.desc()).limit(10).all()
    return render_template('sabana_llamadas/index.html', cargas=cargas_recientes)


@bp.route('/relaciones')
def relaciones():
    """Relaciones unificadas: sábana o Record, VOZ o GPRS (filtros alineados al mapa)."""
    if not _permiso():
        return redirect(url_for('core.dashboard'))

    origen = (request.args.get('origen') or 'sabana').strip().lower()
    if origen not in ('sabana', 'record'):
        origen = 'sabana'
    tipo_tf = (request.args.get('tipo_trafico') or 'voz').strip().lower()
    if tipo_tf not in ('voz', 'gprs'):
        tipo_tf = 'voz'
    is_gprs = tipo_tf == 'gprs'
    is_voz = not is_gprs

    sujeto_id = request.args.get('sujeto_id', type=int)
    carga_id = request.args.get('carga_id', type=int)
    caso_id = request.args.get('caso_id', type=int)
    numero_raw = (request.args.get('numero') or '').strip()
    fecha_desde_str = request.args.get('fecha_desde') or ''
    fecha_hasta_str = request.args.get('fecha_hasta') or ''
    hora_desde_str = request.args.get('hora_desde') or ''
    hora_hasta_str = request.args.get('hora_hasta') or ''
    limit = request.args.get('limit', type=int) or 200
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000

    fecha_desde = _parse_ymd(fecha_desde_str)
    fecha_hasta = _parse_ymd(fecha_hasta_str)
    hora_desde_hm = _normalize_hm(hora_desde_str)
    hora_hasta_hm = _normalize_hm(hora_hasta_str)

    mf = _parse_relaciones_multifilters()

    caso = _get_caso_accesible(caso_id) if caso_id else None
    caso_id_effective = caso.id if caso else None

    rows = []
    gprs_record_truncated = False

    if origen == 'record':
        if not caso:
            flash('Seleccione un caso de análisis para relaciones Record.', 'warning')
        else:
            fuente_id, fuente_ids, fuente_err = _parse_fuente_record_relaciones(caso)
            if fuente_err:
                flash(fuente_err, 'danger')
            elif is_voz:
                rows = _query_relaciones_record_voz(
                    caso, fuente_id, fuente_ids,
                    fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
                    numero_raw or None, limit,
                    numeros=mf['numeros'],
                    imeis=mf['imeis'],
                )
            else:
                rows, gprs_record_truncated = _query_relaciones_record_gprs(
                    caso, fuente_id, fuente_ids,
                    fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
                    numero_raw or None, limit,
                    numeros=mf['numeros'],
                    imeis=mf['imeis'],
                )
                if gprs_record_truncated:
                    flash(
                        'Se alcanzó el límite interno de registros GPRS Record analizados; '
                        'acote fechas, archivo o número para un resultado completo.',
                        'warning',
                    )
    else:
        if is_voz:
            rows = _query_relaciones_voz(
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                hora_desde_hm=hora_desde_hm,
                hora_hasta_hm=hora_hasta_hm,
                sujeto_id=sujeto_id,
                carga_id=carga_id,
                caso_id=caso_id_effective,
                numero_filtro=numero_raw or None,
                sujeto_ids=mf['sujeto_ids'],
                carga_ids=mf['carga_ids'],
                numeros=mf['numeros'],
                imeis=mf['imeis'],
                provincias=mf['provincias'],
                localidades=mf['localidades'],
                max_rows=limit,
            )
        else:
            rows = _query_relaciones_gprs(
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                hora_desde_hm=hora_desde_hm,
                hora_hasta_hm=hora_hasta_hm,
                sujeto_id=sujeto_id,
                carga_id=carga_id,
                caso_id=caso_id_effective,
                numero_filtro=numero_raw or None,
                sujeto_ids=mf['sujeto_ids'],
                carga_ids=mf['carga_ids'],
                numeros=mf['numeros'],
                imeis=mf['imeis'],
                provincias=mf['provincias'],
                localidades=mf['localidades'],
                max_rows=limit,
            )

    numero_set = set()
    for r in rows:
        if getattr(r, 'numero_a', None):
            numero_set.add(str(r.numero_a).strip())
        if is_voz and getattr(r, 'numero_b', None):
            numero_set.add(str(r.numero_b).strip())

    sujetos_por_numero = {}
    if numero_set:
        try:
            accesibles_ids = [sid for (sid,) in _sujetos_query_accessible().with_entities(Sujeto.id).all()]

            exp_rows = db.session.query(
                SujetoNumero.numero,
                Sujeto.id,
                Sujeto.apodo,
                Sujeto.nombre,
                Sujeto.dni,
                Sujeto.imagen,
            ).join(Sujeto, SujetoNumero.sujeto_id == Sujeto.id) \
             .filter(
                 SujetoNumero.unidad_id == current_user.unidad_id,
                 SujetoNumero.numero.in_(list(numero_set)),
                 SujetoNumero.sujeto_id.in_(accesibles_ids) if accesibles_ids else text("0=1"),
             ).order_by(SujetoNumero.numero, Sujeto.id).all()

            for num, sid, apodo, nombre, dni, imagen in exp_rows:
                key = (str(num) or '').strip()
                if not key:
                    continue
                if key not in sujetos_por_numero:
                    display = nombre or apodo or (f"DNI {dni}" if dni else f"Sujeto #{sid}")
                    img_url = url_for('sabana_llamadas.sujetos_imagen', sujeto_id=sid, _external=True) if imagen else None
                    sujetos_por_numero[key] = {
                        'id': sid,
                        'display': display,
                        'imagen_url': img_url,
                    }

            faltantes = [n for n in numero_set if n not in sujetos_por_numero]
            if faltantes and origen == 'sabana':
                if is_voz:
                    q_num_imp = db.session.query(
                        ResultadoTraficoVOZ.numero,
                        Sujeto.id,
                        Sujeto.apodo,
                        Sujeto.nombre,
                        Sujeto.dni,
                        Sujeto.imagen,
                    ).join(CargaLlamada, ResultadoTraficoVOZ.carga_id == CargaLlamada.id) \
                     .join(Sujeto, CargaLlamada.sujeto_id == Sujeto.id) \
                     .filter(
                         CargaLlamada.unidad_id == current_user.unidad_id,
                         _carga_access_predicate(),
                         ResultadoTraficoVOZ.numero.in_(faltantes),
                         Sujeto.id.in_(accesibles_ids) if accesibles_ids else text("0=1"),
                     ).order_by(ResultadoTraficoVOZ.numero, Sujeto.id)
                    model_rows = q_num_imp.all()
                else:
                    q_num_imp = db.session.query(
                        ResultadoTraficoGPRS.numero,
                        Sujeto.id,
                        Sujeto.apodo,
                        Sujeto.nombre,
                        Sujeto.dni,
                        Sujeto.imagen,
                    ).join(CargaLlamada, ResultadoTraficoGPRS.carga_id == CargaLlamada.id) \
                     .join(Sujeto, CargaLlamada.sujeto_id == Sujeto.id) \
                     .filter(
                         CargaLlamada.unidad_id == current_user.unidad_id,
                         _carga_access_predicate(),
                         ResultadoTraficoGPRS.numero.in_(faltantes),
                     ).order_by(ResultadoTraficoGPRS.numero, Sujeto.id)
                    model_rows = q_num_imp.all()

                for num, sid, apodo, nombre, dni, imagen in model_rows:
                    key = str(num).strip()
                    if key and key not in sujetos_por_numero:
                        display = nombre or apodo or (f"DNI {dni}" if dni else f"Sujeto #{sid}")
                        img_url = url_for('sabana_llamadas.sujetos_imagen', sujeto_id=sid, _external=True) if imagen else None
                        sujetos_por_numero[key] = {
                            'id': sid,
                            'display': display,
                            'imagen_url': img_url,
                        }
        except Exception:
            sujetos_por_numero = {}

    relaciones_data = []
    for r in rows:
        sa = sujetos_por_numero.get(str(r.numero_a).strip()) if getattr(r, 'numero_a', None) else None
        if is_gprs:
            sb = None
        else:
            sb = sujetos_por_numero.get(str(r.numero_b).strip()) if getattr(r, 'numero_b', None) else None
        relaciones_data.append({
            'numero_a': r.numero_a,
            'numero_b': r.numero_b,
            'cantidad': int(r.cantidad or 0),
            'primera_fecha': r.primera_fecha,
            'ultima_fecha': r.ultima_fecha,
            'sujeto_a': sa,
            'sujeto_b': sb,
        })

    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre, Sujeto.dni).all()
    cargas_voz = _cargas_query_accessible().filter(
        CargaLlamada.tipo == 'voz'
    ).order_by(CargaLlamada.created_at.desc()).all()
    cargas_gprs = _cargas_query_accessible().filter(
        CargaLlamada.tipo == 'gprs'
    ).order_by(CargaLlamada.created_at.desc()).all()

    fuentes_record = []
    if caso:
        st_f = 'VOZ' if is_voz else 'GPRS'
        fuentes_record = AnalisisPuntoFuente.query.filter(
            AnalisisPuntoFuente.caso_id == caso.id,
            AnalisisPuntoFuente.unidad_id == current_user.unidad_id,
            AnalisisPuntoFuente.source_type == st_f,
        ).order_by(AnalisisPuntoFuente.created_at.desc()).limit(500).all()

    casos_record = _casos_ap_para_unidad()[:200]

    fuente_ids_req = [int(x) for x in request.args.getlist('fuente_ids[]', type=int) if x and int(x) > 0]
    filtros = {
        'origen': origen,
        'tipo_trafico': tipo_tf,
        'caso_id': caso_id,
        'fuente_id': request.args.get('fuente_id', type=int),
        'fuente_ids': fuente_ids_req,
        'sujeto_id': sujeto_id,
        'carga_id': carga_id,
        'sujeto_ids': mf['sujeto_ids'],
        'carga_ids': mf['carga_ids'],
        'numeros_sel': mf['numeros'],
        'imeis_sel': mf['imeis'],
        'provincias_sel': mf['provincias'],
        'localidades_sel': mf['localidades'],
        'numero': numero_raw,
        'fecha_desde': fecha_desde_str,
        'fecha_hasta': fecha_hasta_str,
        'hora_desde': hora_desde_str,
        'hora_hasta': hora_hasta_str,
        'limit': limit,
    }

    unidad_label = ''
    try:
        if current_user.unidad_id:
            u = Unidad.query.get(current_user.unidad_id)
            unidad_label = u.nombre if u else ''
    except Exception:
        unidad_label = ''

    cargas_list = cargas_gprs if is_gprs else cargas_voz
    sujetos_sel_txt = ', '.join(
        s.display_name() for s in sujetos if s.id in (mf['sujeto_ids'] or [])
    )
    cargas_sel_txt = ', '.join(
        f"#{c.id} {c.nombre_archivo or ''}".strip() for c in cargas_list if c.id in (mf['carga_ids'] or [])
    )
    fuente_ids_meta = list(fuente_ids_req)
    if filtros.get('fuente_id') and filtros['fuente_id'] not in fuente_ids_meta:
        fuente_ids_meta.append(filtros['fuente_id'])
    fuentes_sel_txt = ', '.join(
        (f.nombre_archivo or f"#{f.id}") for f in fuentes_record if f.id in fuente_ids_meta
    )

    informe_meta = {
        'unidad': unidad_label,
        'usuario': getattr(current_user, 'username', '') or '',
        'generado_en_utc': datetime.utcnow().isoformat() + 'Z',
        'filtros': {
            'origen': 'Sábana' if origen == 'sabana' else 'Record',
            'tipo': tipo_tf.upper(),
            'caso': (f"{caso.codigo} — {caso.titulo}" if caso else ''),
            'sujeto': next((s.display_name() for s in sujetos if sujeto_id and s.id == sujeto_id), '') if sujeto_id else '',
            'sujetos': sujetos_sel_txt,
            'carga_voz': next((f"#{c.id} {c.nombre_archivo or ''}" for c in cargas_voz if carga_id and c.id == carga_id), '') if (is_voz and carga_id) else '',
            'carga_gprs': next((f"#{c.id} {c.nombre_archivo or ''}" for c in cargas_gprs if carga_id and c.id == carga_id), '') if (is_gprs and carga_id) else '',
            'cargas': cargas_sel_txt,
            'fuentes_record': fuentes_sel_txt,
            'provincias': ', '.join(mf['provincias'] or []),
            'localidades': ', '.join(mf['localidades'] or []),
            'numeros': ', '.join(mf['numeros'] or []),
            'imeis': ', '.join(mf['imeis'] or []),
            'numero': numero_raw,
            'fecha_desde': fecha_desde_str,
            'fecha_hasta': fecha_hasta_str,
            'hora_desde': hora_desde_str,
            'hora_hasta': hora_hasta_str,
            'limit': limit,
        },
    }

    return render_template(
        'sabana_llamadas/relaciones.html',
        sujetos=sujetos,
        cargas_voz=cargas_voz,
        cargas_gprs=cargas_gprs,
        casos_record=casos_record,
        fuentes_record=fuentes_record,
        caso=caso,
        relaciones=relaciones_data,
        filtros=filtros,
        informe_meta=informe_meta,
        informe_sabana=(origen == 'sabana'),
        gprs_record_truncated=gprs_record_truncated,
    )


@bp.route('/gprs/relaciones')
def relaciones_gprs():
    """Compatibilidad: redirige a la vista unificada con tráfico GPRS."""
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    from urllib.parse import urlencode
    pairs = [(k, v) for k, v in request.args.items(multi=True) if k != 'tipo_trafico']
    pairs.append(('tipo_trafico', 'gprs'))
    qs = urlencode(pairs)
    return redirect(url_for('sabana_llamadas.relaciones') + ('?' + qs if qs else ''))


def _sujetos_list_data():
    """Lista accesible y conteo de cargas por sujeto (misma lógica que la vista listado)."""
    lista = _sujetos_query_accessible().order_by(Sujeto.updated_at.desc()).all()
    sujeto_ids = [s.id for s in lista] if lista else []
    cargas_count = {}
    if sujeto_ids:
        rows = db.session.query(
            CargaLlamada.sujeto_id,
            func.count(CargaLlamada.id),
        ).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            CargaLlamada.sujeto_id.in_(sujeto_ids),
        ).group_by(CargaLlamada.sujeto_id).all()
        cargas_count = {int(sid): int(cnt or 0) for sid, cnt in rows if sid is not None}
    return lista, cargas_count


def _sujeto_form_persona_choices():
    return [('', '-- Sin vincular --')] + [
        (p.id, f"{p.nombre_completo} (DNI {p.dni})")
        for p in Persona.query.order_by(Persona.apellido).limit(500).all()
    ]


@bp.route('/sujetos')
def sujetos_list():
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    lista, cargas_count = _sujetos_list_data()
    form_nuevo = None
    if current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        form_nuevo = SujetoNuevoForm()
        form_nuevo.persona_id.choices = _sujeto_form_persona_choices()
        casos_ap = _casos_ap_para_unidad()
        form_nuevo.caso_id.choices = [('', '-- Sin vincular a un caso --')] + [
            (c.id, f'{c.codigo} — {c.titulo}') for c in casos_ap
        ]
    return render_template(
        'sabana_llamadas/sujetos_list.html',
        sujetos=lista,
        cargas_count=cargas_count,
        form_nuevo=form_nuevo,
        abrir_modal_nuevo=False,
    )


@bp.route('/sujetos/nuevo', methods=['GET', 'POST'])
def sujetos_nuevo():
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para crear sujetos.', 'warning')
        return redirect(url_for('sabana_llamadas.sujetos_list'))
    if request.method == 'GET':
        return redirect(url_for('sabana_llamadas.sujetos_list', nuevo=1))
    form = SujetoNuevoForm()
    form.persona_id.choices = _sujeto_form_persona_choices()
    casos_ap = _casos_ap_para_unidad()
    form.caso_id.choices = [('', '-- Sin vincular a un caso --')] + [
        (c.id, f'{c.codigo} — {c.titulo}') for c in casos_ap
    ]
    if form.validate_on_submit():
        s = Sujeto(
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            apodo=form.apodo.data or None,
            nombre=form.nombre.data or None,
            dni=form.dni.data or None,
            observaciones=form.observaciones.data or None,
            persona_id=form.persona_id.data or None,
        )
        db.session.add(s)
        db.session.commit()
        if form.imagen.data and form.imagen.data.filename:
            ruta, err = guardar_imagen_sujeto(form.imagen.data, current_user.unidad_id, s.id)
            if not err and ruta:
                s.imagen = ruta
                db.session.commit()
        cid = form.caso_id.data
        if cid:
            caso_ok = AnalisisPuntoCaso.query.filter_by(id=cid, unidad_id=current_user.unidad_id).first()
            if caso_ok:
                ya = AnalisisPuntoCasoSujeto.query.filter_by(caso_id=caso_ok.id, sujeto_id=s.id).first()
                if not ya:
                    db.session.add(AnalisisPuntoCasoSujeto(
                        caso_id=caso_ok.id,
                        sujeto_id=s.id,
                        unidad_id=current_user.unidad_id,
                        user_id=current_user.id,
                    ))
                    db.session.commit()
        flash('Sujeto creado correctamente.', 'success')
        return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=s.id))
    lista, cargas_count = _sujetos_list_data()
    return render_template(
        'sabana_llamadas/sujetos_list.html',
        sujetos=lista,
        cargas_count=cargas_count,
        form_nuevo=form,
        abrir_modal_nuevo=True,
    )


@bp.route('/sujetos/<int:sujeto_id>')
def sujetos_ver(sujeto_id):
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    sujeto = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first_or_404()
    # Importante: no usar sujeto.cargas directo, porque puede incluir cargas no accesibles
    # (por ejemplo, si el acceso al sujeto vino por una carga compartida).
    cargas = _cargas_query_accessible().options(joinedload(CargaLlamada.caso)) \
        .filter(CargaLlamada.sujeto_id == sujeto.id) \
        .order_by(CargaLlamada.created_at.desc()).all()

    # Números asignados explícitamente al sujeto
    numeros_exp = SujetoNumero.query.filter_by(
        unidad_id=current_user.unidad_id,
        sujeto_id=sujeto.id,
    ).order_by(SujetoNumero.numero).all()

    # Números detectados en cargas VOZ/GPRS de este sujeto (sugerencias)
    numeros_detectados = set()
    if cargas:
        carga_ids = [c.id for c in cargas]
        # VOZ
        rows_voz = ResultadoTraficoVOZ.query.filter(
            ResultadoTraficoVOZ.carga_id.in_(carga_ids),
            ResultadoTraficoVOZ.numero.isnot(None),
            ResultadoTraficoVOZ.numero != '',
        ).with_entities(ResultadoTraficoVOZ.numero).distinct().all()
        for (num,) in rows_voz:
            n = (num or '').strip()
            if n:
                numeros_detectados.add(n)
        # GPRS
        rows_gprs = ResultadoTraficoGPRS.query.filter(
            ResultadoTraficoGPRS.carga_id.in_(carga_ids),
            ResultadoTraficoGPRS.numero.isnot(None),
            ResultadoTraficoGPRS.numero != '',
        ).with_entities(ResultadoTraficoGPRS.numero).distinct().all()
        for (num,) in rows_gprs:
            n = (num or '').strip()
            if n:
                numeros_detectados.add(n)

    # Quitar los que ya están explícitos
    exp_set = { (n.numero or '').strip() for n in numeros_exp if n.numero }
    sugeridos = sorted([n for n in numeros_detectados if n not in exp_set])

    return render_template(
        'sabana_llamadas/sujeto_ver.html',
        sujeto=sujeto,
        cargas=cargas,
        numeros_exp=numeros_exp,
        numeros_sugeridos=sugeridos,
    )


@bp.route('/sujetos/<int:sujeto_id>/imagen')
def sujetos_imagen(sujeto_id):
    """Sirve la imagen del sujeto desde instance/uploads."""
    sujeto = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first_or_404()
    if not sujeto.imagen:
        return '', 404
    upload_folder = current_app.config['UPLOAD_FOLDER']
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(current_app.root_path, upload_folder)
    full_path = os.path.join(upload_folder, sujeto.imagen)
    if not os.path.isfile(full_path):
        return '', 404
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    mime, _ = mimetypes.guess_type(full_path)
    return send_from_directory(directory, filename, mimetype=mime or 'application/octet-stream')


@bp.route('/sujetos/<int:sujeto_id>/editar', methods=['GET', 'POST'])
def sujetos_editar(sujeto_id):
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para editar.', 'warning')
        return redirect(url_for('sabana_llamadas.sujetos_list'))
    sujeto = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first_or_404()
    _assert_owner_or_404(sujeto)
    form = SujetoForm(obj=sujeto)
    form.persona_id.choices = _sujeto_form_persona_choices()
    if form.validate_on_submit():
        sujeto.apodo = form.apodo.data or None
        sujeto.nombre = form.nombre.data or None
        sujeto.dni = form.dni.data or None
        sujeto.observaciones = form.observaciones.data or None
        sujeto.persona_id = form.persona_id.data or None
        # En algunos entornos, form.imagen.data puede ser string vacío en vez de FileStorage;
        # comprobamos de forma segura antes de acceder a .filename.
        img_data = form.imagen.data
        try:
            has_file = bool(img_data) and hasattr(img_data, 'filename') and bool(img_data.filename)
        except Exception:
            has_file = False
        if has_file:
            ruta, err = guardar_imagen_sujeto(img_data, current_user.unidad_id, sujeto.id)
            if not err and ruta:
                sujeto.imagen = ruta
        db.session.commit()
        flash('Sujeto actualizado.', 'success')
        return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=sujeto.id))
    return render_template('sabana_llamadas/sujeto_form.html', form=form, sujeto=sujeto)


@bp.route('/sujetos/<int:sujeto_id>/numeros', methods=['POST'])
def sujetos_add_numero(sujeto_id):
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para editar.', 'warning')
        return redirect(url_for('sabana_llamadas.sujetos_list'))
    sujeto = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first_or_404()
    _assert_owner_or_404(sujeto)
    numero = (request.form.get('numero') or '').strip()
    if not numero:
        flash('Número vacío.', 'warning')
        return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=sujeto.id))
    # Normalizar básico
    numero_norm = numero.replace(' ', '')
    # Evitar duplicados exactos para este sujeto
    exists_num = SujetoNumero.query.filter_by(
        unidad_id=current_user.unidad_id,
        sujeto_id=sujeto.id,
        numero=numero_norm,
    ).first()
    if exists_num:
        flash('El número ya está asignado a este sujeto.', 'info')
        return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=sujeto.id))

    sn = SujetoNumero(
        unidad_id=current_user.unidad_id,
        sujeto_id=sujeto.id,
        numero=numero_norm,
        notas=(request.form.get('notas') or '').strip() or None,
    )
    db.session.add(sn)
    db.session.commit()
    flash(f'Número {numero_norm} asignado al sujeto.', 'success')
    return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=sujeto.id))


@bp.route('/sujetos/<int:sujeto_id>/numeros/<int:num_id>/eliminar', methods=['POST'])
def sujetos_del_numero(sujeto_id, num_id):
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para editar.', 'warning')
        return redirect(url_for('sabana_llamadas.sujetos_list'))
    sujeto = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first_or_404()
    _assert_owner_or_404(sujeto)
    sn = SujetoNumero.query.filter_by(id=num_id, sujeto_id=sujeto.id, unidad_id=current_user.unidad_id).first_or_404()
    db.session.delete(sn)
    db.session.commit()
    flash(f'Número {sn.numero} eliminado del sujeto.', 'success')
    return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=sujeto.id))


def _query_casos_accesibles():
    """Consulta base: casos de la unidad visibles para el usuario (dueño o compartido)."""
    q = AnalisisPuntoCaso.query.filter(AnalisisPuntoCaso.unidad_id == current_user.unidad_id)
    if not _is_superadmin():
        shared_case = exists().where(and_(
            AnalisisPuntoCasoCompartido.caso_id == AnalisisPuntoCaso.id,
            AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
        ))
        q = q.filter(or_(AnalisisPuntoCaso.user_id == current_user.id, shared_case))
    return q


def _casos_ap_para_unidad():
    """Casos investigativos (ap_casos) de la unidad, más recientes primero."""
    return _query_casos_accesibles().order_by(AnalisisPuntoCaso.created_at.desc()).all()


def _get_caso_accesible(caso_id):
    if not caso_id:
        return None
    try:
        cid = int(caso_id)
    except Exception:
        return None
    if cid <= 0:
        return None
    return _query_casos_accesibles().filter(AnalisisPuntoCaso.id == cid).first()


def _apply_mapa_caso_arg_to_carga_query(q_cargas):
    """Si viene ?caso_id= en el request, limita las cargas de sábana a ese caso (con control de acceso)."""
    cid = request.args.get('caso_id', type=int)
    if not cid:
        return q_cargas
    caso = _get_caso_accesible(cid)
    if not caso:
        return q_cargas.filter(CargaLlamada.id == -1)
    return q_cargas.filter(CargaLlamada.caso_id == caso.id)


@bp.route('/gprs/upload', methods=['GET', 'POST'])
def gprs_upload():
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para subir archivos GPRS.', 'warning')
        return redirect(url_for('sabana_llamadas.index'))
    form = UploadGPRSForm()
    casos_ap = _casos_ap_para_unidad()
    form.operadora.choices = [
        ('', 'Seleccionar…'),
        ('PERSONAL', 'PERSONAL'),
        ('MOVISTAR', 'MOVISTAR'),
        ('CLARO', 'CLARO'),
        ('OTRA', 'OTRA'),
    ]
    form.caso_id.choices = [(0, 'Seleccionar caso…')] + [(c.id, f'{c.codigo} — {c.titulo}') for c in casos_ap]
    # Solo sujetos accesibles (dueño o compartidos). Evita vincular cargas a sujetos de terceros sin acceso.
    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
    form.sujeto_id.choices = [('', '-- Sin vincular --')] + [(s.id, s.display_name()) for s in sujetos]
    if form.validate_on_submit():
        sujeto_id = form.sujeto_id.data if form.sujeto_id.data else None
        caso = AnalisisPuntoCaso.query.filter_by(id=form.caso_id.data, unidad_id=current_user.unidad_id).first()
        if not caso:
            flash('Caso inválido o no pertenece a su unidad.', 'warning')
            return render_template('sabana_llamadas/upload_gprs.html', form=form, casos_ap=casos_ap)
        carga, ct, cd, err = procesar_archivo_gprs(
            form.file.data,
            current_user.unidad_id,
            current_user.id,
            sujeto_id,
            operadora=form.operadora.data,
            caso_id=form.caso_id.data,
        )
        if err:
            flash(f'Error: {err}', 'danger')
        else:
            flash(f'Carga GPRS correcta: {ct} registros de tráfico, {cd} datos técnicos.', 'success')
            return redirect(url_for('sabana_llamadas.gprs_upload'))
    return render_template('sabana_llamadas/upload_gprs.html', form=form, casos_ap=casos_ap)


@bp.route('/voz/upload', methods=['GET', 'POST'])
def voz_upload():
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para subir archivos VOZ.', 'warning')
        return redirect(url_for('sabana_llamadas.index'))
    form = UploadVOZForm()
    casos_ap = _casos_ap_para_unidad()
    form.operadora.choices = [
        ('', 'Seleccionar…'),
        ('PERSONAL', 'PERSONAL'),
        ('MOVISTAR', 'MOVISTAR'),
        ('CLARO', 'CLARO'),
        ('OTRA', 'OTRA'),
    ]
    form.caso_id.choices = [(0, 'Seleccionar caso…')] + [(c.id, f'{c.codigo} — {c.titulo}') for c in casos_ap]
    # Solo sujetos accesibles (dueño o compartidos). Evita vincular cargas a sujetos de terceros sin acceso.
    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
    form.sujeto_id.choices = [('', '-- Sin vincular --')] + [(s.id, s.display_name()) for s in sujetos]
    if form.validate_on_submit():
        sujeto_id = form.sujeto_id.data if form.sujeto_id.data else None
        caso = AnalisisPuntoCaso.query.filter_by(id=form.caso_id.data, unidad_id=current_user.unidad_id).first()
        if not caso:
            flash('Caso inválido o no pertenece a su unidad.', 'warning')
            return render_template('sabana_llamadas/upload_voz.html', form=form, casos_ap=casos_ap)
        carga, ct, cd, err = procesar_archivo_voz(
            form.file.data,
            current_user.unidad_id,
            current_user.id,
            sujeto_id,
            operadora=form.operadora.data,
            caso_id=form.caso_id.data,
        )
        if err:
            flash(f'Error: {err}', 'danger')
        else:
            flash(f'Carga VOZ correcta: {ct} registros de tráfico, {cd} datos técnicos.', 'success')
            return redirect(url_for('sabana_llamadas.voz_upload'))
    return render_template('sabana_llamadas/upload_voz.html', form=form, casos_ap=casos_ap)


def _cargas_list_context():
    """Contexto común para la vista de listado + modal de carga unificada."""
    try:
        cargas_sabana = (
            _cargas_query_accessible()
            .options(joinedload(CargaLlamada.caso), joinedload(CargaLlamada.sujeto))
            .order_by(CargaLlamada.created_at.desc())
            .all()
        )
    except OperationalError as e:
        if "1412" in str(e):
            try:
                db.session.rollback()
            except Exception:
                pass
            cargas_sabana = (
                _cargas_query_accessible()
                .options(joinedload(CargaLlamada.caso), joinedload(CargaLlamada.sujeto))
                .order_by(CargaLlamada.created_at.desc())
                .all()
            )
        else:
            raise
    q_records = (
        AnalisisPuntoFuente.query
        .options(joinedload(AnalisisPuntoFuente.caso))
        .filter(
            AnalisisPuntoFuente.unidad_id == current_user.unidad_id,
            AnalisisPuntoFuente.source_type.in_(["VOZ", "GPRS"]),
        )
    )
    if not _is_superadmin():
        shared_case = exists().where(and_(
            AnalisisPuntoCasoCompartido.caso_id == AnalisisPuntoFuente.caso_id,
            AnalisisPuntoCasoCompartido.shared_with_user_id == current_user.id,
        ))
        q_records = q_records.filter(or_(AnalisisPuntoFuente.user_id == current_user.id, shared_case))
    fuentes_record = q_records.order_by(AnalisisPuntoFuente.created_at.desc()).all()
    cargas_historial = []
    for c in cargas_sabana:
        cargas_historial.append({"kind": "sabana", "created_at": c.created_at, "carga": c})
    for f in fuentes_record:
        cargas_historial.append({"kind": "record", "created_at": f.created_at, "fuente": f})
    cargas_historial.sort(key=lambda r: r.get("created_at") or datetime.min, reverse=True)

    sujetos_modal = []
    casos_modal = []
    if current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        sujetos_modal = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
        casos_modal = _casos_ap_para_unidad()
    return {
        'cargas': cargas_sabana,
        'cargas_historial': cargas_historial,
        'sujetos_modal': sujetos_modal,
        'casos_modal': casos_modal,
        'puede_cargar': current_user.has_permission('SABANA_LLAMADAS_UPLOAD'),
        'parse_sabana_processing_detail': _parse_sabana_processing_detail,
    }


@bp.route('/cargas/upload', methods=['GET', 'POST'])
def cargas_upload_unificado():
    """
    POST: procesa carga unificada (sábana o record). GET: redirige al listado con modal.
    """
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para subir archivos.', 'warning')
        return redirect(url_for('sabana_llamadas.cargas_list'))
    if request.method == 'GET':
        return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))

    if request.method == 'POST':
        operadora = (request.form.get('operadora') or '').strip().upper()
        tipo_carga = (request.form.get('tipo_carga') or '').strip().lower()
        sujeto_id = request.form.get('sujeto_id', type=int)
        caso_id = request.form.get('caso_id', type=int)
        f = request.files.get('file')

        if operadora not in {'PERSONAL', 'MOVISTAR', 'CLARO', 'OTRA'}:
            flash('Debe seleccionar una operadora válida.', 'warning')
            return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))
        if tipo_carga not in {
            'sabana_gprs', 'sabana_voz', 'sabana_claro', 'sabana_movistar',
            'record_voz', 'record_gprs', 'record_claro',
        }:
            flash('Debe seleccionar un tipo de archivo válido.', 'warning')
            return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))
        if not f or not f.filename:
            flash('Debe seleccionar un archivo.', 'warning')
            return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))

        if not caso_id:
            flash('Debe seleccionar un caso investigativo antes de cargar archivos (orden: Caso → Sujeto opcional → archivo).', 'warning')
            return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))
        caso = AnalisisPuntoCaso.query.filter_by(id=caso_id, unidad_id=current_user.unidad_id).first()
        if not caso:
            flash('Caso inválido o no pertenece a su unidad.', 'warning')
            return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))

        # Validaciones de destino
        if tipo_carga.startswith('sabana') and sujeto_id:
            sujeto_ok = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first()
            if not sujeto_ok:
                flash('Sujeto inválido o sin acceso.', 'warning')
                return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))

        # Dispatch por tipo
        if tipo_carga == 'sabana_claro':
            if operadora != 'CLARO':
                flash('La sábana Claro completa requiere operadora CLARO.', 'warning')
                return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))
            carga_voz, carga_gprs, stats, err = procesar_archivo_claro(
                f, current_user.unidad_id, current_user.id, sujeto_id or None,
                operadora=operadora, caso_id=caso_id,
            )
            if err:
                flash(f'Error cargando sábana Claro: {err}', 'danger')
            else:
                flash(
                    f'Sábana Claro procesada: VOZ {stats.get("voz", 0)} eventos '
                    f'({stats.get("entrantes", 0)} entrantes, {stats.get("salientes_voz", 0)} salientes voz) '
                    f'→ carga #{carga_voz.id}; GPRS {stats.get("gprs", 0)} conexiones móviles '
                    f'→ carga #{carga_gprs.id}.',
                    'success',
                )
            return redirect(url_for('sabana_llamadas.cargas_list'))

        if tipo_carga == 'sabana_movistar':
            if operadora != 'MOVISTAR':
                flash('La sábana Movistar (TEMIS) requiere operadora MOVISTAR.', 'warning')
                return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))
            carga_voz, carga_gprs, stats, err = procesar_archivo_movistar(
                f, current_user.unidad_id, current_user.id, sujeto_id or None,
                operadora=operadora, caso_id=caso_id,
            )
            if err:
                flash(f'Error cargando sábana Movistar: {err}', 'danger')
            else:
                partes = []
                if carga_voz is not None:
                    partes.append(
                        f'VOZ {stats.get("voz", 0)} eventos '
                        f'({stats.get("salientes", 0)} sal. / {stats.get("entrantes", 0)} ent.) '
                        f'→ #{carga_voz.id}'
                    )
                if carga_gprs is not None:
                    partes.append(
                        f'GPRS/Datos {stats.get("gprs", 0)} eventos → #{carga_gprs.id}'
                    )
                if not partes:
                    flash('Sábana Movistar procesada sin eventos.', 'warning')
                else:
                    flash('Sábana Movistar (TEMIS) procesada: ' + '; '.join(partes) + '.', 'success')
            return redirect(url_for('sabana_llamadas.cargas_list'))

        if tipo_carga == 'sabana_gprs':
            _, ct, cd, err = procesar_archivo_gprs(
                f, current_user.unidad_id, current_user.id, sujeto_id or None,
                operadora=operadora, caso_id=caso_id,
            )
            if err:
                flash(f'Error cargando sábana GPRS: {err}', 'danger')
            else:
                flash(f'Sábana GPRS cargada: {ct} tráfico, {cd} técnicos.', 'success')
            return redirect(url_for('sabana_llamadas.cargas_list'))

        if tipo_carga == 'sabana_voz':
            _, ct, cd, err = procesar_archivo_voz(
                f, current_user.unidad_id, current_user.id, sujeto_id or None,
                operadora=operadora, caso_id=caso_id,
            )
            if err:
                flash(f'Error cargando sábana VOZ: {err}', 'danger')
            else:
                flash(f'Sábana VOZ cargada: {ct} tráfico, {cd} técnicos.', 'success')
            return redirect(url_for('sabana_llamadas.cargas_list'))

        # Record Claro unificado (VOZ + GPRS)
        if tipo_carga == 'record_claro':
            if operadora != 'CLARO':
                flash('El record Claro completo requiere operadora CLARO.', 'warning')
                return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))

            filename = secure_filename(f.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext not in {'.xlsx', '.xls', '.csv'}:
                flash('Formato no permitido. Use .xlsx, .xls o .csv.', 'warning')
                return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))

            base_dir = current_app.config.get('UPLOAD_FOLDER', 'instance/uploads')
            if not os.path.isabs(base_dir):
                base_dir = os.path.join(current_app.root_path, base_dir)
            target_dir = os.path.join(base_dir, 'analisis_puntos', str(current_user.unidad_id), str(caso_id))
            os.makedirs(target_dir, exist_ok=True)
            safe_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
            path = os.path.join(target_dir, safe_name)
            f.save(path)

            sha256 = hashlib.sha256()
            with open(path, 'rb') as rf:
                for chunk in iter(lambda: rf.read(8192), b''):
                    sha256.update(chunk)
            sha = sha256.hexdigest()
            size = os.path.getsize(path)

            fuente_voz = AnalisisPuntoFuente(
                caso_id=caso_id,
                unidad_id=current_user.unidad_id,
                user_id=current_user.id,
                source_type='VOZ',
                operadora=operadora,
                nombre_archivo=safe_name,
                sha256=sha,
                mime_type=f.mimetype,
                size_bytes=size,
                upload_status='PENDING',
            )
            fuente_gprs = AnalisisPuntoFuente(
                caso_id=caso_id,
                unidad_id=current_user.unidad_id,
                user_id=current_user.id,
                source_type='GPRS',
                operadora=operadora,
                nombre_archivo=safe_name,
                sha256=sha,
                mime_type=f.mimetype,
                size_bytes=size,
                upload_status='PENDING',
            )
            db.session.add(fuente_voz)
            db.session.add(fuente_gprs)
            db.session.commit()

            try:
                stats = procesar_record_claro(fuente_voz, fuente_gprs, path)
                flash(
                    f'Record Claro procesado: VOZ {stats.get("voz", 0)} eventos '
                    f'({stats.get("entrantes", 0)} entrantes, {stats.get("salientes_voz", 0)} salientes voz) '
                    f'→ fuente #{fuente_voz.id}; GPRS {stats.get("gprs", 0)} sesiones datos '
                    f'→ fuente #{fuente_gprs.id}.',
                    'success',
                )
            except Exception as e:
                try:
                    fuente_voz.upload_status = 'ERROR'
                    fuente_voz.error_detail = str(e)
                    fuente_gprs.upload_status = 'ERROR'
                    fuente_gprs.error_detail = str(e)
                    db.session.add(fuente_voz)
                    db.session.add(fuente_gprs)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                flash(f'Record Claro subido, pero falló el procesamiento: {e}', 'warning')
            return redirect(url_for('sabana_llamadas.cargas_list'))

        # Record VOZ / GPRS (Personal / formato clásico)
        filename = secure_filename(f.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {'.xlsx', '.xls', '.csv'}:
            flash('Formato no permitido. Use .xlsx, .xls o .csv.', 'warning')
            return redirect(url_for('sabana_llamadas.cargas_list', nuevo=1))

        base_dir = current_app.config.get('UPLOAD_FOLDER', 'instance/uploads')
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(current_app.root_path, base_dir)
        target_dir = os.path.join(base_dir, 'analisis_puntos', str(current_user.unidad_id), str(caso_id))
        os.makedirs(target_dir, exist_ok=True)
        safe_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
        path = os.path.join(target_dir, safe_name)
        f.save(path)

        sha256 = hashlib.sha256()
        with open(path, 'rb') as rf:
            for chunk in iter(lambda: rf.read(8192), b''):
                sha256.update(chunk)

        source_type = 'VOZ' if tipo_carga == 'record_voz' else 'GPRS'
        src = AnalisisPuntoFuente(
            caso_id=caso_id,
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            source_type=source_type,
            operadora=operadora,
            nombre_archivo=safe_name,
            sha256=sha256.hexdigest(),
            mime_type=f.mimetype,
            size_bytes=os.path.getsize(path),
            upload_status='PENDING',
        )
        db.session.add(src)
        db.session.commit()

        # Record VOZ/GPRS: procesar automáticamente.
        if source_type == 'VOZ':
            try:
                res = procesar_fuente_voz(src, path)
                total = int((res or {}).get('eventos_importados', 0))
                omit = int((res or {}).get('filas_omitidas_total', 0))
                leidas = int((res or {}).get('filas_trafico_leidas', total + omit))
                flash(f'Record VOZ cargado y procesado: {total} eventos (filas leídas: {leidas}, omitidas vacías: {omit}).', 'success')
            except Exception as e:
                try:
                    src.upload_status = 'ERROR'
                    src.error_detail = str(e)
                    db.session.add(src)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                flash(f'Record VOZ subido, pero falló el procesamiento: {e}', 'warning')
        else:
            try:
                res = procesar_fuente_gprs(src, path)
                total = int((res or {}).get('eventos_importados', 0))
                omit = int((res or {}).get('filas_omitidas_total', 0))
                leidas = int((res or {}).get('filas_trafico_leidas', total + omit))
                flash(f'Record GPRS cargado y procesado: {total} eventos (filas leídas: {leidas}, omitidas vacías: {omit}).', 'success')
            except Exception as e:
                try:
                    src.upload_status = 'ERROR'
                    src.error_detail = str(e)
                    db.session.add(src)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                flash(f'Record GPRS subido, pero falló el procesamiento: {e}', 'warning')

        return redirect(url_for('sabana_llamadas.cargas_list'))

    return redirect(url_for('sabana_llamadas.cargas_list'))


@bp.route('/mapa')
def mapa():
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    casos_record = _casos_ap_para_unidad()[:200]
    return render_template('sabana_llamadas/mapa.html', casos_record=casos_record)


def _serialize_gprs(r):
    """Serializa un registro ResultadoTraficoGPRS para JSON."""
    return {
        'id': r.id,
        'tipo': 'gprs',
        'imei': r.imei,
        'imsi': r.imsi,
        'numero': getattr(r, 'numero', None),
        'fecha': r.fecha.isoformat() if r.fecha else None,
        'hora': r.hora,
        'duracion': r.duracion,
        'ip': r.ip,
        'ip_dual_stack': r.ip_dual_stack,
        'volumen_kb': r.volumen_kb,
        'celda': r.celda,
        'celda_direccion': r.celda_direccion,
        'celda_localidad': r.celda_localidad,
        'celda_provincia': r.celda_provincia,
        'ip_wifi': r.ip_wifi,
    }


def _serialize_voz(r):
    """Serializa un registro ResultadoTraficoVOZ para JSON."""
    return {
        'id': r.id,
        'tipo': 'voz',
        'imei': r.imei,
        'imsi': r.imsi,
        'numero': getattr(r, 'numero', None),
        'fecha': r.fecha.isoformat() if r.fecha else None,
        'hora': r.hora,
        'tipo_llamada': r.tipo,
        'duracion': r.duracion,
        'otro': r.otro,
        'celda_id': r.celda_id,
        'celda_calle_altura': r.celda_calle_altura,
        'celda_localidad': r.celda_localidad,
        'celda_provincia': r.celda_provincia,
    }


def _serialize_record_voz_event(ev):
    """Serializa ap_eventos tipo VOZ para el mismo panel que sábana VOZ."""
    fd = None
    try:
        if ev.event_dt:
            fd = ev.event_dt.date().isoformat()
    except Exception:
        fd = None
    hora = None
    try:
        if ev.event_dt:
            hora = ev.event_dt.strftime('%H:%M:%S')
    except Exception:
        hora = None
    dur = str(ev.duration_sec) if ev.duration_sec is not None else None
    return {
        'id': ev.id,
        'tipo': 'voz',
        '_record': True,
        'imei': ev.imei,
        'imsi': ev.imsi,
        'numero': ev.origin_msisdn,
        'fecha': fd,
        'hora': hora,
        'tipo_llamada': ev.event_type,
        'duracion': dur,
        'otro': ev.target_msisdn,
        'celda_id': ev.raw_cell_code,
        'celda_calle_altura': None,
        'celda_localidad': None,
        'celda_provincia': None,
    }


def _serialize_record_gprs_event(ev):
    """Serializa ap_eventos tipo GPRS para el mismo panel que sábana GPRS."""
    fd = None
    try:
        if ev.event_dt:
            fd = ev.event_dt.date().isoformat()
    except Exception:
        fd = None
    hora = None
    try:
        if ev.event_dt:
            hora = ev.event_dt.strftime('%H:%M:%S')
    except Exception:
        hora = None
    payload = {}
    try:
        import json as _json
        payload = _json.loads(ev.raw_payload_json) if ev.raw_payload_json else {}
    except Exception:
        payload = {}
    return {
        'id': ev.id,
        'tipo': 'gprs',
        '_record': True,
        'imei': ev.imei,
        'imsi': ev.imsi,
        'numero': ev.origin_msisdn,
        'fecha': fd,
        'hora': hora,
        'duracion': str(ev.duration_sec) if ev.duration_sec is not None else None,
        'ip': payload.get('IP') or payload.get('ip'),
        'ip_dual_stack': payload.get('IP Dual Stack') or payload.get('IP Dual stack'),
        'volumen_kb': payload.get('Volumen (kb)') or payload.get('Volumen(kb)') or payload.get('Volumen KB'),
        'celda': ev.raw_cell_code,
        'celda_direccion': None,
        'celda_localidad': None,
        'celda_provincia': None,
        'ip_wifi': payload.get('IP WIFI') or payload.get('IP Wifi'),
    }


def _parse_ymd(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip(), '%Y-%m-%d').date()
    except Exception:
        return None


def _normalize_hm(s):
    if not s:
        return None
    ss = str(s).strip()
    if not ss:
        return None
    # Aceptar HH:MM o HH:MM:SS
    if len(ss) >= 5:
        return ss[:5]
    return None


def _normalize_celda_id_py(val):
    """
    Normaliza IDs de celda para que coincidan entre:
    - DatoTecnico.celda_id
    - ResultadoTraficoGPRS.celda
    - ResultadoTraficoVOZ.celda_id

    Soporta casos típicos de Excel/DB legacy:
    - '123.0' vs '123'
    - comas decimales
    - espacios
    """
    if val is None:
        return ''
    try:
        # NaN float
        if isinstance(val, float) and str(val) == 'nan':
            return ''
    except Exception:
        pass
    s = str(val).strip()
    if not s:
        return ''
    s = s.replace(',', '.')
    if s.endswith('.0'):
        s = s[:-2]
    # Si quedó como float entero en string, normalizarlo a int
    try:
        f = float(s)
        if f.is_integer():
            s = str(int(f))
    except Exception:
        pass
    return s.strip().upper()


def _normalize_celda_id_sql(col):
    """
    Versión SQL (MySQL-friendly) de normalización de celda_id para joins/filtros.
    Evita que '123.0' rompa el match con '123'.
    """
    c = func.upper(func.trim(func.coalesce(col, '')))
    c = func.replace(c, ',', '.')
    # Quitar sufijo ".0" (común cuando viene de Excel como número)
    c = case(
        (func.right(c, 2) == '.0', func.left(c, func.length(c) - 2)),
        else_=c
    )
    return c


def _hora_ord_sql(col):
    """
    Normaliza hora en SQL para ordenar/filtrar correctamente cuando viene sin cero a la izquierda.
    Ej: '9:05:00' -> '09:05:00'
    """
    s = func.trim(func.coalesce(col, ''))
    s8 = func.substr(s, 1, 8)
    padded = case(
        (func.substr(s8, 2, 1) == ':', func.concat('0', s8)),
        else_=s8
    )
    padded = case((padded == '', '00:00:00'), else_=padded)
    return padded


def _coord_exists_any_accessible(tipo_val, celda_col):
    """
    True si existe alguna fila en Datos Técnicos (de una carga accesible de la unidad)
    que permita geolocalizar la celda del impacto.

    Esto evita el caso típico:
    - el tráfico está en una carga A
    - las coords de esa celda están en otra carga B (misma unidad y accesible)

    En ese caso el impacto igualmente es "mapeable" (impacto-loc ya hace fallback),
    y el orden global no debe “saltear” esos primeros registros.
    """
    return exists().where(and_(
        CargaLlamada.id == DatoTecnico.carga_id,
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        DatoTecnico.tipo == tipo_val,
        _normalize_celda_id_sql(DatoTecnico.celda_id) == _normalize_celda_id_sql(celda_col),
        DatoTecnico.lat.isnot(None),
        DatoTecnico.long.isnot(None),
    ))


def _apply_fecha_hora_filters(q, Model, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm):
    if fecha_desde:
        q = q.filter(Model.fecha.isnot(None), Model.fecha >= datetime(fecha_desde.year, fecha_desde.month, fecha_desde.day))
    if fecha_hasta:
        hasta_dt = datetime(fecha_hasta.year, fecha_hasta.month, fecha_hasta.day) + timedelta(days=1)
        q = q.filter(Model.fecha.isnot(None), Model.fecha < hasta_dt)
    if hora_desde_hm:
        q = q.filter(Model.hora.isnot(None), func.substr(_hora_ord_sql(Model.hora), 1, 5) >= hora_desde_hm)
    if hora_hasta_hm:
        q = q.filter(Model.hora.isnot(None), func.substr(_hora_ord_sql(Model.hora), 1, 5) <= hora_hasta_hm)
    return q


def _apply_numeros_filter_voz(q, numeros):
    """
    Aplica filtro por números a una query sobre ResultadoTraficoVOZ.
    Comportamiento:
    - 1 número: OR estándar (coincide en numero u otro, con LIKE).
    - 2 números: solo llamadas entre ese par (A<->B), en cualquier sentido.
    - 3+ números: OR estándar entre todos.
    """
    if not numeros:
        return q
    nums = [str(n or '').strip().lower() for n in numeros if str(n or '').strip()]
    if not nums:
        return q

    # Modo "par" cuando hay exactamente dos números
    if len(nums) == 2:
        a, b = nums[0], nums[1]
        cond_pair = or_(
            and_(func.lower(ResultadoTraficoVOZ.numero) == a, func.lower(ResultadoTraficoVOZ.otro) == b),
            and_(func.lower(ResultadoTraficoVOZ.numero) == b, func.lower(ResultadoTraficoVOZ.otro) == a),
        )
        return q.filter(
            or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))
        ).filter(cond_pair)

    # Caso general: OR entre todos los números (como antes)
    ors = []
    for n in nums[:50]:
        ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n}%"))
        ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n}%"))
    if ors:
        q = q.filter(
            or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))
        ).filter(or_(*ors))
    return q


def _parse_relaciones_multifilters():
    """Listas desde query string (como el mapa): sujeto_ids[], carga_ids[], numeros[], imeis[], provincias[], localidades[]."""
    sujeto_ids = [int(x) for x in request.args.getlist('sujeto_ids[]', type=int) if x and int(x) > 0]
    sid1 = request.args.get('sujeto_id', type=int)
    if sid1 and sid1 not in sujeto_ids:
        sujeto_ids.append(sid1)
    carga_ids = [int(x) for x in request.args.getlist('carga_ids[]', type=int) if x and int(x) > 0]
    cid1 = request.args.get('carga_id', type=int)
    if cid1 and cid1 not in carga_ids:
        carga_ids.append(cid1)
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    nextra = (request.args.get('numero') or '').strip()
    if nextra and nextra not in numeros:
        numeros.append(nextra)
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]
    provincias = [str(x).strip().lower() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip().lower() for x in request.args.getlist('localidades[]') if str(x).strip()]
    return {
        'sujeto_ids': sujeto_ids[:100],
        'carga_ids': carga_ids[:500],
        'numeros': numeros[:50],
        'imeis': imeis[:50],
        'provincias': provincias[:40],
        'localidades': localidades[:40],
    }


def _apply_relaciones_voz_numeros_filter(q, numeros):
    if not numeros:
        return q
    if len(numeros) == 2:
        a, b = numeros[0].lower(), numeros[1].lower()
        return q.filter(or_(
            and_(func.lower(ResultadoTraficoVOZ.numero) == a, func.lower(ResultadoTraficoVOZ.otro) == b),
            and_(func.lower(ResultadoTraficoVOZ.numero) == b, func.lower(ResultadoTraficoVOZ.otro) == a),
        ))
    ors = []
    for n in numeros:
        nl = n.lower()
        ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f'%{nl}%'))
        ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f'%{nl}%'))
    return q.filter(or_(*ors)) if ors else q


def _apply_relaciones_gprs_numeros_filter(q, numeros):
    if not numeros:
        return q
    ors = []
    for n in numeros:
        nl = n.lower()
        ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f'%{nl}%'))
    return q.filter(or_(*ors)) if ors else q


def _query_relaciones_voz(fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
                          sujeto_id=None, carga_id=None, caso_id=None, numero_filtro=None,
                          sujeto_ids=None, carga_ids=None, numeros=None, imeis=None,
                          provincias=None, localidades=None, max_rows=500):
    """
    Construye y ejecuta una query agregada de relaciones VOZ (numero <-> otro)
    sobre las cargas accesibles al usuario actual.
    """
    sujeto_ids = list(sujeto_ids or [])
    carga_ids = list(carga_ids or [])
    if sujeto_id and sujeto_id not in sujeto_ids:
        sujeto_ids.append(sujeto_id)
    if carga_id and carga_id not in carga_ids:
        carga_ids.append(carga_id)
    numeros_m = list(numeros or [])
    if numero_filtro and str(numero_filtro).strip():
        ns = str(numero_filtro).strip()
        if ns not in numeros_m:
            numeros_m.append(ns)
    imeis = [str(x).strip() for x in (imeis or []) if str(x).strip()]
    provincias = [str(x).strip().lower() for x in (provincias or []) if str(x).strip()]
    localidades = [str(x).strip().lower() for x in (localidades or []) if str(x).strip()]

    qc = _cargas_query_accessible().filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        CargaLlamada.tipo == 'voz',
    )
    if caso_id:
        caso = _get_caso_accesible(caso_id)
        if not caso:
            return []
        qc = qc.filter(CargaLlamada.caso_id == caso.id)
    if sujeto_ids:
        qc = qc.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        qc = qc.filter(CargaLlamada.id.in_(carga_ids))

    carga_ids_res = [cid for (cid,) in qc.with_entities(CargaLlamada.id).all()]
    if not carga_ids_res:
        return []

    q = db.session.query(
        ResultadoTraficoVOZ.numero.label('numero_a'),
        ResultadoTraficoVOZ.otro.label('numero_b'),
        func.count(ResultadoTraficoVOZ.id).label('cantidad'),
        func.min(ResultadoTraficoVOZ.fecha).label('primera_fecha'),
        func.max(ResultadoTraficoVOZ.fecha).label('ultima_fecha'),
    ).filter(
        ResultadoTraficoVOZ.carga_id.in_(carga_ids_res),
        ResultadoTraficoVOZ.numero.isnot(None),
        ResultadoTraficoVOZ.otro.isnot(None),
        ResultadoTraficoVOZ.numero != '',
        ResultadoTraficoVOZ.otro != '',
    )

    q = _apply_fecha_hora_filters(q, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
    if provincias:
        q = q.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(
            func.lower(ResultadoTraficoVOZ.celda_provincia).in_(provincias)
        )
    if localidades:
        q = q.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(
            func.lower(ResultadoTraficoVOZ.celda_localidad).in_(localidades)
        )
    if imeis:
        q = q.filter(ResultadoTraficoVOZ.imei.in_(imeis))
    q = _apply_relaciones_voz_numeros_filter(q, numeros_m)

    q = q.group_by(ResultadoTraficoVOZ.numero, ResultadoTraficoVOZ.otro) \
        .order_by(func.count(ResultadoTraficoVOZ.id).desc())

    if max_rows and max_rows > 0:
        q = q.limit(int(max_rows))

    return q.all()


def _query_relaciones_gprs(fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
                           sujeto_id=None, carga_id=None, caso_id=None, numero_filtro=None,
                           sujeto_ids=None, carga_ids=None, numeros=None, imeis=None,
                           provincias=None, localidades=None, max_rows=500):
    """
    Relaciones GPRS basadas en accesos de datos: numero <-> IP (coalesce ip_wifi, ip_dual_stack, ip).
    """
    sujeto_ids = list(sujeto_ids or [])
    carga_ids = list(carga_ids or [])
    if sujeto_id and sujeto_id not in sujeto_ids:
        sujeto_ids.append(sujeto_id)
    if carga_id and carga_id not in carga_ids:
        carga_ids.append(carga_id)
    numeros_m = list(numeros or [])
    if numero_filtro and str(numero_filtro).strip():
        ns = str(numero_filtro).strip()
        if ns not in numeros_m:
            numeros_m.append(ns)
    imeis = [str(x).strip() for x in (imeis or []) if str(x).strip()]
    provincias = [str(x).strip().lower() for x in (provincias or []) if str(x).strip()]
    localidades = [str(x).strip().lower() for x in (localidades or []) if str(x).strip()]

    qc = _cargas_query_accessible().filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        CargaLlamada.tipo == 'gprs',
    )
    if caso_id:
        caso = _get_caso_accesible(caso_id)
        if not caso:
            return []
        qc = qc.filter(CargaLlamada.caso_id == caso.id)
    if sujeto_ids:
        qc = qc.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        qc = qc.filter(CargaLlamada.id.in_(carga_ids))

    carga_ids_res = [cid for (cid,) in qc.with_entities(CargaLlamada.id).all()]
    if not carga_ids_res:
        return []

    ip_wifi_norm = func.nullif(func.trim(func.coalesce(ResultadoTraficoGPRS.ip_wifi, '')), '')
    ip_ds_norm = func.nullif(func.trim(func.coalesce(ResultadoTraficoGPRS.ip_dual_stack, '')), '')
    ip_norm = func.coalesce(
        ip_wifi_norm,
        ip_ds_norm,
        func.nullif(func.trim(func.coalesce(ResultadoTraficoGPRS.ip, '')), ''),
    )

    q = db.session.query(
        ResultadoTraficoGPRS.numero.label('numero_a'),
        ip_norm.label('numero_b'),
        func.count(ResultadoTraficoGPRS.id).label('cantidad'),
        func.min(ResultadoTraficoGPRS.fecha).label('primera_fecha'),
        func.max(ResultadoTraficoGPRS.fecha).label('ultima_fecha'),
    ).filter(
        ResultadoTraficoGPRS.carga_id.in_(carga_ids_res),
        ResultadoTraficoGPRS.numero.isnot(None),
        ResultadoTraficoGPRS.numero != '',
        ip_norm.isnot(None),
        ip_norm != '',
    )

    q = _apply_fecha_hora_filters(q, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
    if provincias:
        q = q.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(
            func.lower(ResultadoTraficoGPRS.celda_provincia).in_(provincias)
        )
    if localidades:
        q = q.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(
            func.lower(ResultadoTraficoGPRS.celda_localidad).in_(localidades)
        )
    if imeis:
        q = q.filter(ResultadoTraficoGPRS.imei.in_(imeis))
    q = _apply_relaciones_gprs_numeros_filter(q, numeros_m)

    q = q.group_by(ResultadoTraficoGPRS.numero, ip_norm) \
        .order_by(func.count(ResultadoTraficoGPRS.id).desc())

    if max_rows and max_rows > 0:
        q = q.limit(int(max_rows))

    return q.all()


def _apply_event_dt_filters_ap(q, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm):
    """Filtros de fecha/hora sobre AnalisisPuntoEvento.event_dt (MySQL)."""
    Ev = AnalisisPuntoEvento
    if fecha_desde:
        q = q.filter(
            Ev.event_dt.isnot(None),
            Ev.event_dt >= datetime(fecha_desde.year, fecha_desde.month, fecha_desde.day),
        )
    if fecha_hasta:
        hasta_dt = datetime(fecha_hasta.year, fecha_hasta.month, fecha_hasta.day) + timedelta(days=1)
        q = q.filter(
            Ev.event_dt.isnot(None),
            Ev.event_dt < hasta_dt,
        )
    if hora_desde_hm:
        q = q.filter(
            Ev.event_dt.isnot(None),
            func.date_format(Ev.event_dt, '%H:%i') >= hora_desde_hm,
        )
    if hora_hasta_hm:
        q = q.filter(
            Ev.event_dt.isnot(None),
            func.date_format(Ev.event_dt, '%H:%i') <= hora_hasta_hm,
        )
    return q


def _parse_fuente_record_relaciones(caso):
    """
    fuente_id / fuente_ids[] para eventos Record (múltiples archivos como en el mapa).
    Returns: (fuente_id, fuente_ids, error_message_or_None)
    """
    fuente_ids = [int(x) for x in request.args.getlist('fuente_ids[]', type=int) if x and int(x) > 0]
    fuente_one = request.args.get('fuente_id', type=int)
    if fuente_one is not None and fuente_one <= 0:
        fuente_one = None
    if fuente_one and fuente_one not in fuente_ids:
        fuente_ids.append(fuente_one)
    fuente_id = None
    fuente_ids_only = None
    if len(fuente_ids) > 1:
        fuente_ids_only = fuente_ids
    elif len(fuente_ids) == 1:
        fuente_id = fuente_ids[0]
    ids_to_check = fuente_ids_only or ([fuente_id] if fuente_id else [])
    for fid in ids_to_check:
        fuente = AnalisisPuntoFuente.query.filter_by(
            id=fid,
            caso_id=caso.id,
            unidad_id=current_user.unidad_id,
        ).first()
        if not fuente:
            ev_exists = db.session.query(AnalisisPuntoEvento.id).filter(
                AnalisisPuntoEvento.caso_id == caso.id,
                AnalisisPuntoEvento.unidad_id == current_user.unidad_id,
                AnalisisPuntoEvento.fuente_id == fid,
            ).first()
            if not ev_exists:
                return None, None, 'Archivo record no encontrado para este caso.'
    return fuente_id, fuente_ids_only, None


def _record_gprs_ip_from_payload_dict(payload):
    """Misma prioridad que _serialize_record_gprs_event (WiFi → dual → IP)."""
    if not isinstance(payload, dict):
        return None
    ip = payload.get('IP') or payload.get('ip')
    ds = payload.get('IP Dual Stack') or payload.get('IP Dual stack')
    wifi = payload.get('IP WIFI') or payload.get('IP Wifi')
    for x in (wifi, ds, ip):
        if x and str(x).strip():
            return str(x).strip()
    return None


def _apply_record_voz_numeros_filter(q, numeros):
    Ev = AnalisisPuntoEvento
    if not numeros:
        return q
    if len(numeros) == 2:
        a, b = numeros[0].lower(), numeros[1].lower()
        return q.filter(or_(
            and_(func.lower(Ev.origin_msisdn) == a, func.lower(Ev.target_msisdn) == b),
            and_(func.lower(Ev.origin_msisdn) == b, func.lower(Ev.target_msisdn) == a),
        ))
    ors = []
    for n in numeros:
        nl = n.lower()
        ors.append(func.lower(Ev.origin_msisdn).like(f'%{nl}%'))
        ors.append(func.lower(Ev.target_msisdn).like(f'%{nl}%'))
    return q.filter(or_(*ors)) if ors else q


def _query_relaciones_record_voz(caso, fuente_id, fuente_ids, fecha_desde, fecha_hasta,
                                 hora_desde_hm, hora_hasta_hm, numero_filtro, max_rows,
                                 numeros=None, imeis=None):
    """Relaciones VOZ desde ap_eventos (origin_msisdn ↔ target_msisdn)."""
    numeros_m = list(numeros or [])
    if numero_filtro and str(numero_filtro).strip():
        ns = str(numero_filtro).strip()
        if ns not in numeros_m:
            numeros_m.append(ns)
    imeis_l = [str(x).strip() for x in (imeis or []) if str(x).strip()]
    q = db.session.query(
        AnalisisPuntoEvento.origin_msisdn.label('numero_a'),
        AnalisisPuntoEvento.target_msisdn.label('numero_b'),
        func.count(AnalisisPuntoEvento.id).label('cantidad'),
        func.min(AnalisisPuntoEvento.event_dt).label('primera_fecha'),
        func.max(AnalisisPuntoEvento.event_dt).label('ultima_fecha'),
    ).filter(
        AnalisisPuntoEvento.caso_id == caso.id,
        AnalisisPuntoEvento.unidad_id == current_user.unidad_id,
        AnalisisPuntoEvento.source_type == 'VOZ',
        AnalisisPuntoEvento.origin_msisdn.isnot(None),
        AnalisisPuntoEvento.target_msisdn.isnot(None),
        func.trim(AnalisisPuntoEvento.origin_msisdn) != '',
        func.trim(AnalisisPuntoEvento.target_msisdn) != '',
    )
    if fuente_ids:
        q = q.filter(AnalisisPuntoEvento.fuente_id.in_(fuente_ids))
    elif fuente_id is not None:
        q = q.filter(AnalisisPuntoEvento.fuente_id == fuente_id)
    q = _apply_event_dt_filters_ap(q, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
    if imeis_l:
        q = q.filter(AnalisisPuntoEvento.imei.in_(imeis_l))
    q = _apply_record_voz_numeros_filter(q, numeros_m)
    q = q.group_by(
        AnalisisPuntoEvento.origin_msisdn,
        AnalisisPuntoEvento.target_msisdn,
    ).order_by(func.count(AnalisisPuntoEvento.id).desc())
    if max_rows and max_rows > 0:
        q = q.limit(int(max_rows))
    return q.all()


def _query_relaciones_record_gprs(caso, fuente_id, fuente_ids, fecha_desde, fecha_hasta,
                                  hora_desde_hm, hora_hasta_hm, numero_filtro, max_rows,
                                  numeros=None, imeis=None):
    """
    Relaciones GPRS Record: línea ↔ IP desde raw_payload_json (agregación en memoria).
    Limita el barrido de filas para proteger el servidor.
    """
    numeros_m = list(numeros or [])
    if numero_filtro and str(numero_filtro).strip():
        ns = str(numero_filtro).strip()
        if ns not in numeros_m:
            numeros_m.append(ns)
    imeis_l = [str(x).strip() for x in (imeis or []) if str(x).strip()]
    q = AnalisisPuntoEvento.query.filter(
        AnalisisPuntoEvento.caso_id == caso.id,
        AnalisisPuntoEvento.unidad_id == current_user.unidad_id,
        AnalisisPuntoEvento.source_type == 'GPRS',
        AnalisisPuntoEvento.origin_msisdn.isnot(None),
        func.trim(AnalisisPuntoEvento.origin_msisdn) != '',
    )
    if fuente_ids:
        q = q.filter(AnalisisPuntoEvento.fuente_id.in_(fuente_ids))
    elif fuente_id is not None:
        q = q.filter(AnalisisPuntoEvento.fuente_id == fuente_id)
    q = _apply_event_dt_filters_ap(q, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
    if imeis_l:
        q = q.filter(AnalisisPuntoEvento.imei.in_(imeis_l))
    if numeros_m:
        ors = []
        for n in numeros_m:
            nl = n.lower()
            ors.append(func.lower(AnalisisPuntoEvento.origin_msisdn).like(f'%{nl}%'))
        q = q.filter(or_(*ors))

    agg = defaultdict(lambda: {'cantidad': 0, 'primera': None, 'ultima': None})
    scanned = 0
    max_scan = 250000
    truncated = False
    for ev in q.yield_per(1000):
        scanned += 1
        if scanned > max_scan:
            truncated = True
            break
        payload = {}
        try:
            payload = json.loads(ev.raw_payload_json) if ev.raw_payload_json else {}
        except Exception:
            payload = {}
        ip = _record_gprs_ip_from_payload_dict(payload)
        if not ip:
            continue
        linea = str(ev.origin_msisdn).strip()
        key = (linea, ip)
        a = agg[key]
        a['cantidad'] += 1
        edt = ev.event_dt
        if edt:
            if a['primera'] is None or edt < a['primera']:
                a['primera'] = edt
            if a['ultima'] is None or edt > a['ultima']:
                a['ultima'] = edt

    items = []
    for (linea, ip_key), v in agg.items():
        items.append((linea, ip_key, v['cantidad'], v['primera'], v['ultima']))
    items.sort(key=lambda x: -x[2])
    if max_rows and max_rows > 0:
        items = items[: int(max_rows)]

    class _Row:
        pass

    out = []
    for linea, ip_key, cant, p, u in items:
        o = _Row()
        o.numero_a = linea
        o.numero_b = ip_key
        o.cantidad = cant
        o.primera_fecha = p
        o.ultima_fecha = u
        out.append(o)
    return out, truncated


@bp.route('/api/relaciones')
def api_relaciones():
    """
    API JSON de relaciones agregadas (sábana o Record, VOZ o GPRS).
    Parámetros: origen=sabana|record, tipo_trafico=voz|gprs, caso_id (record), fuente_id, mismos filtros que la vista.
    """
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    origen = (request.args.get('origen') or 'sabana').strip().lower()
    if origen not in ('sabana', 'record'):
        origen = 'sabana'
    tipo_tf = (request.args.get('tipo_trafico') or 'voz').strip().lower()
    if tipo_tf not in ('voz', 'gprs'):
        tipo_tf = 'voz'

    sujeto_id = request.args.get('sujeto_id', type=int)
    carga_id = request.args.get('carga_id', type=int)
    caso_id = request.args.get('caso_id', type=int)
    numero_raw = (request.args.get('numero') or '').strip()
    fecha_desde = _parse_ymd(request.args.get('fecha_desde') or '')
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta') or '')
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde') or '')
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta') or '')
    limit = request.args.get('limit', type=int) or 500
    if limit < 1:
        limit = 1
    if limit > 2000:
        limit = 2000

    caso = _get_caso_accesible(caso_id) if caso_id else None
    caso_id_eff = caso.id if caso else None
    mf = _parse_relaciones_multifilters()
    rows = []

    if origen == 'record':
        if not caso:
            return jsonify({'error': 'caso_id requerido para origen record'}), 400
        fuente_id, fuente_ids, fuente_err = _parse_fuente_record_relaciones(caso)
        if fuente_err:
            return jsonify({'error': fuente_err}), 400
        if tipo_tf == 'voz':
            rows = _query_relaciones_record_voz(
                caso, fuente_id, fuente_ids,
                fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
                numero_raw or None, limit,
                numeros=mf['numeros'],
                imeis=mf['imeis'],
            )
        else:
            rows, _trunc = _query_relaciones_record_gprs(
                caso, fuente_id, fuente_ids,
                fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
                numero_raw or None, limit,
                numeros=mf['numeros'],
                imeis=mf['imeis'],
            )
    else:
        if tipo_tf == 'voz':
            rows = _query_relaciones_voz(
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                hora_desde_hm=hora_desde_hm,
                hora_hasta_hm=hora_hasta_hm,
                sujeto_id=sujeto_id,
                carga_id=carga_id,
                caso_id=caso_id_eff,
                numero_filtro=numero_raw or None,
                sujeto_ids=mf['sujeto_ids'],
                carga_ids=mf['carga_ids'],
                numeros=mf['numeros'],
                imeis=mf['imeis'],
                provincias=mf['provincias'],
                localidades=mf['localidades'],
                max_rows=limit,
            )
        else:
            rows = _query_relaciones_gprs(
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                hora_desde_hm=hora_desde_hm,
                hora_hasta_hm=hora_hasta_hm,
                sujeto_id=sujeto_id,
                carga_id=carga_id,
                caso_id=caso_id_eff,
                numero_filtro=numero_raw or None,
                sujeto_ids=mf['sujeto_ids'],
                carga_ids=mf['carga_ids'],
                numeros=mf['numeros'],
                imeis=mf['imeis'],
                provincias=mf['provincias'],
                localidades=mf['localidades'],
                max_rows=limit,
            )

    out = []
    for r in rows:
        out.append({
            'numero_a': r.numero_a,
            'numero_b': r.numero_b,
            'cantidad': int(r.cantidad or 0),
            'primera_fecha': r.primera_fecha.isoformat() if r.primera_fecha else None,
            'ultima_fecha': r.ultima_fecha.isoformat() if r.ultima_fecha else None,
        })
    return jsonify(out)


def _informe_voz_impactos_por_numero(carga_ids, numeros, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm):
    """
    Para cada número en `numeros`, agrupa impactos VOZ por celda (con lat/long y ubicación desde DatoTecnico).
    Devuelve dict: numero -> [ { celda_id, lat, long, direccion, localidad, provincia, cantidad, primera_fecha, ultima_fecha }, ... ]
    """
    if not carga_ids or not numeros:
        return {}
    numeros = [str(n).strip() for n in numeros if n]
    if not numeros:
        return {}

    # Agrupar impactos VOZ por (numero, carga_id, celda_norm): count, min/max fecha
    q_agg = db.session.query(
        ResultadoTraficoVOZ.numero,
        ResultadoTraficoVOZ.carga_id,
        _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id).label('celda_norm'),
        func.count(ResultadoTraficoVOZ.id).label('cantidad'),
        func.min(ResultadoTraficoVOZ.fecha).label('primera_fecha'),
        func.max(ResultadoTraficoVOZ.fecha).label('ultima_fecha'),
    ).filter(
        ResultadoTraficoVOZ.carga_id.in_(carga_ids),
        ResultadoTraficoVOZ.numero.in_(numeros),
        ResultadoTraficoVOZ.celda_id.isnot(None),
    )
    q_agg = _apply_fecha_hora_filters(q_agg, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
    q_agg = q_agg.group_by(
        ResultadoTraficoVOZ.numero,
        ResultadoTraficoVOZ.carga_id,
        _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id),
    ).all()

    # Por (carga_id, celda_norm) obtener un DatoTecnico con lat/long/ubicación (una sola query)
    celdas_need = set()
    for row in q_agg:
        celdas_need.add((row.carga_id, row.celda_norm))

    dt_by_key = {}
    if celdas_need and carga_ids:
        dt_rows = DatoTecnico.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            DatoTecnico.tipo == 'voz',
            DatoTecnico.carga_id.in_(carga_ids),
            DatoTecnico.lat.isnot(None),
            DatoTecnico.long.isnot(None),
        ).all()
        for dt in dt_rows:
            cnorm = _normalize_celda_id_py(dt.celda_id) if dt.celda_id else None
            if cnorm:
                key = (dt.carga_id, cnorm)
                if key in celdas_need and key not in dt_by_key:
                    dt_by_key[key] = {
                        'celda_id': cnorm,
                        'lat': float(dt.lat),
                        'long': float(dt.long),
                        'direccion': (dt.celda_direccion or '').strip() or None,
                        'localidad': (dt.celda_loc or '').strip() or None,
                        'provincia': (dt.celda_prov or '').strip() or None,
                    }

    out = {}
    for row in q_agg:
        num = str(row.numero).strip()
        if num not in out:
            out[num] = []
        loc = dt_by_key.get((row.carga_id, row.celda_norm)) or {
            'celda_id': row.celda_norm,
            'lat': None,
            'long': None,
            'direccion': None,
            'localidad': None,
            'provincia': None,
        }
        out[num].append({
            **loc,
            'cantidad': int(row.cantidad or 0),
            'primera_fecha': row.primera_fecha.isoformat() if row.primera_fecha else None,
            'ultima_fecha': row.ultima_fecha.isoformat() if row.ultima_fecha else None,
        })
    return out


@bp.route('/api/informe-voz')
def api_informe_voz():
    """
    Informe para fiscalía: relaciones VOZ + impactos por número con celdas, lat/long y ubicación.
    Mismos filtros que la vista relaciones (sujeto_id, carga_id, numero, fecha_desde, fecha_hasta, hora_*, limit).
    """
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    sujeto_id = request.args.get('sujeto_id', type=int)
    carga_id = request.args.get('carga_id', type=int)
    caso_id = request.args.get('caso_id', type=int)
    numero_raw = (request.args.get('numero') or '').strip()
    fecha_desde = _parse_ymd(request.args.get('fecha_desde') or '')
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta') or '')
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde') or '')
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta') or '')
    limit = request.args.get('limit', type=int) or 200
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000

    caso_ap = _get_caso_accesible(caso_id) if caso_id else None
    mf = _parse_relaciones_multifilters()

    qc = _cargas_query_accessible().filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        CargaLlamada.tipo == 'voz',
    )
    if caso_ap:
        qc = qc.filter(CargaLlamada.caso_id == caso_ap.id)
    if mf['sujeto_ids']:
        qc = qc.filter(CargaLlamada.sujeto_id.in_(mf['sujeto_ids']))
    elif sujeto_id:
        qc = qc.filter(CargaLlamada.sujeto_id == sujeto_id)
    if mf['carga_ids']:
        qc = qc.filter(CargaLlamada.id.in_(mf['carga_ids']))
    elif carga_id:
        qc = qc.filter(CargaLlamada.id == carga_id)
    carga_ids = [c for (c,) in qc.with_entities(CargaLlamada.id).all()]
    if not carga_ids:
        return jsonify({
            'relaciones': [],
            'resumen': {'total_pares': 0, 'total_comunicaciones': 0, 'numeros_unicos': 0},
            'sujetos_por_numero': {},
            'impactos_por_numero': {},
            'parrafo_informe': '',
        })

    rows = _query_relaciones_voz(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        hora_desde_hm=hora_desde_hm,
        hora_hasta_hm=hora_hasta_hm,
        sujeto_id=sujeto_id,
        carga_id=carga_id,
        caso_id=caso_ap.id if caso_ap else None,
        numero_filtro=numero_raw or None,
        sujeto_ids=mf['sujeto_ids'],
        carga_ids=mf['carga_ids'],
        numeros=mf['numeros'],
        imeis=mf['imeis'],
        provincias=mf['provincias'],
        localidades=mf['localidades'],
        max_rows=limit,
    )

    numero_set = set()
    for r in rows:
        if getattr(r, 'numero_a', None):
            numero_set.add(str(r.numero_a).strip())
        if getattr(r, 'numero_b', None):
            numero_set.add(str(r.numero_b).strip())

    sujetos_por_numero = {}
    if numero_set:
        try:
            accesibles_ids = [sid for (sid,) in _sujetos_query_accessible().with_entities(Sujeto.id).all()]

            exp_rows = db.session.query(
                SujetoNumero.numero,
                Sujeto.id,
                Sujeto.apodo,
                Sujeto.nombre,
                Sujeto.dni,
            ).join(Sujeto, SujetoNumero.sujeto_id == Sujeto.id).filter(
                SujetoNumero.unidad_id == current_user.unidad_id,
                SujetoNumero.numero.in_(list(numero_set)),
                SujetoNumero.sujeto_id.in_(accesibles_ids) if accesibles_ids else text("0=1"),
            ).all()
            for num, sid, apodo, nombre, dni in exp_rows:
                key = str(num).strip()
                if key and key not in sujetos_por_numero:
                    sujetos_por_numero[key] = nombre or apodo or (f'DNI {dni}' if dni else f'Sujeto #{sid}')
            faltantes = [n for n in numero_set if n not in sujetos_por_numero]
            if faltantes:
                imp_rows = db.session.query(
                    ResultadoTraficoVOZ.numero,
                    Sujeto.nombre,
                    Sujeto.apodo,
                    Sujeto.dni,
                    Sujeto.id,
                ).join(CargaLlamada, ResultadoTraficoVOZ.carga_id == CargaLlamada.id).join(
                    Sujeto, CargaLlamada.sujeto_id == Sujeto.id
                ).filter(
                    CargaLlamada.unidad_id == current_user.unidad_id,
                    _carga_access_predicate(),
                    ResultadoTraficoVOZ.numero.in_(faltantes),
                    Sujeto.id.in_(accesibles_ids) if accesibles_ids else text("0=1"),
                ).distinct().all()
                for num, nombre, apodo, dni, sid in imp_rows:
                    key = str(num).strip()
                    if key and key not in sujetos_por_numero:
                        sujetos_por_numero[key] = nombre or apodo or (f'DNI {dni}' if dni else f'Sujeto #{sid}')
        except Exception:
            pass

    relaciones_data = []
    total_comunicaciones = 0
    for r in rows:
        cant = int(r.cantidad or 0)
        total_comunicaciones += cant
        relaciones_data.append({
            'numero_a': r.numero_a,
            'numero_b': r.numero_b,
            'cantidad': cant,
            'primera_fecha': r.primera_fecha.isoformat() if r.primera_fecha else None,
            'ultima_fecha': r.ultima_fecha.isoformat() if r.ultima_fecha else None,
            'sujeto_a': sujetos_por_numero.get(str(r.numero_a).strip()),
            'sujeto_b': sujetos_por_numero.get(str(r.numero_b).strip()),
        })

    impactos_por_numero = _informe_voz_impactos_por_numero(
        carga_ids, list(numero_set), fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
    )

    # Párrafo tipo informe para fiscalía
    partes = []
    partes.append(
        f'En el período analizado se registraron {total_comunicaciones} comunicaciones entre {len(numero_set)} números '
        f'telefónicos, conformando {len(relaciones_data)} pares de interlocutores.'
    )
    for num in sorted(numero_set):
        sujeto = sujetos_por_numero.get(num) or 'sin identificar'
        celdas = impactos_por_numero.get(num) or []
        total_imp = sum(c.get('cantidad', 0) for c in celdas)
        if total_imp > 0:
            partes.append(
                f'Respecto a la línea del número {num} (sujeto: {sujeto}), se observan {total_imp} impactos en celdas. '
            )
            con_geo = [c for c in celdas if c.get('lat') is not None and c.get('long') is not None]
            if con_geo:
                ubicaciones = []
                for c in con_geo[:15]:
                    u = f"celda {c.get('celda_id')} (lat. {c['lat']:.5f}, long. {c['long']:.5f})"
                    if c.get('direccion') or c.get('localidad') or c.get('provincia'):
                        u += f" — {c.get('direccion') or ''} {c.get('localidad') or ''} {c.get('provincia') or ''}".strip()
                    ubicaciones.append(u)
                partes.append(
                    'La persona se encontraba en las siguientes ubicaciones: ' +
                    '; '.join(ubicaciones) + ('.' if len(con_geo) <= 15 else ' (entre otras).')
                )
            if len(con_geo) > 1:
                provincias = set(c.get('provincia') for c in con_geo if c.get('provincia'))
                if len(provincias) > 1:
                    partes.append(f'Se observa un patrón de desplazamiento entre provincias: {", ".join(p for p in provincias if p)}.')
                elif provincias:
                    partes.append(f'Se observa un patrón de concentración en la provincia de {list(provincias)[0]}.')
        else:
            partes.append(f'La línea del número {num} (sujeto: {sujeto}) no presenta impactos geolocalizados en el período.')

    parrafo_informe = '\n\n'.join(partes)

    # Metadatos para el informe (usuario, unidad, filtros usados)
    usuario_label = None
    try:
        usuario_label = getattr(current_user, 'username', None) or getattr(current_user, 'email', None)
    except Exception:
        usuario_label = None
    if not usuario_label:
        try:
            usuario_label = f'Usuario #{current_user.id}'
        except Exception:
            usuario_label = 'Usuario desconocido'

    unidad_nombre = None
    try:
        unidad = getattr(current_user, 'unidad', None)
        if unidad is not None:
            unidad_nombre = getattr(unidad, 'nombre', None) or str(unidad)
    except Exception:
        unidad_nombre = None

    filtros_desc = {}
    if sujeto_id:
        sujeto_obj = Sujeto.query.get(sujeto_id)
        if sujeto_obj:
            filtros_desc['sujeto'] = sujeto_obj.display_name()
    if carga_id:
        carga_obj = CargaLlamada.query.get(carga_id)
        if carga_obj:
            filtros_desc['carga_voz'] = f"#{carga_obj.id} - {carga_obj.nombre_archivo or 'Sin nombre'}"
    if numero_raw:
        filtros_desc['numero'] = numero_raw
    if fecha_desde:
        filtros_desc['fecha_desde'] = fecha_desde.strftime('%d/%m/%Y')
    if fecha_hasta:
        filtros_desc['fecha_hasta'] = fecha_hasta.strftime('%d/%m/%Y')
    if hora_desde_hm:
        filtros_desc['hora_desde'] = hora_desde_hm
    if hora_hasta_hm:
        filtros_desc['hora_hasta'] = hora_hasta_hm
    filtros_desc['limit'] = limit

    metadatos = {
        'usuario': usuario_label,
        'unidad': unidad_nombre,
        'generado_en_utc': datetime.utcnow().isoformat() + 'Z',
        'filtros': filtros_desc,
    }

    return jsonify({
        'relaciones': relaciones_data,
        'resumen': {
            'total_pares': len(relaciones_data),
            'total_comunicaciones': total_comunicaciones,
            'numeros_unicos': len(numero_set),
        },
        'sujetos_por_numero': sujetos_por_numero,
        'impactos_por_numero': impactos_por_numero,
        'parrafo_informe': parrafo_informe,
        'metadatos': metadatos,
    })


def _informe_gprs_impactos_por_numero(carga_ids, numeros, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm):
    """
    Para cada número en `numeros`, agrupa sesiones GPRS por celda (con lat/long y ubicación desde DatoTecnico).
    Devuelve dict: numero -> [ { celda_id, lat, long, direccion, localidad, provincia, cantidad, primera_fecha, ultima_fecha }, ... ]
    """
    if not carga_ids or not numeros:
        return {}
    numeros = [str(n).strip() for n in numeros if n]
    if not numeros:
        return {}

    q_agg = db.session.query(
        ResultadoTraficoGPRS.numero,
        ResultadoTraficoGPRS.carga_id,
        _normalize_celda_id_sql(ResultadoTraficoGPRS.celda).label('celda_norm'),
        func.count(ResultadoTraficoGPRS.id).label('cantidad'),
        func.min(ResultadoTraficoGPRS.fecha).label('primera_fecha'),
        func.max(ResultadoTraficoGPRS.fecha).label('ultima_fecha'),
    ).filter(
        ResultadoTraficoGPRS.carga_id.in_(carga_ids),
        ResultadoTraficoGPRS.numero.in_(numeros),
        ResultadoTraficoGPRS.celda.isnot(None),
    )
    q_agg = _apply_fecha_hora_filters(q_agg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
    q_agg = q_agg.group_by(
        ResultadoTraficoGPRS.numero,
        ResultadoTraficoGPRS.carga_id,
        _normalize_celda_id_sql(ResultadoTraficoGPRS.celda),
    ).all()

    celdas_need = set()
    for row in q_agg:
        celdas_need.add((row.carga_id, row.celda_norm))

    dt_by_key = {}
    if celdas_need and carga_ids:
        dt_rows = DatoTecnico.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            DatoTecnico.tipo == 'gprs',
            DatoTecnico.carga_id.in_(carga_ids),
            DatoTecnico.lat.isnot(None),
            DatoTecnico.long.isnot(None),
        ).all()
        for dt in dt_rows:
            cnorm = _normalize_celda_id_py(dt.celda_id) if dt.celda_id else None
            if cnorm:
                key = (dt.carga_id, cnorm)
                if key in celdas_need and key not in dt_by_key:
                    dt_by_key[key] = {
                        'celda_id': cnorm,
                        'lat': float(dt.lat),
                        'long': float(dt.long),
                        'direccion': (dt.celda_direccion or '').strip() or None,
                        'localidad': (dt.celda_loc or '').strip() or None,
                        'provincia': (dt.celda_prov or '').strip() or None,
                    }

    out = {}
    for row in q_agg:
        num = str(row.numero).strip()
        if num not in out:
            out[num] = []
        loc = dt_by_key.get((row.carga_id, row.celda_norm)) or {
            'celda_id': row.celda_norm,
            'lat': None,
            'long': None,
            'direccion': None,
            'localidad': None,
            'provincia': None,
        }
        out[num].append({
            **loc,
            'cantidad': int(row.cantidad or 0),
            'primera_fecha': row.primera_fecha.isoformat() if row.primera_fecha else None,
            'ultima_fecha': row.ultima_fecha.isoformat() if row.ultima_fecha else None,
        })
    return out


@bp.route('/api/informe-gprs')
def api_informe_gprs():
    """
    Informe para fiscalía: relaciones GPRS (línea ↔ IP) + impactos por número con celdas, lat/long y ubicación.
    Mismos filtros que la vista relaciones_gprs.
    """
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    sujeto_id = request.args.get('sujeto_id', type=int)
    carga_id = request.args.get('carga_id', type=int)
    caso_id = request.args.get('caso_id', type=int)
    numero_raw = (request.args.get('numero') or '').strip()
    fecha_desde = _parse_ymd(request.args.get('fecha_desde') or '')
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta') or '')
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde') or '')
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta') or '')
    limit = request.args.get('limit', type=int) or 200
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000

    caso_ap = _get_caso_accesible(caso_id) if caso_id else None
    mf = _parse_relaciones_multifilters()

    qc = _cargas_query_accessible().filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        CargaLlamada.tipo == 'gprs',
    )
    if caso_ap:
        qc = qc.filter(CargaLlamada.caso_id == caso_ap.id)
    if mf['sujeto_ids']:
        qc = qc.filter(CargaLlamada.sujeto_id.in_(mf['sujeto_ids']))
    elif sujeto_id:
        qc = qc.filter(CargaLlamada.sujeto_id == sujeto_id)
    if mf['carga_ids']:
        qc = qc.filter(CargaLlamada.id.in_(mf['carga_ids']))
    elif carga_id:
        qc = qc.filter(CargaLlamada.id == carga_id)
    carga_ids = [c for (c,) in qc.with_entities(CargaLlamada.id).all()]
    if not carga_ids:
        return jsonify({
            'relaciones': [],
            'resumen': {'total_pares': 0, 'total_comunicaciones': 0, 'numeros_unicos': 0},
            'sujetos_por_numero': {},
            'impactos_por_numero': {},
            'parrafo_informe': '',
            'metadatos': {},
        })

    rows = _query_relaciones_gprs(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        hora_desde_hm=hora_desde_hm,
        hora_hasta_hm=hora_hasta_hm,
        sujeto_id=sujeto_id,
        carga_id=carga_id,
        caso_id=caso_ap.id if caso_ap else None,
        numero_filtro=numero_raw or None,
        sujeto_ids=mf['sujeto_ids'],
        carga_ids=mf['carga_ids'],
        numeros=mf['numeros'],
        imeis=mf['imeis'],
        provincias=mf['provincias'],
        localidades=mf['localidades'],
        max_rows=limit,
    )

    numero_set = set()
    for r in rows:
        if getattr(r, 'numero_a', None):
            numero_set.add(str(r.numero_a).strip())

    sujetos_por_numero = {}
    if numero_set:
        try:
            accesibles_ids = [sid for (sid,) in _sujetos_query_accessible().with_entities(Sujeto.id).all()]

            exp_rows = db.session.query(
                SujetoNumero.numero,
                Sujeto.id,
                Sujeto.apodo,
                Sujeto.nombre,
                Sujeto.dni,
            ).join(Sujeto, SujetoNumero.sujeto_id == Sujeto.id).filter(
                SujetoNumero.unidad_id == current_user.unidad_id,
                SujetoNumero.numero.in_(list(numero_set)),
                SujetoNumero.sujeto_id.in_(accesibles_ids) if accesibles_ids else text("0=1"),
            ).all()
            for num, sid, apodo, nombre, dni in exp_rows:
                key = str(num).strip()
                if key and key not in sujetos_por_numero:
                    sujetos_por_numero[key] = nombre or apodo or (f'DNI {dni}' if dni else f'Sujeto #{sid}')
        except Exception:
            pass

    relaciones_data = []
    total_sesiones = 0
    for r in rows:
        cant = int(r.cantidad or 0)
        total_sesiones += cant
        relaciones_data.append({
            'numero_a': r.numero_a,
            'numero_b': r.numero_b,
            'cantidad': cant,
            'primera_fecha': r.primera_fecha.isoformat() if r.primera_fecha else None,
            'ultima_fecha': r.ultima_fecha.isoformat() if r.ultima_fecha else None,
            'sujeto_a': sujetos_por_numero.get(str(r.numero_a).strip()),
            'sujeto_b': None,
        })

    impactos_por_numero = _informe_gprs_impactos_por_numero(
        carga_ids, list(numero_set), fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm,
    )

    partes = []
    partes.append(
        f'En el período analizado se registraron {total_sesiones} accesos de datos GPRS correspondientes a {len(numero_set)} líneas, '
        f'conformando {len(relaciones_data)} pares línea–IP.'
    )
    for num in sorted(numero_set):
        sujeto = sujetos_por_numero.get(num) or 'sin identificar'
        celdas = impactos_por_numero.get(num) or []
        total_imp = sum(c.get('cantidad', 0) for c in celdas)
        if total_imp > 0:
            partes.append(
                f'Respecto a la línea del número {num} (sujeto: {sujeto}), se observan {total_imp} impactos de datos en celdas técnicas.'
            )
            con_geo = [c for c in celdas if c.get('lat') is not None and c.get('long') is not None]
            if con_geo:
                ubicaciones = []
                for c in con_geo[:15]:
                    u = f"celda {c.get('celda_id')} (lat. {c['lat']:.5f}, long. {c['long']:.5f})"
                    if c.get('direccion') or c.get('localidad') or c.get('provincia'):
                        u += f" — {c.get('direccion') or ''} {c.get('localidad') or ''} {c.get('provincia') or ''}".strip()
                    ubicaciones.append(u)
                partes.append(
                    'La línea registra actividad de datos en las siguientes ubicaciones: ' +
                    '; '.join(ubicaciones) + ('.' if len(con_geo) <= 15 else ' (entre otras).')
                )
        else:
            partes.append(f'La línea del número {num} (sujeto: {sujeto}) no presenta impactos GPRS geolocalizados en el período.')

    parrafo_informe = '\n\n'.join(partes)

    usuario_label = None
    try:
        usuario_label = getattr(current_user, 'username', None) or getattr(current_user, 'email', None)
    except Exception:
        usuario_label = None
    if not usuario_label:
        try:
            usuario_label = f'Usuario #{current_user.id}'
        except Exception:
            usuario_label = 'Usuario desconocido'

    unidad_nombre = None
    try:
        unidad = getattr(current_user, 'unidad', None)
        if unidad is not None:
            unidad_nombre = getattr(unidad, 'nombre', None) or str(unidad)
    except Exception:
        unidad_nombre = None

    filtros_desc = {}
    if sujeto_id:
        sujeto_obj = Sujeto.query.get(sujeto_id)
        if sujeto_obj:
            filtros_desc['sujeto'] = sujeto_obj.display_name()
    if carga_id:
        carga_obj = CargaLlamada.query.get(carga_id)
        if carga_obj:
            filtros_desc['carga_voz'] = f"#{carga_obj.id} - {carga_obj.nombre_archivo or 'Sin nombre'}"
    if numero_raw:
        filtros_desc['numero'] = numero_raw
    if fecha_desde:
        filtros_desc['fecha_desde'] = fecha_desde.strftime('%d/%m/%Y')
    if fecha_hasta:
        filtros_desc['fecha_hasta'] = fecha_hasta.strftime('%d/%m/%Y')
    if hora_desde_hm:
        filtros_desc['hora_desde'] = hora_desde_hm
    if hora_hasta_hm:
        filtros_desc['hora_hasta'] = hora_hasta_hm
    filtros_desc['limit'] = limit

    metadatos = {
        'usuario': usuario_label,
        'unidad': unidad_nombre,
        'generado_en_utc': datetime.utcnow().isoformat() + 'Z',
        'filtros': filtros_desc,
    }

    return jsonify({
        'relaciones': relaciones_data,
        'resumen': {
            'total_pares': len(relaciones_data),
            'total_comunicaciones': total_sesiones,
            'numeros_unicos': len(numero_set),
        },
        'sujetos_por_numero': sujetos_por_numero,
        'impactos_por_numero': impactos_por_numero,
        'parrafo_informe': parrafo_informe,
        'metadatos': metadatos,
    })


def _coerce_date_from_db(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, 'year') and hasattr(v, 'month') and hasattr(v, 'day'):
        try:
            return datetime(int(v.year), int(v.month), int(v.day)).date()
        except Exception:
            return None
    try:
        s = str(v).strip()
        if not s:
            return None
        if len(s) >= 10:
            return datetime.strptime(s[:10], '%Y-%m-%d').date()
    except Exception:
        return None
    return None


def _weekday_labels_es():
    # Python weekday(): Monday=0 ... Sunday=6
    return ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']


def _build_patrones_from_rows(day_rows, hour_rows):
    weekdays = [{'idx': i, 'label': lbl, 'count': 0} for i, lbl in enumerate(_weekday_labels_es())]
    by_hour = [{'hour': f'{h:02d}', 'count': 0} for h in range(24)]
    total = 0

    for dval, cnt in day_rows or []:
        d = _coerce_date_from_db(dval)
        if not d:
            continue
        wd = int(d.weekday())
        c = int(cnt or 0)
        if 0 <= wd <= 6:
            weekdays[wd]['count'] += c
            total += c

    for hh, cnt in hour_rows or []:
        try:
            h = int(str(hh or '').strip()[:2])
        except Exception:
            continue
        if 0 <= h <= 23:
            by_hour[h]['count'] += int(cnt or 0)

    top_weekday = None
    top_hour = None
    if weekdays:
        tw = max(weekdays, key=lambda x: x['count'])
        if (tw.get('count') or 0) > 0:
            top_weekday = tw
    if by_hour:
        th = max(by_hour, key=lambda x: x['count'])
        if (th.get('count') or 0) > 0:
            top_hour = th

    return {
        'by_weekday': weekdays,
        'by_hour': by_hour,
        'total_eventos': int(total),
        'top_weekday': top_weekday,
        'top_hour': top_hour,
    }


def _patrones_rows_sabana(tipo_tf, caso_id, mf, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm):
    if tipo_tf == 'gprs':
        q = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.fecha.isnot(None),
        )
        if caso_id:
            q = q.filter(CargaLlamada.caso_id == caso_id)
        if mf['sujeto_ids']:
            q = q.filter(CargaLlamada.sujeto_id.in_(mf['sujeto_ids']))
        if mf['carga_ids']:
            q = q.filter(CargaLlamada.id.in_(mf['carga_ids']))
        q = _apply_fecha_hora_filters(q, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if mf['provincias']:
            q = q.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(
                func.lower(ResultadoTraficoGPRS.celda_provincia).in_(mf['provincias'])
            )
        if mf['localidades']:
            q = q.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(
                func.lower(ResultadoTraficoGPRS.celda_localidad).in_(mf['localidades'])
            )
        if mf['imeis']:
            q = q.filter(ResultadoTraficoGPRS.imei.in_(mf['imeis']))
        q = _apply_relaciones_gprs_numeros_filter(q, mf['numeros'])
        day_rows = q.with_entities(func.date(ResultadoTraficoGPRS.fecha), func.count(ResultadoTraficoGPRS.id)).group_by(func.date(ResultadoTraficoGPRS.fecha)).all()
        hour_rows = q.filter(ResultadoTraficoGPRS.hora.isnot(None)).with_entities(
            func.substr(_hora_ord_sql(ResultadoTraficoGPRS.hora), 1, 2).label('hh'),
            func.count(ResultadoTraficoGPRS.id)
        ).group_by('hh').all()
        return day_rows, hour_rows

    q = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        ResultadoTraficoVOZ.fecha.isnot(None),
    )
    if caso_id:
        q = q.filter(CargaLlamada.caso_id == caso_id)
    if mf['sujeto_ids']:
        q = q.filter(CargaLlamada.sujeto_id.in_(mf['sujeto_ids']))
    if mf['carga_ids']:
        q = q.filter(CargaLlamada.id.in_(mf['carga_ids']))
    q = _apply_fecha_hora_filters(q, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
    if mf['provincias']:
        q = q.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(
            func.lower(ResultadoTraficoVOZ.celda_provincia).in_(mf['provincias'])
        )
    if mf['localidades']:
        q = q.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(
            func.lower(ResultadoTraficoVOZ.celda_localidad).in_(mf['localidades'])
        )
    if mf['imeis']:
        q = q.filter(ResultadoTraficoVOZ.imei.in_(mf['imeis']))
    q = _apply_relaciones_voz_numeros_filter(q, mf['numeros'])
    day_rows = q.with_entities(func.date(ResultadoTraficoVOZ.fecha), func.count(ResultadoTraficoVOZ.id)).group_by(func.date(ResultadoTraficoVOZ.fecha)).all()
    hour_rows = q.filter(ResultadoTraficoVOZ.hora.isnot(None)).with_entities(
        func.substr(_hora_ord_sql(ResultadoTraficoVOZ.hora), 1, 2).label('hh'),
        func.count(ResultadoTraficoVOZ.id)
    ).group_by('hh').all()
    return day_rows, hour_rows


def _patrones_rows_record(tipo_tf, caso_id, fuente_ids, mf, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm):
    _caso, qev = _record_eventos_base(caso_id, fuente_ids)
    if qev is None:
        return [], []
    st = ['GPRS'] if tipo_tf == 'gprs' else ['VOZ']
    qev = _apply_tipos_ap_evento(qev, [x.lower() for x in st])
    qev = _apply_ap_evento_fecha_filters(qev, fecha_desde, fecha_hasta)
    if hora_desde_hm:
        qev = qev.filter(AnalisisPuntoEvento.event_dt.isnot(None), func.date_format(AnalisisPuntoEvento.event_dt, '%H:%i') >= hora_desde_hm)
    if hora_hasta_hm:
        qev = qev.filter(AnalisisPuntoEvento.event_dt.isnot(None), func.date_format(AnalisisPuntoEvento.event_dt, '%H:%i') <= hora_hasta_hm)
    qev = _record_join_celda_if_geo(qev, mf['provincias'], mf['localidades'])
    if mf['imeis']:
        qev = qev.filter(AnalisisPuntoEvento.imei.in_(mf['imeis']))
    if mf['numeros']:
        if tipo_tf == 'gprs':
            ors = []
            for n in mf['numeros']:
                nl = n.lower()
                ors.append(func.lower(AnalisisPuntoEvento.origin_msisdn).like(f'%{nl}%'))
            if ors:
                qev = qev.filter(or_(*ors))
        else:
            qev = _apply_record_voz_numeros_filter(qev, mf['numeros'])
    qev = qev.filter(AnalisisPuntoEvento.event_dt.isnot(None))
    day_rows = qev.with_entities(func.date(AnalisisPuntoEvento.event_dt), func.count(AnalisisPuntoEvento.id)).group_by(func.date(AnalisisPuntoEvento.event_dt)).all()
    hour_rows = qev.with_entities(
        func.date_format(AnalisisPuntoEvento.event_dt, '%H').label('hh'),
        func.count(AnalisisPuntoEvento.id)
    ).group_by('hh').all()
    return day_rows, hour_rows


@bp.route('/api/relaciones/patrones')
def api_relaciones_patrones():
    """Patrones de tiempo (dia de semana / hora) para Relaciones segun filtros activos."""
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    origen = (request.args.get('origen') or 'sabana').strip().lower()
    if origen not in ('sabana', 'record'):
        origen = 'sabana'
    tipo_tf = (request.args.get('tipo_trafico') or 'voz').strip().lower()
    if tipo_tf not in ('voz', 'gprs'):
        tipo_tf = 'voz'

    caso_id = request.args.get('caso_id', type=int)
    caso_ap = _get_caso_accesible(caso_id) if caso_id else None
    mf = _parse_relaciones_multifilters()
    fecha_desde = _parse_ymd(request.args.get('fecha_desde') or '')
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta') or '')
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde') or '')
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta') or '')

    day_rows, hour_rows = [], []
    if origen == 'record':
        if not caso_ap:
            return jsonify(_build_patrones_from_rows([], []))
        fuente_ids = [int(x) for x in request.args.getlist('fuente_ids[]', type=int) if x and int(x) > 0]
        fuente_one = request.args.get('fuente_id', type=int)
        if fuente_one and fuente_one > 0 and fuente_one not in fuente_ids:
            fuente_ids.append(fuente_one)
        day_rows, hour_rows = _patrones_rows_record(
            tipo_tf, caso_ap.id, fuente_ids, mf, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm
        )
    else:
        day_rows, hour_rows = _patrones_rows_sabana(
            tipo_tf, caso_ap.id if caso_ap else None, mf, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm
        )

    return jsonify(_build_patrones_from_rows(day_rows, hour_rows))


@bp.route('/api/mapa/impacto-nota', methods=['GET', 'POST'])
def api_mapa_impacto_nota():
    """
    Permite guardar y recuperar una nota + color para un impacto concreto (registro de tráfico).
    Clave: (unidad_id, tipo, impacto_id, user_id).
    """
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    if request.method == 'GET':
        tipo = (request.args.get('tipo') or '').strip().lower()
        impacto_id = request.args.get('impacto_id', type=int)
        if not tipo or not impacto_id:
            return jsonify({'nota': None, 'color': None})
        nota = SabanaImpactoNota.query.filter_by(
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            tipo=tipo,
            impacto_id=impacto_id,
        ).first()
        if not nota:
            return jsonify({'nota': None, 'color': None})
        return jsonify({'nota': nota.nota or '', 'color': nota.color or None})

    data = request.get_json(silent=True) or {}
    tipo = (data.get('tipo') or '').strip().lower()
    impacto_id = data.get('impacto_id')
    nota_txt = (data.get('nota') or '').strip()
    color = (data.get('color') or '').strip() or None
    try:
        impacto_id = int(impacto_id)
    except Exception:
        impacto_id = None
    if not tipo or impacto_id is None:
        return jsonify({'error': 'missing_fields'}), 400

    nota = SabanaImpactoNota.query.filter_by(
        unidad_id=current_user.unidad_id,
        user_id=current_user.id,
        tipo=tipo,
        impacto_id=impacto_id,
    ).first()
    if not nota:
        nota = SabanaImpactoNota(
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            tipo=tipo,
            impacto_id=impacto_id,
        )
        db.session.add(nota)
    nota.nota = nota_txt or None
    nota.color = color
    db.session.commit()
    return jsonify({'ok': True, 'nota': nota.nota or '', 'color': nota.color or None})


@bp.route('/api/mapa/puntos')
def api_mapa_puntos():
    """API para puntos con lat/long. Filtros: sujeto_ids[], carga_ids[], tipos[] (gprs/voz)."""
    if not _permiso():
        return jsonify([]), 403
    q = DatoTecnico.query.join(CargaLlamada).filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        DatoTecnico.lat.isnot(None),
        DatoTecnico.long.isnot(None),
    )
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    if sujeto_ids:
        q = q.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q = q.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q = q.filter(DatoTecnico.tipo.in_(tipos))
    rows = q.with_entities(
        DatoTecnico.id, DatoTecnico.lat, DatoTecnico.long,
        DatoTecnico.tipo, DatoTecnico.rango_consulta, DatoTecnico.celda_direccion,
        CargaLlamada.id.label('carga_id'), CargaLlamada.sujeto_id,
    ).all()
    out = []
    for r in rows:
        out.append({
            'id': r.id,
            'lat': float(r.lat),
            'lng': float(r.long),
            'tipo': r.tipo,
            'rango_consulta': r.rango_consulta,
            'celda_direccion': r.celda_direccion,
            'carga_id': r.carga_id,
            'sujeto_id': r.sujeto_id,
        })
    return jsonify(out)


def _serialize_caso_mapa_punto(p):
    uname = None
    try:
        if getattr(p, 'user', None):
            u = p.user
            uname = (getattr(u, 'username', None) or '').strip() or None
    except Exception:
        pass
    c_at = None
    try:
        if p.created_at:
            c_at = p.created_at.isoformat() + 'Z'
    except Exception:
        pass
    return {
        'id': p.id,
        'caso_id': p.caso_id,
        'lat': float(p.lat),
        'lng': float(p.lon),
        'tipo': (p.tipo or 'otro').strip().lower(),
        'etiqueta': p.etiqueta,
        'nota': p.nota,
        'origen_contexto': p.origen_contexto,
        'icono': (getattr(p, 'icono', None) or '').strip().lower() or None,
        'created_by': uname,
        'created_at': c_at,
    }


_TIPOS_MAPA_PUNTO = frozenset({'domicilio', 'encuentro', 'hecho', 'otro'})
_ICONOS_MAPA_PUNTO = frozenset({'pin', 'casa', 'hecho', 'encuentro', 'auto', 'tienda', 'cruz'})


def _normalize_mapa_punto_icono(raw):
    s = (raw or '').strip().lower()
    if s in _ICONOS_MAPA_PUNTO:
        return s
    return 'pin'


@bp.route('/api/mapa/caso-puntos', methods=['GET', 'POST'])
def api_mapa_caso_puntos():
    """Puntos de referencia geográficos vinculados a un caso (mapa Sábana/Record)."""
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    if request.method == 'GET':
        caso_id = request.args.get('caso_id', type=int)
        caso = _get_caso_accesible(caso_id)
        if not caso:
            return jsonify([])
        rows = (
            AnalisisPuntoCasoMapaPunto.query.options(joinedload(AnalisisPuntoCasoMapaPunto.user))
            .filter(
                AnalisisPuntoCasoMapaPunto.caso_id == caso.id,
                AnalisisPuntoCasoMapaPunto.unidad_id == current_user.unidad_id,
            )
            .order_by(AnalisisPuntoCasoMapaPunto.created_at.asc())
            .all()
        )
        return jsonify([_serialize_caso_mapa_punto(p) for p in rows])

    data = request.get_json(silent=True) or {}
    caso_id = data.get('caso_id')
    try:
        caso_id = int(caso_id)
    except Exception:
        caso_id = None
    caso = _get_caso_accesible(caso_id)
    if not caso:
        return jsonify({'error': 'caso_invalido'}), 400

    try:
        lat = float(data.get('lat'))
        lon = float(data.get('lng'))
    except Exception:
        return jsonify({'error': 'coordenadas_invalidas'}), 400
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return jsonify({'error': 'coordenadas_fuera_rango'}), 400

    tipo = (data.get('tipo') or 'otro').strip().lower()
    if tipo not in _TIPOS_MAPA_PUNTO:
        tipo = 'otro'

    etiqueta = (data.get('etiqueta') or '').strip() or None
    if etiqueta and len(etiqueta) > 120:
        etiqueta = etiqueta[:120]

    nota = (data.get('nota') or '').strip() or None
    if nota and len(nota) > 4000:
        nota = nota[:4000]

    origen = (data.get('origen_contexto') or '').strip().lower()
    if origen not in ('sabana', 'record'):
        origen = None

    icono = _normalize_mapa_punto_icono(data.get('icono'))

    now = datetime.utcnow()
    row = AnalisisPuntoCasoMapaPunto(
        caso_id=caso.id,
        unidad_id=current_user.unidad_id,
        user_id=current_user.id,
        lat=lat,
        lon=lon,
        tipo=tipo,
        etiqueta=etiqueta,
        nota=nota,
        origen_contexto=origen,
        icono=icono,
        created_at=now,
        updated_at=now,
    )
    db.session.add(row)
    db.session.commit()
    row = AnalisisPuntoCasoMapaPunto.query.options(joinedload(AnalisisPuntoCasoMapaPunto.user)).filter_by(id=row.id).first()
    return jsonify({'ok': True, 'punto': _serialize_caso_mapa_punto(row)})


@bp.route('/api/mapa/caso-puntos/<int:punto_id>', methods=['PUT', 'DELETE'])
def api_mapa_caso_punto_eliminar(punto_id):
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403
    p = AnalisisPuntoCasoMapaPunto.query.filter_by(
        id=punto_id,
        unidad_id=current_user.unidad_id,
    ).first()
    if not p:
        return jsonify({'error': 'not_found'}), 404
    caso = _get_caso_accesible(p.caso_id)
    if not caso:
        return jsonify({'error': 'forbidden'}), 403

    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        try:
            lat = float(data.get('lat'))
            lon = float(data.get('lng'))
        except Exception:
            return jsonify({'error': 'coordenadas_invalidas'}), 400
        if lat < -90 or lat > 90 or lon < -180 or lon > 180:
            return jsonify({'error': 'coordenadas_fuera_rango'}), 400

        tipo = (data.get('tipo') or 'otro').strip().lower()
        if tipo not in _TIPOS_MAPA_PUNTO:
            tipo = 'otro'

        etiqueta = (data.get('etiqueta') or '').strip() or None
        if etiqueta and len(etiqueta) > 120:
            etiqueta = etiqueta[:120]

        nota = (data.get('nota') or '').strip() or None
        if nota and len(nota) > 4000:
            nota = nota[:4000]

        origen = (data.get('origen_contexto') or '').strip().lower()
        if origen not in ('sabana', 'record'):
            origen = p.origen_contexto

        if 'icono' in data:
            icono = _normalize_mapa_punto_icono(data.get('icono'))
        else:
            icono = _normalize_mapa_punto_icono(getattr(p, 'icono', None))

        p.lat = lat
        p.lon = lon
        p.tipo = tipo
        p.etiqueta = etiqueta
        p.nota = nota
        p.origen_contexto = origen
        p.icono = icono
        p.updated_at = datetime.utcnow()
        db.session.add(p)
        db.session.commit()
        p = AnalisisPuntoCasoMapaPunto.query.options(joinedload(AnalisisPuntoCasoMapaPunto.user)).filter_by(id=p.id).first()
        return jsonify({'ok': True, 'punto': _serialize_caso_mapa_punto(p)})

    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/api/mapa/impactos')
def api_mapa_impactos():
    """
    Puntos por celda (lat/long) con lista de impactos (registros de tráfico) en esa celda.
    Filtros: sujeto_ids[], carga_ids[], tipos[].
    """
    if not _permiso():
        return jsonify([]), 403
    q = DatoTecnico.query.join(CargaLlamada).filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        DatoTecnico.lat.isnot(None),
        DatoTecnico.long.isnot(None),
        DatoTecnico.celda_id.isnot(None),
    )
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    if sujeto_ids:
        q = q.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q = q.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q = q.filter(DatoTecnico.tipo.in_(tipos))

    caso_mapa = None
    caso_id_mapa = request.args.get('caso_id', type=int)
    if caso_id_mapa:
        caso_mapa = _get_caso_accesible(caso_id_mapa)
        if not caso_mapa:
            return jsonify([]), 403
        q = q.filter(CargaLlamada.caso_id == caso_mapa.id)

    # Filtros avanzados (aplican a los impactos de tráfico, no a las celdas técnicas)
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]

    # Si resumen=1, no mandamos la lista completa de impactos por celda (solo conteo).
    # El frontend puede pedir el detalle on-demand con /api/mapa/celda-impactos.
    resumen_flag = (request.args.get('resumen') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí')

    if provincias:
        q = q.filter(DatoTecnico.celda_prov.isnot(None)).filter(DatoTecnico.celda_prov.in_(provincias))
    if localidades:
        q = q.filter(DatoTecnico.celda_loc.isnot(None)).filter(DatoTecnico.celda_loc.in_(localidades))

    # Evitar pines duplicados: algunas cargas pueden traer múltiples filas técnicas para la misma celda.
    # Elegimos la más reciente (max id) por (tipo, carga_id, celda_id) manteniendo los filtros aplicados.
    try:
        sub = q.with_entities(func.max(DatoTecnico.id).label('id')).group_by(
            DatoTecnico.tipo, DatoTecnico.carga_id, DatoTecnico.celda_id
        ).subquery()
        q = DatoTecnico.query.join(sub, DatoTecnico.id == sub.c.id).join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            DatoTecnico.lat.isnot(None),
            DatoTecnico.long.isnot(None),
            DatoTecnico.celda_id.isnot(None),
        )
        if caso_mapa:
            q = q.filter(CargaLlamada.caso_id == caso_mapa.id)
    except Exception:
        # Si el motor no soporta el subquery/group_by como esperamos, seguimos sin dedupe.
        pass

    # Por defecto limitamos celdas para respuesta más rápida y mapa estable.
    # El frontend puede pedir all=1 y paginar con offset/limit para traer todas.
    all_flag = (request.args.get('all') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí')
    MAX_CELDAS_DEFAULT = 1500
    MAX_LIMIT_POR_PAGINA = 2000

    q = q.order_by(DatoTecnico.id)

    excede = False
    has_more = False
    next_offset = None

    if all_flag:
        offset = request.args.get('offset', default=0, type=int) or 0
        limit = request.args.get('limit', default=1000, type=int) or 1000
        if limit < 1:
            limit = 1
        if limit > MAX_LIMIT_POR_PAGINA:
            limit = MAX_LIMIT_POR_PAGINA
        if offset < 0:
            offset = 0
        celdas = q.offset(offset).limit(limit + 1).all()
        has_more = len(celdas) > limit
        if has_more:
            celdas = celdas[:limit]
            next_offset = offset + limit
    else:
        celdas = q.limit(MAX_CELDAS_DEFAULT + 1).all()
        excede = len(celdas) > MAX_CELDAS_DEFAULT
        if excede:
            celdas = celdas[:MAX_CELDAS_DEFAULT]

    # Map carga_id -> sujeto_id (evita N+1 al serializar)
    carga_ids_set = {dt.carga_id for dt in celdas if dt and dt.carga_id}
    carga_to_sujeto = {}
    if carga_ids_set:
        for cid, sid in db.session.query(CargaLlamada.id, CargaLlamada.sujeto_id).filter(CargaLlamada.id.in_(list(carga_ids_set))).all():
            carga_to_sujeto[cid] = sid
    # Si se aplican filtros sobre impactos, no mostrar celdas sin impactos.
    # (Además de fecha/hora/números/IMEI, esto también ayuda cuando filtran por provincia/localidad.)
    filtros_impactos_activos = bool(
        fecha_desde or fecha_hasta or hora_desde_hm or hora_hasta_hm or numeros or imeis or provincias or localidades
    )

    # Optimización: evitar N+1 (una query por celda). Traemos impactos en bloque por tipo y agrupamos.
    gprs_keys = set()
    voz_keys = set()
    for dt in celdas:
        if not dt or not dt.carga_id or not dt.celda_id:
            continue
        celda_norm = _normalize_celda_id_py(dt.celda_id)
        if not celda_norm:
            continue
        if dt.tipo == 'gprs':
            gprs_keys.add((dt.carga_id, celda_norm))
        else:
            voz_keys.add((dt.carga_id, celda_norm))

    def _iter_chunks(seq, size):
        seq = list(seq)
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    impactos_gprs = {}
    impactos_gprs_count = {}
    if gprs_keys:
        # chunking: evita límites de parámetros en algunos motores
        for key_chunk in _iter_chunks(gprs_keys, 500):
            # Normalizar celda para evitar "perder" impactos con espacios/variantes del Excel (ej. 123.0 vs 123)
            q_reg = ResultadoTraficoGPRS.query.filter(
                tuple_(ResultadoTraficoGPRS.carga_id, _normalize_celda_id_sql(ResultadoTraficoGPRS.celda)).in_(key_chunk)
            )
            q_reg = _apply_fecha_hora_filters(q_reg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
            if provincias:
                q_reg = q_reg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
            if localidades:
                q_reg = q_reg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
            if imeis:
                q_reg = q_reg.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
            if numeros:
                ors = []
                for n in numeros[:50]:
                    ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
                if ors:
                    q_reg = q_reg.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
            if resumen_flag:
                # Más eficiente en MySQL: agrupar y contar en DB (evita traer todas las filas).
                celda_norm_col = _normalize_celda_id_sql(ResultadoTraficoGPRS.celda)
                rows = q_reg.with_entities(
                    ResultadoTraficoGPRS.carga_id,
                    celda_norm_col.label('celda_norm'),
                    func.count(ResultadoTraficoGPRS.id),
                ).group_by(ResultadoTraficoGPRS.carga_id, celda_norm_col).all()
                for carga_id, celda_norm, cnt in rows:
                    key = (carga_id, _normalize_celda_id_py(celda_norm))
                    impactos_gprs_count[key] = impactos_gprs_count.get(key, 0) + int(cnt or 0)
            else:
                for r in q_reg.order_by(ResultadoTraficoGPRS.fecha, _hora_ord_sql(ResultadoTraficoGPRS.hora), ResultadoTraficoGPRS.id).all():
                    key = (r.carga_id, _normalize_celda_id_py(r.celda))
                    impactos_gprs.setdefault(key, []).append(_serialize_gprs(r))
                    impactos_gprs_count[key] = impactos_gprs_count.get(key, 0) + 1

    impactos_voz = {}
    impactos_voz_count = {}
    if voz_keys:
        for key_chunk in _iter_chunks(voz_keys, 500):
            q_reg = ResultadoTraficoVOZ.query.filter(
                tuple_(ResultadoTraficoVOZ.carga_id, _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id)).in_(key_chunk)
            )
            q_reg = _apply_fecha_hora_filters(q_reg, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
            if provincias:
                q_reg = q_reg.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
            if localidades:
                q_reg = q_reg.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
            if imeis:
                q_reg = q_reg.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
            if numeros:
                q_reg = _apply_numeros_filter_voz(q_reg, numeros)
            if resumen_flag:
                # Más eficiente en MySQL: agrupar y contar en DB (evita traer todas las filas).
                celda_norm_col = _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id)
                rows = q_reg.with_entities(
                    ResultadoTraficoVOZ.carga_id,
                    celda_norm_col.label('celda_norm'),
                    func.count(ResultadoTraficoVOZ.id),
                ).group_by(ResultadoTraficoVOZ.carga_id, celda_norm_col).all()
                for carga_id, celda_norm, cnt in rows:
                    key = (carga_id, _normalize_celda_id_py(celda_norm))
                    impactos_voz_count[key] = impactos_voz_count.get(key, 0) + int(cnt or 0)
            else:
                for r in q_reg.order_by(ResultadoTraficoVOZ.fecha, _hora_ord_sql(ResultadoTraficoVOZ.hora), ResultadoTraficoVOZ.id).all():
                    key = (r.carga_id, _normalize_celda_id_py(r.celda_id))
                    impactos_voz.setdefault(key, []).append(_serialize_voz(r))
                    impactos_voz_count[key] = impactos_voz_count.get(key, 0) + 1

    out = []
    for dt in celdas:
        if not dt:
            continue
        celda_norm = _normalize_celda_id_py(dt.celda_id)
        key = (dt.carga_id, celda_norm)
        impactos = impactos_gprs.get(key, []) if dt.tipo == 'gprs' else impactos_voz.get(key, [])
        impactos_count = impactos_gprs_count.get(key, 0) if dt.tipo == 'gprs' else impactos_voz_count.get(key, 0)

        if filtros_impactos_activos and impactos_count <= 0:
            continue

        item = {
            'id': dt.id,
            'lat': float(dt.lat),
            'lng': float(dt.long),
            'celda_id': celda_norm,
            'carga_id': dt.carga_id,
            'sujeto_id': carga_to_sujeto.get(dt.carga_id),
            'tipo': dt.tipo,
            'celda_direccion': dt.celda_direccion or celda_norm,
            'rango_consulta': dt.rango_consulta,
            'impactos_count': int(impactos_count or 0),
        }
        if not resumen_flag:
            item['impactos'] = impactos
        out.append(item)
    resp = jsonify(out)
    if excede:
        resp.headers['X-Limitado'] = str(MAX_CELDAS_DEFAULT)
    if all_flag:
        resp.headers['X-Has-More'] = '1' if has_more else '0'
        if next_offset is not None:
            resp.headers['X-Next-Offset'] = str(next_offset)
    return resp


def _record_mapa_qev_from_request_filters(request, caso, require_cell=True):
    """
    Query base de ap_eventos con los mismos filtros de tráfico/archivo/fecha/número/IMEI
    que /api/mapa/record-impactos (sin geografía).
    Returns:
        (qev, None) o (None, respuesta_flask) si hay que devolver temprano ([] o error fuente).
    """
    st = (request.args.get('source_type') or '').strip().upper()
    if st not in ('', 'VOZ', 'GPRS'):
        st = ''
    tipos_req = [str(x).strip().lower() for x in request.args.getlist('tipos[]') if str(x).strip()]
    tipos_src = set()
    for t in tipos_req:
        if t == 'voz':
            tipos_src.add('VOZ')
        elif t == 'gprs':
            tipos_src.add('GPRS')

    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]

    fuente_id = request.args.get('fuente_id', type=int)
    if fuente_id is not None and fuente_id <= 0:
        fuente_id = None
    fuente_ids = [int(x) for x in request.args.getlist('fuente_ids[]', type=int) if x and int(x) > 0]
    if fuente_ids:
        fuente_id = None
    if fuente_id is not None:
        fuente = AnalisisPuntoFuente.query.filter_by(
            id=fuente_id,
            caso_id=caso.id,
            unidad_id=current_user.unidad_id,
        ).first()
        if not fuente:
            ev_exists = db.session.query(AnalisisPuntoEvento.id).filter(
                AnalisisPuntoEvento.caso_id == caso.id,
                AnalisisPuntoEvento.unidad_id == current_user.unidad_id,
                AnalisisPuntoEvento.fuente_id == fuente_id,
            ).first()
            if not ev_exists:
                return None, (jsonify({'error': 'fuente no encontrada para el caso'}), 404)

    qev = AnalisisPuntoEvento.query.filter(
        AnalisisPuntoEvento.caso_id == caso.id,
        AnalisisPuntoEvento.unidad_id == current_user.unidad_id,
    )
    if require_cell:
        qev = qev.filter(AnalisisPuntoEvento.cell_id.isnot(None))
    if st in ('VOZ', 'GPRS'):
        if tipos_src and st not in tipos_src:
            return None, (jsonify([]), 200)
        qev = qev.filter(AnalisisPuntoEvento.source_type == st)
    elif tipos_src:
        qev = qev.filter(AnalisisPuntoEvento.source_type.in_(list(tipos_src)))
    if fuente_ids:
        qev = qev.filter(AnalisisPuntoEvento.fuente_id.in_(fuente_ids))
    elif fuente_id is not None:
        qev = qev.filter(AnalisisPuntoEvento.fuente_id == fuente_id)
    if fecha_desde:
        qev = qev.filter(
            AnalisisPuntoEvento.event_dt.isnot(None),
            AnalisisPuntoEvento.event_dt >= datetime(fecha_desde.year, fecha_desde.month, fecha_desde.day)
        )
    if fecha_hasta:
        hasta_dt = datetime(fecha_hasta.year, fecha_hasta.month, fecha_hasta.day) + timedelta(days=1)
        qev = qev.filter(
            AnalisisPuntoEvento.event_dt.isnot(None),
            AnalisisPuntoEvento.event_dt < hasta_dt
        )
    if imeis:
        qev = qev.filter(AnalisisPuntoEvento.imei.isnot(None), AnalisisPuntoEvento.imei.in_(imeis))
    if numeros:
        ors = []
        for n in numeros[:50]:
            nl = n.lower()
            ors.append(func.lower(AnalisisPuntoEvento.origin_msisdn).like(f"%{nl}%"))
            ors.append(func.lower(AnalisisPuntoEvento.target_msisdn).like(f"%{nl}%"))
        if ors:
            qev = qev.filter(or_(*ors))

    return qev, None


@bp.route('/api/relaciones/record-geo-resumen')
def api_relaciones_record_geo_resumen():
    """Resumen de georreferenciacion para informe Record segun filtros actuales."""
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    caso_id = request.args.get('caso_id', type=int)
    if not caso_id:
        return jsonify({
            'total_filtrados': 0,
            'con_cell_id': 0,
            'con_celda_geo': 0,
            'sin_cell_id': 0,
            'sin_celda_geo': 0,
        })
    caso = _get_caso_accesible(caso_id)
    if not caso:
        return jsonify({
            'total_filtrados': 0,
            'con_cell_id': 0,
            'con_celda_geo': 0,
            'sin_cell_id': 0,
            'sin_celda_geo': 0,
        })

    qev, early = _record_mapa_qev_from_request_filters(request, caso, require_cell=False)
    if early is not None:
        return jsonify({
            'total_filtrados': 0,
            'con_cell_id': 0,
            'con_celda_geo': 0,
            'sin_cell_id': 0,
            'sin_celda_geo': 0,
        })

    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    if hora_desde_hm:
        qev = qev.filter(
            AnalisisPuntoEvento.event_dt.isnot(None),
            func.date_format(AnalisisPuntoEvento.event_dt, '%H:%i') >= hora_desde_hm,
        )
    if hora_hasta_hm:
        qev = qev.filter(
            AnalisisPuntoEvento.event_dt.isnot(None),
            func.date_format(AnalisisPuntoEvento.event_dt, '%H:%i') <= hora_hasta_hm,
        )

    provincias = [str(x).strip().lower() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip().lower() for x in request.args.getlist('localidades[]') if str(x).strip()]
    if provincias or localidades:
        conds = [
            AnalisisPuntoCelda.id == AnalisisPuntoEvento.cell_id,
            AnalisisPuntoCelda.unidad_id == current_user.unidad_id,
        ]
        if provincias:
            conds.append(AnalisisPuntoCelda.province.isnot(None))
            conds.append(func.lower(AnalisisPuntoCelda.province).in_(provincias))
        if localidades:
            conds.append(AnalisisPuntoCelda.locality.isnot(None))
            conds.append(func.lower(AnalisisPuntoCelda.locality).in_(localidades))
        qev = qev.filter(
            AnalisisPuntoEvento.cell_id.isnot(None),
            exists().where(and_(*conds)),
        )

    total_filtrados = int(qev.with_entities(func.count(AnalisisPuntoEvento.id)).scalar() or 0)
    con_cell_id = int(
        qev.filter(AnalisisPuntoEvento.cell_id.isnot(None)).with_entities(func.count(AnalisisPuntoEvento.id)).scalar() or 0
    )
    con_celda_geo = int(
        qev.filter(
            exists().where(and_(
                AnalisisPuntoCelda.id == AnalisisPuntoEvento.cell_id,
                AnalisisPuntoCelda.unidad_id == current_user.unidad_id,
                AnalisisPuntoCelda.lat.isnot(None),
                AnalisisPuntoCelda.lon.isnot(None),
            ))
        ).with_entities(func.count(AnalisisPuntoEvento.id)).scalar() or 0
    )
    sin_cell_id = max(0, total_filtrados - con_cell_id)
    sin_celda_geo = max(0, con_cell_id - con_celda_geo)
    return jsonify({
        'total_filtrados': total_filtrados,
        'con_cell_id': con_cell_id,
        'con_celda_geo': con_celda_geo,
        'sin_cell_id': sin_cell_id,
        'sin_celda_geo': sin_celda_geo,
    })


def _msisdn_agg_key(s):
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    digits = ''.join(c for c in t if c.isdigit())
    return digits or t.lower()


def _record_impactos_build_list(req):
    """
    Misma lógica que api_mapa_record_impactos.
    Retorna (None, respuesta_flask) en error o (lista_items, caso) si ok.
    """
    caso_id = req.args.get('caso_id', type=int)
    if not caso_id:
        return None, (jsonify({'error': 'caso_id requerido'}), 400)
    caso = _get_caso_accesible(caso_id)
    if not caso:
        return None, (jsonify({'error': 'caso no encontrado'}), 404)

    max_m = req.args.get('max_m', type=int)
    if max_m is not None and max_m < 0:
        max_m = None
    center_lat = req.args.get('center_lat', type=float)
    center_lng = req.args.get('center_lng', type=float)
    perimetro_m = req.args.get('perimetro_m', type=int)
    ref_punto_ids = [int(x) for x in req.args.getlist('ref_punto_ids[]', type=int) if x and int(x) > 0]

    geo_centers = []
    if ref_punto_ids:
        if perimetro_m is None or perimetro_m <= 0:
            return None, (jsonify({'error': 'Para filtro por puntos de referencia indique perimetro_m > 0'}), 400)
        puntos_ref = AnalisisPuntoCasoMapaPunto.query.filter(
            AnalisisPuntoCasoMapaPunto.caso_id == caso.id,
            AnalisisPuntoCasoMapaPunto.unidad_id == current_user.unidad_id,
            AnalisisPuntoCasoMapaPunto.id.in_(ref_punto_ids),
        ).all()
        geo_centers = [(p.lat, p.lon) for p in puntos_ref if p.lat is not None and p.lon is not None]
        if len(geo_centers) != len(ref_punto_ids):
            return None, (jsonify({'error': 'Algunos puntos de referencia no existen o no son accesibles'}), 400)
    elif any(v is not None for v in (center_lat, center_lng, perimetro_m)):
        if center_lat is None or center_lng is None or perimetro_m is None or perimetro_m <= 0:
            return None, (jsonify({'error': 'Para filtro geográfico use center_lat, center_lng y perimetro_m > 0'}), 400)
        geo_centers = [(center_lat, center_lng)]

    geo_filter_enabled = len(geo_centers) > 0

    qev, early = _record_mapa_qev_from_request_filters(req, caso)
    if early is not None:
        return None, early

    hora_desde_hm = _normalize_hm(req.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(req.args.get('hora_hasta'))
    provincias = [str(x).strip().lower() for x in req.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip().lower() for x in req.args.getlist('localidades[]') if str(x).strip()]

    st = (req.args.get('source_type') or '').strip().upper()
    if st not in ('', 'VOZ', 'GPRS'):
        st = ''

    events = qev.order_by(AnalisisPuntoEvento.event_dt.asc(), AnalisisPuntoEvento.id.asc()).all()
    by_cell = {}
    for ev in events:
        cid = ev.cell_id
        if not cid:
            continue
        by_cell.setdefault(cid, []).append(ev)

    out = []

    def _event_hm(ev):
        try:
            if ev.event_dt:
                return ev.event_dt.strftime('%H:%M')
        except Exception:
            pass
        hh = (getattr(ev, 'event_hour', None) or '').strip()
        if not hh:
            return None
        if len(hh) == 1:
            hh = '0' + hh
        if len(hh) >= 2:
            return hh[:2] + ':00'
        return None

    for cell_id, evs in by_cell.items():
        cel = AnalisisPuntoCelda.query.filter_by(id=cell_id, unidad_id=current_user.unidad_id).first()
        if not cel or cel.lat is None or cel.lon is None:
            continue
        if provincias:
            prov = (cel.province or '').strip().lower()
            if not prov or prov not in provincias:
                continue
        if localidades:
            loc = (cel.locality or '').strip().lower()
            if not loc or loc not in localidades:
                continue
        distancia_m = None
        if geo_filter_enabled:
            mind = None
            for cla, clo in geo_centers:
                d = _haversine_m(cla, clo, cel.lat, cel.lon)
                if d is None:
                    continue
                if mind is None or d < mind:
                    mind = d
            distancia_m = mind
            if distancia_m is None or distancia_m > perimetro_m:
                continue
        celda_norm = _normalize_celda_id_py(cel.cell_code)
        rfull = int(cel.coverage_radius_m or 0)
        rdraw = rfull
        if max_m is not None and rfull > 0:
            rdraw = min(rfull, max_m)
        elif max_m is not None:
            rdraw = max_m

        impactos = []
        for ev in evs:
            hm = _event_hm(ev)
            if hora_desde_hm:
                if hm is None or hm < hora_desde_hm:
                    continue
            if hora_hasta_hm:
                if hm is None or hm > hora_hasta_hm:
                    continue
            ev_t = (ev.source_type or '').upper()
            if ev_t == 'VOZ' and st in ('', 'VOZ'):
                impactos.append(_serialize_record_voz_event(ev))
            elif ev_t == 'GPRS' and st in ('', 'GPRS'):
                impactos.append(_serialize_record_gprs_event(ev))
        if not impactos:
            continue

        for i, imp in enumerate(impactos, start=1):
            imp['_ord'] = i

        try:
            az_rec = int(cel.azimuth_deg) if cel.azimuth_deg is not None else None
        except Exception:
            az_rec = None
        try:
            ap_rec = int(cel.aperture_h_deg) if cel.aperture_h_deg is not None else None
        except Exception:
            ap_rec = None
        item = {
            'id': cel.id,
            'lat': float(cel.lat),
            'lng': float(cel.lon),
            'celda_id': celda_norm,
            'carga_id': caso.id,
            'sujeto_id': None,
            'tipo': (impactos[0].get('tipo') if impactos and isinstance(impactos[0], dict) else ('gprs' if st == 'GPRS' else 'voz')),
            'celda_direccion': cel.address or celda_norm,
            'rango_consulta': None,
            'impactos_count': len(impactos),
            'impactos': impactos,
            '_record': True,
            '_record_caso_id': caso.id,
            'radius_full_m': rfull,
            'radius_draw_m': rdraw if rdraw and rdraw > 0 else None,
            'distance_to_center_m': int(round(distancia_m)) if distancia_m is not None else None,
            'azimuth_deg': az_rec,
            'aperture_h_deg': ap_rec,
            'province_cell': (cel.province or '').strip() or None,
            'locality_cell': (cel.locality or '').strip() or None,
        }
        out.append(item)

    return (out, caso)


def _offset_lat_lon_meters(lat, lon, dist_m, bearing_deg):
    """Desplaza un punto por distancia (m) y rumbo (grados)."""
    br = math.radians(bearing_deg)
    dx = dist_m * math.sin(br)
    dy = dist_m * math.cos(br)
    m_per_lat = 111320.0
    m_per_lon = 111320.0 * math.cos(math.radians(float(lat)))
    return float(lat) + dy / m_per_lat, float(lon) + dx / m_per_lon


def _circle_ring_coords(lat, lon, radius_m, n=36):
    """Lista de (lon, lat) cerrando un anillo para KML."""
    pts = []
    for i in range(n + 1):
        ang = (360.0 / n) * i
        la, lo = _offset_lat_lon_meters(lat, lon, float(radius_m), ang)
        pts.append((lo, la))
    return pts


def _xml_text(s):
    if s is None:
        return ''
    return html.escape(str(s), quote=True)


def _parse_float_loose(s):
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    try:
        return float(t.replace(',', '.'))
    except Exception:
        return None


def _rad_km_str_to_m(s):
    v = _parse_float_loose(s)
    if v is None or v <= 0:
        return None
    return max(1, int(round(v * 1000.0)))


def _sector_polygon_ring_latlon(lat, lon, radius_m, azimuth_deg, aperture_full_deg):
    """Anillo de polígono tipo sector (centro → arco a distancia radius_m), coherente con el mapa web."""
    try:
        az = float(azimuth_deg) % 360.0
    except Exception:
        return None
    ap = float(aperture_full_deg) if aperture_full_deg is not None else 60.0
    if ap <= 0:
        ap = 60.0
    try:
        r = float(radius_m)
    except Exception:
        return None
    if r <= 0:
        return None
    half = ap / 2.0
    start = az - half
    end = az + half
    step = max(3.0, min(12.0, ap / 7.0))
    ring = [(float(lon), float(lat))]
    a = start
    while a <= end + 1e-6:
        la, lo = _offset_lat_lon_meters(lat, lon, r, a)
        ring.append((lo, la))
        a += step
    la, lo = _offset_lat_lon_meters(lat, lon, r, end)
    ring.append((lo, la))
    ring.append((float(lon), float(lat)))
    return ring


def _enrich_sabana_items_for_kmz(items):
    """Adjunta azimut / abertura / radio desde sabana_datos_tecnicos por id de DatoTecnico."""
    if not items:
        return
    ids = []
    for it in items:
        if it and it.get('id') is not None:
            try:
                ids.append(int(it['id']))
            except Exception:
                pass
    if not ids:
        return
    rows = DatoTecnico.query.filter(DatoTecnico.id.in_(ids)).all()
    by_id = {r.id: r for r in rows}
    for it in items:
        if not it:
            continue
        rid = it.get('id')
        if rid is None or rid not in by_id:
            continue
        dt = by_id[rid]
        it['kmz_azimuth'] = _parse_float_loose(dt.azimuth)
        it['kmz_a_horiz'] = _parse_float_loose(dt.a_horiz)
        if it.get('kmz_a_horiz') is None or it['kmz_a_horiz'] <= 0:
            it['kmz_a_horiz'] = 60.0
        it['kmz_radius_m'] = _rad_km_str_to_m(dt.rad_cob_km)


def _kml_export_filter_summary(req):
    """Texto multilínea para descripción del documento KMZ."""
    lines = []
    if not req:
        return lines
    tipos = req.args.getlist('tipos[]')
    if tipos:
        lines.append('Tipos: ' + ', '.join(tipos))
    fd = req.args.get('fecha_desde') or ''
    fh = req.args.get('fecha_hasta') or ''
    if fd or fh:
        lines.append(f'Fechas evento: {fd or "—"} → {fh or "—"}')
    hd = req.args.get('hora_desde') or ''
    hh = req.args.get('hora_hasta') or ''
    if hd or hh:
        lines.append(f'Horas: {hd or "—"} – {hh or "—"}')
    st = (req.args.get('source_type') or '').strip()
    if st:
        lines.append('Fuente tráfico (Record): ' + st)
    fuentes = req.args.getlist('fuente_ids[]')
    if fuentes:
        lines.append('Archivos/fuentes (ids): ' + ', '.join(fuentes[:30]) + ('…' if len(fuentes) > 30 else ''))
    nums = req.args.getlist('numeros[]')
    if nums:
        lines.append(f'Filtro números: {len(nums)} valor(es)')
    ims = req.args.getlist('imeis[]')
    if ims:
        lines.append(f'Filtro IMEI: {len(ims)} valor(es)')
    prov = req.args.getlist('provincias[]')
    loc = req.args.getlist('localidades[]')
    if prov:
        lines.append('Provincias: ' + ', '.join(prov[:12]) + ('…' if len(prov) > 12 else ''))
    if loc:
        lines.append('Localidades: ' + ', '.join(loc[:12]) + ('…' if len(loc) > 12 else ''))
    ref_ids = req.args.getlist('ref_punto_ids[]')
    pm = req.args.get('perimetro_m', type=int)
    if ref_ids:
        lines.append(f'Puntos de ref. (filtro geo): {len(ref_ids)} id(s)' + (f', perímetro {pm} m' if pm else ''))
    max_m = req.args.get('max_m', type=int)
    if max_m:
        lines.append(f'Radio máx. visual celdas (Record): {max_m} m')
    return lines


def _impactos_fetch_all_pages_internal(req):
    """
    Replica la paginación del mapa (all=1, resumen=1) llamando al endpoint impactos
    en el mismo origen, reenviando la cookie de sesión.
    """
    from urllib.parse import urlencode
    pairs = []
    for k, vals in req.args.lists():
        if k in ('source', 'kind', 'offset', 'limit'):
            continue
        for v in vals:
            pairs.append((k, v))
    pairs.append(('all', '1'))
    pairs.append(('resumen', '1'))
    base_root = req.url_root.rstrip('/')
    limit = 2000
    offset = 0
    merged = []
    cookie = req.headers.get('Cookie') or ''
    while offset < 100000:
        q_pairs = pairs + [('offset', str(offset)), ('limit', str(limit))]
        qs = urlencode(q_pairs)
        url = f'{base_root}/sabana-llamadas/api/mapa/impactos?{qs}'
        r = urllib.request.Request(url, headers={'Cookie': cookie, 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(r, timeout=180) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                chunk = json.loads(raw)
        except Exception as e:
            current_app.logger.warning('KMZ impactos fetch: %s', e)
            return None, 'No se pudieron obtener datos de sábana para el KMZ.'
        if not isinstance(chunk, list):
            return None, 'Respuesta inválida de impactos.'
        merged.extend(chunk)
        if len(chunk) < limit:
            break
        offset += limit
    return merged, None


def _build_kmz_bytes(source, caso, record_items, sabana_items, req):
    """Genera ZIP KMZ con doc.kml: filtros, puntos de referencia del caso, celdas con disco y sector azimut."""
    title_bits = []
    if caso:
        title_bits.append(getattr(caso, 'codigo', '') or '')
        title_bits.append(getattr(caso, 'titulo', '') or '')
    doc_name = ' — '.join([t for t in title_bits if t]) or 'Mapa SIOC — Sabana'
    desc_lines = [
        'Exportado desde SIOC · Sabana de Llamadas.',
        f'Capas incluidas: {source}.',
    ]
    desc_lines.extend(_kml_export_filter_summary(req))
    doc_desc = _xml_text('\n'.join(desc_lines))

    kml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>{_xml_text(doc_name)}</name>',
        f'<description>{doc_desc}</description>',
        '<Style id="pinCell"><IconStyle><scale>0.85</scale><Icon><href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href></Icon></IconStyle></Style>',
        '<Style id="pinRef"><IconStyle><scale>0.9</scale><Icon><href>http://maps.google.com/mapfiles/kml/pushpin/grn-pushpin.png</href></Icon></IconStyle></Style>',
        '<Style id="styleDisk"><LineStyle><color>ff00d7ff</color><width>1.5</width></LineStyle><PolyStyle><color>4000d7ff</color></PolyStyle></Style>',
        '<Style id="styleSector"><LineStyle><color>ff5882fd</color><width>1.5</width></LineStyle><PolyStyle><color>3a5882fd</color></PolyStyle></Style>',
        '<Style id="styleRefPerim"><LineStyle><color>ff00ffff</color><width>2</width></LineStyle><PolyStyle><color>3300ffff</color></PolyStyle></Style>',
    ]

    ref_filter_ids = {int(x) for x in req.args.getlist('ref_punto_ids[]', type=int) if x and int(x) > 0}
    per_m = req.args.get('perimetro_m', type=int)

    if caso:
        all_refs = (
            AnalisisPuntoCasoMapaPunto.query.options(joinedload(AnalisisPuntoCasoMapaPunto.user))
            .filter_by(
                caso_id=caso.id,
                unidad_id=current_user.unidad_id,
            )
            .order_by(AnalisisPuntoCasoMapaPunto.id.asc())
            .all()
        )
        kml_parts.append('<Folder><name>1 · Puntos de referencia del caso</name>')
        for p in all_refs:
            if p.lat is None or p.lon is None:
                continue
            lab = (p.etiqueta or '').strip() or (p.tipo or 'Referencia')
            fold_nm = f'{lab} (id {p.id})'
            who = ''
            try:
                if p.user and getattr(p.user, 'username', None):
                    who = str(p.user.username)
            except Exception:
                who = ''
            desc_parts = [
                f'<b>Punto de referencia</b>',
                f'<br/>Tipo: {html.escape(str(p.tipo or ""))}',
                f'<br/>Etiqueta: {html.escape(str(lab))}',
            ]
            if p.nota:
                desc_parts.append(f'<br/>Nota: {html.escape(str(p.nota)[:800])}')
            if who:
                desc_parts.append(f'<br/>Registró: {html.escape(who)}')
            desc_parts.append(f'<br/>Coord.: {p.lat:.6f}, {p.lon:.6f}')
            if p.icono:
                desc_parts.append(f'<br/>Icono: {html.escape(str(p.icono))}')
            if p.origen_contexto:
                desc_parts.append(f'<br/>Origen: {html.escape(str(p.origen_contexto))}')
            if p.id in ref_filter_ids and per_m and per_m > 0:
                desc_parts.append(f'<br/><b>Perímetro de filtro activo:</b> {per_m} m')
            desc_html = ''.join(desc_parts)

            kml_parts.append('<Folder>')
            kml_parts.append(f'<name>{_xml_text(fold_nm)}</name>')
            kml_parts.append(f'<description><![CDATA[{desc_html}]]></description>')
            kml_parts.append('<Placemark>')
            kml_parts.append(f'<name>{_xml_text("Ubicación")}</name>')
            kml_parts.append('<styleUrl>#pinRef</styleUrl>')
            kml_parts.append('<Point>')
            kml_parts.append(f'<coordinates>{float(p.lon)},{float(p.lat)},0</coordinates>')
            kml_parts.append('</Point>')
            kml_parts.append('</Placemark>')
            if p.id in ref_filter_ids and per_m and per_m > 0:
                ring = _circle_ring_coords(float(p.lat), float(p.lon), float(per_m))
                coord_txt = ' '.join(f'{lo},{la},0' for lo, la in ring)
                kml_parts.append('<Placemark>')
                kml_parts.append(f'<name>{_xml_text("Perímetro filtro (" + str(per_m) + " m)")}</name>')
                kml_parts.append('<styleUrl>#styleRefPerim</styleUrl>')
                kml_parts.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>' + coord_txt + '</coordinates></LinearRing></outerBoundaryIs></Polygon>')
                kml_parts.append('</Placemark>')
            kml_parts.append('</Folder>')
        kml_parts.append('</Folder>')

    def _append_celda_placemarks(folder_title, items, is_record):
        kml_parts.append(f'<Folder><name>{_xml_text(folder_title)}</name>')
        for it in items or []:
            if not it or it.get('lat') is None or it.get('lng') is None:
                continue
            la = float(it['lat'])
            lo = float(it['lng'])
            cid = str(it.get('celda_id') or '')
            tipo = str(it.get('tipo') or '')
            cnt = it.get('impactos_count')
            r_draw = it.get('radius_draw_m')
            try:
                rd = int(r_draw) if r_draw is not None else 0
            except Exception:
                rd = 0

            if is_record:
                az_v = it.get('azimuth_deg')
                ap_v = it.get('aperture_h_deg')
                r_full = it.get('radius_full_m')
            else:
                az_v = it.get('kmz_azimuth')
                ap_v = it.get('kmz_a_horiz')
                r_full = it.get('kmz_radius_m')
                if rd <= 0 and r_full:
                    try:
                        rd = int(r_full)
                    except Exception:
                        rd = 0

            fold_name = f'{cid} · {tipo} · {cnt} imp.'
            desc = [
                '<table border="0" cellpadding="4" cellspacing="0" style="font-family:sans-serif;font-size:11px;">',
                f'<tr><td><b>Celda</b></td><td>{html.escape(cid)}</td></tr>',
                f'<tr><td><b>Tipo</b></td><td>{html.escape(tipo)}</td></tr>',
                f'<tr><td><b>Impactos</b></td><td>{html.escape(str(cnt))}</td></tr>',
            ]
            if is_record:
                if it.get('province_cell'):
                    desc.append(f'<tr><td>Provincia</td><td>{html.escape(str(it["province_cell"]))}</td></tr>')
                if it.get('locality_cell'):
                    desc.append(f'<tr><td>Localidad</td><td>{html.escape(str(it["locality_cell"]))}</td></tr>')
                if it.get('celda_direccion'):
                    desc.append(f'<tr><td>Dirección</td><td>{html.escape(str(it["celda_direccion"])[:240])}</td></tr>')
                if r_full is not None and int(r_full or 0) > 0:
                    desc.append(f'<tr><td>Radio cobertura (BD)</td><td>{int(r_full)} m</td></tr>')
                if it.get('radius_draw_m'):
                    desc.append(f'<tr><td>Radio dibujado / KMZ</td><td>{html.escape(str(it["radius_draw_m"]))} m</td></tr>')
                if az_v is not None:
                    desc.append(f'<tr><td><b>Azimut</b></td><td>{html.escape(str(az_v))}°</td></tr>')
                if ap_v is not None:
                    desc.append(f'<tr><td>Abertura horizontal</td><td>{html.escape(str(ap_v))}°</td></tr>')
                elif az_v is not None:
                    desc.append('<tr><td>Abertura horizontal</td><td>60° (predeterminado)</td></tr>')
                if it.get('distance_to_center_m') is not None:
                    desc.append(f'<tr><td>Dist. a ref. (filtro)</td><td>{html.escape(str(it["distance_to_center_m"]))} m</td></tr>')
            else:
                if it.get('celda_direccion'):
                    desc.append(f'<tr><td>Dirección</td><td>{html.escape(str(it["celda_direccion"]))}</td></tr>')
                if it.get('kmz_radius_m'):
                    desc.append(f'<tr><td>Radio cob. (datos técnicos)</td><td>{html.escape(str(it["kmz_radius_m"]))} m</td></tr>')
                if az_v is not None:
                    desc.append(f'<tr><td><b>Azimut</b></td><td>{html.escape(str(az_v))}°</td></tr>')
                if ap_v is not None:
                    desc.append(f'<tr><td>Abertura horizontal</td><td>{html.escape(str(ap_v))}°</td></tr>')

            desc.append('</table>')
            desc_html = ''.join(desc)

            kml_parts.append('<Folder>')
            kml_parts.append(f'<name>{_xml_text(fold_name)}</name>')
            kml_parts.append(f'<description><![CDATA[{desc_html}]]></description>')

            kml_parts.append('<Placemark>')
            kml_parts.append(f'<name>{_xml_text("Antena (centro)")}</name>')
            kml_parts.append('<styleUrl>#pinCell</styleUrl>')
            kml_parts.append('<Point>')
            kml_parts.append(f'<coordinates>{lo},{la},0</coordinates>')
            kml_parts.append('</Point>')
            kml_parts.append('</Placemark>')

            if rd > 0:
                ring_d = _circle_ring_coords(la, lo, float(rd))
                coord_d = ' '.join(f'{x},{y},0' for x, y in ring_d)
                kml_parts.append('<Placemark>')
                kml_parts.append(f'<name>{_xml_text("Cobertura (disco " + str(rd) + " m)")}</name>')
                kml_parts.append('<styleUrl>#styleDisk</styleUrl>')
                kml_parts.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>' + coord_d + '</coordinates></LinearRing></outerBoundaryIs></Polygon>')
                kml_parts.append('</Placemark>')

            az_use = _parse_float_loose(az_v) if az_v is not None else None
            if az_use is not None and rd > 0:
                ap_use = float(ap_v) if ap_v is not None and float(ap_v) > 0 else 60.0
                sec = _sector_polygon_ring_latlon(la, lo, float(rd), az_use, ap_use)
                if sec:
                    coord_s = ' '.join(f'{a},{b},0' for a, b in sec)
                    kml_parts.append('<Placemark>')
                    kml_parts.append(f'<name>{_xml_text("Sector azimut (" + str(int(ap_use)) + "°)")}</name>')
                    kml_parts.append('<styleUrl>#styleSector</styleUrl>')
                    kml_parts.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>' + coord_s + '</coordinates></LinearRing></outerBoundaryIs></Polygon>')
                    kml_parts.append('</Placemark>')

            kml_parts.append('</Folder>')
        kml_parts.append('</Folder>')

    if record_items:
        _append_celda_placemarks('2 · Celdas Record (ap)', record_items, True)
    if sabana_items:
        _append_celda_placemarks('3 · Celdas Sábana', sabana_items, False)

    kml_parts.append('</Document></kml>')
    kml_xml = '\n'.join(kml_parts)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('doc.kml', kml_xml.encode('utf-8'))
    buf.seek(0)
    return buf.getvalue()


@bp.route('/api/mapa/export-kmz')
def api_mapa_export_kmz():
    """
    KMZ para Google Earth: mismos filtros que el mapa (query string como record-impactos o impactos).
    source=record | sabana | ambos (default record si viene caso_id de análisis; si no, sabana).
    """
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403

    src = (request.args.get('source') or 'record').strip().lower()
    if src not in ('record', 'sabana', 'ambos'):
        src = 'record'

    caso = None
    record_items = None
    sabana_items = None

    if src in ('record', 'ambos'):
        rec_res = _record_impactos_build_list(request)
        if rec_res[0] is None:
            return rec_res[1]
        record_items, caso = rec_res

    if src in ('sabana', 'ambos'):
        sabana_items, err = _impactos_fetch_all_pages_internal(request)
        if err:
            return jsonify({'error': err}), 500
        if sabana_items:
            _enrich_sabana_items_for_kmz(sabana_items)
        if src == 'sabana' and (not sabana_items):
            return jsonify({'error': 'Sin celdas con los filtros actuales.'}), 400

    caso_doc = caso
    if caso_doc is None:
        _cid = request.args.get('caso_id', type=int)
        if _cid:
            caso_doc = _get_caso_accesible(_cid)

    if src == 'record' and (not record_items):
        nrefs = 0
        if caso_doc:
            nrefs = (
                AnalisisPuntoCasoMapaPunto.query.filter_by(
                    caso_id=caso_doc.id,
                    unidad_id=current_user.unidad_id,
                ).count()
            )
        if nrefs == 0:
            return jsonify({'error': 'Sin celdas Record con los filtros actuales (y sin puntos de referencia en el caso).'}), 400

    if src == 'ambos' and (not record_items) and (not sabana_items):
        return jsonify({'error': 'Sin datos con los filtros actuales.'}), 400

    kmz = _build_kmz_bytes(src, caso_doc, record_items or [], sabana_items or [], request)

    def _safe_kmz_code_token(caso_obj):
        if not caso_obj:
            return ''
        raw = getattr(caso_obj, 'codigo', None) or ''
        if not raw:
            return ''
        t = ''.join(ch if (ch.isalnum() or ch in '-_.') else '_' for ch in str(raw).strip())
        while '__' in t:
            t = t.replace('__', '_')
        t = t.strip('_')[:56]
        return t or ''

    code_tok = _safe_kmz_code_token(caso_doc)
    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    name_parts = ['mapa', src]
    if code_tok:
        name_parts.append(code_tok)
    name_parts.append(ts)
    fn = '-'.join(name_parts) + '.kmz'

    bio = io.BytesIO(kmz)
    bio.seek(0)
    return send_file(
        bio,
        mimetype='application/vnd.google-earth.kmz',
        as_attachment=True,
        download_name=fn,
    )


@bp.route('/api/mapa/record-impactos')
def api_mapa_record_impactos():
    """
    Puntos por celda (Record / ap_*) para el mapa central, mismo formato que /api/mapa/impactos.
    Params:
    - caso_id (requerido)
    - max_m: radio máximo visual (metros); si viene, se usa min(radio_celda, max_m)
    - center_lat, center_lng, perimetro_m: filtro geográfico (punto + radio en metros)
    - ref_punto_ids[]: ids de ap_caso_mapa_puntos del caso; con perimetro_m filtra por cercanía a cualquiera de esos puntos (OR)
    - source_type: VOZ | GPRS | vacío (todos; GPRS aún sin parser completo)
    - fuente_id: id de ap_fuentes para filtrar un archivo específico del caso
    - fuente_ids[]: lista de ids de ap_fuentes (filtro unificado desde "Archivo / Carga")
    - filtros compartidos de mapa: tipos[], fecha_desde/fecha_hasta, hora_desde/hora_hasta, numeros[], imeis[], provincias[], localidades[]
    """
    if not _permiso():
        return jsonify([]), 403
    out, caso = _record_impactos_build_list(request)
    if out is None:
        return caso
    resp = jsonify(out)
    resp.headers['X-Record-Caso'] = str(caso.id)
    return resp


@bp.route('/api/mapa/ref-punto-numeros-cercanos')
def api_mapa_ref_punto_numeros_cercanos():
    """
    Números distintos (MSISDN origen/destino en ap_eventos) con impactos en celdas que «cubren» el
    punto de referencia según ref_geo_mode. Orden: distancia ref→antena ascendente.
    Respeta los mismos filtros de mapa Record que /api/mapa/record-impactos (tipos, fechas, fuentes, etc.).

    GET:
      - caso_id, ref_punto_id (requeridos)
      - perimetro_m: radio de búsqueda en metros (default 2000, máx 500000); en modo «centro» es el
        tope de distancia ref→antena; en «disco/sector» sin radio en BD actúa como tope de respaldo
      - ref_geo_mode: centro | disco | sector (default centro)
      - limit: cantidad máxima de números distintos (default 50, máx 500)
    """
    if not _permiso():
        return jsonify({'error': 'forbidden'}), 403
    caso_id = request.args.get('caso_id', type=int)
    ref_id = request.args.get('ref_punto_id', type=int)
    if not caso_id or not ref_id:
        return jsonify({'error': 'caso_id y ref_punto_id requeridos'}), 400

    caso = _get_caso_accesible(caso_id)
    if not caso:
        return jsonify({'error': 'caso no encontrado'}), 404

    pref = AnalisisPuntoCasoMapaPunto.query.filter_by(
        id=ref_id,
        caso_id=caso.id,
        unidad_id=current_user.unidad_id,
    ).first()
    if not pref or pref.lat is None or pref.lon is None:
        return jsonify({'error': 'punto de referencia no encontrado'}), 404

    perimetro_m = request.args.get('perimetro_m', type=int)
    if perimetro_m is None or perimetro_m <= 0:
        perimetro_m = 2000
    perimetro_m = min(perimetro_m, 500000)

    limit = request.args.get('limit', type=int) or 50
    limit = max(1, min(limit, 500))

    ref_geo_mode = (request.args.get('ref_geo_mode') or 'centro').strip().lower()
    if ref_geo_mode not in ('centro', 'disco', 'sector'):
        ref_geo_mode = 'centro'

    qev, early = _record_mapa_qev_from_request_filters(request, caso)
    if early is not None:
        return early

    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    provincias = [str(x).strip().lower() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip().lower() for x in request.args.getlist('localidades[]') if str(x).strip()]

    events = qev.order_by(AnalisisPuntoEvento.event_dt.asc(), AnalisisPuntoEvento.id.asc()).all()
    by_cell = {}
    for ev in events:
        cid = ev.cell_id
        if not cid:
            continue
        by_cell.setdefault(cid, []).append(ev)

    ref_la, ref_lo = float(pref.lat), float(pref.lon)

    def _event_hm(ev):
        try:
            if ev.event_dt:
                return ev.event_dt.strftime('%H:%M')
        except Exception:
            pass
        hh = (getattr(ev, 'event_hour', None) or '').strip()
        if not hh:
            return None
        if len(hh) == 1:
            hh = '0' + hh
        if len(hh) >= 2:
            return hh[:2] + ':00'
        return None

    by_num = {}

    for cell_id, evs in by_cell.items():
        cel = AnalisisPuntoCelda.query.filter_by(id=cell_id, unidad_id=current_user.unidad_id).first()
        if not cel or cel.lat is None or cel.lon is None:
            continue
        if provincias:
            prov = (cel.province or '').strip().lower()
            if not prov or prov not in provincias:
                continue
        if localidades:
            loc = (cel.locality or '').strip().lower()
            if not loc or loc not in localidades:
                continue
        ok_geom, d_int = _ref_punto_in_celda_geom(ref_la, ref_lo, cel, perimetro_m, ref_geo_mode)
        if not ok_geom or d_int is None:
            continue
        celda_norm = _normalize_celda_id_py(cel.cell_code)

        for ev in evs:
            hm = _event_hm(ev)
            if hora_desde_hm:
                if hm is None or hm < hora_desde_hm:
                    continue
            if hora_hasta_hm:
                if hm is None or hm > hora_hasta_hm:
                    continue
            nks = {}
            for raw in (ev.origin_msisdn, ev.target_msisdn):
                k = _msisdn_agg_key(raw)
                if k and k not in nks:
                    nks[k] = str(raw).strip()
            for nk, disp in nks.items():
                prev = by_num.get(nk)
                if prev is None:
                    by_num[nk] = {
                        'numero': disp,
                        'min_dist_m': d_int,
                        'impactos': 1,
                        'celda_mas_cercana': celda_norm,
                    }
                else:
                    prev['impactos'] = prev.get('impactos', 0) + 1
                    if d_int < prev['min_dist_m']:
                        prev['min_dist_m'] = d_int
                        prev['celda_mas_cercana'] = celda_norm

    rows = sorted(by_num.values(), key=lambda x: (x['min_dist_m'], (x.get('numero') or '')))
    total = len(rows)
    rows = rows[:limit]

    return jsonify({
        'ok': True,
        'ref_punto_id': ref_id,
        'perimetro_m': perimetro_m,
        'ref_geo_mode': ref_geo_mode,
        'ref_geo_mode_desc': _REF_GEO_MODE_DESC.get(ref_geo_mode, ''),
        'total_distintos': total,
        'mostrando': len(rows),
        'numeros': rows,
    })


@bp.route('/api/mapa/record-fuentes')
def api_mapa_record_fuentes():
    """Lista archivos record (ap_fuentes) disponibles por caso para el filtro del mapa."""
    if not _permiso():
        return jsonify([]), 403
    caso_id = request.args.get('caso_id', type=int)
    if not caso_id:
        return jsonify({'error': 'caso_id requerido'}), 400
    caso = _get_caso_accesible(caso_id)
    if not caso:
        return jsonify({'error': 'caso no encontrado'}), 404

    st = (request.args.get('source_type') or '').strip().upper()
    if st not in ('', 'VOZ', 'GPRS'):
        st = ''

    q = AnalisisPuntoFuente.query.filter(
        AnalisisPuntoFuente.caso_id == caso.id,
        AnalisisPuntoFuente.unidad_id == current_user.unidad_id,
    )
    if st in ('VOZ', 'GPRS'):
        q = q.filter(AnalisisPuntoFuente.source_type == st)
    rows = q.order_by(AnalisisPuntoFuente.created_at.desc(), AnalisisPuntoFuente.id.desc()).limit(500).all()
    if rows:
        return jsonify([
            {
                'id': r.id,
                'nombre_archivo': r.nombre_archivo,
                'source_type': r.source_type,
                'operadora': r.operadora,
                'created_at': r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ])

    # Fallback: si faltan metadatos en ap_fuentes, listar fuente_id detectadas en ap_eventos.
    qev = db.session.query(
        AnalisisPuntoEvento.fuente_id.label('fuente_id'),
        func.max(AnalisisPuntoEvento.source_type).label('source_type'),
        func.max(AnalisisPuntoEvento.created_at).label('created_at'),
    ).filter(
        AnalisisPuntoEvento.caso_id == caso.id,
        AnalisisPuntoEvento.unidad_id == current_user.unidad_id,
        AnalisisPuntoEvento.fuente_id.isnot(None),
    )
    if st in ('VOZ', 'GPRS'):
        qev = qev.filter(AnalisisPuntoEvento.source_type == st)
    qev = qev.group_by(AnalisisPuntoEvento.fuente_id).order_by(func.max(AnalisisPuntoEvento.created_at).desc()).limit(500)
    ev_rows = qev.all()
    return jsonify([
        {
            'id': int(r.fuente_id),
            'nombre_archivo': f'Fuente #{int(r.fuente_id)} (sin metadatos)',
            'source_type': (r.source_type or None),
            'operadora': None,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        }
        for r in ev_rows if r and r.fuente_id is not None
    ])


@bp.route('/api/mapa/celda-impactos')
def api_mapa_celda_impactos():
    """
    Devuelve la lista de impactos (registros de tráfico) de una celda específica.
    Se usa para cargar el detalle on-demand al click en el mapa.

    Params requeridos:
    - tipo: 'gprs' o 'voz'
    - carga_id: int
    - celda_id: str
    """
    if not _permiso():
        return jsonify([]), 403

    tipo = (request.args.get('tipo') or '').strip().lower()
    carga_id = request.args.get('carga_id', type=int)
    celda_id = _normalize_celda_id_py((request.args.get('celda_id') or '').strip())
    if not tipo or tipo not in ('gprs', 'voz') or not carga_id or not celda_id:
        return jsonify([]), 400

    # Si with_ord=1, devolver también el #orden global real (según filtros actuales y solo_geo=1)
    with_ord = (request.args.get('with_ord') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí')

    # Filtros avanzados (sobre impactos de tráfico)
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]

    if tipo == 'gprs':
        q_reg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id == carga_id,
            _normalize_celda_id_sql(ResultadoTraficoGPRS.celda) == celda_id,
        )
        q_reg = _apply_fecha_hora_filters(q_reg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q_reg = q_reg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            q_reg = q_reg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            q_reg = q_reg.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                q_reg = q_reg.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        registros = q_reg.order_by(ResultadoTraficoGPRS.fecha, _hora_ord_sql(ResultadoTraficoGPRS.hora), ResultadoTraficoGPRS.id).all()
        out = [_serialize_gprs(r) for r in registros]
    else:
        q_reg = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id == carga_id,
            _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id) == celda_id,
        )
        q_reg = _apply_fecha_hora_filters(q_reg, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q_reg = q_reg.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            q_reg = q_reg.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            q_reg = q_reg.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                q_reg = q_reg.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        registros = q_reg.order_by(ResultadoTraficoVOZ.fecha, _hora_ord_sql(ResultadoTraficoVOZ.hora), ResultadoTraficoVOZ.id).all()
        out = [_serialize_voz(r) for r in registros]

    # Adjuntar orden global real, para evitar numeración "local" cuando hay miles de registros.
    # Esto reemplaza el pedido de orden por IDs desde el frontend (que puede fallar por URL larga).
    if with_ord and out:
        # Determinar el universo de cargas a considerar para el orden global (según filtros actuales)
        q_cargas = _cargas_query_accessible()
        if sujeto_ids:
            q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
        if carga_ids:
            q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
        if tipos:
            q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
        cargas_ids = [r[0] for r in q_cargas.with_entities(CargaLlamada.id).all()]
        if cargas_ids:
            def hora_ord(col):
                return _hora_ord_sql(col)

            # Siempre coherente con el mapa: orden solo para impactos mapeables
            solo_geo = True

            g_sel = None
            v_sel = None

            if (not tipos) or ('gprs' in tipos) or (tipo == 'gprs'):
                qg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
                    CargaLlamada.unidad_id == current_user.unidad_id,
                    _carga_access_predicate(),
                    ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
                )
                if solo_geo:
                    coord_exists = _coord_exists_any_accessible('gprs', ResultadoTraficoGPRS.celda)
                    qg = qg.filter(ResultadoTraficoGPRS.celda.isnot(None), coord_exists)
                qg = _apply_fecha_hora_filters(qg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
                if provincias:
                    qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
                if localidades:
                    qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
                if imeis:
                    qg = qg.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
                if numeros:
                    ors = []
                    for n in numeros[:50]:
                        ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
                    if ors:
                        qg = qg.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
                g_sel = qg.with_entities(
                    literal('gprs').label('tipo'),
                    ResultadoTraficoGPRS.id.label('impacto_id'),
                    ResultadoTraficoGPRS.fecha.label('fecha'),
                    hora_ord(ResultadoTraficoGPRS.hora).label('hora'),
                )

            if (not tipos) or ('voz' in tipos) or (tipo == 'voz'):
                qv = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
                    CargaLlamada.unidad_id == current_user.unidad_id,
                    _carga_access_predicate(),
                    ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
                )
                if solo_geo:
                    coord_exists = _coord_exists_any_accessible('voz', ResultadoTraficoVOZ.celda_id)
                    qv = qv.filter(ResultadoTraficoVOZ.celda_id.isnot(None), coord_exists)
                qv = _apply_fecha_hora_filters(qv, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
                if provincias:
                    qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
                if localidades:
                    qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
                if imeis:
                    qv = qv.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
                if numeros:
                    ors = []
                    for n in numeros[:50]:
                        ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                        ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
                    if ors:
                        qv = qv.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
                v_sel = qv.with_entities(
                    literal('voz').label('tipo'),
                    ResultadoTraficoVOZ.id.label('impacto_id'),
                    ResultadoTraficoVOZ.fecha.label('fecha'),
                    hora_ord(ResultadoTraficoVOZ.hora).label('hora'),
                )

            union_q = None
            if g_sel is not None and v_sel is not None:
                union_q = g_sel.union_all(v_sel)
            elif g_sel is not None:
                union_q = g_sel
            elif v_sel is not None:
                union_q = v_sel

            if union_q is not None:
                u = union_q.subquery('u')
                ranked = db.session.query(
                    u.c.tipo,
                    u.c.impacto_id,
                    func.row_number().over(order_by=(u.c.fecha, u.c.hora, u.c.tipo, u.c.impacto_id)).label('ord')
                ).subquery('ranked')

                wanted_pairs = [(tipo, int(x.get('id'))) for x in out if x and x.get('id') is not None]
                ord_rows = []
                if wanted_pairs:
                    ord_rows = db.session.query(ranked.c.impacto_id, ranked.c.ord).filter(
                        tuple_(ranked.c.tipo, ranked.c.impacto_id).in_(wanted_pairs)
                    ).all()
                ord_map = {int(i): int(o) for (i, o) in ord_rows if i is not None and o is not None}
                for it in out:
                    try:
                        iid = it.get('id')
                        if iid is not None and int(iid) in ord_map:
                            it['_ord'] = ord_map[int(iid)]
                    except Exception:
                        pass

    resp = jsonify(out)
    resp.headers['X-Count'] = str(len(out))
    return resp


@bp.route('/api/mapa/orden-celdas')
def api_mapa_orden_celdas():
    """
    Devuelve, para los filtros actuales, el primer/último orden cronológico por celda (tipo+carga+celda_id).
    Se usa en el frontend para que cada pin muestre el # del primer impacto cronológico.
    """
    if not _permiso():
        return jsonify([]), 403

    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')

    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]
    # Para modo progresivo (frontend): devolver solo órdenes hasta N
    max_ord = request.args.get('max_ord', type=int)
    if max_ord is not None and max_ord < 1:
        max_ord = 1

    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
    q_cargas = _apply_mapa_caso_arg_to_carga_query(q_cargas)
    cargas_ids = [r[0] for r in q_cargas.with_entities(CargaLlamada.id).all()]
    if not cargas_ids:
        return jsonify([])

    rows = []

    def add_rows_gprs():
        coord_exists = _coord_exists_any_accessible('gprs', ResultadoTraficoGPRS.celda)
        q = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
            ResultadoTraficoGPRS.celda.isnot(None),
            coord_exists,
        )
        q = _apply_fecha_hora_filters(q, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q = q.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            q = q.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            q = q.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                q = q.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        for carga_id, celda, fecha, hora in q.with_entities(
            ResultadoTraficoGPRS.carga_id, ResultadoTraficoGPRS.celda, ResultadoTraficoGPRS.fecha, ResultadoTraficoGPRS.hora
        ).all():
            rows.append(('gprs', int(carga_id), _normalize_celda_id_py(celda), fecha, hora))

    def add_rows_voz():
        coord_exists = _coord_exists_any_accessible('voz', ResultadoTraficoVOZ.celda_id)
        q = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
            ResultadoTraficoVOZ.celda_id.isnot(None),
            coord_exists,
        )
        q = _apply_fecha_hora_filters(q, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q = q.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            q = q.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            q = q.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                q = q.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        for carga_id, celda_id, fecha, hora in q.with_entities(
            ResultadoTraficoVOZ.carga_id, ResultadoTraficoVOZ.celda_id, ResultadoTraficoVOZ.fecha, ResultadoTraficoVOZ.hora
        ).all():
            rows.append(('voz', int(carga_id), _normalize_celda_id_py(celda_id), fecha, hora))

    if not tipos or 'gprs' in tipos:
        add_rows_gprs()
    if not tipos or 'voz' in tipos:
        add_rows_voz()

    def _hora_key(h):
        if not h:
            return (0, 0, 0)
        s = str(h).strip()
        if not s:
            return (0, 0, 0)
        parts = s.split(':')
        try:
            hh = int(parts[0]) if len(parts) > 0 else 0
            mm = int(parts[1]) if len(parts) > 1 else 0
            ss = int(parts[2]) if len(parts) > 2 else 0
            return (hh, mm, ss)
        except Exception:
            return (0, 0, 0)

    def sort_key(r):
        # r: (tipo,carga,celda,fecha_dt,hora_str)
        f = r[3] or datetime.min
        return (f, _hora_key(r[4]))

    rows.sort(key=sort_key)

    total_impactos = len(rows)
    truncated = False
    if max_ord is not None and total_impactos > max_ord:
        rows = rows[:max_ord]
        truncated = True

    out_map = {}
    for idx, r in enumerate(rows, 1):
        tipo, carga_id, celda_id, _, _ = r
        k = (tipo, carga_id, celda_id)
        cur = out_map.get(k)
        if not cur:
            out_map[k] = {'ord_min': idx, 'ord_max': idx}
        else:
            if idx < cur['ord_min']:
                cur['ord_min'] = idx
            if idx > cur['ord_max']:
                cur['ord_max'] = idx

    out = [{'tipo': k[0], 'carga_id': k[1], 'celda_id': k[2], 'ord_min': v['ord_min'], 'ord_max': v['ord_max']} for k, v in out_map.items()]
    resp = jsonify(out)
    resp.headers['X-Total-Impactos'] = str(total_impactos)
    resp.headers['X-Total-Celdas'] = str(len(out))
    if truncated:
        resp.headers['X-Truncated'] = '1'
    return resp


@bp.route('/api/mapa/orden-celdas-celda')
def api_mapa_orden_celdas_celda():
    """
    Devuelve, para los filtros actuales, el primer/último orden cronológico por celda física:
    (tipo + celda_id) SIN incluir carga_id.

    Esto evita inconsistencias cuando el mapa usa coordenadas de una carga distinta (fallback),
    pero el investigador necesita ver el orden real de esa celda en el universo filtrado.
    """
    if not _permiso():
        return jsonify([]), 403

    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')

    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]
    max_ord = request.args.get('max_ord', type=int)
    if max_ord is not None and max_ord < 1:
        max_ord = 1

    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
    q_cargas = _apply_mapa_caso_arg_to_carga_query(q_cargas)
    cargas_ids = [r[0] for r in q_cargas.with_entities(CargaLlamada.id).all()]
    if not cargas_ids:
        return jsonify([])

    # Construir base UNION (global) sin depender de coordenadas.
    g_sel = None
    v_sel = None

    if not tipos or 'gprs' in tipos:
        qg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
            ResultadoTraficoGPRS.celda.isnot(None),
        )
        qg = _apply_fecha_hora_filters(qg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            qg = qg.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                qg = qg.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        g_sel = qg.with_entities(
            literal('gprs').label('tipo'),
            ResultadoTraficoGPRS.id.label('impacto_id'),
            _normalize_celda_id_sql(ResultadoTraficoGPRS.celda).label('celda_norm'),
            ResultadoTraficoGPRS.fecha.label('fecha'),
            _hora_ord_sql(ResultadoTraficoGPRS.hora).label('hora'),
        )

    if not tipos or 'voz' in tipos:
        qv = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
            ResultadoTraficoVOZ.celda_id.isnot(None),
        )
        qv = _apply_fecha_hora_filters(qv, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            qv = qv.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                qv = qv.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        v_sel = qv.with_entities(
            literal('voz').label('tipo'),
            ResultadoTraficoVOZ.id.label('impacto_id'),
            _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id).label('celda_norm'),
            ResultadoTraficoVOZ.fecha.label('fecha'),
            _hora_ord_sql(ResultadoTraficoVOZ.hora).label('hora'),
        )

    union_q = None
    if g_sel is not None and v_sel is not None:
        union_q = g_sel.union_all(v_sel)
    elif g_sel is not None:
        union_q = g_sel
    elif v_sel is not None:
        union_q = v_sel
    else:
        return jsonify([])

    u = union_q.subquery('u')
    ranked = db.session.query(
        u.c.tipo,
        u.c.impacto_id,
        u.c.celda_norm,
        func.row_number().over(order_by=(u.c.fecha, u.c.hora, u.c.tipo, u.c.impacto_id)).label('ord')
    ).subquery('ranked')

    # total global (sin truncar) para header
    total_impactos = db.session.query(func.count()).select_from(ranked).scalar() or 0

    q_ranked = db.session.query(ranked.c.tipo, ranked.c.celda_norm, ranked.c.ord)
    truncated = False
    if max_ord is not None and total_impactos > max_ord:
        q_ranked = q_ranked.filter(ranked.c.ord <= max_ord)
        truncated = True

    rows = db.session.query(
        ranked.c.tipo,
        ranked.c.celda_norm,
        func.min(ranked.c.ord).label('ord_min'),
        func.max(ranked.c.ord).label('ord_max'),
    ).filter(
        ranked.c.celda_norm.isnot(None),
        ranked.c.celda_norm != '',
    )
    if max_ord is not None and total_impactos > max_ord:
        rows = rows.filter(ranked.c.ord <= max_ord)
    rows = rows.group_by(ranked.c.tipo, ranked.c.celda_norm).all()

    out = [{'tipo': t, 'celda_id': c, 'ord_min': int(omin), 'ord_max': int(omax)} for (t, c, omin, omax) in rows if t and c]
    resp = jsonify(out)
    resp.headers['X-Total-Impactos'] = str(int(total_impactos))
    resp.headers['X-Total-Celdas'] = str(len(out))
    if truncated:
        resp.headers['X-Truncated'] = '1'
    # Debug opcional
    if (request.args.get('debug') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí'):
        try:
            first_row = db.session.query(ranked.c.tipo, ranked.c.celda_norm, ranked.c.ord).order_by(ranked.c.ord.asc()).first()
            if first_row:
                current_app.logger.warning(
                    "[sabana] orden-celdas-celda debug first: tipo=%s celda_norm=%s ord=%s total=%s",
                    first_row[0], first_row[1], first_row[2], total_impactos
                )
                # También en headers para inspección rápida desde DevTools (Network)
                resp.headers['X-Debug-First-Tipo'] = str(first_row[0])
                resp.headers['X-Debug-First-Celda'] = str(first_row[1])
                resp.headers['X-Debug-First-Ord'] = str(first_row[2])
        except Exception:
            pass
    return resp


@bp.route('/api/mapa/orden-impactos')
def api_mapa_orden_impactos():
    """
    Devuelve el orden cronológico global (1..N) por impacto (registro de tráfico),
    según los filtros actuales. Se usa para mostrar '#orden' en el panel y navegar.
    """
    if not _permiso():
        return jsonify([]), 403

    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')

    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]
    max_ord = request.args.get('max_ord', type=int)
    if max_ord is not None and max_ord < 1:
        max_ord = 1
    # Si solo_geo=1, el orden se calcula solo con impactos que tienen coordenadas (mapeables).
    # Esto hace que el mapa muestre #1..N de forma coherente con los pines/spiderfy/ruta.
    solo_geo = (request.args.get('solo_geo') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí')

    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
    q_cargas = _apply_mapa_caso_arg_to_carga_query(q_cargas)
    cargas_ids = [r[0] for r in q_cargas.with_entities(CargaLlamada.id).all()]
    if not cargas_ids:
        return jsonify([])

    rows = []  # (fecha_dt, hora_tuple, tipo, impacto_id)

    def _hora_key(h):
        if not h:
            return (0, 0, 0)
        s = str(h).strip()
        if not s:
            return (0, 0, 0)
        parts = s.split(':')
        try:
            hh = int(parts[0]) if len(parts) > 0 else 0
            mm = int(parts[1]) if len(parts) > 1 else 0
            ss = int(parts[2]) if len(parts) > 2 else 0
            return (hh, mm, ss)
        except Exception:
            return (0, 0, 0)

    if not tipos or 'gprs' in tipos:
        q = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
        )
        if solo_geo:
            coord_exists = _coord_exists_any_accessible('gprs', ResultadoTraficoGPRS.celda)
            q = q.filter(ResultadoTraficoGPRS.celda.isnot(None), coord_exists)
        q = _apply_fecha_hora_filters(q, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q = q.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            q = q.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            q = q.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                q = q.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        for impacto_id, fecha, hora in q.with_entities(ResultadoTraficoGPRS.id, ResultadoTraficoGPRS.fecha, ResultadoTraficoGPRS.hora).all():
            rows.append((fecha or datetime.min, _hora_key(hora), 'gprs', int(impacto_id)))

    if not tipos or 'voz' in tipos:
        q = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
        )
        if solo_geo:
            coord_exists = _coord_exists_any_accessible('voz', ResultadoTraficoVOZ.celda_id)
            q = q.filter(ResultadoTraficoVOZ.celda_id.isnot(None), coord_exists)
        q = _apply_fecha_hora_filters(q, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q = q.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            q = q.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            q = q.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                q = q.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        for impacto_id, fecha, hora in q.with_entities(ResultadoTraficoVOZ.id, ResultadoTraficoVOZ.fecha, ResultadoTraficoVOZ.hora).all():
            rows.append((fecha or datetime.min, _hora_key(hora), 'voz', int(impacto_id)))

    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    total = len(rows)
    if max_ord is not None and total > max_ord:
        rows = rows[:max_ord]
    out = []
    for i, r in enumerate(rows, 1):
        out.append({'tipo': r[2], 'impacto_id': r[3], 'ord': i})
    resp = jsonify(out)
    resp.headers['X-Total-Impactos'] = str(total)
    if max_ord is not None and total > max_ord:
        resp.headers['X-Truncated'] = '1'
    return resp


@bp.route('/api/debug/primeros-mapeo')
def api_debug_primeros_mapeo():
    """
    DEBUG: muestra los primeros registros cronológicos y cómo matchean con Datos Técnicos.

    GET /sabana-llamadas/api/debug/primeros-mapeo?limit=60

    JOIN:
      - por tipo
      - por UPPER(TRIM(celda_id)) (sin carga_id)
    """
    if not _permiso():
        return jsonify([]), 403

    limit = request.args.get('limit', type=int) or 60
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')

    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]

    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
    cargas_ids = [r[0] for r in q_cargas.with_entities(CargaLlamada.id).all()]
    if not cargas_ids:
        return jsonify([])

    # Datos técnicos por celda física (tipo+celda_norm) -> tomar el más reciente con coords
    sub_dt = db.session.query(
        DatoTecnico.tipo.label('tipo'),
        _normalize_celda_id_sql(DatoTecnico.celda_id).label('celda_norm'),
        func.max(DatoTecnico.id).label('dt_id'),
    ).join(
        CargaLlamada, CargaLlamada.id == DatoTecnico.carga_id
    ).filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        DatoTecnico.lat.isnot(None),
        DatoTecnico.long.isnot(None),
        DatoTecnico.celda_id.isnot(None),
    ).group_by(
        DatoTecnico.tipo, _normalize_celda_id_sql(DatoTecnico.celda_id)
    ).subquery('dt_max')

    dt2 = aliased(DatoTecnico)

    # Base union (registros de tráfico) con celda original + celda_norm
    g_sel = None
    v_sel = None

    if not tipos or 'gprs' in tipos:
        qg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
            ResultadoTraficoGPRS.celda.isnot(None),
        )
        qg = _apply_fecha_hora_filters(qg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            qg = qg.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                qg = qg.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        g_sel = qg.with_entities(
            ResultadoTraficoGPRS.id.label('id'),
            literal('gprs').label('tipo'),
            ResultadoTraficoGPRS.carga_id.label('carga_id'),
            ResultadoTraficoGPRS.celda.label('celda_original'),
            _normalize_celda_id_sql(ResultadoTraficoGPRS.celda).label('celda_norm'),
            ResultadoTraficoGPRS.fecha.label('fecha'),
            _hora_ord_sql(ResultadoTraficoGPRS.hora).label('hora_ord'),
        )

    if not tipos or 'voz' in tipos:
        qv = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
            ResultadoTraficoVOZ.celda_id.isnot(None),
        )
        qv = _apply_fecha_hora_filters(qv, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            qv = qv.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                qv = qv.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        v_sel = qv.with_entities(
            ResultadoTraficoVOZ.id.label('id'),
            literal('voz').label('tipo'),
            ResultadoTraficoVOZ.carga_id.label('carga_id'),
            ResultadoTraficoVOZ.celda_id.label('celda_original'),
            _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id).label('celda_norm'),
            ResultadoTraficoVOZ.fecha.label('fecha'),
            _hora_ord_sql(ResultadoTraficoVOZ.hora).label('hora_ord'),
        )

    union_q = None
    if g_sel is not None and v_sel is not None:
        union_q = g_sel.union_all(v_sel)
    elif g_sel is not None:
        union_q = g_sel
    elif v_sel is not None:
        union_q = v_sel
    else:
        return jsonify([])

    u = union_q.subquery('u')

    q = db.session.query(
        u.c.id,
        u.c.tipo,
        u.c.carga_id,
        u.c.celda_original,
        u.c.celda_norm,
        u.c.fecha,
        u.c.hora_ord,
        dt2.lat,
        dt2.long,
    ).outerjoin(
        sub_dt,
        and_(sub_dt.c.tipo == u.c.tipo, sub_dt.c.celda_norm == u.c.celda_norm)
    ).outerjoin(
        dt2,
        dt2.id == sub_dt.c.dt_id
    ).order_by(
        u.c.fecha.asc(), u.c.hora_ord.asc(), u.c.id.asc()
    ).limit(limit)

    out = []
    for r in q.all():
        fecha_hora = None
        try:
            if r.fecha:
                # fecha puede venir con hora 00:00; usamos la hora normalizada
                fh = r.fecha
                fecha_hora = fh.strftime('%Y-%m-%d') + ' ' + (r.hora_ord or '00:00:00')
        except Exception:
            fecha_hora = None
        out.append({
            'id': int(r.id) if r.id is not None else None,
            'tipo': r.tipo,
            'carga_id': int(r.carga_id) if r.carga_id is not None else None,
            'celda_original': r.celda_original,
            'celda_norm': r.celda_norm,
            'fecha_hora': fecha_hora,
            'latitud': float(r.lat) if r.lat is not None else None,
            'longitud': float(r.long) if r.long is not None else None,
            'tiene_coords': 1 if (r.lat is not None and r.long is not None) else 0,
        })

    return jsonify(out)


@bp.route('/api/mapa/orden-impactos-por-ids')
def api_mapa_orden_impactos_por_ids():
    """
    Devuelve el #orden global (cronológico) para un subconjunto de impactos.

    Se usa para numerar el enjambre (spiderfy) con el orden global real sin bajar los 30k+ impactos.

    Params:
    - tipo: 'gprs' | 'voz'
    - impacto_ids[]: lista de ints (IDs de la tabla correspondiente)
    - (mismos filtros que /orden-impactos: sujeto_ids[], carga_ids[], tipos[], fecha/hora, numeros[], provincias[], localidades[], imeis[])
    - solo_geo: si 1, solo considera impactos mapeables (con coords)
    """
    if not _permiso():
        return jsonify([]), 403

    tipo_req = (request.args.get('tipo') or '').strip().lower()
    impacto_ids = request.args.getlist('impacto_ids[]', type=int)
    if tipo_req not in ('gprs', 'voz') or not impacto_ids:
        return jsonify([]), 400

    # Filtros globales (mismos que orden-impactos)
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]
    solo_geo = (request.args.get('solo_geo') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí')

    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
    cargas_ids = [r[0] for r in q_cargas.with_entities(CargaLlamada.id).all()]
    if not cargas_ids:
        return jsonify([])

    # Subselect union: (tipo, impacto_id, fecha_dt, hora_ord)
    def hora_ord(col):
        return _hora_ord_sql(col)

    g_sel = None
    v_sel = None

    if (not tipos) or ('gprs' in tipos) or (tipo_req == 'gprs'):
        qg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
        )
        if solo_geo:
            coord_exists = _coord_exists_any_accessible('gprs', ResultadoTraficoGPRS.celda)
            qg = qg.filter(ResultadoTraficoGPRS.celda.isnot(None), coord_exists)
        qg = _apply_fecha_hora_filters(qg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            qg = qg.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                qg = qg.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        g_sel = qg.with_entities(
            literal('gprs').label('tipo'),
            ResultadoTraficoGPRS.id.label('impacto_id'),
            ResultadoTraficoGPRS.fecha.label('fecha'),
            hora_ord(ResultadoTraficoGPRS.hora).label('hora'),
        )

    if (not tipos) or ('voz' in tipos) or (tipo_req == 'voz'):
        qv = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
        )
        if solo_geo:
            coord_exists = _coord_exists_any_accessible('voz', ResultadoTraficoVOZ.celda_id)
            qv = qv.filter(ResultadoTraficoVOZ.celda_id.isnot(None), coord_exists)
        qv = _apply_fecha_hora_filters(qv, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            qv = qv.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                qv = qv.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        v_sel = qv.with_entities(
            literal('voz').label('tipo'),
            ResultadoTraficoVOZ.id.label('impacto_id'),
            ResultadoTraficoVOZ.fecha.label('fecha'),
            hora_ord(ResultadoTraficoVOZ.hora).label('hora'),
        )

    # Construir UNION global para que el orden sea realmente global (incluye ambos tipos).
    union_q = None
    if g_sel is not None and v_sel is not None:
        union_q = g_sel.union_all(v_sel)
    elif g_sel is not None:
        union_q = g_sel
    elif v_sel is not None:
        union_q = v_sel
    else:
        return jsonify([])

    u = union_q.subquery('u')
    ranked = db.session.query(
        u.c.tipo,
        u.c.impacto_id,
        func.row_number().over(order_by=(u.c.fecha, u.c.hora, u.c.tipo, u.c.impacto_id)).label('ord')
    ).subquery('ranked')

    # Filtrar solo los IDs que nos interesan (del tipo pedido)
    # Importante: el ord es global, aunque pidamos un solo tipo.
    wanted_pairs = [(tipo_req, int(i)) for i in impacto_ids if i]
    if not wanted_pairs:
        return jsonify([])
    rows = db.session.query(ranked.c.tipo, ranked.c.impacto_id, ranked.c.ord).filter(
        tuple_(ranked.c.tipo, ranked.c.impacto_id).in_(wanted_pairs)
    ).all()
    out = [{'tipo': t, 'impacto_id': int(i), 'ord': int(o)} for (t, i, o) in rows if t and i is not None and o is not None]
    return jsonify(out)


@bp.route('/api/mapa/orden-primero')
def api_mapa_orden_primero():
    """
    Devuelve el primer impacto cronológico (ord=1) según filtros actuales.
    Útil para depurar y confirmar dónde cae el #1.
    """
    if not _permiso():
        return jsonify({}), 403

    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')

    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]

    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
    cargas_ids = [r[0] for r in q_cargas.with_entities(CargaLlamada.id).all()]
    if not cargas_ids:
        return jsonify({}), 200

    def _hora_key(h):
        if not h:
            return (0, 0, 0)
        s = str(h).strip()
        if not s:
            return (0, 0, 0)
        parts = s.split(':')
        try:
            hh = int(parts[0]) if len(parts) > 0 else 0
            mm = int(parts[1]) if len(parts) > 1 else 0
            ss = int(parts[2]) if len(parts) > 2 else 0
            return (hh, mm, ss)
        except Exception:
            return (0, 0, 0)

    best = None  # (fecha_dt, hora_tuple, tipo, impacto_id, carga_id, celda_id)

    if not tipos or 'gprs' in tipos:
        q = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
        )
        coord_exists = _coord_exists_any_accessible('gprs', ResultadoTraficoGPRS.celda)
        q = q.filter(coord_exists)
        q = _apply_fecha_hora_filters(q, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q = q.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            q = q.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            q = q.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                q = q.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        for impacto_id, fecha, hora, carga_id, celda_id in q.with_entities(
            ResultadoTraficoGPRS.id, ResultadoTraficoGPRS.fecha, ResultadoTraficoGPRS.hora, ResultadoTraficoGPRS.carga_id, ResultadoTraficoGPRS.celda
        ).all():
            key = (fecha or datetime.min, _hora_key(hora), 'gprs', int(impacto_id))
            cand = (key[0], key[1], key[2], key[3], int(carga_id), _normalize_celda_id_py(celda_id) or None)
            if best is None or (cand[0], cand[1], cand[2], cand[3]) < (best[0], best[1], best[2], best[3]):
                best = cand

    if not tipos or 'voz' in tipos:
        q = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
        )
        coord_exists = _coord_exists_any_accessible('voz', ResultadoTraficoVOZ.celda_id)
        q = q.filter(coord_exists)
        q = _apply_fecha_hora_filters(q, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q = q.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            q = q.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            q = q.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                q = q.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        for impacto_id, fecha, hora, carga_id, celda_id in q.with_entities(
            ResultadoTraficoVOZ.id, ResultadoTraficoVOZ.fecha, ResultadoTraficoVOZ.hora, ResultadoTraficoVOZ.carga_id, ResultadoTraficoVOZ.celda_id
        ).all():
            key = (fecha or datetime.min, _hora_key(hora), 'voz', int(impacto_id))
            cand = (key[0], key[1], key[2], key[3], int(carga_id), _normalize_celda_id_py(celda_id) or None)
            if best is None or (cand[0], cand[1], cand[2], cand[3]) < (best[0], best[1], best[2], best[3]):
                best = cand

    if not best:
        return jsonify({}), 200

    _, _, tipo, impacto_id, carga_id, celda_id = best
    # Resolver coords/dirección si existe dato técnico
    dt = None
    if tipo == 'gprs':
        celda_norm = _normalize_celda_id_py(celda_id)
        dt = DatoTecnico.query.filter(
            DatoTecnico.carga_id == carga_id,
            DatoTecnico.tipo == 'gprs',
            _normalize_celda_id_sql(DatoTecnico.celda_id) == celda_norm,
        ).filter(
            DatoTecnico.lat.isnot(None), DatoTecnico.long.isnot(None)
        ).order_by(DatoTecnico.id.desc()).first()
        imp = ResultadoTraficoGPRS.query.filter_by(id=impacto_id).first()
        payload = {'ord': 1, 'tipo': 'gprs', 'impacto_id': impacto_id, 'carga_id': carga_id, 'celda_id': celda_id, 'impacto': _serialize_gprs(imp) if imp else None}
    else:
        celda_norm = _normalize_celda_id_py(celda_id)
        dt = DatoTecnico.query.filter(
            DatoTecnico.carga_id == carga_id,
            DatoTecnico.tipo == 'voz',
            _normalize_celda_id_sql(DatoTecnico.celda_id) == celda_norm,
        ).filter(
            DatoTecnico.lat.isnot(None), DatoTecnico.long.isnot(None)
        ).order_by(DatoTecnico.id.desc()).first()
        imp = ResultadoTraficoVOZ.query.filter_by(id=impacto_id).first()
        payload = {'ord': 1, 'tipo': 'voz', 'impacto_id': impacto_id, 'carga_id': carga_id, 'celda_id': celda_id, 'impacto': _serialize_voz(imp) if imp else None}

    if dt:
        payload['lat'] = float(dt.lat)
        payload['lng'] = float(dt.long)
        payload['celda_direccion'] = dt.celda_direccion
    return jsonify(payload), 200


def _impacto_loc_payload_from_ap_evento(ev, tipo_lower):
    """
    Modo Record: el mapa usa IDs de ap_eventos, no ResultadoTrafico*.
    Devuelve dict con el mismo esquema que impacto-loc (lat/lng, azimuth desde ap_celdas).
    """
    st = 'VOZ' if tipo_lower == 'voz' else 'GPRS'
    if not ev or (ev.source_type or '').upper() != st:
        return None
    caso = _get_caso_accesible(ev.caso_id)
    if not caso:
        return None
    if not ev.cell_id:
        return None
    cel = AnalisisPuntoCelda.query.filter_by(
        id=ev.cell_id,
        unidad_id=current_user.unidad_id,
    ).first()
    if not cel or cel.lat is None or cel.lon is None:
        return None

    if tipo_lower == 'voz':
        impacto_d = _serialize_record_voz_event(ev)
    else:
        impacto_d = _serialize_record_gprs_event(ev)

    rad_km = None
    try:
        if cel.coverage_radius_m is not None and int(cel.coverage_radius_m) > 0:
            rad_km = float(cel.coverage_radius_m) / 1000.0
    except Exception:
        rad_km = None
    if rad_km is None or rad_km <= 0:
        rad_km = 3.0

    try:
        a_horiz = float(cel.aperture_h_deg) if cel.aperture_h_deg is not None else 60.0
    except Exception:
        a_horiz = 60.0

    return {
        'lat': float(cel.lat),
        'lng': float(cel.lon),
        'has_coords': True,
        'coords_source': 'record_celda',
        'coords_carga_id': None,
        'tipo': tipo_lower,
        'carga_id': caso.id,
        'sujeto_id': None,
        'celda_id': cel.cell_code,
        'celda_direccion': cel.address or cel.cell_code,
        'impacto': impacto_d,
        'azimuth': cel.azimuth_deg,
        'rad_cob_km': str(rad_km),
        'a_horiz': a_horiz,
        'a_vert': cel.aperture_v_deg,
    }


@bp.route('/api/mapa/impacto-loc')
def api_mapa_impacto_loc():
    """
    Devuelve ubicación (lat/lng) y detalle de un impacto, para centrar el mapa.
    Params: tipo=gprs|voz, impacto_id=int
    """
    if not _permiso():
        return jsonify({}), 403
    tipo = (request.args.get('tipo') or '').strip().lower()
    impacto_id = request.args.get('impacto_id', type=int)
    if tipo not in ('gprs', 'voz') or not impacto_id:
        return jsonify({}), 400

    if tipo == 'gprs':
        r = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.id == impacto_id,
        ).first()
        if not r:
            ev_ap = AnalisisPuntoEvento.query.filter_by(
                id=impacto_id,
                unidad_id=current_user.unidad_id,
            ).first()
            if ev_ap:
                payload_rec = _impacto_loc_payload_from_ap_evento(ev_ap, 'gprs')
                if payload_rec:
                    return jsonify(payload_rec), 200
            return jsonify({}), 404
        celda_norm = _normalize_celda_id_py(r.celda)
        # Buscar coords por (carga_id, celda) de forma normalizada
        dt = DatoTecnico.query.filter(
            DatoTecnico.carga_id == r.carga_id,
            DatoTecnico.tipo == 'gprs',
            _normalize_celda_id_sql(DatoTecnico.celda_id) == celda_norm,
        ).filter(
            DatoTecnico.lat.isnot(None), DatoTecnico.long.isnot(None)
        ).order_by(DatoTecnico.id.desc()).first()
        coords_source = 'same_carga'
        if not dt:
            # Fallback: si otra carga ya tiene la celda con coords, usarla (sin “adivinar”).
            dt = DatoTecnico.query.join(CargaLlamada).filter(
                CargaLlamada.unidad_id == current_user.unidad_id,
                _carga_access_predicate(),
                DatoTecnico.tipo == 'gprs',
                _normalize_celda_id_sql(DatoTecnico.celda_id) == celda_norm,
                DatoTecnico.lat.isnot(None),
                DatoTecnico.long.isnot(None),
            ).order_by(DatoTecnico.id.desc()).first()
            coords_source = 'other_carga' if dt else None
        if not dt:
            return jsonify({
                'has_coords': False,
                'tipo': 'gprs',
                'carga_id': r.carga_id,
                'celda_id': r.celda,
                'impacto': _serialize_gprs(r),
            }), 200
        return jsonify({
            'lat': float(dt.lat),
            'lng': float(dt.long),
            'has_coords': True,
            'coords_source': coords_source,
            'coords_carga_id': int(dt.carga_id) if getattr(dt, 'carga_id', None) is not None else None,
            'tipo': 'gprs',
            'carga_id': r.carga_id,
            'sujeto_id': CargaLlamada.query.with_entities(CargaLlamada.sujeto_id).filter(CargaLlamada.id == r.carga_id).scalar(),
            'celda_id': dt.celda_id,
            'celda_direccion': dt.celda_direccion,
            'impacto': _serialize_gprs(r),
            # Datos técnicos extra para visualización (sector/azimut)
            'azimuth': dt.azimuth,
            'rad_cob_km': dt.rad_cob_km,
            'a_horiz': dt.a_horiz,
            'a_vert': dt.a_vert,
        })

    r = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        ResultadoTraficoVOZ.id == impacto_id,
    ).first()
    if not r:
        ev_ap = AnalisisPuntoEvento.query.filter_by(
            id=impacto_id,
            unidad_id=current_user.unidad_id,
        ).first()
        if ev_ap:
            payload_rec = _impacto_loc_payload_from_ap_evento(ev_ap, 'voz')
            if payload_rec:
                return jsonify(payload_rec), 200
        return jsonify({}), 404
    celda_norm = _normalize_celda_id_py(r.celda_id)
    dt = DatoTecnico.query.filter(
        DatoTecnico.carga_id == r.carga_id,
        DatoTecnico.tipo == 'voz',
        _normalize_celda_id_sql(DatoTecnico.celda_id) == celda_norm,
    ).filter(
        DatoTecnico.lat.isnot(None), DatoTecnico.long.isnot(None)
    ).order_by(DatoTecnico.id.desc()).first()
    coords_source = 'same_carga'
    if not dt:
        dt = DatoTecnico.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            DatoTecnico.tipo == 'voz',
            _normalize_celda_id_sql(DatoTecnico.celda_id) == celda_norm,
            DatoTecnico.lat.isnot(None),
            DatoTecnico.long.isnot(None),
        ).order_by(DatoTecnico.id.desc()).first()
        coords_source = 'other_carga' if dt else None
    if not dt:
        return jsonify({
            'has_coords': False,
            'tipo': 'voz',
            'carga_id': r.carga_id,
            'celda_id': r.celda_id,
            'impacto': _serialize_voz(r),
        }), 200
    return jsonify({
        'lat': float(dt.lat),
        'lng': float(dt.long),
        'has_coords': True,
        'coords_source': coords_source,
        'coords_carga_id': int(dt.carga_id) if getattr(dt, 'carga_id', None) is not None else None,
        'tipo': 'voz',
        'carga_id': r.carga_id,
        'sujeto_id': CargaLlamada.query.with_entities(CargaLlamada.sujeto_id).filter(CargaLlamada.id == r.carga_id).scalar(),
        'celda_id': dt.celda_id,
        'celda_direccion': dt.celda_direccion,
        'impacto': _serialize_voz(r),
        # Datos técnicos extra para visualización (sector/azimut)
        'azimuth': dt.azimuth,
        'rad_cob_km': dt.rad_cob_km,
        'a_horiz': dt.a_horiz,
        'a_vert': dt.a_vert,
    })


@bp.route('/api/mapa/ruta')
def api_mapa_ruta():
    """
    Ruta ordenada por fecha/hora: lista de puntos (lat, lng) con numero 1..N
    para dibujar polilínea y animación. Filtros: sujeto_ids[], carga_ids[], tipos[].
    """
    if not _permiso():
        return jsonify([]), 403
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    q_cargas = _apply_mapa_caso_arg_to_carga_query(q_cargas)
    cargas_rows = q_cargas.with_entities(CargaLlamada.id, CargaLlamada.sujeto_id).all()
    cargas_ids = [r[0] for r in cargas_rows]
    carga_to_sujeto = {r[0]: r[1] for r in cargas_rows}
    if not cargas_ids:
        return jsonify([])

    # Filtros avanzados (sobre impactos de tráfico)
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]

    # Modo liviano: para “trazado” sobre Celdas no necesitamos el payload completo del impacto.
    lite = (request.args.get('lite') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí')

    # Coordenadas por celda física (tipo + celda_norm) sin depender de la carga.
    # Esto evita perder puntos cuando la celda tiene coords en “otra carga” accesible.
    sub_dt = db.session.query(
        DatoTecnico.tipo.label('tipo'),
        _normalize_celda_id_sql(DatoTecnico.celda_id).label('celda_norm'),
        func.max(DatoTecnico.id).label('dt_id'),
    ).join(
        CargaLlamada, CargaLlamada.id == DatoTecnico.carga_id
    ).filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        DatoTecnico.lat.isnot(None),
        DatoTecnico.long.isnot(None),
        DatoTecnico.celda_id.isnot(None),
    )
    if tipos:
        sub_dt = sub_dt.filter(DatoTecnico.tipo.in_(tipos))
    sub_dt = sub_dt.group_by(
        DatoTecnico.tipo, _normalize_celda_id_sql(DatoTecnico.celda_id)
    ).subquery('dt_ruta_max')

    dt2 = aliased(DatoTecnico)
    celda_coords = {}
    for tipo_dt, celda_norm, lat, lng in db.session.query(
        sub_dt.c.tipo, sub_dt.c.celda_norm, dt2.lat, dt2.long
    ).join(
        dt2, dt2.id == sub_dt.c.dt_id
    ).all():
        if not tipo_dt or not celda_norm:
            continue
        try:
            celda_coords[(str(tipo_dt), str(celda_norm))] = (float(lat), float(lng))
        except Exception:
            continue

    def _hora_key(h):
        if not h:
            return (0, 0, 0)
        s = str(h).strip()
        if not s:
            return (0, 0, 0)
        parts = s.split(':')
        try:
            hh = int(parts[0]) if len(parts) > 0 and parts[0] != '' else 0
            mm = int(parts[1]) if len(parts) > 1 and parts[1] != '' else 0
            ss = int(parts[2]) if len(parts) > 2 and parts[2] != '' else 0
            return (hh, mm, ss)
        except Exception:
            return (0, 0, 0)

    out = []
    if not tipos or 'gprs' in tipos:
        q_gprs = ResultadoTraficoGPRS.query.filter(
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
            ResultadoTraficoGPRS.celda.isnot(None),
        )
        q_gprs = _apply_fecha_hora_filters(q_gprs, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q_gprs = q_gprs.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            q_gprs = q_gprs.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            q_gprs = q_gprs.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                q_gprs = q_gprs.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        for r in q_gprs.order_by(ResultadoTraficoGPRS.fecha, _hora_ord_sql(ResultadoTraficoGPRS.hora), ResultadoTraficoGPRS.id).all():
            key = ('gprs', _normalize_celda_id_py(r.celda))
            if key in celda_coords:
                lat, lng = celda_coords[key]
                item = {
                    'lat': lat, 'lng': lng,
                    'fecha': r.fecha.isoformat() if r.fecha else None,
                    'hora': r.hora,
                    '_fecha_dt': r.fecha,
                    '_hora_key': _hora_key(r.hora),
                    'carga_id': r.carga_id,
                    'sujeto_id': carga_to_sujeto.get(r.carga_id),
                    'impacto_id': r.id, 'tipo': 'gprs',
                }
                if not lite:
                    item['impacto'] = _serialize_gprs(r)
                out.append(item)
    if not tipos or 'voz' in tipos:
        q_voz = ResultadoTraficoVOZ.query.filter(
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
            ResultadoTraficoVOZ.celda_id.isnot(None),
        )
        q_voz = _apply_fecha_hora_filters(q_voz, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            q_voz = q_voz.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            q_voz = q_voz.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            q_voz = q_voz.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                q_voz = q_voz.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        for r in q_voz.order_by(ResultadoTraficoVOZ.fecha, _hora_ord_sql(ResultadoTraficoVOZ.hora), ResultadoTraficoVOZ.id).all():
            key = ('voz', _normalize_celda_id_py(r.celda_id))
            if key in celda_coords:
                lat, lng = celda_coords[key]
                item = {
                    'lat': lat, 'lng': lng,
                    'fecha': r.fecha.isoformat() if r.fecha else None,
                    'hora': r.hora,
                    '_fecha_dt': r.fecha,
                    '_hora_key': _hora_key(r.hora),
                    'carga_id': r.carga_id,
                    'sujeto_id': carga_to_sujeto.get(r.carga_id),
                    'impacto_id': r.id, 'tipo': 'voz',
                }
                if not lite:
                    item['impacto'] = _serialize_voz(r)
                out.append(item)

    # Ordenar por fecha y hora (recorrido completo en orden cronológico)
    out.sort(key=lambda x: (
        x.get('_fecha_dt') or datetime.min,
        x.get('_hora_key') or (0, 0, 0),
        x.get('tipo') or '',
        x.get('impacto_id') or 0,
    ))
    for p in out:
        p.pop('_fecha_dt', None)
        p.pop('_hora_key', None)
    total = len(out)

    # Por defecto se limita para evitar respuestas enormes; el frontend del mapa pide all=1
    # para mostrar el recorrido completo.
    all_flag = (request.args.get('all') or '').strip().lower() in ('1', 'true', 't', 'yes', 'si', 'sí')
    MAX_PUNTOS_RUTA = 5000
    if (not all_flag) and total > MAX_PUNTOS_RUTA:
        # Si hay más del límite, se muestrean puntos de todo el recorrido (no solo el inicio).
        step = (total - 1) / (MAX_PUNTOS_RUTA - 1) if MAX_PUNTOS_RUTA > 1 else 0
        indices = [0] + [int(round(i * step)) for i in range(1, MAX_PUNTOS_RUTA - 1)] + [total - 1]
        seen = set()
        indices_ord = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                indices_ord.append(i)
        indices_ord.sort()
        out = [out[i] for i in indices_ord]
    for i, p in enumerate(out, 1):
        p['numero'] = i
    resp = jsonify(out)
    resp.headers['X-Total-Puntos'] = str(total)
    resp.headers['X-Mostrando'] = str(len(out))
    return resp


@bp.route('/api/mapa/trazado')
def api_mapa_trazado():
    """
    Devuelve puntos (lat/lng) para trazar una polilínea en vista “Celdas”,
    respetando los mismos filtros del mapa y, opcionalmente, el rango progresivo:

    Params:
      - mismos filtros que el mapa (sujeto_ids[], carga_ids[], tipos[], fecha/hora, numeros[], provincias[], localidades[], imeis[])
      - max_ord: si se provee, devuelve solo los impactos con ord <= max_ord (orden global cronológico).

    Nota: solo devuelve impactos que tienen coordenadas disponibles (por Datos Técnicos, sin depender de carga).
    """
    if not _permiso():
        return jsonify([]), 403

    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')

    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    numeros = [str(x).strip() for x in request.args.getlist('numeros[]') if str(x).strip()]
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    imeis = [str(x).strip() for x in request.args.getlist('imeis[]') if str(x).strip()]
    max_ord = request.args.get('max_ord', type=int)
    if max_ord is not None and max_ord < 1:
        max_ord = 1

    q_cargas = _cargas_query_accessible()
    if sujeto_ids:
        q_cargas = q_cargas.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
    if carga_ids:
        q_cargas = q_cargas.filter(CargaLlamada.id.in_(carga_ids))
    if tipos:
        q_cargas = q_cargas.filter(CargaLlamada.tipo.in_(tipos))
    q_cargas = _apply_mapa_caso_arg_to_carga_query(q_cargas)
    cargas_rows = q_cargas.with_entities(CargaLlamada.id, CargaLlamada.sujeto_id).all()
    cargas_ids = [r[0] for r in cargas_rows]
    carga_to_sujeto = {r[0]: r[1] for r in cargas_rows}
    if not cargas_ids:
        return jsonify([])

    # Coordenadas por celda física (tipo + celda_norm) sin depender de la carga.
    sub_dt = db.session.query(
        DatoTecnico.tipo.label('tipo'),
        _normalize_celda_id_sql(DatoTecnico.celda_id).label('celda_norm'),
        func.max(DatoTecnico.id).label('dt_id'),
    ).join(
        CargaLlamada, CargaLlamada.id == DatoTecnico.carga_id
    ).filter(
        CargaLlamada.unidad_id == current_user.unidad_id,
        _carga_access_predicate(),
        DatoTecnico.lat.isnot(None),
        DatoTecnico.long.isnot(None),
        DatoTecnico.celda_id.isnot(None),
    )
    if tipos:
        sub_dt = sub_dt.filter(DatoTecnico.tipo.in_(tipos))
    sub_dt = sub_dt.group_by(
        DatoTecnico.tipo, _normalize_celda_id_sql(DatoTecnico.celda_id)
    ).subquery('dt_trazado_max')

    dt2 = aliased(DatoTecnico)
    dt_coords = db.session.query(
        sub_dt.c.tipo.label('tipo'),
        sub_dt.c.celda_norm.label('celda_norm'),
        dt2.lat.label('lat'),
        dt2.long.label('lng'),
        dt2.celda_id.label('celda_id'),
        dt2.celda_direccion.label('celda_direccion'),
    ).join(dt2, dt2.id == sub_dt.c.dt_id).subquery('dt_coords')

    # Base union (impactos) con celda_norm y hora_ord (para ROW_NUMBER global)
    g_sel = None
    v_sel = None
    if not tipos or 'gprs' in tipos:
        qg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.carga_id.in_(cargas_ids),
            ResultadoTraficoGPRS.celda.isnot(None),
        )
        qg = _apply_fecha_hora_filters(qg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if imeis:
            qg = qg.filter(ResultadoTraficoGPRS.imei.isnot(None)).filter(ResultadoTraficoGPRS.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoGPRS.numero).like(f"%{n.lower()}%"))
            if ors:
                qg = qg.filter(ResultadoTraficoGPRS.numero.isnot(None)).filter(or_(*ors))
        g_sel = qg.with_entities(
            literal('gprs').label('tipo'),
            ResultadoTraficoGPRS.id.label('impacto_id'),
            ResultadoTraficoGPRS.carga_id.label('carga_id'),
            _normalize_celda_id_sql(ResultadoTraficoGPRS.celda).label('celda_norm'),
            ResultadoTraficoGPRS.fecha.label('fecha'),
            _hora_ord_sql(ResultadoTraficoGPRS.hora).label('hora_ord'),
            ResultadoTraficoGPRS.hora.label('hora'),
        )

    if not tipos or 'voz' in tipos:
        qv = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.carga_id.in_(cargas_ids),
            ResultadoTraficoVOZ.celda_id.isnot(None),
        )
        qv = _apply_fecha_hora_filters(qv, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
        if provincias:
            qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if imeis:
            qv = qv.filter(ResultadoTraficoVOZ.imei.isnot(None)).filter(ResultadoTraficoVOZ.imei.in_(imeis))
        if numeros:
            ors = []
            for n in numeros[:50]:
                ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
            if ors:
                qv = qv.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
        v_sel = qv.with_entities(
            literal('voz').label('tipo'),
            ResultadoTraficoVOZ.id.label('impacto_id'),
            ResultadoTraficoVOZ.carga_id.label('carga_id'),
            _normalize_celda_id_sql(ResultadoTraficoVOZ.celda_id).label('celda_norm'),
            ResultadoTraficoVOZ.fecha.label('fecha'),
            _hora_ord_sql(ResultadoTraficoVOZ.hora).label('hora_ord'),
            ResultadoTraficoVOZ.hora.label('hora'),
        )

    union_q = None
    if g_sel is not None and v_sel is not None:
        union_q = g_sel.union_all(v_sel)
    elif g_sel is not None:
        union_q = g_sel
    elif v_sel is not None:
        union_q = v_sel
    else:
        return jsonify([])

    u = union_q.subquery('u_trazado')

    ranked = db.session.query(
        u.c.tipo,
        u.c.impacto_id,
        u.c.carga_id,
        u.c.celda_norm,
        u.c.fecha,
        u.c.hora,
        func.row_number().over(order_by=(u.c.fecha, u.c.hora_ord, u.c.tipo, u.c.impacto_id)).label('ord'),
    ).subquery('ranked_trazado')

    q = db.session.query(
        ranked.c.ord,
        ranked.c.tipo,
        ranked.c.impacto_id,
        ranked.c.carga_id,
        ranked.c.fecha,
        ranked.c.hora,
        dt_coords.c.lat,
        dt_coords.c.lng,
        dt_coords.c.celda_id,
        dt_coords.c.celda_direccion,
    ).join(
        dt_coords,
        and_(dt_coords.c.tipo == ranked.c.tipo, dt_coords.c.celda_norm == ranked.c.celda_norm)
    )

    if max_ord is not None:
        q = q.filter(ranked.c.ord <= int(max_ord))

    rows = q.order_by(ranked.c.ord.asc()).all()
    out = []
    for r in rows:
        out.append({
            'numero': int(r.ord) if r.ord is not None else None,
            'tipo': r.tipo,
            'impacto_id': int(r.impacto_id) if r.impacto_id is not None else None,
            'carga_id': int(r.carga_id) if r.carga_id is not None else None,
            'sujeto_id': int(carga_to_sujeto.get(r.carga_id)) if carga_to_sujeto.get(r.carga_id) is not None else None,
            'fecha': r.fecha.isoformat() if r.fecha else None,
            'hora': r.hora,
            'lat': float(r.lat) if r.lat is not None else None,
            'lng': float(r.lng) if r.lng is not None else None,
            'celda_id': r.celda_id,
            'celda_direccion': r.celda_direccion,
        })

    resp = jsonify(out)
    resp.headers['X-Total-Puntos'] = str(len(out))
    resp.headers['X-Mostrando'] = str(len(out))
    if max_ord is not None:
        resp.headers['X-Max-Ord'] = str(int(max_ord))
    return resp


@bp.route('/api/mapa/impacto/<tipo>/<int:impacto_id>')
def api_mapa_impacto_detalle(tipo, impacto_id):
    """Detalle de un solo impacto (registro de tráfico) para el modal."""
    if not _permiso():
        return jsonify({}), 403
    if tipo == 'gprs':
        r = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoGPRS.id == impacto_id,
        ).first()
        if r:
            return jsonify(_serialize_gprs(r))
    elif tipo == 'voz':
        r = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            ResultadoTraficoVOZ.id == impacto_id,
        ).first()
        if r:
            return jsonify(_serialize_voz(r))
    return jsonify({}), 404


@bp.route('/api/filtros')
def api_filtros():
    """Devuelve opciones para filtros: sujetos y cargas de la unidad."""
    if not _permiso():
        return jsonify({}), 403
    cargas_limit = request.args.get('cargas_limit', default=2000, type=int) or 2000
    if cargas_limit < 1:
        cargas_limit = 1
    # Evitar respuestas gigantes; si necesitás más, conviene paginar o buscar por texto.
    if cargas_limit > 5000:
        cargas_limit = 5000
    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
    q_cargas_f = _cargas_query_accessible()
    caso_filt = request.args.get('caso_id', type=int)
    if caso_filt:
        caso_ok = _get_caso_accesible(caso_filt)
        if caso_ok:
            q_cargas_f = q_cargas_f.filter(CargaLlamada.caso_id == caso_ok.id)
        else:
            q_cargas_f = q_cargas_f.filter(CargaLlamada.id == -1)
    cargas = q_cargas_f.order_by(CargaLlamada.created_at.desc()).limit(cargas_limit).all()
    return jsonify({
        'sujetos': [{'id': s.id, 'nombre': s.display_name()} for s in sujetos],
        'cargas': [{'id': c.id, 'tipo': c.tipo, 'nombre_archivo': c.nombre_archivo or '', 'created_at': c.created_at.isoformat() if c.created_at else None} for c in cargas],
    })


@bp.route('/api/share/users')
def api_share_users():
    """Busca usuarios activos en la misma unidad para compartir."""
    if not _permiso():
        return jsonify([]), 403
    q_txt = (request.args.get('q') or '').strip().lower()
    limit = request.args.get('limit', default=20, type=int) or 20
    if limit < 1:
        limit = 1
    if limit > 50:
        limit = 50
    q = User.query.filter(
        User.unidad_id == current_user.unidad_id,
        User.active.is_(True),
        User.id != current_user.id,
    )
    if q_txt:
        q = q.filter(or_(
            func.lower(User.username).like(f"%{q_txt}%"),
            func.lower(User.email).like(f"%{q_txt}%"),
        ))
    rows = q.order_by(User.username).limit(limit).all()
    return jsonify([{'id': u.id, 'username': u.username, 'email': u.email} for u in rows])


def _validate_share_target_user(user_id):
    if not user_id or user_id == current_user.id:
        return None
    u = User.query.filter(
        User.id == int(user_id),
        User.unidad_id == current_user.unidad_id,
        User.active.is_(True),
    ).first()
    return u


@bp.route('/api/share/carga/<int:carga_id>', methods=['GET', 'POST', 'DELETE'])
def api_share_carga(carga_id):
    """Gestiona el share de una carga. Solo dueño (o superadmin)."""
    if not _permiso():
        return jsonify([]), 403
    carga = _cargas_query_accessible().filter(CargaLlamada.id == carga_id).first_or_404()
    _assert_owner_or_404(carga)

    if request.method == 'GET':
        shares = CargaLlamadaCompartida.query.join(User, User.id == CargaLlamadaCompartida.shared_with_user_id) \
            .filter(CargaLlamadaCompartida.carga_id == carga_id) \
            .order_by(User.username).all()
        return jsonify([{'id': s.shared_with.id, 'username': s.shared_with.username, 'email': s.shared_with.email} for s in shares])

    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        user_id = payload.get('user_id')
        u = _validate_share_target_user(user_id)
        if not u:
            return jsonify({'error': 'Usuario inválido'}), 400
        sh = CargaLlamadaCompartida(
            carga_id=carga_id,
            shared_with_user_id=u.id,
            shared_by_user_id=current_user.id,
            created_at=datetime.utcnow(),
        )
        db.session.add(sh)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        return jsonify({'ok': True})

    # DELETE
    user_id = request.args.get('user_id', type=int)
    u = _validate_share_target_user(user_id)
    if not u:
        return jsonify({'error': 'Usuario inválido'}), 400
    CargaLlamadaCompartida.query.filter_by(carga_id=carga_id, shared_with_user_id=u.id).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/api/share/sujeto/<int:sujeto_id>', methods=['GET', 'POST', 'DELETE'])
def api_share_sujeto(sujeto_id):
    """Gestiona el share de un sujeto. Solo dueño (o superadmin)."""
    if not _permiso():
        return jsonify([]), 403
    sujeto = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first_or_404()
    _assert_owner_or_404(sujeto)

    if request.method == 'GET':
        shares = SujetoCompartido.query.join(User, User.id == SujetoCompartido.shared_with_user_id) \
            .filter(SujetoCompartido.sujeto_id == sujeto_id) \
            .order_by(User.username).all()
        return jsonify([{'id': s.shared_with.id, 'username': s.shared_with.username, 'email': s.shared_with.email} for s in shares])

    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        user_id = payload.get('user_id')
        u = _validate_share_target_user(user_id)
        if not u:
            return jsonify({'error': 'Usuario inválido'}), 400
        sh = SujetoCompartido(
            sujeto_id=sujeto_id,
            shared_with_user_id=u.id,
            shared_by_user_id=current_user.id,
            created_at=datetime.utcnow(),
        )
        db.session.add(sh)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        return jsonify({'ok': True})

    # DELETE
    user_id = request.args.get('user_id', type=int)
    u = _validate_share_target_user(user_id)
    if not u:
        return jsonify({'error': 'Usuario inválido'}), 400
    SujetoCompartido.query.filter_by(sujeto_id=sujeto_id, shared_with_user_id=u.id).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/api/share/caso/<int:caso_id>', methods=['GET', 'POST', 'DELETE'])
def api_share_caso(caso_id):
    """Gestiona compartir por caso: habilita trabajo conjunto sobre sábanas/records del caso."""
    if not _permiso():
        return jsonify([]), 403
    caso = AnalisisPuntoCaso.query.filter_by(id=caso_id, unidad_id=current_user.unidad_id).first_or_404()
    if not _is_superadmin() and caso.user_id != current_user.id:
        return jsonify({'error': 'Sin permiso para compartir este caso'}), 403

    if request.method == 'GET':
        shares = AnalisisPuntoCasoCompartido.query.join(
            User, User.id == AnalisisPuntoCasoCompartido.shared_with_user_id
        ).filter(
            AnalisisPuntoCasoCompartido.caso_id == caso_id
        ).order_by(User.username).all()
        return jsonify([{'id': s.shared_with.id, 'username': s.shared_with.username, 'email': s.shared_with.email} for s in shares])

    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        user_id = payload.get('user_id')
        u = _validate_share_target_user(user_id)
        if not u:
            return jsonify({'error': 'Usuario inválido'}), 400
        sh = AnalisisPuntoCasoCompartido(
            caso_id=caso_id,
            shared_with_user_id=u.id,
            shared_by_user_id=current_user.id,
            created_at=datetime.utcnow(),
        )
        db.session.add(sh)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        return jsonify({'ok': True})

    user_id = request.args.get('user_id', type=int)
    u = _validate_share_target_user(user_id)
    if not u:
        return jsonify({'error': 'Usuario inválido'}), 400
    AnalisisPuntoCasoCompartido.query.filter_by(caso_id=caso_id, shared_with_user_id=u.id).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True})


def _mapa_datos_modo_arg():
    v = (request.args.get('mapa_datos_modo') or 'sabana').strip().lower()
    if v not in ('sabana', 'record', 'ambos'):
        return 'sabana'
    return v


def _parse_tipos_list():
    return [str(x).strip().lower() for x in request.args.getlist('tipos[]') if str(x).strip()]


def _fuente_ids_record_from_request():
    return [int(x) for x in request.args.getlist('fuente_ids[]', type=int) if x and int(x) > 0]


def _clean_filter_text(value):
    if value is None:
        return ''
    txt = str(value).replace('\xa0', ' ').strip()
    if not txt:
        return ''
    return ' '.join(txt.split())


def _norm_filter_text(value):
    txt = _clean_filter_text(value).lower()
    if not txt:
        return ''
    return ''.join(
        ch for ch in unicodedata.normalize('NFKD', txt)
        if not unicodedata.combining(ch)
    )


def _sql_filter_text(value):
    return _clean_filter_text(value).lower()


def _normalize_filter_input_list(values):
    out = []
    seen = set()
    for v in values or []:
        clean = _clean_filter_text(v)
        key = _norm_filter_text(clean)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _sorted_unique_filter_values(values, limit=None):
    uniq = {}
    for v in values or []:
        clean = _clean_filter_text(v)
        key = _norm_filter_text(clean)
        if key and key not in uniq:
            uniq[key] = clean
    arr = sorted(uniq.values(), key=lambda x: _norm_filter_text(x))
    if limit is not None and limit > 0:
        return arr[:int(limit)]
    return arr


_REL_FILTROS_CACHE = {}
_REL_FILTROS_CACHE_TTL_SEC = 45
_REL_FILTROS_CACHE_MAX = 400


def _rel_filtros_cache_key(prefix):
    args_key = tuple(sorted([(k, _clean_filter_text(v)) for k, v in request.args.items(multi=True)]))
    return (
        prefix,
        int(getattr(current_user, 'id', 0) or 0),
        int(getattr(current_user, 'unidad_id', 0) or 0),
        args_key,
    )


def _rel_filtros_cache_get(prefix):
    key = _rel_filtros_cache_key(prefix)
    now = time.time()
    data = _REL_FILTROS_CACHE.get(key)
    if not data:
        return None
    exp_ts, payload = data
    if exp_ts <= now:
        _REL_FILTROS_CACHE.pop(key, None)
        return None
    return payload


def _rel_filtros_cache_set(prefix, payload):
    now = time.time()
    # Limpieza simple: expirados y control de tamaño
    if _REL_FILTROS_CACHE:
        expired = [k for k, (exp, _v) in _REL_FILTROS_CACHE.items() if exp <= now]
        for k in expired:
            _REL_FILTROS_CACHE.pop(k, None)
    if len(_REL_FILTROS_CACHE) >= _REL_FILTROS_CACHE_MAX:
        # Evict por expiración más cercana
        try:
            oldest_key = min(_REL_FILTROS_CACHE.items(), key=lambda item: item[1][0])[0]
            _REL_FILTROS_CACHE.pop(oldest_key, None)
        except Exception:
            _REL_FILTROS_CACHE.clear()
    key = _rel_filtros_cache_key(prefix)
    _REL_FILTROS_CACHE[key] = (now + _REL_FILTROS_CACHE_TTL_SEC, payload)


def _apply_ap_evento_fecha_filters(qev, fecha_desde, fecha_hasta):
    if fecha_desde:
        qev = qev.filter(
            AnalisisPuntoEvento.event_dt.isnot(None),
            AnalisisPuntoEvento.event_dt >= datetime(fecha_desde.year, fecha_desde.month, fecha_desde.day),
        )
    if fecha_hasta:
        hasta_dt = datetime(fecha_hasta.year, fecha_hasta.month, fecha_hasta.day) + timedelta(days=1)
        qev = qev.filter(AnalisisPuntoEvento.event_dt.isnot(None), AnalisisPuntoEvento.event_dt < hasta_dt)
    return qev


def _record_eventos_base(caso_id, fuente_ids):
    caso = _get_caso_accesible(caso_id)
    if not caso:
        return None, None
    qev = AnalisisPuntoEvento.query.filter(
        AnalisisPuntoEvento.caso_id == caso.id,
        AnalisisPuntoEvento.unidad_id == current_user.unidad_id,
    )
    if fuente_ids:
        qev = qev.filter(AnalisisPuntoEvento.fuente_id.in_(fuente_ids))
    return caso, qev


def _apply_tipos_ap_evento(qev, tipos_norm):
    if not tipos_norm:
        return qev
    st = []
    if 'gprs' in tipos_norm:
        st.append('GPRS')
    if 'voz' in tipos_norm:
        st.append('VOZ')
    if st:
        qev = qev.filter(AnalisisPuntoEvento.source_type.in_(st))
    return qev


def _record_join_celda_if_geo(qev, provincias, localidades):
    """Restringe por provincia/localidad de ap_celdas (requiere cell_id)."""
    need = bool(provincias or localidades)
    if not need:
        return qev
    qev = qev.filter(AnalisisPuntoEvento.cell_id.isnot(None)).join(
        AnalisisPuntoCelda, AnalisisPuntoEvento.cell_id == AnalisisPuntoCelda.id
    ).filter(AnalisisPuntoCelda.unidad_id == current_user.unidad_id)
    if provincias:
        pl = [_sql_filter_text(p) for p in provincias if _sql_filter_text(p)]
        if pl:
            qev = qev.filter(func.lower(func.trim(AnalisisPuntoCelda.province)).in_(pl))
    if localidades:
        ll = [_sql_filter_text(l) for l in localidades if _sql_filter_text(l)]
        if ll:
            qev = qev.filter(func.lower(func.trim(AnalisisPuntoCelda.locality)).in_(ll))
    return qev


def _record_filtros_numeros(caso_id, fuente_ids, tipos_norm, q_txt, fecha_desde, fecha_hasta, provincias, localidades, limit):
    _caso, qev = _record_eventos_base(caso_id, fuente_ids)
    if qev is None:
        return []
    qev = _apply_tipos_ap_evento(qev, tipos_norm)
    qev = _apply_ap_evento_fecha_filters(qev, fecha_desde, fecha_hasta)
    qev = _record_join_celda_if_geo(qev, provincias, localidades)
    ql = (q_txt or '').strip().lower()
    queries = []
    qo = qev.filter(AnalisisPuntoEvento.origin_msisdn.isnot(None), AnalisisPuntoEvento.origin_msisdn != '')
    if ql:
        qo = qo.filter(func.lower(func.trim(AnalisisPuntoEvento.origin_msisdn)).like(f"%{ql}%"))
    queries.append(qo.with_entities(AnalisisPuntoEvento.origin_msisdn.label('numero')).distinct())
    qt = qev.filter(AnalisisPuntoEvento.target_msisdn.isnot(None), AnalisisPuntoEvento.target_msisdn != '')
    if ql:
        qt = qt.filter(func.lower(func.trim(AnalisisPuntoEvento.target_msisdn)).like(f"%{ql}%"))
    queries.append(qt.with_entities(AnalisisPuntoEvento.target_msisdn.label('numero')).distinct())
    q_union = queries[0]
    for qq in queries[1:]:
        q_union = q_union.union(qq)
    sub = q_union.subquery()
    col0 = list(sub.c)[0]
    rows = db.session.query(col0).order_by(col0).limit(limit).all()
    return _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)


def _record_filtros_imeis(caso_id, fuente_ids, tipos_norm, q_txt, fecha_desde, fecha_hasta, provincias, localidades, limit):
    _caso, qev = _record_eventos_base(caso_id, fuente_ids)
    if qev is None:
        return []
    qev = _apply_tipos_ap_evento(qev, tipos_norm)
    qev = _apply_ap_evento_fecha_filters(qev, fecha_desde, fecha_hasta)
    qev = _record_join_celda_if_geo(qev, provincias, localidades)
    qev = qev.filter(AnalisisPuntoEvento.imei.isnot(None), AnalisisPuntoEvento.imei != '')
    ql = (q_txt or '').strip().lower()
    if ql:
        qev = qev.filter(func.lower(func.trim(AnalisisPuntoEvento.imei)).like(f"%{ql}%"))
    rows = qev.with_entities(AnalisisPuntoEvento.imei).distinct().order_by(AnalisisPuntoEvento.imei).limit(limit).all()
    return _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)


def _record_filtros_provincias(caso_id, fuente_ids, tipos_norm, q_txt, limit):
    _caso, qev = _record_eventos_base(caso_id, fuente_ids)
    if qev is None:
        return []
    qev = _apply_tipos_ap_evento(qev, tipos_norm)
    qev = qev.filter(AnalisisPuntoEvento.cell_id.isnot(None)).join(
        AnalisisPuntoCelda, AnalisisPuntoEvento.cell_id == AnalisisPuntoCelda.id
    ).filter(
        AnalisisPuntoCelda.unidad_id == current_user.unidad_id,
        AnalisisPuntoCelda.province.isnot(None),
    )
    if q_txt:
        ql = _sql_filter_text(q_txt)
        qev = qev.filter(func.lower(func.trim(AnalisisPuntoCelda.province)).like(f"%{ql}%"))
    rows = qev.with_entities(AnalisisPuntoCelda.province).distinct().order_by(AnalisisPuntoCelda.province).limit(limit).all()
    return _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)


def _record_filtros_localidades(caso_id, fuente_ids, tipos_norm, provincias, q_txt, limit):
    _caso, qev = _record_eventos_base(caso_id, fuente_ids)
    if qev is None:
        return []
    qev = _apply_tipos_ap_evento(qev, tipos_norm)
    qev = qev.filter(AnalisisPuntoEvento.cell_id.isnot(None)).join(
        AnalisisPuntoCelda, AnalisisPuntoEvento.cell_id == AnalisisPuntoCelda.id
    ).filter(
        AnalisisPuntoCelda.unidad_id == current_user.unidad_id,
        AnalisisPuntoCelda.locality.isnot(None),
    )
    if provincias:
        pl = [_sql_filter_text(p) for p in provincias if _sql_filter_text(p)]
        if pl:
            qev = qev.filter(func.lower(func.trim(AnalisisPuntoCelda.province)).in_(pl))
    if q_txt:
        ql = _sql_filter_text(q_txt)
        qev = qev.filter(func.lower(func.trim(AnalisisPuntoCelda.locality)).like(f"%{ql}%"))
    rows = qev.with_entities(AnalisisPuntoCelda.locality).distinct().order_by(AnalisisPuntoCelda.locality).limit(limit).all()
    return _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)


@bp.route('/api/filtros/mapa-tipos')
def api_filtros_mapa_tipos():
    """
    Tipos de tráfico disponibles según origen del mapa (sábana / record / ambos), para armar checkboxes dinámicos.
    Devuelve lista de strings: 'gprs', 'voz'.
    """
    if not _permiso():
        return jsonify([]), 403
    modo = _mapa_datos_modo_arg()
    caso_id = request.args.get('caso_id', type=int)
    carga_ids = [int(x) for x in request.args.getlist('carga_ids[]', type=int) if x and int(x) > 0]
    fuente_ids = _fuente_ids_record_from_request()
    found = []
    if modo in ('sabana', 'ambos'):
        q = DatoTecnico.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
        )
        if carga_ids:
            q = q.filter(CargaLlamada.id.in_(carga_ids))
        rows = q.with_entities(DatoTecnico.tipo).distinct().all()
        for (t,) in rows:
            tl = (t or '').strip().lower()
            if tl == 'gprs' and 'gprs' not in found:
                found.append('gprs')
            if tl == 'voz' and 'voz' not in found:
                found.append('voz')
    if modo in ('record', 'ambos') and caso_id:
        _caso, qev = _record_eventos_base(caso_id, fuente_ids)
        if qev is not None:
            rows = qev.with_entities(AnalisisPuntoEvento.source_type).distinct().all()
            for (st,) in rows:
                su = (st or '').strip().upper()
                if su == 'GPRS' and 'gprs' not in found:
                    found.append('gprs')
                if su == 'VOZ' and 'voz' not in found:
                    found.append('voz')
    order = []
    for t in ('gprs', 'voz'):
        if t in found:
            order.append(t)
    if not order:
        order = ['gprs', 'voz']
    return jsonify(order)


@bp.route('/api/filtros/numeros')
def api_filtros_numeros():
    """Devuelve números para buscador multi-select (GPRS.numero y VOZ.numero/otro)."""
    if not _permiso():
        return jsonify([]), 403
    cached = _rel_filtros_cache_get('api_filtros_numeros')
    if cached is not None:
        return jsonify(cached)
    modo = _mapa_datos_modo_arg()
    caso_id = request.args.get('caso_id', type=int)
    fuente_ids = _fuente_ids_record_from_request()
    q_txt = _clean_filter_text(request.args.get('q'))
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = _parse_tipos_list()
    provincias = _normalize_filter_input_list(request.args.getlist('provincias[]'))
    localidades = _normalize_filter_input_list(request.args.getlist('localidades[]'))
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    limit = request.args.get('limit', default=50, type=int) or 50
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    provincias_l = [_sql_filter_text(x) for x in provincias if _sql_filter_text(x)]
    localidades_l = [_sql_filter_text(x) for x in localidades if _sql_filter_text(x)]

    out_sabana = []
    if modo in ('sabana', 'ambos'):
        include_gprs = (not tipos) or ('gprs' in tipos)
        include_voz = (not tipos) or ('voz' in tipos)
        queries = []
        if include_gprs:
            qg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
                CargaLlamada.unidad_id == current_user.unidad_id,
                _carga_access_predicate(),
                ResultadoTraficoGPRS.numero.isnot(None),
                ResultadoTraficoGPRS.numero != '',
            )
            if sujeto_ids:
                qg = qg.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
            if carga_ids:
                qg = qg.filter(CargaLlamada.id.in_(carga_ids))
            qg = _apply_fecha_hora_filters(qg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
            if provincias_l:
                qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoGPRS.celda_provincia)).in_(provincias_l)
                )
            if localidades_l:
                qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoGPRS.celda_localidad)).in_(localidades_l)
                )
            if q_txt:
                ql = q_txt.lower()
                qg = qg.filter(func.lower(func.trim(ResultadoTraficoGPRS.numero)).like(f"%{ql}%"))
            queries.append(qg.with_entities(ResultadoTraficoGPRS.numero.label('numero')).distinct())
        if include_voz:
            qv = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
                CargaLlamada.unidad_id == current_user.unidad_id,
                _carga_access_predicate(),
                or_(
                    (ResultadoTraficoVOZ.otro.isnot(None) & (ResultadoTraficoVOZ.otro != '')),
                    (ResultadoTraficoVOZ.numero.isnot(None) & (ResultadoTraficoVOZ.numero != '')),
                )
            )
            if sujeto_ids:
                qv = qv.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
            if carga_ids:
                qv = qv.filter(CargaLlamada.id.in_(carga_ids))
            qv = _apply_fecha_hora_filters(qv, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
            if provincias_l:
                qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoVOZ.celda_provincia)).in_(provincias_l)
                )
            if localidades_l:
                qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoVOZ.celda_localidad)).in_(localidades_l)
                )
            if q_txt:
                ql = q_txt.lower()
                qv = qv.filter(or_(
                    func.lower(func.trim(ResultadoTraficoVOZ.otro)).like(f"%{ql}%"),
                    func.lower(func.trim(ResultadoTraficoVOZ.numero)).like(f"%{ql}%"),
                ))
            queries.append(qv.with_entities(ResultadoTraficoVOZ.otro.label('numero')).filter(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.otro != '').distinct())
            queries.append(qv.with_entities(ResultadoTraficoVOZ.numero.label('numero')).filter(ResultadoTraficoVOZ.numero.isnot(None), ResultadoTraficoVOZ.numero != '').distinct())
        if queries:
            q_union = queries[0]
            for qq in queries[1:]:
                q_union = q_union.union(qq)
            sub = q_union.subquery()
            col0 = list(sub.c)[0]
            rows = db.session.query(col0).order_by(col0).limit(limit).all()
            out_sabana = _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)

    out_record = []
    if modo in ('record', 'ambos') and caso_id:
        out_record = _record_filtros_numeros(
            caso_id, fuente_ids, tipos, q_txt, fecha_desde, fecha_hasta, provincias, localidades, limit
        )

    out_sabana = _sorted_unique_filter_values(out_sabana, limit)
    out_record = _sorted_unique_filter_values(out_record, limit)
    if modo == 'sabana':
        result = out_sabana
    elif modo == 'record':
        result = out_record
    else:
        result = _sorted_unique_filter_values(out_sabana + out_record, limit)
    _rel_filtros_cache_set('api_filtros_numeros', result)
    return jsonify(result)


@bp.route('/api/filtros/provincias')
def api_filtros_provincias():
    """Devuelve provincias (celda_prov) para multi-select. Params: q, sujeto_ids[], carga_ids[], tipos[], limit."""
    if not _permiso():
        return jsonify([]), 403
    cached = _rel_filtros_cache_get('api_filtros_provincias')
    if cached is not None:
        return jsonify(cached)
    modo = _mapa_datos_modo_arg()
    caso_id = request.args.get('caso_id', type=int)
    fuente_ids = _fuente_ids_record_from_request()
    q_txt = _clean_filter_text(request.args.get('q'))
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = _parse_tipos_list()
    limit = request.args.get('limit', default=80, type=int) or 80
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    out_sabana = []
    if modo in ('sabana', 'ambos'):
        q = DatoTecnico.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            DatoTecnico.celda_prov.isnot(None),
        )
        if sujeto_ids:
            q = q.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
        if carga_ids:
            q = q.filter(CargaLlamada.id.in_(carga_ids))
        if tipos:
            q = q.filter(DatoTecnico.tipo.in_(tipos))
        if q_txt:
            ql = _sql_filter_text(q_txt)
            q = q.filter(func.lower(func.trim(DatoTecnico.celda_prov)).like(f"%{ql}%"))
        rows = q.with_entities(DatoTecnico.celda_prov).distinct().order_by(DatoTecnico.celda_prov).limit(limit).all()
        out_sabana = _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)

    out_record = []
    if modo in ('record', 'ambos') and caso_id:
        out_record = _record_filtros_provincias(caso_id, fuente_ids, tipos, q_txt, limit)

    out_sabana = _sorted_unique_filter_values(out_sabana, limit)
    out_record = _sorted_unique_filter_values(out_record, limit)
    if modo == 'sabana':
        result = out_sabana
    elif modo == 'record':
        result = out_record
    else:
        result = _sorted_unique_filter_values(out_sabana + out_record, limit)
    _rel_filtros_cache_set('api_filtros_provincias', result)
    return jsonify(result)


@bp.route('/api/filtros/localidades')
def api_filtros_localidades():
    """Devuelve localidades (celda_loc) para multi-select. Params: q, sujeto_ids[], carga_ids[], tipos[], provincias[], limit."""
    if not _permiso():
        return jsonify([]), 403
    cached = _rel_filtros_cache_get('api_filtros_localidades')
    if cached is not None:
        return jsonify(cached)
    modo = _mapa_datos_modo_arg()
    caso_id = request.args.get('caso_id', type=int)
    fuente_ids = _fuente_ids_record_from_request()
    q_txt = _clean_filter_text(request.args.get('q'))
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = _parse_tipos_list()
    provincias = _normalize_filter_input_list(request.args.getlist('provincias[]'))
    limit = request.args.get('limit', default=120, type=int) or 120
    if limit < 1:
        limit = 1
    if limit > 300:
        limit = 300

    out_sabana = []
    if modo in ('sabana', 'ambos'):
        q = DatoTecnico.query.join(CargaLlamada).filter(
            CargaLlamada.unidad_id == current_user.unidad_id,
            _carga_access_predicate(),
            DatoTecnico.celda_loc.isnot(None),
        )
        if sujeto_ids:
            q = q.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
        if carga_ids:
            q = q.filter(CargaLlamada.id.in_(carga_ids))
        if tipos:
            q = q.filter(DatoTecnico.tipo.in_(tipos))
        if provincias:
            pl = [_sql_filter_text(p) for p in provincias if _sql_filter_text(p)]
            if pl:
                q = q.filter(DatoTecnico.celda_prov.isnot(None)).filter(func.lower(func.trim(DatoTecnico.celda_prov)).in_(pl))
        if q_txt:
            ql = _sql_filter_text(q_txt)
            q = q.filter(func.lower(func.trim(DatoTecnico.celda_loc)).like(f"%{ql}%"))
        rows = q.with_entities(DatoTecnico.celda_loc).distinct().order_by(DatoTecnico.celda_loc).limit(limit).all()
        out_sabana = _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)

    out_record = []
    if modo in ('record', 'ambos') and caso_id:
        out_record = _record_filtros_localidades(caso_id, fuente_ids, tipos, provincias, q_txt, limit)

    out_sabana = _sorted_unique_filter_values(out_sabana, limit)
    out_record = _sorted_unique_filter_values(out_record, limit)
    if modo == 'sabana':
        result = out_sabana
    elif modo == 'record':
        result = out_record
    else:
        result = _sorted_unique_filter_values(out_sabana + out_record, limit)
    _rel_filtros_cache_set('api_filtros_localidades', result)
    return jsonify(result)


@bp.route('/api/filtros/imeis')
def api_filtros_imeis():
    """Devuelve IMEIs (GPRS/VOZ) para multi-select. Params: q, sujeto_ids[], carga_ids[], tipos[], provincia/localidad, fecha/hora, limit."""
    if not _permiso():
        return jsonify([]), 403
    cached = _rel_filtros_cache_get('api_filtros_imeis')
    if cached is not None:
        return jsonify(cached)
    modo = _mapa_datos_modo_arg()
    caso_id = request.args.get('caso_id', type=int)
    fuente_ids = _fuente_ids_record_from_request()
    q_txt = _clean_filter_text(request.args.get('q'))
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = _parse_tipos_list()
    provincias = _normalize_filter_input_list(request.args.getlist('provincias[]'))
    localidades = _normalize_filter_input_list(request.args.getlist('localidades[]'))
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    limit = request.args.get('limit', default=80, type=int) or 80
    if limit < 1:
        limit = 1
    if limit > 300:
        limit = 300

    provincias_l = [_sql_filter_text(x) for x in provincias if _sql_filter_text(x)]
    localidades_l = [_sql_filter_text(x) for x in localidades if _sql_filter_text(x)]

    out_sabana = []
    if modo in ('sabana', 'ambos'):
        include_gprs = (not tipos) or ('gprs' in tipos)
        include_voz = (not tipos) or ('voz' in tipos)
        queries = []
        if include_gprs:
            qg = ResultadoTraficoGPRS.query.join(CargaLlamada).filter(
                CargaLlamada.unidad_id == current_user.unidad_id,
                _carga_access_predicate(),
                ResultadoTraficoGPRS.imei.isnot(None),
                ResultadoTraficoGPRS.imei != '',
            )
            if sujeto_ids:
                qg = qg.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
            if carga_ids:
                qg = qg.filter(CargaLlamada.id.in_(carga_ids))
            qg = _apply_fecha_hora_filters(qg, ResultadoTraficoGPRS, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
            if provincias_l:
                qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoGPRS.celda_provincia)).in_(provincias_l)
                )
            if localidades_l:
                qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoGPRS.celda_localidad)).in_(localidades_l)
                )
            if q_txt:
                ql = q_txt.lower()
                qg = qg.filter(func.lower(func.trim(ResultadoTraficoGPRS.imei)).like(f"%{ql}%"))
            queries.append(qg.with_entities(ResultadoTraficoGPRS.imei.label('imei')).distinct())
        if include_voz:
            qv = ResultadoTraficoVOZ.query.join(CargaLlamada).filter(
                CargaLlamada.unidad_id == current_user.unidad_id,
                _carga_access_predicate(),
                ResultadoTraficoVOZ.imei.isnot(None),
                ResultadoTraficoVOZ.imei != '',
            )
            if sujeto_ids:
                qv = qv.filter(CargaLlamada.sujeto_id.in_(sujeto_ids))
            if carga_ids:
                qv = qv.filter(CargaLlamada.id.in_(carga_ids))
            qv = _apply_fecha_hora_filters(qv, ResultadoTraficoVOZ, fecha_desde, fecha_hasta, hora_desde_hm, hora_hasta_hm)
            if provincias_l:
                qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoVOZ.celda_provincia)).in_(provincias_l)
                )
            if localidades_l:
                qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(
                    func.lower(func.trim(ResultadoTraficoVOZ.celda_localidad)).in_(localidades_l)
                )
            if q_txt:
                ql = q_txt.lower()
                qv = qv.filter(func.lower(func.trim(ResultadoTraficoVOZ.imei)).like(f"%{ql}%"))
            queries.append(qv.with_entities(ResultadoTraficoVOZ.imei.label('imei')).distinct())
        if queries:
            q_union = queries[0]
            for qq in queries[1:]:
                q_union = q_union.union(qq)
            sub = q_union.subquery()
            col0 = list(sub.c)[0]
            rows = db.session.query(col0).order_by(col0).limit(limit).all()
            out_sabana = _sorted_unique_filter_values([r[0] for r in rows if r and r[0]], limit)

    out_record = []
    if modo in ('record', 'ambos') and caso_id:
        out_record = _record_filtros_imeis(
            caso_id, fuente_ids, tipos, q_txt, fecha_desde, fecha_hasta, provincias, localidades, limit
        )

    out_sabana = _sorted_unique_filter_values(out_sabana, limit)
    out_record = _sorted_unique_filter_values(out_record, limit)
    if modo == 'sabana':
        result = out_sabana
    elif modo == 'record':
        result = out_record
    else:
        result = _sorted_unique_filter_values(out_sabana + out_record, limit)
    _rel_filtros_cache_set('api_filtros_imeis', result)
    return jsonify(result)


@bp.route('/cargas')
def cargas_list():
    """Lista de cargas (historial) y modal de carga unificada en la misma pantalla."""
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    ctx = _cargas_list_context()
    return render_template('sabana_llamadas/cargas_list.html', **ctx)


@bp.route('/cargas/<int:carga_id>/detalle')
def cargas_detalle(carga_id):
    """Detalle de trazabilidad de procesamiento de una carga de sábana."""
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    carga = (
        _cargas_query_accessible()
        .options(joinedload(CargaLlamada.caso), joinedload(CargaLlamada.sujeto))
        .filter(CargaLlamada.id == carga_id)
        .first_or_404()
    )
    summary = _parse_sabana_processing_detail(carga)
    if carga.tipo == 'gprs':
        n_eventos_db = ResultadoTraficoGPRS.query.filter_by(carga_id=carga.id).count()
    else:
        n_eventos_db = ResultadoTraficoVOZ.query.filter_by(carga_id=carga.id).count()
    n_tecnicos_db = DatoTecnico.query.filter_by(carga_id=carga.id, tipo=carga.tipo).count()
    return render_template(
        'sabana_llamadas/carga_detalle.html',
        carga=carga,
        processing_summary=summary,
        n_eventos_db=n_eventos_db,
        n_tecnicos_db=n_tecnicos_db,
    )


@bp.route('/cargas/<int:carga_id>/vincular', methods=['GET', 'POST'])
def cargas_vincular(carga_id):
    """Vincula una carga a un caso (obligatorio) y opcionalmente a un sujeto."""
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para vincular cargas.', 'warning')
        return redirect(url_for('sabana_llamadas.cargas_list'))

    carga = (
        _cargas_query_accessible()
        .options(joinedload(CargaLlamada.caso))
        .filter(CargaLlamada.id == carga_id)
        .first_or_404()
    )
    _assert_owner_or_404(carga)
    form = VincularCargaForm()
    casos_ap = _casos_ap_para_unidad()
    form.caso_id.choices = [(0, 'Seleccionar caso…')] + [(c.id, f'{c.codigo} — {c.titulo}') for c in casos_ap]
    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
    form.sujeto_id.choices = [('', '-- Sin sujeto --')] + [(s.id, s.display_name()) for s in sujetos]

    if form.validate_on_submit():
        caso = AnalisisPuntoCaso.query.filter_by(id=form.caso_id.data, unidad_id=current_user.unidad_id).first()
        if not caso:
            flash('Caso inválido o no pertenece a su unidad.', 'warning')
            return render_template('sabana_llamadas/carga_vincular.html', form=form, carga=carga, casos_ap=casos_ap)
        carga.caso_id = caso.id
        carga.sujeto_id = form.sujeto_id.data
        db.session.commit()
        flash('Caso y sujeto de la carga actualizados correctamente.', 'success')
        if carga.sujeto_id:
            return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=carga.sujeto_id))
        return redirect(url_for('sabana_llamadas.cargas_list'))

    form.caso_id.data = carga.caso_id or 0
    form.sujeto_id.data = carga.sujeto_id
    return render_template('sabana_llamadas/carga_vincular.html', form=form, carga=carga, casos_ap=casos_ap)


@bp.route('/cargas/<int:carga_id>/eliminar', methods=['POST'])
def cargas_eliminar(carga_id):
    """Elimina una carga y todos sus registros asociados (tráfico + datos técnicos)."""
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para eliminar cargas.', 'warning')
        return redirect(url_for('sabana_llamadas.cargas_list'))

    carga = _cargas_query_accessible().filter(CargaLlamada.id == carga_id).first()
    if not carga:
        flash('Carga no encontrada.', 'warning')
        return redirect(url_for('sabana_llamadas.cargas_list'))
    _assert_owner_or_404(carga)

    sujeto_id = carga.sujeto_id

    # Borrar registros asociados
    ResultadoTraficoGPRS.query.filter_by(carga_id=carga.id).delete(synchronize_session=False)
    ResultadoTraficoVOZ.query.filter_by(carga_id=carga.id).delete(synchronize_session=False)
    DatoTecnico.query.filter_by(carga_id=carga.id).delete(synchronize_session=False)

    # Intentar borrar el archivo físico
    if carga.nombre_archivo:
        upload_folder = current_app.config['UPLOAD_FOLDER']
        if not os.path.isabs(upload_folder):
            upload_folder = os.path.join(current_app.root_path, upload_folder)
        path = os.path.join(upload_folder, str(carga.unidad_id), 'sabana', carga.nombre_archivo)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    db.session.delete(carga)
    db.session.commit()

    flash('Carga eliminada correctamente.', 'success')
    if sujeto_id:
        return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=sujeto_id))
    return redirect(url_for('sabana_llamadas.cargas_list'))

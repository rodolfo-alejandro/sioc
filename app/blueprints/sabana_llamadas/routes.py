"""
Rutas del módulo Sabana de Llamadas
"""
import os
import mimetypes
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, send_from_directory
from flask_login import login_required, current_user
from sqlalchemy import func, or_, inspect, text, tuple_, literal, case
from sqlalchemy.sql import exists, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.blueprints.sabana_llamadas import bp
from app.blueprints.sabana_llamadas.forms import (
    UploadGPRSForm,
    UploadVOZForm,
    SujetoForm,
    VincularCargaForm,
)
from app.blueprints.sabana_llamadas.services import (
    procesar_archivo_gprs,
    procesar_archivo_voz,
    guardar_imagen_sujeto,
)
from app.extensions import db
from app.models.sabana_llamadas import (
    Sujeto,
    CargaLlamada,
    CargaLlamadaCompartida,
    SujetoCompartido,
    DatoTecnico,
    ResultadoTraficoGPRS,
    ResultadoTraficoVOZ,
)
from app.models.persona import Persona
from app.models.user import User


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
    return or_(owned, shared_carga, shared_suj)


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
    return or_(owned, shared_suj, shared_via_carga)


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

        # Índices de lookup para shares (PK ya asegura unicidad)
        idx_changed = ensure_index('sabana_cargas_compartidas', 'idx_sabana_cargas_compartidas_shared_with',
                                   "CREATE INDEX idx_sabana_cargas_compartidas_shared_with ON sabana_cargas_compartidas (shared_with_user_id)") or idx_changed
        idx_changed = ensure_index('sabana_sujetos_compartidos', 'idx_sabana_sujetos_compartidos_shared_with',
                                   "CREATE INDEX idx_sabana_sujetos_compartidos_shared_with ON sabana_sujetos_compartidos (shared_with_user_id)") or idx_changed

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
        .order_by(CargaLlamada.created_at.desc()).limit(10).all()
    return render_template('sabana_llamadas/index.html', cargas=cargas_recientes)


@bp.route('/sujetos')
def sujetos_list():
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    lista = _sujetos_query_accessible().order_by(Sujeto.updated_at.desc()).all()
    # Conteo de cargas ACCESIBLES por sujeto (evita N+1 y evita filtrar mal en template).
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
    return render_template('sabana_llamadas/sujetos_list.html', sujetos=lista, cargas_count=cargas_count)


@bp.route('/sujetos/nuevo', methods=['GET', 'POST'])
def sujetos_nuevo():
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para crear sujetos.', 'warning')
        return redirect(url_for('sabana_llamadas.sujetos_list'))
    form = SujetoForm()
    form.persona_id.choices = [('', '-- Sin vincular --')] + [
        (p.id, f"{p.nombre_completo} (DNI {p.dni})")
        for p in Persona.query.order_by(Persona.apellido).limit(500).all()
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
        flash('Sujeto creado correctamente.', 'success')
        return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=s.id))
    return render_template('sabana_llamadas/sujeto_form.html', form=form, sujeto=None)


@bp.route('/sujetos/<int:sujeto_id>')
def sujetos_ver(sujeto_id):
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    sujeto = _sujetos_query_accessible().filter(Sujeto.id == sujeto_id).first_or_404()
    # Importante: no usar sujeto.cargas directo, porque puede incluir cargas no accesibles
    # (por ejemplo, si el acceso al sujeto vino por una carga compartida).
    cargas = _cargas_query_accessible().filter(CargaLlamada.sujeto_id == sujeto.id) \
        .order_by(CargaLlamada.created_at.desc()).all()
    return render_template('sabana_llamadas/sujeto_ver.html', sujeto=sujeto, cargas=cargas)


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
    form.persona_id.choices = [('', '-- Sin vincular --')] + [
        (p.id, f"{p.nombre_completo} (DNI {p.dni})")
        for p in Persona.query.order_by(Persona.apellido).limit(500).all()
    ]
    if form.validate_on_submit():
        sujeto.apodo = form.apodo.data or None
        sujeto.nombre = form.nombre.data or None
        sujeto.dni = form.dni.data or None
        sujeto.observaciones = form.observaciones.data or None
        sujeto.persona_id = form.persona_id.data or None
        if form.imagen.data and form.imagen.data.filename:
            ruta, err = guardar_imagen_sujeto(form.imagen.data, current_user.unidad_id, sujeto.id)
            if not err and ruta:
                sujeto.imagen = ruta
        db.session.commit()
        flash('Sujeto actualizado.', 'success')
        return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=sujeto.id))
    return render_template('sabana_llamadas/sujeto_form.html', form=form, sujeto=sujeto)


@bp.route('/gprs/upload', methods=['GET', 'POST'])
def gprs_upload():
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para subir archivos GPRS.', 'warning')
        return redirect(url_for('sabana_llamadas.index'))
    form = UploadGPRSForm()
    # Solo sujetos accesibles (dueño o compartidos). Evita vincular cargas a sujetos de terceros sin acceso.
    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
    form.sujeto_id.choices = [('', '-- Sin vincular --')] + [(s.id, s.display_name()) for s in sujetos]
    if form.validate_on_submit():
        sujeto_id = form.sujeto_id.data if form.sujeto_id.data else None
        carga, ct, cd, err = procesar_archivo_gprs(
            form.file.data, current_user.unidad_id, current_user.id, sujeto_id
        )
        if err:
            flash(f'Error: {err}', 'danger')
        else:
            flash(f'Carga GPRS correcta: {ct} registros de tráfico, {cd} datos técnicos.', 'success')
            return redirect(url_for('sabana_llamadas.gprs_upload'))
    return render_template('sabana_llamadas/upload_gprs.html', form=form)


@bp.route('/voz/upload', methods=['GET', 'POST'])
def voz_upload():
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para subir archivos VOZ.', 'warning')
        return redirect(url_for('sabana_llamadas.index'))
    form = UploadVOZForm()
    # Solo sujetos accesibles (dueño o compartidos). Evita vincular cargas a sujetos de terceros sin acceso.
    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
    form.sujeto_id.choices = [('', '-- Sin vincular --')] + [(s.id, s.display_name()) for s in sujetos]
    if form.validate_on_submit():
        sujeto_id = form.sujeto_id.data if form.sujeto_id.data else None
        carga, ct, cd, err = procesar_archivo_voz(
            form.file.data, current_user.unidad_id, current_user.id, sujeto_id
        )
        if err:
            flash(f'Error: {err}', 'danger')
        else:
            flash(f'Carga VOZ correcta: {ct} registros de tráfico, {cd} datos técnicos.', 'success')
            return redirect(url_for('sabana_llamadas.voz_upload'))
    return render_template('sabana_llamadas/upload_voz.html', form=form)


@bp.route('/mapa')
def mapa():
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    return render_template('sabana_llamadas/mapa.html')


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
                ors = []
                for n in numeros[:50]:
                    ors.append(func.lower(ResultadoTraficoVOZ.otro).like(f"%{n.lower()}%"))
                    ors.append(func.lower(ResultadoTraficoVOZ.numero).like(f"%{n.lower()}%"))
                if ors:
                    q_reg = q_reg.filter(or_(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.numero.isnot(None))).filter(or_(*ors))
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
    cargas = _cargas_query_accessible().order_by(CargaLlamada.created_at.desc()).limit(cargas_limit).all()
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


@bp.route('/api/filtros/numeros')
def api_filtros_numeros():
    """Devuelve números para buscador multi-select (GPRS.numero y VOZ.numero/otro)."""
    if not _permiso():
        return jsonify([]), 403
    q_txt = (request.args.get('q') or '').strip()
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    limit = request.args.get('limit', default=50, type=int) or 50
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

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
        if provincias:
            qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if q_txt:
            ql = q_txt.lower()
            qg = qg.filter(func.lower(ResultadoTraficoGPRS.numero).like(f"%{ql}%"))
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
        if provincias:
            qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if q_txt:
            ql = q_txt.lower()
            qv = qv.filter(or_(
                func.lower(ResultadoTraficoVOZ.otro).like(f"%{ql}%"),
                func.lower(ResultadoTraficoVOZ.numero).like(f"%{ql}%"),
            ))
        # Unir ambos campos en una única lista
        queries.append(qv.with_entities(ResultadoTraficoVOZ.otro.label('numero')).filter(ResultadoTraficoVOZ.otro.isnot(None), ResultadoTraficoVOZ.otro != '').distinct())
        queries.append(qv.with_entities(ResultadoTraficoVOZ.numero.label('numero')).filter(ResultadoTraficoVOZ.numero.isnot(None), ResultadoTraficoVOZ.numero != '').distinct())

    if not queries:
        return jsonify([])

    q_union = queries[0]
    for qq in queries[1:]:
        q_union = q_union.union(qq)

    # MySQL + UNION + ORDER BY por label puede fallar. Ordenamos usando subquery y primer columna.
    sub = q_union.subquery()
    col0 = list(sub.c)[0]
    rows = db.session.query(col0).order_by(col0).limit(limit).all()
    out = [r[0] for r in rows if r and r[0]]
    return jsonify(out)


@bp.route('/api/filtros/provincias')
def api_filtros_provincias():
    """Devuelve provincias (celda_prov) para multi-select. Params: q, sujeto_ids[], carga_ids[], tipos[], limit."""
    if not _permiso():
        return jsonify([]), 403
    q_txt = (request.args.get('q') or '').strip()
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    limit = request.args.get('limit', default=80, type=int) or 80
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

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
        ql = q_txt.lower()
        q = q.filter(func.lower(DatoTecnico.celda_prov).like(f"%{ql}%"))

    rows = q.with_entities(DatoTecnico.celda_prov).distinct().order_by(DatoTecnico.celda_prov).limit(limit).all()
    out = [r[0] for r in rows if r and r[0]]
    return jsonify(out)


@bp.route('/api/filtros/localidades')
def api_filtros_localidades():
    """Devuelve localidades (celda_loc) para multi-select. Params: q, sujeto_ids[], carga_ids[], tipos[], provincias[], limit."""
    if not _permiso():
        return jsonify([]), 403
    q_txt = (request.args.get('q') or '').strip()
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    limit = request.args.get('limit', default=120, type=int) or 120
    if limit < 1:
        limit = 1
    if limit > 300:
        limit = 300

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
        q = q.filter(DatoTecnico.celda_prov.isnot(None)).filter(DatoTecnico.celda_prov.in_(provincias))
    if q_txt:
        ql = q_txt.lower()
        q = q.filter(func.lower(DatoTecnico.celda_loc).like(f"%{ql}%"))

    rows = q.with_entities(DatoTecnico.celda_loc).distinct().order_by(DatoTecnico.celda_loc).limit(limit).all()
    out = [r[0] for r in rows if r and r[0]]
    return jsonify(out)


@bp.route('/api/filtros/imeis')
def api_filtros_imeis():
    """Devuelve IMEIs (GPRS/VOZ) para multi-select. Params: q, sujeto_ids[], carga_ids[], tipos[], provincia/localidad, fecha/hora, limit."""
    if not _permiso():
        return jsonify([]), 403
    q_txt = (request.args.get('q') or '').strip()
    sujeto_ids = request.args.getlist('sujeto_ids[]', type=int)
    carga_ids = request.args.getlist('carga_ids[]', type=int)
    tipos = request.args.getlist('tipos[]')
    provincias = [str(x).strip() for x in request.args.getlist('provincias[]') if str(x).strip()]
    localidades = [str(x).strip() for x in request.args.getlist('localidades[]') if str(x).strip()]
    fecha_desde = _parse_ymd(request.args.get('fecha_desde'))
    fecha_hasta = _parse_ymd(request.args.get('fecha_hasta'))
    hora_desde_hm = _normalize_hm(request.args.get('hora_desde'))
    hora_hasta_hm = _normalize_hm(request.args.get('hora_hasta'))
    limit = request.args.get('limit', default=80, type=int) or 80
    if limit < 1:
        limit = 1
    if limit > 300:
        limit = 300

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
        if provincias:
            qg = qg.filter(ResultadoTraficoGPRS.celda_provincia.isnot(None)).filter(ResultadoTraficoGPRS.celda_provincia.in_(provincias))
        if localidades:
            qg = qg.filter(ResultadoTraficoGPRS.celda_localidad.isnot(None)).filter(ResultadoTraficoGPRS.celda_localidad.in_(localidades))
        if q_txt:
            ql = q_txt.lower()
            qg = qg.filter(func.lower(ResultadoTraficoGPRS.imei).like(f"%{ql}%"))
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
        if provincias:
            qv = qv.filter(ResultadoTraficoVOZ.celda_provincia.isnot(None)).filter(ResultadoTraficoVOZ.celda_provincia.in_(provincias))
        if localidades:
            qv = qv.filter(ResultadoTraficoVOZ.celda_localidad.isnot(None)).filter(ResultadoTraficoVOZ.celda_localidad.in_(localidades))
        if q_txt:
            ql = q_txt.lower()
            qv = qv.filter(func.lower(ResultadoTraficoVOZ.imei).like(f"%{ql}%"))
        queries.append(qv.with_entities(ResultadoTraficoVOZ.imei.label('imei')).distinct())

    if not queries:
        return jsonify([])

    q_union = queries[0]
    for qq in queries[1:]:
        q_union = q_union.union(qq)

    sub = q_union.subquery()
    col0 = list(sub.c)[0]
    rows = db.session.query(col0).order_by(col0).limit(limit).all()
    out = [r[0] for r in rows if r and r[0]]
    return jsonify(out)


@bp.route('/cargas')
def cargas_list():
    """Lista de cargas (archivos subidos), vinculadas o no a sujetos."""
    if not _permiso():
        return redirect(url_for('core.dashboard'))
    cargas = _cargas_query_accessible() \
        .order_by(CargaLlamada.created_at.desc()).all()
    return render_template('sabana_llamadas/cargas_list.html', cargas=cargas)


@bp.route('/cargas/<int:carga_id>/vincular', methods=['GET', 'POST'])
def cargas_vincular(carga_id):
    """Vincula una carga existente a un sujeto (o la deja sin sujeto)."""
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para vincular cargas.', 'warning')
        return redirect(url_for('sabana_llamadas.cargas_list'))

    carga = _cargas_query_accessible().filter(CargaLlamada.id == carga_id).first_or_404()
    _assert_owner_or_404(carga)
    form = VincularCargaForm()
    sujetos = _sujetos_query_accessible().order_by(Sujeto.apodo, Sujeto.nombre).all()
    form.sujeto_id.choices = [('', '-- Sin sujeto --')] + [(s.id, s.display_name()) for s in sujetos]

    if form.validate_on_submit():
        carga.sujeto_id = form.sujeto_id.data
        db.session.commit()
        flash('Carga vinculada correctamente.', 'success')
        if carga.sujeto_id:
            return redirect(url_for('sabana_llamadas.sujetos_ver', sujeto_id=carga.sujeto_id))
        return redirect(url_for('sabana_llamadas.cargas_list'))

    # Valor inicial del select
    form.sujeto_id.data = carga.sujeto_id
    return render_template('sabana_llamadas/carga_vincular.html', form=form, carga=carga)


@bp.route('/cargas/<int:carga_id>/eliminar', methods=['POST'])
def cargas_eliminar(carga_id):
    """Elimina una carga y todos sus registros asociados (tráfico + datos técnicos)."""
    if not current_user.has_permission('SABANA_LLAMADAS_UPLOAD'):
        flash('Sin permiso para eliminar cargas.', 'warning')
        return redirect(url_for('sabana_llamadas.index'))

    carga = _cargas_query_accessible().filter(CargaLlamada.id == carga_id).first()
    if not carga:
        flash('Carga no encontrada.', 'warning')
        return redirect(url_for('sabana_llamadas.index'))
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
    # Si no hay sujeto, volver a la pantalla de carga según tipo
    if carga.tipo == 'gprs':
        return redirect(url_for('sabana_llamadas.gprs_upload'))
    if carga.tipo == 'voz':
        return redirect(url_for('sabana_llamadas.voz_upload'))
    return redirect(url_for('sabana_llamadas.index'))

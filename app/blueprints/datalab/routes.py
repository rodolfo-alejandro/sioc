"""
Rutas de DataLab
"""
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app.blueprints.datalab import bp
from app.blueprints.datalab.forms import UploadDatasetForm, UploadDenunciasForm
from app.blueprints.datalab.services import process_uploaded_file, get_user_datasets, get_dataset_by_id
from app.blueprints.datalab.services_denuncias import procesar_archivo_denuncias, obtener_datos_graficos, aplicar_filtros
from app.services.rbac import require_permission
from app.services.audit import audit_log
from app.models.denuncia_web import DenunciaWeb


@bp.route('/upload', methods=['GET', 'POST'])
@login_required
@require_permission('DATALAB_UPLOAD')
def upload():
    """Subir archivo al DataLab"""
    form = UploadDatasetForm()
    
    if form.validate_on_submit():
        dataset, error = process_uploaded_file(
            file=form.file.data,
            name=form.name.data,
            unidad_id=current_user.unidad_id,
            user_id=current_user.id
        )
        
        if dataset:
            flash(f'Dataset "{dataset.name}" subido correctamente ({dataset.rows_count} filas, {dataset.columns_count} columnas)', 'success')
            return redirect(url_for('datalab.dataset_view', dataset_id=dataset.id))
        else:
            flash(error, 'danger')
    
    return render_template('datalab/upload.html', form=form)


@bp.route('/datasets')
@login_required
@require_permission('DATALAB_VIEW')
def datasets():
    """Lista de datasets"""
    datasets_list = get_user_datasets(current_user.id, current_user.unidad_id).all()
    
    # Búsqueda
    search = request.args.get('search', '')
    if search:
        datasets_list = [d for d in datasets_list if search.lower() in d.name.lower()]
    
    return render_template('datalab/datasets.html', datasets=datasets_list, search=search)


@bp.route('/datasets/<int:dataset_id>')
@login_required
@require_permission('DATALAB_VIEW')
def dataset_view(dataset_id):
    """Vista detallada de un dataset"""
    dataset = get_dataset_by_id(dataset_id, current_user.unidad_id)
    
    if not dataset:
        flash('Dataset no encontrado o sin permisos', 'danger')
        return redirect(url_for('datalab.datasets'))
    
    # Auditoría
    audit_log('DATASET_VIEWED', f'Dataset {dataset.name} visualizado')
    
    # Obtener datos
    preview = dataset.get_preview()
    profile = dataset.get_profile()
    charts = dataset.get_charts()
    
    return render_template(
        'datalab/dataset_view.html',
        dataset=dataset,
        preview=preview,
        profile=profile,
        charts=charts
    )


# ==================== RUTAS DE DENUNCIAS WEB ====================

@bp.route('/denuncias/upload', methods=['GET', 'POST'])
@login_required
@require_permission('DATALAB_UPLOAD')
def denuncias_upload():
    """Cargar archivo Excel de denuncias web"""
    form = UploadDenunciasForm()
    
    # Obtener estadísticas actuales
    total_actual = DenunciaWeb.query.filter_by(unidad_id=current_user.unidad_id).count()
    ultima_carga = DenunciaWeb.query.filter_by(unidad_id=current_user.unidad_id).order_by(DenunciaWeb.created_at.desc()).first()
    
    if form.validate_on_submit():
        cantidad, error = procesar_archivo_denuncias(
            file=form.file.data,
            unidad_id=current_user.unidad_id,
            user_id=current_user.id,
            eliminar_existentes=True
        )
        
        if cantidad is not None:
            flash(f'✅ {cantidad} denuncias cargadas correctamente', 'success')
            if error:
                flash(f'⚠️ {error}', 'warning')
            return redirect(url_for('datalab.denuncias_upload'))
        else:
            flash(f'❌ Error: {error}', 'danger')
    
    return render_template('datalab/denuncias/upload.html', 
                         form=form, 
                         total_actual=total_actual,
                         ultima_carga=ultima_carga)


@bp.route('/denuncias/dashboard', methods=['GET', 'POST'])
@login_required
@require_permission('DATALAB_VIEW')
def denuncias_dashboard():
    """Dashboard de denuncias web con gráficos y filtros"""
    # Procesar filtros del formulario
    filtros = {}
    
    if request.method == 'POST':
        # Filtros de selección múltiple
        filtros['tipos'] = [t for t in request.form.getlist('tipos[]') if t]
        filtros['departamentos'] = [d for d in request.form.getlist('departamentos[]') if d]
        filtros['divisiones'] = [d for d in request.form.getlist('divisiones[]') if d]
        filtros['secciones'] = [s for s in request.form.getlist('secciones[]') if s]
        filtros['estados'] = [e for e in request.form.getlist('estados[]') if e]
        filtros['actuarios'] = [a for a in request.form.getlist('actuarios[]') if a]
        
        # Filtros de rango
        if request.form.get('fecha_desde'):
            try:
                filtros['fecha_desde'] = datetime.strptime(request.form.get('fecha_desde'), '%Y-%m-%d')
            except:
                pass
        if request.form.get('fecha_hasta'):
            try:
                filtros['fecha_hasta'] = datetime.strptime(request.form.get('fecha_hasta'), '%Y-%m-%d')
            except:
                pass
        if request.form.get('dias_desde'):
            try:
                filtros['dias_desde'] = int(request.form.get('dias_desde'))
            except:
                pass
        if request.form.get('dias_hasta'):
            try:
                filtros['dias_hasta'] = int(request.form.get('dias_hasta'))
            except:
                pass
        if request.form.get('avance_desde'):
            try:
                filtros['avance_desde'] = float(request.form.get('avance_desde'))
            except:
                pass
        if request.form.get('avance_hasta'):
            try:
                filtros['avance_hasta'] = float(request.form.get('avance_hasta'))
            except:
                pass
    
    # Obtener datos para gráficos
    datos = obtener_datos_graficos(current_user.unidad_id, filtros if filtros else None)
    
    return render_template('datalab/denuncias/dashboard.html', 
                         datos=datos,
                         filtros_aplicados=filtros)


@bp.route('/denuncias/dashboard/api', methods=['GET'])
@login_required
@require_permission('DATALAB_VIEW')
def denuncias_dashboard_api():
    """API para obtener datos de gráficos (AJAX)"""
    from app.models.denuncia_web import DenunciaWeb
    
    # Si solo se piden opciones de filtros
    if request.args.get('opciones'):
        opcion = request.args.get('opciones')
        query = DenunciaWeb.query.filter_by(unidad_id=current_user.unidad_id)

        # Filtrar por departamentos si se proporcionan
        departamentos = request.args.getlist('departamentos[]')
        if departamentos and '' not in departamentos:
            query = query.filter(DenunciaWeb.departamento.in_(departamentos))

        # Filtrar por divisiones si se proporcionan
        divisiones = request.args.getlist('divisiones[]')
        if divisiones and '' not in divisiones:
            query = query.filter(DenunciaWeb.division.in_(divisiones))
        
        if opcion == 'divisiones':
            divisiones = sorted([d[0] for d in query.with_entities(DenunciaWeb.division).distinct().all() if d[0]])
            return jsonify({'divisiones': divisiones})
        elif opcion == 'secciones':
            secciones = sorted([s[0] for s in query.with_entities(DenunciaWeb.sinar_a_cargo).distinct().all() if s[0]])
            return jsonify({'secciones': secciones})
    
    # Procesar filtros normales
    filtros = {}

    # Procesar parámetros GET
    # OJO: en el frontend se envían como `tipos[]`, `departamentos[]`, etc.
    # por lo que debemos usar getlist('nombre[]') y comprobar esa lista.
    tipos = request.args.getlist('tipos[]')
    if tipos and '' not in tipos:
        filtros['tipos'] = tipos

    departamentos = request.args.getlist('departamentos[]')
    if departamentos and '' not in departamentos:
        filtros['departamentos'] = departamentos

    divisiones = request.args.getlist('divisiones[]')
    if divisiones and '' not in divisiones:
        filtros['divisiones'] = divisiones

    secciones = request.args.getlist('secciones[]')
    if secciones and '' not in secciones:
        filtros['secciones'] = secciones

    estados = request.args.getlist('estados[]')
    if estados and '' not in estados:
        filtros['estados'] = estados
    actuarios = request.args.getlist('actuarios[]')
    if actuarios:
        if actuarios and '' not in actuarios:
            filtros['actuarios'] = actuarios
    if request.args.get('fecha_desde'):
        try:
            filtros['fecha_desde'] = datetime.strptime(request.args.get('fecha_desde'), '%Y-%m-%d')
        except:
            pass
    if request.args.get('fecha_hasta'):
        try:
            filtros['fecha_hasta'] = datetime.strptime(request.args.get('fecha_hasta'), '%Y-%m-%d')
        except:
            pass
    if request.args.get('dias_desde'):
        try:
            filtros['dias_desde'] = int(request.args.get('dias_desde'))
        except:
            pass
    if request.args.get('dias_hasta'):
        try:
            filtros['dias_hasta'] = int(request.args.get('dias_hasta'))
        except:
            pass
    if request.args.get('avance_desde'):
        try:
            filtros['avance_desde'] = float(request.args.get('avance_desde'))
        except:
            pass
    if request.args.get('avance_hasta'):
        try:
            filtros['avance_hasta'] = float(request.args.get('avance_hasta'))
        except:
            pass
    
    datos = obtener_datos_graficos(current_user.unidad_id, filtros if filtros else None)
    return jsonify(datos)


@bp.route('/denuncias/lista', methods=['GET'])
@login_required
@require_permission('DATALAB_VIEW')
def denuncias_lista():
    """
    Devuelve una lista de denuncias en formato JSON para drill-down desde los gráficos.
    Respeta todos los filtros del dashboard y permite aplicar un \"slice\" adicional
    según el gráfico (estado, rango de días, rango de avance, actuario).
    """
    filtros = {}

    tipos = request.args.getlist('tipos[]')
    if tipos and '' not in tipos:
        filtros['tipos'] = tipos
    departamentos = request.args.getlist('departamentos[]')
    if departamentos and '' not in departamentos:
        filtros['departamentos'] = departamentos
    divisiones = request.args.getlist('divisiones[]')
    if divisiones and '' not in divisiones:
        filtros['divisiones'] = divisiones
    secciones = request.args.getlist('secciones[]')
    if secciones and '' not in secciones:
        filtros['secciones'] = secciones
    estados = request.args.getlist('estados[]')
    if estados and '' not in estados:
        filtros['estados'] = estados
    actuarios = request.args.getlist('actuarios[]')
    if actuarios and '' not in actuarios:
        filtros['actuarios'] = actuarios

    if request.args.get('fecha_desde'):
        try:
            filtros['fecha_desde'] = datetime.strptime(request.args.get('fecha_desde'), '%Y-%m-%d')
        except Exception:
            pass
    if request.args.get('fecha_hasta'):
        try:
            filtros['fecha_hasta'] = datetime.strptime(request.args.get('fecha_hasta'), '%Y-%m-%d')
        except Exception:
            pass
    if request.args.get('dias_desde'):
        try:
            filtros['dias_desde'] = int(request.args.get('dias_desde'))
        except Exception:
            pass
    if request.args.get('dias_hasta'):
        try:
            filtros['dias_hasta'] = int(request.args.get('dias_hasta'))
        except Exception:
            pass
    if request.args.get('avance_desde'):
        try:
            filtros['avance_desde'] = float(request.args.get('avance_desde'))
        except Exception:
            pass
    if request.args.get('avance_hasta'):
        try:
            filtros['avance_hasta'] = float(request.args.get('avance_hasta'))
        except Exception:
            pass

    # Query base y aplicación de filtros
    query = DenunciaWeb.query.filter_by(unidad_id=current_user.unidad_id)
    query = aplicar_filtros(query, filtros if filtros else None)

    # Slice adicional según el gráfico
    slice_tipo = request.args.get('slice_tipo')  # estados|dias|avance|actuarios
    slice_label = request.args.get('slice_label')

    if slice_tipo and slice_label:
        if slice_tipo == 'estados':
            query = query.filter(DenunciaWeb.estado_nombre == slice_label)
        elif slice_tipo == 'actuarios':
            query = query.filter(DenunciaWeb.nombre_actuario == slice_label)
        elif slice_tipo == 'dias':
            # Mapear rangos de texto a limites numéricos de dias_investigacion
            if slice_label.startswith('0-100'):
                query = query.filter(DenunciaWeb.dias_investigacion >= 0,
                                     DenunciaWeb.dias_investigacion < 100)
            elif slice_label.startswith('100-200'):
                query = query.filter(DenunciaWeb.dias_investigacion >= 100,
                                     DenunciaWeb.dias_investigacion < 200)
            elif slice_label.startswith('200-300'):
                query = query.filter(DenunciaWeb.dias_investigacion >= 200,
                                     DenunciaWeb.dias_investigacion < 300)
            elif '+300' in slice_label:
                query = query.filter(DenunciaWeb.dias_investigacion >= 300)
        elif slice_tipo == 'avance':
            # Rango de avance en porcentaje
            if slice_label == '10-20':
                query = query.filter(DenunciaWeb.avance >= 10, DenunciaWeb.avance <= 20)
            elif slice_label == '30-50':
                query = query.filter(DenunciaWeb.avance >= 30, DenunciaWeb.avance <= 50)
            elif slice_label == '60-70':
                query = query.filter(DenunciaWeb.avance >= 60, DenunciaWeb.avance <= 70)
            elif slice_label == '80-100':
                query = query.filter(DenunciaWeb.avance >= 80, DenunciaWeb.avance <= 100)
            elif slice_label == 'Vacías':
                query = query.filter(DenunciaWeb.avance.is_(None))

    # Limitar resultados para no saturar la UI
    limite = min(int(request.args.get('limit', 200)), 1000)
    registros = query.order_by(DenunciaWeb.fecha_registro.desc()).limit(limite).all()

    def serialize(d):
        return {
            'id': d.id,
            'numero_ap': d.numero_ap,
            'fecha_registro': d.fecha_registro.isoformat() if d.fecha_registro else None,
            'estado': d.estado_nombre,
            'actuario': d.nombre_actuario,
            'avance': d.avance,
            'departamento': d.departamento,
            'division': d.division,
            'tipo_origen': d.tipo_origen
        }

    data = [serialize(d) for d in registros]
    return jsonify({'total': query.count(), 'registros': data})


@bp.route('/denuncias/detalle/<int:denuncia_id>', methods=['GET'])
@login_required
@require_permission('DATALAB_VIEW')
def denuncias_detalle(denuncia_id):
    """
    Devuelve el detalle de una denuncia en JSON para mostrar en un modal.
    """
    denuncia = DenunciaWeb.query.filter_by(unidad_id=current_user.unidad_id, id=denuncia_id).first_or_404()

    def serialize_detalle(d):
        return {
            'id': d.id,
            'numero_ap': d.numero_ap,
            'fecha_registro': d.fecha_registro.isoformat() if d.fecha_registro else None,
            'fecha_hecho': d.fecha_hecho.isoformat() if d.fecha_hecho else None,
            'departamento': d.departamento,
            'division': d.division,
            'sinar_a_cargo': d.sinar_a_cargo,
            'estado': d.estado_nombre,
            'avance': d.avance,
            'actuario': d.nombre_actuario,
            'caratula': d.caratula,
            'lugar_hecho': d.lugar_hecho,
            'municipio': d.municipio,
            'relato_hecho': d.relato_hecho,
            'acciones_desplegadas': d.acciones_desplegadas,
            'observaciones': d.observaciones
        }

    return jsonify(serialize_detalle(denuncia))

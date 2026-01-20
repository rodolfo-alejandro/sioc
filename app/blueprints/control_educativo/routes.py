"""
Rutas para el módulo de Control Educativo
Solo rutas, sin lógica de negocio (la lógica va en services)
"""
from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from . import bp
from ...services.control_educativo import ControlEducativoService
from ...services.rbac import require_permission

@bp.route('/')
@login_required
@require_permission('CONTROL_EDUCATIVO_VIEW')
def index():
    """Lista de establecimientos educativos"""
    service = ControlEducativoService()
    
    # Filtros
    busqueda = request.args.get('busqueda', '').strip()
    tipo_id = request.args.get('tipo', type=int)
    barrio_id = request.args.get('barrio', type=int)
    nivel = request.args.get('nivel', '').strip()
    
    establecimientos = service.listar_establecimientos(
        unidad_id=current_user.unidad_id,
        busqueda=busqueda,
        tipo_id=tipo_id,
        barrio_id=barrio_id,
        nivel=nivel
    )
    
    datos_referencia = service.obtener_datos_referencia()
    
    return render_template(
        'control_educativo/index.html',
        establecimientos=establecimientos,
        datos_referencia=datos_referencia
    )

@bp.route('/registrar', methods=['GET', 'POST'])
@login_required
@require_permission('CONTROL_EDUCATIVO_CREATE')
def registrar():
    """Registrar un nuevo establecimiento educativo"""
    service = ControlEducativoService()
    
    if request.method == 'POST':
        try:
            resultado = service.crear_establecimiento(
                form_data=request.form,
                usuario_id=current_user.id,
                unidad_id=current_user.unidad_id
            )
            
            if resultado['success']:
                flash('Establecimiento registrado correctamente', 'success')
                return redirect(url_for('control_educativo.index'))
            else:
                flash(resultado.get('error', 'Error al registrar establecimiento'), 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    datos_referencia = service.obtener_datos_referencia()
    
    return render_template(
        'control_educativo/registrar.html',
        datos_referencia=datos_referencia
    )

@bp.route('/ver/<int:establecimiento_id>')
@login_required
@require_permission('CONTROL_EDUCATIVO_VIEW')
def ver(establecimiento_id):
    """Ver detalle de un establecimiento"""
    service = ControlEducativoService()
    
    establecimiento = service.obtener_establecimiento_por_id(
        establecimiento_id=establecimiento_id,
        unidad_id=current_user.unidad_id
    )
    
    if not establecimiento:
        flash('Establecimiento no encontrado', 'error')
        return redirect(url_for('control_educativo.index'))
    
    controles = service.listar_controles_establecimiento(establecimiento_id=establecimiento_id)
    personal = service.listar_personal_establecimiento(establecimiento_id=establecimiento_id)
    
    return render_template(
        'control_educativo/ver.html',
        establecimiento=establecimiento,
        controles=controles,
        personal=personal
    )

@bp.route('/controlar/<int:establecimiento_id>', methods=['GET', 'POST'])
@login_required
@require_permission('CONTROL_EDUCATIVO_CREATE')
def controlar(establecimiento_id):
    """Realizar un control a un establecimiento"""
    service = ControlEducativoService()
    
    establecimiento = service.obtener_establecimiento_por_id(
        establecimiento_id=establecimiento_id,
        unidad_id=current_user.unidad_id
    )
    
    if not establecimiento:
        flash('Establecimiento no encontrado', 'error')
        return redirect(url_for('control_educativo.index'))
    
    if request.method == 'POST':
        try:
            resultado = service.crear_control(
                establecimiento_id=establecimiento_id,
                form_data=request.form,
                usuario_id=current_user.id,
                unidad_id=current_user.unidad_id
            )
            
            if resultado['success']:
                flash('Control registrado correctamente', 'success')
                return redirect(url_for('control_educativo.ver', establecimiento_id=establecimiento_id))
            else:
                flash(resultado.get('error', 'Error al registrar control'), 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    datos_referencia = service.obtener_datos_referencia()
    personal = service.listar_personal_establecimiento(establecimiento_id=establecimiento_id)
    
    return render_template(
        'control_educativo/controlar.html',
        establecimiento=establecimiento,
        datos_referencia=datos_referencia,
        personal=personal
    )


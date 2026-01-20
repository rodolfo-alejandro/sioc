"""
Rutas para el módulo de Control Comercial
Solo rutas, sin lógica de negocio (la lógica va en services)
"""
from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from . import bp
from ...services.control_comercial import ControlComercialService
from ...services.audit import audit_log
from ...services.rbac import require_permission

@bp.route('/')
@login_required
@require_permission('CONTROL_COMERCIAL_VIEW')
def index():
    """Lista de comercios"""
    service = ControlComercialService()
    
    # Filtros
    rubro_id = request.args.get('rubro_id', type=int)
    barrio_id = request.args.get('barrio_id', type=int)
    buscar = request.args.get('buscar', '').strip()
    
    comercios = service.listar_comercios(
        unidad_id=current_user.unidad_id,
        rubro_id=rubro_id,
        barrio_id=barrio_id,
        buscar=buscar
    )
    
    datos_referencia = service.obtener_datos_referencia()
    
    return render_template(
        'control_comercial/index.html',
        comercios=comercios,
        datos_referencia=datos_referencia
    )

@bp.route('/registrar', methods=['GET', 'POST'])
@login_required
@require_permission('CONTROL_COMERCIAL_CREATE')
def registrar():
    """Registrar un nuevo comercio"""
    service = ControlComercialService()
    
    if request.method == 'POST':
        try:
            resultado = service.crear_comercio(
                form_data=request.form,
                usuario_id=current_user.id,
                unidad_id=current_user.unidad_id
            )
            
            if resultado['success']:
                audit_log(
                    user_id=current_user.id,
                    action='COMERCIO_CREATED',
                    details=f"Comercio: {resultado.get('denominacion')}"
                )
                flash('Comercio registrado correctamente', 'success')
                return redirect(url_for('control_comercial.index'))
            else:
                flash(resultado.get('error', 'Error al registrar comercio'), 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    datos_referencia = service.obtener_datos_referencia()
    
    return render_template(
        'control_comercial/registrar.html',
        datos_referencia=datos_referencia
    )

@bp.route('/ver/<int:comercio_id>')
@login_required
@require_permission('CONTROL_COMERCIAL_VIEW')
def ver(comercio_id):
    """Ver detalle de un comercio"""
    service = ControlComercialService()
    
    comercio = service.obtener_comercio_por_id(
        comercio_id=comercio_id,
        unidad_id=current_user.unidad_id
    )
    
    if not comercio:
        flash('Comercio no encontrado', 'error')
        return redirect(url_for('control_comercial.index'))
    
    controles = service.listar_controles_comercio(comercio_id=comercio_id)
    
    return render_template(
        'control_comercial/ver.html',
        comercio=comercio,
        controles=controles
    )

@bp.route('/controlar/<int:comercio_id>', methods=['GET', 'POST'])
@login_required
@require_permission('CONTROL_COMERCIAL_CREATE')
def controlar(comercio_id):
    """Realizar un control a un comercio"""
    service = ControlComercialService()
    
    comercio = service.obtener_comercio_por_id(
        comercio_id=comercio_id,
        unidad_id=current_user.unidad_id
    )
    
    if not comercio:
        flash('Comercio no encontrado', 'error')
        return redirect(url_for('control_comercial.index'))
    
    if request.method == 'POST':
        try:
            resultado = service.crear_control(
                comercio_id=comercio_id,
                form_data=request.form,
                usuario_id=current_user.id,
                unidad_id=current_user.unidad_id
            )
            
            if resultado['success']:
                audit_log(
                    user_id=current_user.id,
                    action='CONTROL_COMERCIAL_CREATED',
                    details=f"Control en: {comercio.denominacion}"
                )
                flash('Control registrado correctamente', 'success')
                return redirect(url_for('control_comercial.ver', comercio_id=comercio_id))
            else:
                flash(resultado.get('error', 'Error al registrar control'), 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    datos_referencia = service.obtener_datos_referencia()
    
    return render_template(
        'control_comercial/controlar.html',
        comercio=comercio,
        datos_referencia=datos_referencia
    )

@bp.route('/alertas')
@login_required
@require_permission('CONTROL_COMERCIAL_VIEW')
def alertas():
    """Alertas de comercios (habilitaciones vencidas, etc.)"""
    service = ControlComercialService()
    
    alertas_data = service.obtener_alertas(unidad_id=current_user.unidad_id)
    
    return render_template('control_comercial/alertas.html', alertas=alertas_data)

@bp.route('/mapa')
@login_required
@require_permission('CONTROL_COMERCIAL_VIEW')
def mapa():
    """Mapa de comercios"""
    service = ControlComercialService()
    
    comercios = service.listar_comercios(unidad_id=current_user.unidad_id)
    
    return render_template('control_comercial/mapa.html', comercios=comercios)


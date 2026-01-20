"""
Rutas para el módulo de Intervenciones
Solo rutas, sin lógica de negocio (la lógica va en services)
"""
from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from . import bp
from ...services.intervenciones import IntervencionesService
from ...services.audit import audit_log
from ...services.rbac import require_permission

@bp.route('/identificacion-persona', methods=['GET', 'POST'])
@login_required
@require_permission('INTERVENCIONES_CREATE')
def identificacion_persona():
    """Formulario para identificación de personas"""
    service = IntervencionesService()
    
    if request.method == 'POST':
        try:
            resultado = service.crear_identificacion_persona(
                form_data=request.form,
                usuario_id=current_user.id,
                unidad_id=current_user.unidad_id
            )
            
            if resultado['success']:
                audit_log(
                    user_id=current_user.id,
                    action='IDENTIFICACION_PERSONA_CREATED',
                    details=f"Persona DNI: {resultado.get('dni')}"
                )
                flash('Identificación registrada correctamente', 'success')
                return redirect(url_for('intervenciones.identificacion_persona'))
            else:
                flash(resultado.get('error', 'Error al registrar identificación'), 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    # Obtener datos de referencia para el formulario
    datos_referencia = service.obtener_datos_referencia()
    
    return render_template(
        'intervenciones/identificacion_persona.html',
        datos_referencia=datos_referencia
    )

@bp.route('/control-vehicular', methods=['GET', 'POST'])
@login_required
@require_permission('INTERVENCIONES_CREATE')
def control_vehicular():
    """Formulario para control vehicular"""
    service = IntervencionesService()
    
    if request.method == 'POST':
        try:
            resultado = service.crear_control_vehicular(
                form_data=request.form,
                usuario_id=current_user.id,
                unidad_id=current_user.unidad_id
            )
            
            if resultado['success']:
                audit_log(
                    user_id=current_user.id,
                    action='CONTROL_VEHICULAR_CREATED',
                    details=f"Vehículo: {resultado.get('patente', 'N/A')}"
                )
                flash('Control vehicular registrado correctamente', 'success')
                return redirect(url_for('intervenciones.control_vehicular'))
            else:
                flash(resultado.get('error', 'Error al registrar control'), 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    # Obtener datos de referencia
    datos_referencia = service.obtener_datos_referencia_vehiculos()
    
    return render_template(
        'intervenciones/control_vehicular.html',
        datos_referencia=datos_referencia
    )

@bp.route('/listar', methods=['GET'])
@login_required
@require_permission('INTERVENCIONES_VIEW')
def listar():
    """Lista de intervenciones del usuario/unidad"""
    service = IntervencionesService()
    
    # Filtros
    tipo = request.args.get('tipo')
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    
    intervenciones = service.listar_intervenciones(
        unidad_id=current_user.unidad_id,
        usuario_id=current_user.id if not current_user.has_permission('INTERVENCIONES_VIEW_ALL') else None,
        tipo=tipo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta
    )
    
    return render_template('intervenciones/listar.html', intervenciones=intervenciones)

@bp.route('/ver/<int:intervencion_id>', methods=['GET'])
@login_required
@require_permission('INTERVENCIONES_VIEW')
def ver(intervencion_id):
    """Ver detalle de una intervención"""
    service = IntervencionesService()
    
    intervencion = service.obtener_intervencion_por_id(
        intervencion_id=intervencion_id,
        unidad_id=current_user.unidad_id
    )
    
    if not intervencion:
        flash('Intervención no encontrada', 'error')
        return redirect(url_for('intervenciones.listar'))
    
    return render_template('intervenciones/ver.html', intervencion=intervencion)


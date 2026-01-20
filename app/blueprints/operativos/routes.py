"""
Rutas para el módulo de Operativos Activos
"""
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp
from ...services.rbac import require_permission
from ...services.operativos import OperativosService


@bp.route('/iniciar', methods=['GET', 'POST'])
@login_required
@require_permission('OPERATIVOS_CREATE')
def iniciar():
    service = OperativosService()

    if request.method == 'POST':
        resultado = service.iniciar_operativo(
            usuario_id=current_user.id,
            tipo_operativo_id=request.form.get('tipo_operativo_id'),
            nombre_operativo=request.form.get('nombre_operativo'),
            descripcion=request.form.get('descripcion')
        )
        if resultado['success']:
            flash('Operativo iniciado correctamente.', 'success')
            return redirect(url_for('operativos.estado'))
        flash(resultado.get('error', 'Error al iniciar operativo'), 'error')

    tipos = service.obtener_tipos_operativo()
    return render_template('operativos/iniciar.html', tipos_operativos=tipos)


@bp.route('/estado')
@login_required
@require_permission('OPERATIVOS_VIEW')
def estado():
    service = OperativosService()
    operativo = service.obtener_operativo_activo(usuario_id=current_user.id)
    return render_template('operativos/estado.html', operativo=operativo)


@bp.route('/finalizar', methods=['POST'])
@login_required
@require_permission('OPERATIVOS_CREATE')
def finalizar():
    service = OperativosService()
    resultado = service.finalizar_operativo(usuario_id=current_user.id)
    if resultado['success']:
        flash('Operativo finalizado correctamente.', 'success')
    else:
        flash(resultado.get('error', 'Error al finalizar operativo'), 'error')
    return redirect(url_for('operativos.estado'))



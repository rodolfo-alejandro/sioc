"""
Rutas para el módulo de Relaciones
Vista general muy simple de relaciones entre personas.
"""
from flask import render_template
from flask_login import login_required
from . import bp
from ...services.rbac import require_permission
from ...models.relaciones import RelacionPersona


@bp.route('/')
@login_required
@require_permission('RELACIONES_VIEW')
def index():
    relaciones = RelacionPersona.query.order_by(
        RelacionPersona.fecha_deteccion.desc()
    ).limit(100).all()
    return render_template('relaciones/index.html', relaciones=relaciones)



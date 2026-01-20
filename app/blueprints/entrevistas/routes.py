"""
Rutas para el módulo de Entrevistas
Por ahora solo lista básica de entrevistas puerta a puerta.
"""
from flask import render_template
from flask_login import login_required
from . import bp
from ...services.rbac import require_permission
from ...models.entrevistas import EntrevistaPuertaPuerta


@bp.route('/')
@login_required
@require_permission('ENTREVISTAS_VIEW')
def index():
    entrevistas = EntrevistaPuertaPuerta.query.order_by(
        EntrevistaPuertaPuerta.fecha_entrevista.desc()
    ).limit(50).all()
    return render_template('entrevistas/index.html', entrevistas=entrevistas)



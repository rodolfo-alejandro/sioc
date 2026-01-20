"""
Rutas para el módulo de Grupos
Muestra una lista básica de grupos.
"""
from flask import render_template
from flask_login import login_required
from . import bp
from ...services.rbac import require_permission
from ...models.grupos import GrupoIntervencion


@bp.route('/')
@login_required
@require_permission('GRUPOS_VIEW')
def index():
    grupos = GrupoIntervencion.query.order_by(
        GrupoIntervencion.fecha_creacion.desc()
    ).limit(50).all()
    return render_template('grupos/index.html', grupos=grupos)



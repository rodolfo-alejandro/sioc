"""
Rutas Core (Dashboard)
"""
from flask import render_template
from flask_login import login_required, current_user
from app.blueprints.core import bp
from app.services.rbac import require_permission
from app.models.dataset import Dataset
from app.models.user import User


@bp.route('/')
@bp.route('/dashboard')
@login_required
@require_permission('CORE_VIEW')
def dashboard():
    """Dashboard principal"""
    # Obtener estadísticas
    datasets_count = 0
    users_count = 0
    
    if current_user.has_permission('DATALAB_VIEW'):
        datasets_count = Dataset.query.filter_by(unidad_id=current_user.unidad_id).count()
    
    if current_user.has_permission('ADMIN_USERS'):
        if current_user.has_role('SUPERADMIN'):
            users_count = User.query.filter_by(active=True).count()
        else:
            users_count = User.query.filter_by(unidad_id=current_user.unidad_id, active=True).count()
    
    return render_template('core/dashboard.html', 
                         datasets_count=datasets_count,
                         users_count=users_count)


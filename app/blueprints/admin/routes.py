"""
Rutas de Administración
"""
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.blueprints.admin import bp
from app.blueprints.admin.forms import UserForm
from app.blueprints.admin.services import create_user, update_user, reset_user_password
from app.services.rbac import require_permission
from app.models.user import User
from app.models.role import Role
from app.extensions import db


@bp.route('/users')
@login_required
@require_permission('ADMIN_USERS')
def users():
    """Lista de usuarios"""
    # Filtrar por unidad si no es superadmin
    query = User.query
    
    if not current_user.has_role('SUPERADMIN'):
        query = query.filter_by(unidad_id=current_user.unidad_id)
    
    # Búsqueda
    search = request.args.get('search', '')
    if search:
        query = query.filter(
            (User.username.contains(search)) |
            (User.email.contains(search))
        )
    
    users_list = query.order_by(User.created_at.desc()).all()
    
    return render_template('admin/users.html', users=users_list, search=search)


@bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@require_permission('ADMIN_USERS')
def user_new():
    """Crear nuevo usuario"""
    form = UserForm()
    
    # Si no es superadmin, solo puede crear en su unidad
    if not current_user.has_role('SUPERADMIN'):
        form.unidad_id.data = current_user.unidad_id
        form.unidad_id.render_kw = {'disabled': True}
    
    if form.validate_on_submit():
        password = form.password.data or 'TempPass123!'
        
        user, error = create_user(
            username=form.username.data,
            email=form.email.data,
            password=password,
            unidad_id=form.unidad_id.data,
            role_id=form.role_id.data,
            active=form.active.data,
            must_change_password=form.must_change_password.data
        )
        
        if user:
            flash(f'Usuario {user.username} creado correctamente', 'success')
            return redirect(url_for('admin.users'))
        else:
            flash(error, 'danger')
    
    return render_template('admin/user_form.html', form=form, user=None, action='Crear')


@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('ADMIN_USERS')
def user_edit(user_id):
    """Editar usuario"""
    user = User.query.get_or_404(user_id)
    
    # Verificar permisos de unidad
    if not current_user.has_role('SUPERADMIN') and user.unidad_id != current_user.unidad_id:
        flash('No tiene permisos para editar este usuario', 'danger')
        return redirect(url_for('admin.users'))
    
    form = UserForm(obj=user)
    
    # Pre-llenar rol
    if user.roles:
        form.role_id.data = user.roles[0].id
    
    # Si no es superadmin, no puede cambiar unidad
    if not current_user.has_role('SUPERADMIN'):
        form.unidad_id.render_kw = {'disabled': True}
    
    if form.validate_on_submit():
        user, error = update_user(
            user_id=user.id,
            username=form.username.data,
            email=form.email.data,
            unidad_id=form.unidad_id.data,
            role_id=form.role_id.data,
            active=form.active.data,
            must_change_password=form.must_change_password.data
        )
        
        if user:
            flash(f'Usuario {user.username} actualizado correctamente', 'success')
            return redirect(url_for('admin.users'))
        else:
            flash(error, 'danger')
    
    return render_template('admin/user_form.html', form=form, user=user, action='Editar')


@bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@require_permission('ADMIN_USERS')
def user_toggle_active(user_id):
    """Activar/desactivar usuario"""
    user = User.query.get_or_404(user_id)
    
    # Verificar permisos
    if not current_user.has_role('SUPERADMIN') and user.unidad_id != current_user.unidad_id:
        return jsonify({'success': False, 'message': 'Sin permisos'}), 403
    
    user.active = not user.active
    db.session.commit()
    
    status = 'activado' if user.active else 'desactivado'
    flash(f'Usuario {status} correctamente', 'success')
    
    return jsonify({'success': True, 'active': user.active})


@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@require_permission('ADMIN_USERS')
def user_reset_password(user_id):
    """Resetear contraseña de usuario"""
    user = User.query.get_or_404(user_id)
    
    # Verificar permisos
    if not current_user.has_role('SUPERADMIN') and user.unidad_id != current_user.unidad_id:
        return jsonify({'success': False, 'message': 'Sin permisos'}), 403
    
    user, error = reset_user_password(user_id)
    
    if user:
        flash(f'Contraseña de {user.username} reseteada. Debe cambiar al iniciar sesión.', 'success')
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': error}), 400


@bp.route('/roles')
@login_required
@require_permission('ADMIN_USERS')
def roles():
    """Lista de roles (básico)"""
    roles_list = Role.query.order_by(Role.name).all()
    return render_template('admin/roles.html', roles=roles_list)


"""
Rutas de Administración
"""
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.blueprints.admin import bp
from app.blueprints.admin.forms import UserForm, UnidadForm
from app.blueprints.admin.services import create_user, update_user, reset_user_password
from app.services.rbac import require_permission
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.unidad import Unidad
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
        unidad_id = form.unidad_id.data
        if not current_user.has_role('SUPERADMIN'):
            unidad_id = current_user.unidad_id
        password = form.password.data or 'TempPass123!'
        
        user, error = create_user(
            username=form.username.data,
            email=form.email.data,
            password=password,
            unidad_id=unidad_id,
            role_id=form.role_id.data,
            active=form.active.data,
            must_change_password=form.must_change_password.data
        )
        
        if user:
            # Actualizar permisos adicionales del usuario
            selected_ids = form.permissions.data or []
            user.extra_permissions.clear()
            if selected_ids:
                perms = Permission.query.filter(Permission.id.in_(selected_ids)).all()
                for perm in perms:
                    user.extra_permissions.append(perm)
            db.session.commit()

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
    
    # Pre-llenar rol/permisos solo al abrir formulario (no pisar datos enviados por POST)
    if request.method == 'GET':
        if user.roles:
            form.role_id.data = user.roles[0].id
        form.permissions.data = [p.id for p in user.extra_permissions]
    
    # Si no es superadmin, no puede cambiar unidad
    if not current_user.has_role('SUPERADMIN'):
        form.unidad_id.render_kw = {'disabled': True}
    
    if form.validate_on_submit():
        unidad_id = form.unidad_id.data
        if not current_user.has_role('SUPERADMIN'):
            unidad_id = user.unidad_id
        user, error = update_user(
            user_id=user.id,
            username=form.username.data,
            email=form.email.data,
            unidad_id=unidad_id,
            role_id=form.role_id.data,
            active=form.active.data,
            must_change_password=form.must_change_password.data
        )
        
        if user:
            # Actualizar permisos adicionales del usuario
            selected_ids = form.permissions.data or []
            user.extra_permissions.clear()
            if selected_ids:
                perms = Permission.query.filter(Permission.id.in_(selected_ids)).all()
                for perm in perms:
                    user.extra_permissions.append(perm)
            db.session.commit()

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
    
    user, temp_password, error = reset_user_password(user_id)

    if user:
        flash(f'Contraseña de {user.username} reseteada. Debe cambiar al iniciar sesión.', 'success')
        return jsonify({'success': True, 'password': temp_password})
    else:
        return jsonify({'success': False, 'message': error}), 400


@bp.route('/roles')
@login_required
@require_permission('ADMIN_USERS')
def roles():
    """Lista de roles (básico)"""
    roles_list = Role.query.order_by(Role.name).all()
    return render_template('admin/roles.html', roles=roles_list)


@bp.route('/unidades')
@login_required
@require_permission('ADMIN_USERS')
def unidades():
    """Lista de dependencias/unidades."""
    search = (request.args.get('search') or '').strip()
    query = Unidad.query
    if search:
        query = query.filter(Unidad.nombre.contains(search))
    unidades_list = query.order_by(Unidad.nombre.asc()).all()
    return render_template('admin/unidades.html', unidades=unidades_list, search=search)


@bp.route('/unidades/new', methods=['GET', 'POST'])
@login_required
@require_permission('ADMIN_USERS')
def unidad_new():
    """Crear dependencia/unidad."""
    form = UnidadForm()
    if form.validate_on_submit():
        nombre = (form.nombre.data or '').strip()
        existente = Unidad.query.filter(db.func.lower(Unidad.nombre) == nombre.lower()).first()
        if existente:
            flash('Ya existe una dependencia con ese nombre', 'danger')
        else:
            unidad = Unidad(nombre=nombre, activo=form.activo.data)
            db.session.add(unidad)
            db.session.commit()
            flash('Dependencia creada correctamente', 'success')
            return redirect(url_for('admin.unidades'))
    return render_template('admin/unidad_form.html', form=form, unidad=None, action='Crear')


@bp.route('/unidades/<int:unidad_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('ADMIN_USERS')
def unidad_edit(unidad_id):
    """Editar dependencia/unidad."""
    unidad = Unidad.query.get_or_404(unidad_id)
    form = UnidadForm(obj=unidad)
    if form.validate_on_submit():
        nombre = (form.nombre.data or '').strip()
        existente = Unidad.query.filter(
            db.func.lower(Unidad.nombre) == nombre.lower(),
            Unidad.id != unidad.id
        ).first()
        if existente:
            flash('Ya existe otra dependencia con ese nombre', 'danger')
        else:
            unidad.nombre = nombre
            unidad.activo = form.activo.data
            db.session.commit()
            flash('Dependencia actualizada correctamente', 'success')
            return redirect(url_for('admin.unidades'))
    return render_template('admin/unidad_form.html', form=form, unidad=unidad, action='Editar')


@bp.route('/unidades/<int:unidad_id>/toggle-active', methods=['POST'])
@login_required
@require_permission('ADMIN_USERS')
def unidad_toggle_active(unidad_id):
    """Activar/desactivar dependencia."""
    unidad = Unidad.query.get_or_404(unidad_id)
    unidad.activo = not unidad.activo
    db.session.commit()
    return jsonify({'success': True, 'active': unidad.activo})


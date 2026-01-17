"""
Rutas de Autenticación
"""
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user, login_required
from app.blueprints.auth import bp
from app.blueprints.auth.forms import LoginForm, ChangePasswordForm
from app.blueprints.auth.services import authenticate_user, logout_current_user, change_user_password


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login"""
    if current_user.is_authenticated:
        return redirect(url_for('core.dashboard'))
    
    form = LoginForm()
    
    if form.validate_on_submit():
        user, error = authenticate_user(
            form.username.data,
            form.password.data,
            remember=form.remember_me.data
        )
        
        if user:
            # Si debe cambiar contraseña, redirigir
            if user.must_change_password:
                flash('Debe cambiar su contraseña antes de continuar', 'warning')
                return redirect(url_for('auth.change_password'))
            
            # Redirigir a la página solicitada o dashboard
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('core.dashboard'))
        else:
            flash(error, 'danger')
    
    return render_template('auth/login.html', form=form)


@bp.route('/logout')
@login_required
def logout():
    """Cerrar sesión"""
    logout_current_user()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Cambiar contraseña"""
    form = ChangePasswordForm()
    
    if form.validate_on_submit():
        success, error = change_user_password(
            current_user,
            form.current_password.data,
            form.new_password.data
        )
        
        if success:
            flash('Contraseña cambiada correctamente', 'success')
            return redirect(url_for('core.dashboard'))
        else:
            flash(error, 'danger')
    
    return render_template('auth/change_password.html', form=form)


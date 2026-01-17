"""
Servicios de Autenticación
"""
from datetime import datetime
from flask_login import login_user, logout_user
from app.extensions import db
from app.models.user import User
from app.services.audit import audit_log


def authenticate_user(username, password, remember=False):
    """
    Autentica un usuario.
    
    Returns:
        tuple: (user, error_message)
    """
    user = User.query.filter_by(username=username).first()
    
    if not user:
        return None, "Usuario o contraseña incorrectos"
    
    if not user.active:
        return None, "Usuario inactivo. Contacte al administrador"
    
    if not user.check_password(password):
        return None, "Usuario o contraseña incorrectos"
    
    # Actualizar último login
    user.last_login_at = datetime.utcnow()
    db.session.commit()
    
    # Login
    login_user(user, remember=remember)
    
    # Auditoría
    audit_log('LOGIN', f'Usuario {username} inició sesión')
    
    return user, None


def logout_current_user():
    """Cierra sesión del usuario actual"""
    username = None
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            username = current_user.username
    except:
        pass
    
    logout_user()
    
    if username:
        audit_log('LOGOUT', f'Usuario {username} cerró sesión')


def change_user_password(user, current_password, new_password):
    """
    Cambia la contraseña de un usuario.
    
    Returns:
        tuple: (success, error_message)
    """
    if not user.check_password(current_password):
        return False, "Contraseña actual incorrecta"
    
    user.set_password(new_password)
    user.must_change_password = False
    db.session.commit()
    
    audit_log('PASSWORD_CHANGED', f'Usuario {user.username} cambió su contraseña')
    
    return True, None


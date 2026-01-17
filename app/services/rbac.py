"""
Servicios de RBAC (Role-Based Access Control)
"""
from functools import wraps
from flask import abort, current_app
from flask_login import current_user


def require_login(f):
    """Decorator que requiere que el usuario esté autenticado"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        return f(*args, **kwargs)
    return decorated_function


def require_permission(permission_code):
    """
    Decorator que requiere que el usuario tenga un permiso específico.
    
    Uso:
        @require_permission('DATALAB_UPLOAD')
        def upload_dataset():
            ...
    """
    def decorator(f):
        @wraps(f)
        @require_login
        def decorated_function(*args, **kwargs):
            if not current_user.has_permission(permission_code):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_role(role_name):
    """
    Decorator que requiere que el usuario tenga un rol específico.
    
    Uso:
        @require_role('SUPERADMIN')
        def admin_function():
            ...
    """
    def decorator(f):
        @wraps(f)
        @require_login
        def decorated_function(*args, **kwargs):
            if not current_user.has_role(role_name):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


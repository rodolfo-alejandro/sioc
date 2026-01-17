"""
Servicios de Administración
"""
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.unidad import Unidad
from app.services.audit import audit_log


def create_user(username, email, password, unidad_id, role_id, active=True, must_change_password=False):
    """
    Crea un nuevo usuario.
    
    Returns:
        tuple: (user, error_message)
    """
    # Verificar usuario único
    if User.query.filter_by(username=username).first():
        return None, "El nombre de usuario ya existe"
    
    if User.query.filter_by(email=email).first():
        return None, "El email ya está registrado"
    
    # Verificar unidad
    unidad = Unidad.query.get(unidad_id)
    if not unidad:
        return None, "Unidad no válida"
    
    # Verificar rol
    role = Role.query.get(role_id)
    if not role:
        return None, "Rol no válido"
    
    # Crear usuario
    user = User(
        username=username,
        email=email,
        unidad_id=unidad_id,
        active=active,
        must_change_password=must_change_password
    )
    user.set_password(password)
    user.roles.append(role)
    
    db.session.add(user)
    db.session.commit()
    
    audit_log('USER_CREATED', f'Usuario {username} creado')
    
    return user, None


def update_user(user_id, username=None, email=None, unidad_id=None, role_id=None, 
                active=None, must_change_password=None):
    """
    Actualiza un usuario existente.
    
    Returns:
        tuple: (user, error_message)
    """
    user = User.query.get(user_id)
    if not user:
        return None, "Usuario no encontrado"
    
    if username and username != user.username:
        if User.query.filter_by(username=username).first():
            return None, "El nombre de usuario ya existe"
        user.username = username
    
    if email and email != user.email:
        if User.query.filter_by(email=email).first():
            return None, "El email ya está registrado"
        user.email = email
    
    if unidad_id:
        unidad = Unidad.query.get(unidad_id)
        if not unidad:
            return None, "Unidad no válida"
        user.unidad_id = unidad_id
    
    if role_id:
        role = Role.query.get(role_id)
        if not role:
            return None, "Rol no válido"
        # Reemplazar roles (para simplificar, un usuario tiene un rol principal)
        user.roles.clear()
        user.roles.append(role)
    
    if active is not None:
        user.active = active
    
    if must_change_password is not None:
        user.must_change_password = must_change_password
    
    db.session.commit()
    
    audit_log('USER_UPDATED', f'Usuario {user.username} actualizado')
    
    return user, None


def reset_user_password(user_id, new_password=None):
    """
    Resetea la contraseña de un usuario.
    
    Returns:
        tuple: (user, error_message)
    """
    user = User.query.get(user_id)
    if not user:
        return None, "Usuario no encontrado"
    
    if new_password:
        user.set_password(new_password)
    else:
        # Contraseña por defecto
        user.set_password('TempPass123!')
    
    user.must_change_password = True
    db.session.commit()
    
    audit_log('PASSWORD_RESET', f'Contraseña de usuario {user.username} reseteada')
    
    return user, None


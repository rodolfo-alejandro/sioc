"""
Modelo de Usuario
"""
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


# Tabla de asociación muchos a muchos: usuarios y roles
user_roles = db.Table(
    'user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    """Modelo de usuario con autenticación y RBAC"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    
    # Relaciones
    roles = db.relationship('Role', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))
    audit_logs = db.relationship('AuditLog', backref='user', lazy='dynamic')
    datasets = db.relationship('Dataset', backref='user', lazy='dynamic')
    
    def set_password(self, password):
        """Genera hash de la contraseña"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verifica la contraseña"""
        return check_password_hash(self.password_hash, password)
    
    def has_permission(self, permission_code):
        """Verifica si el usuario tiene un permiso específico"""
        # Si es superadmin, tiene todos los permisos
        if self.has_role('SUPERADMIN'):
            return True
        
        for role in self.roles:
            if role.has_permission(permission_code):
                return True
        return False
    
    def has_role(self, role_name):
        """Verifica si el usuario tiene un rol específico"""
        return any(role.name == role_name for role in self.roles)
    
    def get_permissions(self):
        """Obtiene todos los permisos del usuario"""
        permissions = set()
        for role in self.roles:
            for perm in role.permissions:
                permissions.add(perm.code)
        return permissions
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'active': self.active,
            'unidad_id': self.unidad_id,
            'roles': [role.name for role in self.roles],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None
        }


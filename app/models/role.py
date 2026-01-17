"""
Modelo de Rol
"""
from app.extensions import db


# Tabla de asociación muchos a muchos: roles y permisos
role_permissions = db.Table(
    'role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'), primary_key=True)
)


class Role(db.Model):
    """Modelo de rol para RBAC"""
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)
    
    # Relaciones
    permissions = db.relationship(
        'Permission', 
        secondary=role_permissions, 
        backref=db.backref('roles', lazy='dynamic')
    )
    
    def has_permission(self, permission_code):
        """Verifica si el rol tiene un permiso específico"""
        return any(perm.code == permission_code for perm in self.permissions)
    
    def __repr__(self):
        return f'<Role {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'permissions': [perm.code for perm in self.permissions]
        }


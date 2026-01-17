"""
Modelo de Permiso
"""
from app.extensions import db


class Permission(db.Model):
    """Modelo de permiso para RBAC"""
    __tablename__ = 'permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)
    
    def __repr__(self):
        return f'<Permission {self.code}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'description': self.description
        }


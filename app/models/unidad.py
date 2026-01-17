"""
Modelo de Unidad Organizacional
"""
from datetime import datetime
from app.extensions import db


class Unidad(db.Model):
    """Representa una unidad organizacional (Dirección General / Unidad / Área)"""
    __tablename__ = 'unidades'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    users = db.relationship('User', backref='unidad', lazy='dynamic')
    datasets = db.relationship('Dataset', backref='unidad', lazy='dynamic')
    
    def __repr__(self):
        return f'<Unidad {self.nombre}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'activo': self.activo,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


"""
Modelo de Ubicación
Representa una ubicación geográfica (coordenadas)
"""
from datetime import datetime
from ..database.db import db

class Ubicacion(db.Model):
    __tablename__ = 'ubicaciones'
    
    id = db.Column(db.Integer, primary_key=True)
    latitud = db.Column(db.Float, nullable=False)
    longitud = db.Column(db.Float, nullable=False)
    barrio_id = db.Column(db.Integer, db.ForeignKey('barrios.id'), nullable=True)
    direccion = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    barrio = db.relationship('Barrio', backref='ubicaciones')
    
    def __repr__(self):
        return f'<Ubicacion ({self.latitud}, {self.longitud})>'


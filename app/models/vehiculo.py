"""
Modelo de Vehículo
Representa un vehículo en el sistema
"""
from datetime import datetime
from ..database.db import db

class Vehiculo(db.Model):
    __tablename__ = 'vehiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    patente = db.Column(db.String(10), unique=True, nullable=False, index=True)
    marca_id = db.Column(db.Integer, db.ForeignKey('marcas_vehiculos.id'), nullable=True)
    modelo_id = db.Column(db.Integer, db.ForeignKey('modelos_vehiculos.id'), nullable=True)
    color_id = db.Column(db.Integer, db.ForeignKey('colores_vehiculos.id'), nullable=True)
    tipo_vehiculo_id = db.Column(db.Integer, db.ForeignKey('tipos_vehiculos.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    marca = db.relationship('MarcaVehiculo', backref='vehiculos')
    modelo = db.relationship('ModeloVehiculo', backref='vehiculos')
    color = db.relationship('ColorVehiculo', backref='vehiculos')
    tipo_vehiculo = db.relationship('TipoVehiculo', backref='vehiculos')
    
    def __repr__(self):
        return f'<Vehiculo {self.patente}>'


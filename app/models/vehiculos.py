"""
Modelos de Referencias de Vehículos
MarcaVehiculo, ModeloVehiculo, ColorVehiculo, TipoVehiculo
"""
from datetime import datetime
from ..database.db import db

class MarcaVehiculo(db.Model):
    __tablename__ = 'marcas_vehiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<MarcaVehiculo {self.nombre}>'

class ModeloVehiculo(db.Model):
    __tablename__ = 'modelos_vehiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    marca_id = db.Column(db.Integer, db.ForeignKey('marcas_vehiculos.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación
    marca = db.relationship('MarcaVehiculo', backref='modelos')
    
    # Índice único compuesto
    __table_args__ = (db.UniqueConstraint('marca_id', 'nombre', name='uq_marca_modelo'),)
    
    def __repr__(self):
        return f'<ModeloVehiculo {self.nombre}>'

class ColorVehiculo(db.Model):
    __tablename__ = 'colores_vehiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ColorVehiculo {self.nombre}>'

class TipoVehiculo(db.Model):
    __tablename__ = 'tipos_vehiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TipoVehiculo {self.nombre}>'


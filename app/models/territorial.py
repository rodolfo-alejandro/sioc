"""
Modelos Territoriales
Barrio, Comisaria, Jerarquia
"""
from datetime import datetime
from ..database.db import db

class Barrio(db.Model):
    __tablename__ = 'barrios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Barrio {self.nombre}>'

class Comisaria(db.Model):
    __tablename__ = 'comisarias'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Comisaria {self.nombre}>'

class Jerarquia(db.Model):
    __tablename__ = 'jerarquias'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    orden = db.Column(db.Integer, nullable=True)  # Para ordenar jerarquías
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Jerarquia {self.nombre}>'


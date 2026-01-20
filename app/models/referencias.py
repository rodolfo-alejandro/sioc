"""
Modelos de Referencias
Tablas de referencia para datos comunes (Sexo, Nacionalidad, EstadoCivil, etc.)
"""
from datetime import datetime
from ..database.db import db

class Sexo(db.Model):
    __tablename__ = 'sexos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Sexo {self.nombre}>'

class Nacionalidad(db.Model):
    __tablename__ = 'nacionalidades'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    codigo = db.Column(db.String(3), nullable=True)  # ISO code
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Nacionalidad {self.nombre}>'

class EstadoCivil(db.Model):
    __tablename__ = 'estados_civiles'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<EstadoCivil {self.nombre}>'

class Ocupacion(db.Model):
    __tablename__ = 'ocupaciones'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Ocupacion {self.nombre}>'

class TipoContactoEmergencia(db.Model):
    __tablename__ = 'tipos_contacto_emergencia'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TipoContactoEmergencia {self.nombre}>'


"""
Modelo de Persona
Representa una persona física en el sistema
"""
from datetime import datetime
from ..database.db import db

class Persona(db.Model):
    __tablename__ = 'personas'
    
    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(20), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    fecha_nacimiento = db.Column(db.Date, nullable=True)
    sexo_id = db.Column(db.Integer, db.ForeignKey('sexos.id'), nullable=True)
    nacionalidad_id = db.Column(db.Integer, db.ForeignKey('nacionalidades.id'), nullable=True, default=1)
    estado_civil_id = db.Column(db.Integer, db.ForeignKey('estados_civiles.id'), nullable=True)
    ocupacion_id = db.Column(db.Integer, db.ForeignKey('ocupaciones.id'), nullable=True)
    direccion = db.Column(db.String(200), nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    contacto_emergencia_nombre = db.Column(db.String(100), nullable=True)
    contacto_emergencia_telefono = db.Column(db.String(20), nullable=True)
    contacto_emergencia_relacion_id = db.Column(db.Integer, db.ForeignKey('tipos_contacto_emergencia.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    sexo = db.relationship('Sexo', backref='personas')
    nacionalidad = db.relationship('Nacionalidad', backref='personas')
    estado_civil = db.relationship('EstadoCivil', backref='personas')
    ocupacion = db.relationship('Ocupacion', backref='personas')
    contacto_emergencia_relacion = db.relationship('TipoContactoEmergencia', backref='personas')
    
    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"
    
    def __repr__(self):
        return f'<Persona {self.dni}: {self.nombre_completo}>'


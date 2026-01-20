"""
Modelos para Relaciones entre personas y organizaciones
"""
from datetime import datetime
from ..database.db import db


class RelacionPersona(db.Model):
    __tablename__ = 'relaciones_personas'

    id = db.Column(db.Integer, primary_key=True)
    persona1_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=False)
    persona2_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=False)
    tipo_relacion = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    confianza = db.Column(db.Integer)
    fecha_deteccion = db.Column(db.DateTime, default=datetime.utcnow)
    fuente_deteccion = db.Column(db.String(200))
    activa = db.Column(db.Boolean, default=True)

    persona1 = db.relationship('Persona', foreign_keys=[persona1_id], backref='relaciones_como_persona1')
    persona2 = db.relationship('Persona', foreign_keys=[persona2_id], backref='relaciones_como_persona2')

    def __repr__(self) -> str:
        return f'<RelacionPersona {self.persona1_id} - {self.persona2_id}: {self.tipo_relacion}>'


class OrganizacionCriminal(db.Model):
    __tablename__ = 'organizaciones_criminales'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    tipo_organizacion = db.Column(db.String(100))
    nivel_peligrosidad = db.Column(db.Integer)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    activa = db.Column(db.Boolean, default=True)

    def __repr__(self) -> str:
        return f'<OrganizacionCriminal {self.nombre}>'


class PersonaOrganizacion(db.Model):
    __tablename__ = 'personas_organizaciones'

    id = db.Column(db.Integer, primary_key=True)
    persona_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=False)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones_criminales.id'), nullable=False)
    rol_en_organizacion = db.Column(db.String(100))
    nivel_implicacion = db.Column(db.Integer)
    fecha_vinculacion = db.Column(db.DateTime, default=datetime.utcnow)
    activa = db.Column(db.Boolean, default=True)

    persona = db.relationship('Persona', backref='organizaciones_persona')
    organizacion = db.relationship('OrganizacionCriminal', backref='personas_organizacion')

    def __repr__(self) -> str:
        return f'<PersonaOrganizacion {self.persona_id} - {self.organizacion_id}>'



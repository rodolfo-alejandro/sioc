"""
Modelos para Grupos de Intervención
"""
from datetime import datetime
from ..database.db import db


class GrupoIntervencion(db.Model):
    __tablename__ = 'grupos_intervenciones'

    id = db.Column(db.Integer, primary_key=True)
    intervencion_id = db.Column(db.Integer, db.ForeignKey('intervenciones.id'), nullable=False)
    nombre_grupo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)

    intervencion = db.relationship('Intervencion', backref='grupos')

    def __repr__(self) -> str:
        return f'<GrupoIntervencion {self.nombre_grupo}>'


class PersonaGrupo(db.Model):
    __tablename__ = 'personas_grupos'

    id = db.Column(db.Integer, primary_key=True)
    persona_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=False)
    grupo_id = db.Column(db.Integer, db.ForeignKey('grupos_intervenciones.id'), nullable=False)
    rol_en_grupo = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    fecha_vinculacion = db.Column(db.DateTime, default=datetime.utcnow)

    persona = db.relationship('Persona', backref='grupos_personas')
    grupo = db.relationship('GrupoIntervencion', backref='personas_grupo')

    def __repr__(self) -> str:
        return f'<PersonaGrupo {self.persona_id} - {self.grupo_id}>'



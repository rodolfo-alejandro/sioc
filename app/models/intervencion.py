"""
Modelo de Intervención
Representa cualquier tipo de intervención policial (identificación, control vehicular, etc.)
"""
from datetime import datetime
from ..database.db import db

class Intervencion(db.Model):
    __tablename__ = 'intervenciones'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo_intervencion = db.Column(db.String(100), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    persona_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculos.id'), nullable=True)
    ubicacion_id = db.Column(db.Integer, db.ForeignKey('ubicaciones.id'), nullable=True)
    fecha_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    observaciones = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    usuario = db.relationship('User', backref='intervenciones')
    unidad = db.relationship('Unidad', backref='intervenciones')
    persona = db.relationship('Persona', backref='intervenciones')
    vehiculo = db.relationship('Vehiculo', backref='intervenciones')
    ubicacion = db.relationship('Ubicacion', backref='intervenciones')
    
    def __repr__(self):
        return f'<Intervencion {self.tipo_intervencion} - {self.fecha_hora}>'


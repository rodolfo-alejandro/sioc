"""
Modelos para Operativos y Operativos Activos
"""
from datetime import datetime
from ..database.db import db


class TipoOperativo(db.Model):
    __tablename__ = 'tipos_operativos'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    descripcion = db.Column(db.String(255))
    activo = db.Column(db.Boolean, default=True)

    def __repr__(self) -> str:
        return f'<TipoOperativo {self.nombre}>'


class OperativoActivo(db.Model):
    __tablename__ = 'operativos_activos'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tipo_operativo_id = db.Column(db.Integer, db.ForeignKey('tipos_operativos.id'), nullable=False)
    nombre_operativo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    fecha_inicio = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_fin = db.Column(db.DateTime)
    activo = db.Column(db.Boolean, default=True)

    usuario = db.relationship('User', backref='operativos_activos')
    tipo_operativo = db.relationship('TipoOperativo', backref='operativos_activos')

    def __repr__(self) -> str:
        return f'<OperativoActivo {self.nombre_operativo}>'



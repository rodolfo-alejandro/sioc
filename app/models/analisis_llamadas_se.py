"""
Modelo para análisis de llamadas SE 2026.
"""
from datetime import datetime

from app.extensions import db


class LlamadaSE(db.Model):
    __tablename__ = "analisis_llamadas_se"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    fecha_importacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)

    llamada_fecha = db.Column(db.DateTime, nullable=True, index=True)
    llamada_alerta_id = db.Column(db.Integer, nullable=True, index=True)
    llamada_alerta_desc = db.Column(db.String(255), nullable=True, index=True)
    llamada_coordx = db.Column(db.Float, nullable=True, index=True)
    llamada_coordy = db.Column(db.Float, nullable=True, index=True)
    llamada_detalle = db.Column(db.Text, nullable=True)
    llamada_dep_id = db.Column(db.Integer, nullable=True, index=True)
    llamada_dep_nombre = db.Column(db.String(255), nullable=True, index=True)
    llamada_barrio_id = db.Column(db.Integer, nullable=True, index=True)
    llamada_barrio_nombre = db.Column(db.String(255), nullable=True, index=True)
    llamada_local_id = db.Column(db.Integer, nullable=True, index=True)
    llamada_local_nombre = db.Column(db.String(255), nullable=True, index=True)
    llamada_jurisdiccion = db.Column(db.String(255), nullable=True, index=True)
    llamada_mes = db.Column(db.String(50), nullable=True, index=True)
    llamada_semana = db.Column(db.String(20), nullable=True, index=True)
    llamada_dia_semana = db.Column(db.String(50), nullable=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    unidad = db.relationship("Unidad", backref="analisis_llamadas_se")
    usuario_creador = db.relationship("User", backref="analisis_llamadas_se")


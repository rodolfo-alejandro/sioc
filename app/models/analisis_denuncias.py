"""
Modelo para denuncias web de drogas.
"""
from datetime import datetime

from app.extensions import db


class DenunciaWeb(db.Model):
    __tablename__ = "analisis_denuncias_web"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    fecha_importacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)

    causas_id = db.Column(db.String(80), nullable=False, index=True)
    nro_actuacion = db.Column(db.String(80), nullable=True, index=True)
    anio_actuacion = db.Column(db.Integer, nullable=True, index=True)
    fecha_denuncia = db.Column(db.DateTime, nullable=True, index=True)

    id_dep_registro = db.Column(db.String(80), nullable=True)
    desc_dep_registro = db.Column(db.String(255), nullable=True, index=True)
    id_dep_padre = db.Column(db.String(80), nullable=True)
    desc_dep_padre = db.Column(db.String(255), nullable=True)
    id_dep_actuario = db.Column(db.String(80), nullable=True)
    desc_dep_actuario = db.Column(db.String(255), nullable=True, index=True)

    actuario_grado = db.Column(db.String(120), nullable=True)
    actuario_apenom = db.Column(db.String(255), nullable=True, index=True)
    fecha_recepcion = db.Column(db.DateTime, nullable=True)
    causa_estado = db.Column(db.String(120), nullable=True, index=True)
    fecha_apertura = db.Column(db.DateTime, nullable=True)
    fecha_desestimada = db.Column(db.DateTime, nullable=True, index=True)
    fecha_sol_allanamiento = db.Column(db.DateTime, nullable=True, index=True)

    relato = db.Column(db.Text, nullable=True)
    relato_original = db.Column(db.Text, nullable=True)
    localidad = db.Column(db.String(120), nullable=True, index=True)
    barrio = db.Column(db.String(120), nullable=True, index=True)
    coord = db.Column(db.String(120), nullable=True)
    latitud = db.Column(db.Float, nullable=True, index=True)
    longitud = db.Column(db.Float, nullable=True, index=True)
    investigados = db.Column(db.Text, nullable=True)
    observacion_interna = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    unidad = db.relationship("Unidad", backref="analisis_denuncias")
    usuario_creador = db.relationship("User", backref="analisis_denuncias")

    __table_args__ = (
        db.UniqueConstraint("unidad_id", "causas_id", name="uq_analisis_denuncias_unidad_causa"),
        db.Index("ix_analisis_denuncias_lat_lon", "latitud", "longitud"),
    )


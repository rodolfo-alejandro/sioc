"""
Modelo para análisis anual de intervenciones de drogas.
"""
from datetime import datetime

from app.extensions import db


class AnalisisIntervencion(db.Model):
    __tablename__ = "analisis_intervenciones"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    fecha_importacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)

    anio = db.Column(db.Integer, nullable=False, index=True)
    causas_id = db.Column(db.Integer, nullable=True, index=True)
    causas_interv_id = db.Column(db.Integer, nullable=False, index=True)

    tipo_interv_desc = db.Column(db.String(80), nullable=True, index=True)
    causa_escala = db.Column(db.String(80), nullable=True, index=True)
    causa_actividad = db.Column(db.String(80), nullable=True, index=True)
    tipo_operativo = db.Column(db.String(120), nullable=True, index=True)

    barrios_id = db.Column(db.Integer, nullable=True, index=True)
    barrios_nombre = db.Column(db.String(255), nullable=True, index=True)
    localidad_nombre = db.Column(db.String(120), nullable=True, index=True)
    zona = db.Column(db.String(255), nullable=True, index=True)
    coordx = db.Column(db.Float, nullable=True, index=True)
    coordy = db.Column(db.Float, nullable=True, index=True)

    interv_fecha = db.Column(db.Date, nullable=True, index=True)
    interv_hora = db.Column(db.Time, nullable=True, index=True)
    interv_dia_semana = db.Column(db.String(30), nullable=True, index=True)
    interv_mes = db.Column(db.String(30), nullable=True, index=True)
    interv_mes_num = db.Column(db.Integer, nullable=True, index=True)
    interv_trimestre = db.Column(db.Integer, nullable=True, index=True)

    pers_interviniente = db.Column(db.String(255), nullable=True)
    dep_interviniente = db.Column(db.String(255), nullable=True, index=True)
    distrito = db.Column(db.String(255), nullable=True, index=True)
    dep_policial = db.Column(db.String(255), nullable=True, index=True)
    departamento_operativo = db.Column(db.String(64), nullable=True, index=True)

    secuestro_marihuana = db.Column(db.Float, nullable=False, default=0)
    secuestro_cocaina = db.Column(db.Float, nullable=False, default=0)
    secuestro_dosis = db.Column(db.Float, nullable=False, default=0)
    secuestro_plantas = db.Column(db.Float, nullable=False, default=0)
    secuestro_plantines = db.Column(db.Float, nullable=False, default=0)
    secuestro_semillas = db.Column(db.Float, nullable=False, default=0)
    pesos_arg = db.Column(db.Float, nullable=False, default=0)
    dolares = db.Column(db.Float, nullable=False, default=0)
    euro = db.Column(db.Float, nullable=False, default=0)
    reales = db.Column(db.Float, nullable=False, default=0)
    bolivianos = db.Column(db.Float, nullable=False, default=0)
    hojas_coca = db.Column(db.Float, nullable=False, default=0)

    det_hombre_may = db.Column(db.Integer, nullable=False, default=0)
    det_hombre_men = db.Column(db.Integer, nullable=False, default=0)
    det_mujer_may = db.Column(db.Integer, nullable=False, default=0)
    det_mujer_men = db.Column(db.Integer, nullable=False, default=0)
    is_hombre_may = db.Column(db.Integer, nullable=False, default=0)
    is_hombre_men = db.Column(db.Integer, nullable=False, default=0)
    is_mujer_may = db.Column(db.Integer, nullable=False, default=0)
    is_mujer_men = db.Column(db.Integer, nullable=False, default=0)

    us_carga = db.Column(db.String(120), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    unidad = db.relationship("Unidad", backref="analisis_intervenciones")
    usuario_creador = db.relationship("User", backref="analisis_intervenciones")

    __table_args__ = (
        db.UniqueConstraint("unidad_id", "causas_interv_id", name="uq_analisis_intervenciones_unidad_causas_interv"),
        db.Index("ix_analisis_intervenciones_lat_lon", "coordx", "coordy"),
    )

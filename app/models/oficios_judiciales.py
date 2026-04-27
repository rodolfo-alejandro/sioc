"""
Modelos para carga inteligente de oficios judiciales.
"""
from datetime import datetime

from app.extensions import db


class ConsignaJudicial(db.Model):
    __tablename__ = "oficios_consignas"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    expediente = db.Column(db.String(120), nullable=True, index=True)
    juzgado = db.Column(db.String(255), nullable=True, index=True)
    caratula = db.Column(db.Text, nullable=True)
    tipo_medida = db.Column(db.String(80), nullable=True, index=True)
    tipo_consigna = db.Column(db.String(30), nullable=True, index=True)  # fija | ambulatoria | personalizada | indeterminada
    fecha_oficio = db.Column(db.Date, nullable=True, index=True)
    fecha_notificacion = db.Column(db.Date, nullable=True, index=True)  # inicio real
    cantidad_dias = db.Column(db.Integer, nullable=True)
    dias_fija = db.Column(db.Integer, nullable=True)
    dias_ambulatoria = db.Column(db.Integer, nullable=True)
    dias_personalizada = db.Column(db.Integer, nullable=True)
    distancia = db.Column(db.String(80), nullable=True)
    turnos = db.Column(db.String(120), nullable=True)
    acusado_notificar = db.Column(db.String(20), nullable=True)  # si | no | indeterminada
    estado = db.Column(db.String(40), nullable=False, default="activa", index=True)
    observaciones = db.Column(db.Text, nullable=True)

    texto_fuente = db.Column(db.Text, nullable=True)
    fuente_principal = db.Column(db.String(20), nullable=False, default="ocr")  # ocr | qr
    qr_url = db.Column(db.String(500), nullable=True)
    archivo_origen = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    unidad = db.relationship("Unidad", backref="oficios_consignas")
    usuario_creador = db.relationship("User", backref="oficios_consignas")

    personas = db.relationship(
        "ConsignaPersona",
        backref="consigna",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    domicilios = db.relationship(
        "ConsignaDomicilio",
        backref="consigna",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    medidas_detalle = db.relationship(
        "ConsignaMedidaDetalle",
        backref="consigna",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class ConsignaPersona(db.Model):
    __tablename__ = "oficios_consigna_personas"

    id = db.Column(db.Integer, primary_key=True)
    consigna_id = db.Column(db.Integer, db.ForeignKey("oficios_consignas.id"), nullable=False, index=True)
    nombre = db.Column(db.String(255), nullable=False, index=True)
    dni = db.Column(db.String(40), nullable=True, index=True)
    tipo = db.Column(db.String(30), nullable=False, index=True)  # victima | denunciado | notificado


class ConsignaDomicilio(db.Model):
    __tablename__ = "oficios_consigna_domicilios"

    id = db.Column(db.Integer, primary_key=True)
    consigna_id = db.Column(db.Integer, db.ForeignKey("oficios_consignas.id"), nullable=False, index=True)
    direccion = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(30), nullable=False, index=True)  # victima | denunciado


class ConsignaMedidaDetalle(db.Model):
    __tablename__ = "oficios_consigna_medidas_detalle"

    id = db.Column(db.Integer, primary_key=True)
    consigna_id = db.Column(db.Integer, db.ForeignKey("oficios_consignas.id"), nullable=False, index=True)
    descripcion = db.Column(db.Text, nullable=False)


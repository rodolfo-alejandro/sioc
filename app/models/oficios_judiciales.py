"""
Modelos para carga inteligente de oficios judiciales.
"""
from datetime import datetime

from sqlalchemy import UniqueConstraint

from app.extensions import db


class ConsignaJudicial(db.Model):
    __tablename__ = "oficios_consignas"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    expediente = db.Column(db.String(191), nullable=True, index=True)
    expediente_key = db.Column(db.String(191), nullable=True, index=True)
    juzgado = db.Column(db.String(255), nullable=True, index=True)
    juzgado_key = db.Column(db.String(255), nullable=True, index=True)
    caratula = db.Column(db.Text, nullable=True)
    tipo_medida = db.Column(db.String(191), nullable=True, index=True)
    tipo_consigna = db.Column(db.String(30), nullable=True, index=True)  # fija | ambulatoria | personalizada | indeterminada
    fiscalia = db.Column(db.String(255), nullable=True, index=True)
    fiscalia_key = db.Column(db.String(255), nullable=True, index=True)
    telefono_contacto = db.Column(db.String(120), nullable=True, index=True)
    seps_ingreso = db.Column(db.String(128), nullable=True, index=True)
    seps_salida = db.Column(db.String(128), nullable=True, index=True)
    fecha_oficio = db.Column(db.Date, nullable=True, index=True)
    fecha_notificacion = db.Column(db.Date, nullable=True, index=True)  # inicio real
    cantidad_dias = db.Column(db.Integer, nullable=True)
    dias_fija = db.Column(db.Integer, nullable=True)
    dias_ambulatoria = db.Column(db.Integer, nullable=True)
    dias_personalizada = db.Column(db.Integer, nullable=True)
    distancia = db.Column(db.String(80), nullable=True)
    turnos = db.Column(db.String(255), nullable=True)
    acusado_notificar = db.Column(db.String(20), nullable=True)  # si | no | indeterminada
    estado = db.Column(db.String(40), nullable=False, default="activa", index=True)
    observaciones = db.Column(db.Text, nullable=True)

    texto_fuente = db.Column(db.Text, nullable=True)
    fuente_principal = db.Column(db.String(20), nullable=False, default="ocr")  # ocr | qr
    qr_url = db.Column(db.String(500), nullable=True)
    archivo_origen = db.Column(db.String(500), nullable=True)

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
    dias_por_tipo = db.relationship(
        "ConsignaDiasPorTipo",
        back_populates="consigna",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class ConsignaDiasPorTipo(db.Model):
    """
    Días cargados por ítem del catálogo «Tipos de consigna» (normalizado por ID).
    Permite filtros / agregaciones: JOIN con oficios_catalogo_tipos_consigna.
    """

    __tablename__ = "oficios_consigna_dias_tipo"
    __table_args__ = (UniqueConstraint("consigna_id", "tipo_catalogo_id", name="uq_oficios_consigna_dias_tipo"),)

    id = db.Column(db.Integer, primary_key=True)
    consigna_id = db.Column(
        db.Integer,
        db.ForeignKey("oficios_consignas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo_catalogo_id = db.Column(
        db.Integer,
        db.ForeignKey("oficios_catalogo_tipos_consigna.id"),
        nullable=False,
        index=True,
    )
    dias = db.Column(db.Integer, nullable=False, default=0)

    consigna = db.relationship("ConsignaJudicial", back_populates="dias_por_tipo")
    tipo_catalogo = db.relationship("CatalogoTipoConsigna", backref=db.backref("dias_en_consignas", lazy="dynamic"))


class ConsignaPersona(db.Model):
    __tablename__ = "oficios_consigna_personas"

    id = db.Column(db.Integer, primary_key=True)
    consigna_id = db.Column(db.Integer, db.ForeignKey("oficios_consignas.id"), nullable=False, index=True)
    nombre = db.Column(db.String(255), nullable=False, index=True)
    nombre_key = db.Column(db.String(255), nullable=True, index=True)
    dni = db.Column(db.String(40), nullable=True, index=True)
    dni_key = db.Column(db.String(20), nullable=True, index=True)
    tipo = db.Column(db.String(30), nullable=False, index=True)  # victima | denunciado | notificado
    notificar = db.Column(db.String(20), nullable=True)  # si | no | indeterminada


class ConsignaDomicilio(db.Model):
    __tablename__ = "oficios_consigna_domicilios"

    id = db.Column(db.Integer, primary_key=True)
    consigna_id = db.Column(db.Integer, db.ForeignKey("oficios_consignas.id"), nullable=False, index=True)
    direccion = db.Column(db.Text, nullable=False)
    barrio_codigo = db.Column(db.String(40), nullable=True, index=True)
    barrio_nombre = db.Column(db.String(255), nullable=True, index=True)
    latitud = db.Column(db.Float, nullable=True, index=True)
    longitud = db.Column(db.Float, nullable=True, index=True)
    tipo = db.Column(db.String(30), nullable=False, index=True)  # victima | denunciado


class ConsignaMedidaDetalle(db.Model):
    __tablename__ = "oficios_consigna_medidas_detalle"

    id = db.Column(db.Integer, primary_key=True)
    consigna_id = db.Column(db.Integer, db.ForeignKey("oficios_consignas.id"), nullable=False, index=True)
    descripcion = db.Column(db.Text, nullable=False)


class CatalogoJuzgado(db.Model):
    __tablename__ = "oficios_catalogo_juzgados"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(255), nullable=False, unique=True, index=True)
    clave = db.Column(db.String(255), nullable=True, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)


class CatalogoTipoMedida(db.Model):
    __tablename__ = "oficios_catalogo_tipos_medida"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(191), nullable=False, unique=True, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)


class CatalogoTipoConsigna(db.Model):
    __tablename__ = "oficios_catalogo_tipos_consigna"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(60), nullable=False, unique=True, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)


class CatalogoFiscalia(db.Model):
    __tablename__ = "oficios_catalogo_fiscalias"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(255), nullable=False, unique=True, index=True)
    clave = db.Column(db.String(255), nullable=True, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)


class CatalogoBarrio(db.Model):
    __tablename__ = "oficios_catalogo_barrios"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), nullable=True, index=True)
    nombre = db.Column(db.String(255), nullable=False, unique=True, index=True)
    dependencia_codigo = db.Column(db.String(40), nullable=True, index=True)
    dependencia_nombre = db.Column(db.String(255), nullable=True, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)


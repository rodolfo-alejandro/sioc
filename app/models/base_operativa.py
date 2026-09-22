"""
Base Operativa (Excel manual Capital / Interior).

Hechos e identificados en hojas separadas, unidos por REGISTRO N° (CAP).
"""
from datetime import datetime

from app.extensions import db


class BaseProcedimiento(db.Model):
    __tablename__ = "base_operativa_procedimientos"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    fecha_importacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)

    # capital | interior
    ambito = db.Column(db.String(20), nullable=False, index=True)
    # Clave de negocio: CAP0001, INT0001, etc. (REGISTRO N°)
    registro_nro = db.Column(db.String(40), nullable=False, index=True)
    nro_ap = db.Column(db.String(80), nullable=True)
    anio = db.Column(db.Integer, nullable=False, index=True)

    sector = db.Column(db.String(120), nullable=True, index=True)
    tipo_informe = db.Column(db.String(120), nullable=True, index=True)
    estado = db.Column(db.String(80), nullable=True, index=True)
    lugar_proced = db.Column(db.String(500), nullable=True)
    causa_allanada = db.Column(db.String(120), nullable=True)
    cantidad_lugares = db.Column(db.Integer, nullable=True)
    barrio = db.Column(db.String(255), nullable=True, index=True)
    localidad = db.Column(db.String(120), nullable=True, index=True)
    departamento = db.Column(db.String(120), nullable=True, index=True)
    dependencia = db.Column(db.String(255), nullable=True, index=True)
    dur = db.Column(db.String(80), nullable=True, index=True)

    latitud = db.Column(db.Float, nullable=True, index=True)
    longitud = db.Column(db.Float, nullable=True, index=True)

    fecha = db.Column(db.Date, nullable=True, index=True)
    hora = db.Column(db.Time, nullable=True)
    dia_proc = db.Column(db.String(40), nullable=True)
    mes = db.Column(db.String(40), nullable=True)
    semana = db.Column(db.String(40), nullable=True)
    trimestre = db.Column(db.String(40), nullable=True)

    of_interviniente = db.Column(db.String(255), nullable=True, index=True)
    sinar_interviniente = db.Column(db.String(255), nullable=True, index=True)
    nro_expediente = db.Column(db.String(120), nullable=True)
    micro_macro = db.Column(db.String(120), nullable=True, index=True)
    tipo_operativo = db.Column(db.String(120), nullable=True, index=True)
    delito = db.Column(db.String(500), nullable=True, index=True)
    info_relev = db.Column(db.Text, nullable=True)
    dinares = db.Column(db.String(120), nullable=True)
    personas_ident_operativo = db.Column(db.Integer, nullable=True)

    marihuana_grs = db.Column(db.Float, nullable=False, default=0)
    cocaina_grs = db.Column(db.Float, nullable=False, default=0)
    hoja_coca_kg = db.Column(db.Float, nullable=False, default=0)
    plantas = db.Column(db.Float, nullable=False, default=0)
    plantines = db.Column(db.Float, nullable=False, default=0)
    semillas = db.Column(db.Float, nullable=False, default=0)
    pastillas_cant = db.Column(db.Float, nullable=False, default=0)
    otras_sustancias = db.Column(db.String(255), nullable=True)

    pesos_arg = db.Column(db.Float, nullable=False, default=0)
    dolares = db.Column(db.Float, nullable=False, default=0)
    euro = db.Column(db.Float, nullable=False, default=0)
    reales = db.Column(db.Float, nullable=False, default=0)
    bolivianos = db.Column(db.Float, nullable=False, default=0)
    otras_divisas = db.Column(db.String(120), nullable=True)

    total_detenidos_demorados = db.Column(db.Integer, nullable=False, default=0)
    total_detenidos = db.Column(db.Integer, nullable=False, default=0)
    total_demorados = db.Column(db.Integer, nullable=False, default=0)
    det_hombre_may = db.Column(db.Integer, nullable=False, default=0)
    det_hombre_men = db.Column(db.Integer, nullable=False, default=0)
    det_mujer_may = db.Column(db.Integer, nullable=False, default=0)
    det_mujer_men = db.Column(db.Integer, nullable=False, default=0)
    is_hombre_may = db.Column(db.Integer, nullable=False, default=0)
    is_hombre_men = db.Column(db.Integer, nullable=False, default=0)
    is_mujer_may = db.Column(db.Integer, nullable=False, default=0)
    is_mujer_men = db.Column(db.Integer, nullable=False, default=0)

    fiscalia = db.Column(db.String(255), nullable=True)
    juzgado = db.Column(db.String(255), nullable=True)
    otros_secuestros = db.Column(db.Text, nullable=True)
    dominios = db.Column(db.Text, nullable=True)

    # Resumen denormalizado de identificados (para listado auditoría)
    acusados_texto = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    unidad = db.relationship("Unidad", backref="base_operativa_procedimientos")
    usuario_creador = db.relationship("User", backref="base_operativa_procedimientos")
    identificados = db.relationship(
        "BaseIdentificado",
        back_populates="procedimiento",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "unidad_id", "ambito", "registro_nro",
            name="uq_base_op_unidad_ambito_registro",
        ),
        db.Index("ix_base_op_lat_lon", "latitud", "longitud"),
    )

    @property
    def clave_negocio(self) -> str:
        return f"{self.ambito}:{self.registro_nro}"


class BaseIdentificado(db.Model):
    __tablename__ = "base_operativa_identificados"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    procedimiento_id = db.Column(
        db.Integer,
        db.ForeignKey("base_operativa_procedimientos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ambito = db.Column(db.String(20), nullable=False, index=True)
    registro_nro = db.Column(db.String(40), nullable=False, index=True)

    tipo = db.Column(db.String(40), nullable=True, index=True)  # DETENIDO / DEMORADO
    nombre = db.Column(db.String(255), nullable=True, index=True)
    edad = db.Column(db.Integer, nullable=True)
    fecha_nacimiento = db.Column(db.Date, nullable=True)
    dni = db.Column(db.String(40), nullable=True, index=True)
    domicilio = db.Column(db.String(500), nullable=True)
    latitud = db.Column(db.Float, nullable=True)
    longitud = db.Column(db.Float, nullable=True)
    barrio = db.Column(db.String(255), nullable=True)
    sector = db.Column(db.String(120), nullable=True)
    ocupacion = db.Column(db.String(255), nullable=True)
    alias = db.Column(db.String(255), nullable=True)
    localidad = db.Column(db.String(120), nullable=True)
    nacionalidad = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    procedimiento = db.relationship("BaseProcedimiento", back_populates="identificados")

    __table_args__ = (
        db.Index("ix_base_op_ident_unidad_reg", "unidad_id", "ambito", "registro_nro"),
    )

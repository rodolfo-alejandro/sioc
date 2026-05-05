"""
Modelos: capacitaciones, padrón Drogas, inscriptos, asistencia.
Espacio de tablas con prefijo cap_* para evitar colisiones.
"""
from datetime import datetime

from sqlalchemy import Index

from app.extensions import db


class PadronDrogas(db.Model):
    """Padrón global de personal (único por DNI normalizado)."""

    __tablename__ = "cap_padron_drogas"

    id = db.Column(db.Integer, primary_key=True)
    legajo = db.Column(db.String(64), nullable=True, index=True)
    apellido = db.Column(db.String(120), nullable=True, index=True)
    nombre = db.Column(db.String(120), nullable=True, index=True)
    dni = db.Column(db.String(32), nullable=True)
    dni_key = db.Column(db.String(20), nullable=False, unique=True, index=True)
    grado = db.Column(db.String(120), nullable=True, index=True)
    sexo = db.Column(db.String(40), nullable=True)
    dependencia = db.Column(db.String(255), nullable=True, index=True)
    organismo = db.Column(db.String(255), nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)
    fecha_importacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    fecha_actualizacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    origen_archivo = db.Column(db.String(500), nullable=True)

    inscriptos_match = db.relationship("InscriptoEvento", back_populates="padron_ref", lazy="dynamic")


class EventoCapacitacion(db.Model):
    """Evento / capacitación reutilizable en el tiempo."""

    __tablename__ = "cap_eventos"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    tipo_evento = db.Column(db.String(80), nullable=True, index=True)
    modalidad = db.Column(db.String(40), nullable=True, index=True)
    fecha = db.Column(db.Date, nullable=True, index=True)
    hora_inicio = db.Column(db.Time, nullable=True)
    hora_fin = db.Column(db.Time, nullable=True)
    lugar = db.Column(db.String(255), nullable=True)
    enlace_virtual = db.Column(db.String(500), nullable=True)
    estado = db.Column(db.String(40), nullable=False, default="planificado", index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    creado_por = db.relationship("User", foreign_keys=[creado_por_id], backref=db.backref("eventos_capacitacion", lazy="dynamic"))
    inscriptos = db.relationship("InscriptoEvento", back_populates="evento", cascade="all, delete-orphan", lazy="dynamic")
    momentos = db.relationship("MomentoAsistencia", back_populates="evento", cascade="all, delete-orphan", lazy="dynamic")
    registros = db.relationship("RegistroAsistencia", back_populates="evento", cascade="all, delete-orphan", lazy="dynamic")


class InscriptoEvento(db.Model):
    """Inscripto por evento (lista propia del evento)."""

    __tablename__ = "cap_inscriptos_evento"
    __table_args__ = (Index("ix_cap_inscripto_evento", "evento_id", "estado_validacion"),)

    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey("cap_eventos.id", ondelete="CASCADE"), nullable=False, index=True)
    apellido_nombre = db.Column(db.String(255), nullable=True)
    dni = db.Column(db.String(32), nullable=True)
    dni_key = db.Column(db.String(20), nullable=False, index=True)
    telefono = db.Column(db.String(80), nullable=True)
    correo = db.Column(db.String(255), nullable=True)
    dependencia_declarada = db.Column(db.String(255), nullable=True)
    cargo = db.Column(db.String(255), nullable=True)
    modalidad_declarada = db.Column(db.String(80), nullable=True)
    comentarios = db.Column(db.Text, nullable=True)

    pertenece_drogas = db.Column(db.Boolean, nullable=False, default=False, index=True)
    padron_drogas_id = db.Column(db.Integer, db.ForeignKey("cap_padron_drogas.id", ondelete="SET NULL"), nullable=True, index=True)
    estado_validacion = db.Column(db.String(40), nullable=False, default="externo", index=True)
    observacion_validacion = db.Column(db.String(500), nullable=True)

    evento = db.relationship("EventoCapacitacion", back_populates="inscriptos")
    padron_ref = db.relationship("PadronDrogas", back_populates="inscriptos_match")
    registros = db.relationship("RegistroAsistencia", back_populates="inscripto", lazy="dynamic")

    @property
    def dependencia_para_reporte(self) -> str | None:
        """Inscripción (import) o, si calza padrón Drogas, dependencia del padrón."""
        d = (self.dependencia_declarada or "").strip()
        if d:
            return d
        p = self.padron_ref
        if p is not None and (p.dependencia or "").strip():
            return (p.dependencia or "").strip()
        return None


class MomentoAsistencia(db.Model):
    """Momento de control (inicio, intermedio, final, etc.)."""

    __tablename__ = "cap_momentos_asistencia"
    __table_args__ = (Index("ix_cap_momento_evento_orden", "evento_id", "orden"),)

    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey("cap_eventos.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(40), nullable=False, default="personalizado", index=True)
    codigo_validacion = db.Column(db.String(32), nullable=False, index=True)
    token_publico = db.Column(db.String(64), nullable=True, unique=True, index=True)
    fecha_apertura = db.Column(db.DateTime, nullable=True)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)
    orden = db.Column(db.Integer, nullable=False, default=0)

    evento = db.relationship("EventoCapacitacion", back_populates="momentos")
    registros = db.relationship("RegistroAsistencia", back_populates="momento", lazy="dynamic")


class RegistroAsistencia(db.Model):
    """Registro de intento o asistencia válida."""

    __tablename__ = "cap_registros_asistencia"
    __table_args__ = (
        Index("ix_cap_reg_evento_momento_inscripto", "evento_id", "momento_id", "inscripto_id"),
        Index("ix_cap_reg_dni_momento", "evento_id", "momento_id", "dni_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey("cap_eventos.id", ondelete="CASCADE"), nullable=False, index=True)
    inscripto_id = db.Column(db.Integer, db.ForeignKey("cap_inscriptos_evento.id", ondelete="SET NULL"), nullable=True, index=True)
    momento_id = db.Column(db.Integer, db.ForeignKey("cap_momentos_asistencia.id", ondelete="CASCADE"), nullable=False, index=True)
    dni_ingresado = db.Column(db.String(32), nullable=True)
    dni_key = db.Column(db.String(20), nullable=True, index=True)
    codigo_ingresado = db.Column(db.String(64), nullable=True)
    fecha_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    valido = db.Column(db.Boolean, nullable=False, default=False, index=True)
    motivo = db.Column(db.String(80), nullable=True)

    evento = db.relationship("EventoCapacitacion", back_populates="registros")
    inscripto = db.relationship("InscriptoEvento", back_populates="registros")
    momento = db.relationship("MomentoAsistencia", back_populates="registros")

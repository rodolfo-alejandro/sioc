"""
Auditoría de calidad sobre Denuncias Web.

No modifica los datos originales: guarda observaciones del auditor
por campo (o una observación general) en tabla aparte.
"""
from datetime import datetime

from app.extensions import db

# Campo especial para la observación general del registro
CAMPO_GENERAL = "__general__"

# Principales: lo que el auditor revisa primero
CAMPOS_PRINCIPALES = (
    ("nro_actuacion", "Nro actuación"),
    ("anio_actuacion", "Año actuación"),
    ("causa_estado", "Estado"),
    ("desc_dep_registro", "Dependencia registro"),
    ("desc_dep_padre", "Dependencia padre"),
    ("desc_dep_actuario", "Dependencia actuario"),
    ("actuario_grado", "Actuario grado"),
    ("actuario_apenom", "Actuario"),
    ("fecha_denuncia", "Fecha denuncia"),
    ("fecha_recepcion", "Fecha recepción"),
    ("fecha_apertura", "Fecha apertura"),
    ("fecha_desestimada", "Fecha desestimada"),
    ("fecha_sol_allanamiento", "Solicitud allanamiento"),
    ("localidad", "Localidad"),
    ("investigados", "Investigados"),
    ("relato", "Relato"),  # relato_original o relato (uno solo)
    ("observacion_interna", "Observación interna"),
)

# Secundarios: geo / barrio (menos prioritarios en la auditoría)
CAMPOS_SECUNDARIOS = (
    ("barrio", "Barrio"),
    ("coord", "Coordenadas (texto)"),
    ("latitud", "Latitud"),
    ("longitud", "Longitud"),
)

# Columnas del listado (tabla ancha con scroll horizontal)
CAMPOS_LISTADO = (
    ("nro_actuacion", "Nro"),
    ("fecha_denuncia", "Fecha"),
    ("causa_estado", "Estado"),
    ("desc_dep_registro", "Dependencia"),
    ("desc_dep_actuario", "Dep. actuario"),
    ("actuario_apenom", "Actuario"),
    ("localidad", "Localidad"),
    ("barrio", "Barrio"),
    ("latitud", "Lat"),
    ("longitud", "Lon"),
    ("investigados", "Investigados"),
    ("relato", "Relato"),
)

# Estados de observación (BD) → etiquetas UI
ESTADO_LABEL = {
    "pendiente": "Pendiente a auditar",
    "resuelta": "Auditado",
    "auditado": "Auditado",
}

CAMPOS_AUDITABLES = CAMPOS_PRINCIPALES + CAMPOS_SECUNDARIOS
CAMPOS_AUDITABLES_MAP = {k: v for k, v in CAMPOS_AUDITABLES}
CAMPOS_SECUNDARIOS_KEYS = {k for k, _ in CAMPOS_SECUNDARIOS}


class AuditoriaObs(db.Model):
    """Observación de auditoría sobre un campo (o general) de una denuncia web."""

    __tablename__ = "auditoria_obs"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    denuncia_id = db.Column(
        db.Integer,
        db.ForeignKey("analisis_denuncias_web.id"),
        nullable=False,
        index=True,
    )
    campo = db.Column(db.String(80), nullable=False, index=True)
    valor_sistema = db.Column(db.Text, nullable=True)
    valor_auditor = db.Column(db.Text, nullable=True)
    nota = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(20), nullable=False, default="pendiente", index=True)
    auditor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    unidad = db.relationship("Unidad", backref="auditoria_obs")
    auditor = db.relationship("User", backref="auditoria_obs_cargadas", foreign_keys=[auditor_id])

    __table_args__ = (
        db.UniqueConstraint("denuncia_id", "campo", name="uq_auditoria_obs_denuncia_campo"),
        db.Index("ix_auditoria_obs_unidad_estado", "unidad_id", "estado"),
    )

    @property
    def es_general(self) -> bool:
        return self.campo == CAMPO_GENERAL

    @property
    def campo_label(self) -> str:
        if self.es_general:
            return "Observación general"
        return CAMPOS_AUDITABLES_MAP.get(self.campo, self.campo)

"""
Auditoría de calidad: Denuncias Web e Intervenciones.

No modifica los datos originales: guarda observaciones del auditor
por campo (o una observación general) en tabla aparte.
"""
from datetime import datetime

from app.extensions import db

CAMPO_GENERAL = "__general__"

MODULO_DENUNCIAS = "denuncias_web"
MODULO_INTERVENCIONES = "intervenciones"

# —— Denuncias Web ——
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
    ("relato", "Relato"),
    ("observacion_interna", "Observación interna"),
)

CAMPOS_SECUNDARIOS = (
    ("barrio", "Barrio"),
    ("coord", "Coordenadas (texto)"),
    ("latitud", "Latitud"),
    ("longitud", "Longitud"),
)

CAMPOS_LISTADO = (
    ("nro_actuacion", "Nro"),
    ("fecha_denuncia", "Fecha"),
    ("causa_estado", "Estado"),
    ("desc_dep_registro", "Dependencia"),
    ("desc_dep_actuario", "Dep. actuario"),
    ("actuario", "Actuario"),
    ("localidad", "Localidad"),
    ("barrio", "Barrio"),
    ("latitud", "Lat"),
    ("longitud", "Lon"),
    ("investigados", "Investigados"),
    ("relato", "Relato"),
)

COLUMNAS_OCULTABLES = frozenset({"localidad", "barrio", "latitud", "longitud"})

# —— Intervenciones (no hay "actuario" ni "acusados" por nombre en el Excel) ——
# Personal: pers_interviniente | Detenidos/IS: conteos | Sustancias + dinero: sí
CAMPOS_INTERV_PRINCIPALES = (
    ("causas_interv_id", "Nro intervención"),
    ("causas_id", "Causa"),
    ("interv_fecha", "Fecha"),
    ("tipo_interv_desc", "Tipo intervención"),
    ("causa_escala", "Escala"),
    ("causa_actividad", "Actividad"),
    ("tipo_operativo", "Tipo operativo"),
    ("pers_interviniente", "Personal interviniente"),
    ("dep_interviniente", "Dep. interviniente (SINAR)"),
    ("departamento_operativo", "Depto. operativo"),
    ("zona", "DINAR / Zona"),
    ("distrito", "Distrito"),
    ("dep_policial", "Dep. policial"),
    ("detenidos_total", "Detenidos (total)"),
    ("identificados_total", "Identificados / IS (total)"),
    ("secuestro_marihuana", "Marihuana (g/kg)"),
    ("secuestro_cocaina", "Cocaína (g/kg)"),
    ("secuestro_plantas", "Plantas (u.)"),
    ("secuestro_plantines", "Plantines (u.)"),
    ("secuestro_semillas", "Semillas (u.)"),
    ("hojas_coca", "Hojas de coca (g/kg)"),
    ("pesos_arg", "Pesos ARS ($)"),
    ("dolares", "Dólares (US$)"),
    ("euro", "Euros (€)"),
    ("reales", "Reales (R$)"),
    ("bolivianos", "Bolivianos (Bs)"),
)

CAMPOS_INTERV_SECUNDARIOS = (
    ("localidad_nombre", "Localidad"),
    ("barrios_nombre", "Barrio"),
    ("coordx", "Lat (coordX)"),
    ("coordy", "Lon (coordY)"),
    ("det_hombre_may", "Det. hombre mayor"),
    ("det_hombre_men", "Det. hombre menor"),
    ("det_mujer_may", "Det. mujer mayor"),
    ("det_mujer_men", "Det. mujer menor"),
    ("is_hombre_may", "IS hombre mayor"),
    ("is_hombre_men", "IS hombre menor"),
    ("is_mujer_may", "IS mujer mayor"),
    ("is_mujer_men", "IS mujer menor"),
)

CAMPOS_INTERV_LISTADO = (
    ("causas_interv_id", "Nro interv"),
    ("interv_fecha", "Fecha"),
    ("tipo_interv_desc", "Tipo"),
    ("causa_escala", "Escala"),
    ("tipo_operativo", "Operativo"),
    ("pers_interviniente", "Personal interviniente"),
    ("dep_interviniente", "SINAR"),
    ("zona", "DINAR"),
    ("departamento_operativo", "Depto. op."),
    ("detenidos_total", "Detenidos"),
    ("identificados_total", "IS / Identif."),
    ("secuestro_marihuana", "Marihuana"),
    ("secuestro_cocaina", "Cocaína"),
    ("secuestro_plantas", "Plantas"),
    ("secuestro_plantines", "Plantines"),
    ("hojas_coca", "Hojas coca"),
    ("pesos_arg", "$ ARS"),
    ("dolares", "US$"),
    ("euro", "€"),
    ("localidad_nombre", "Localidad"),
    ("barrios_nombre", "Barrio"),
    ("coordx", "Lat"),
    ("coordy", "Lon"),
    ("distrito", "Distrito"),
    ("dep_policial", "Dep. policial"),
    ("causa_actividad", "Actividad"),
    ("secuestro_semillas", "Semillas"),
    ("reales", "R$"),
    ("bolivianos", "Bs"),
)

# Ocultas por defecto (se pueden marcar arriba)
COLUMNAS_OCULTABLES_INTERV = frozenset(
    {
        "localidad_nombre",
        "barrios_nombre",
        "coordx",
        "coordy",
        "distrito",
        "dep_policial",
        "causa_actividad",
        "departamento_operativo",
        "causa_escala",
        "tipo_operativo",
        "secuestro_plantas",
        "secuestro_plantines",
        "secuestro_semillas",
        "hojas_coca",
        "euro",
        "reales",
        "bolivianos",
    }
)

ESTADO_LABEL = {
    "pendiente": "Pendiente a auditar",
    "resuelta": "Auditado",
    "auditado": "Auditado",
}

CAMPOS_AUDITABLES = CAMPOS_PRINCIPALES + CAMPOS_SECUNDARIOS
CAMPOS_AUDITABLES_MAP = {k: v for k, v in CAMPOS_AUDITABLES}
CAMPOS_AUDITABLES_MAP["actuario"] = "Actuario"

CAMPOS_INTERV_AUDITABLES = CAMPOS_INTERV_PRINCIPALES + CAMPOS_INTERV_SECUNDARIOS
CAMPOS_INTERV_MAP = {k: v for k, v in CAMPOS_INTERV_AUDITABLES}


class AuditoriaObs(db.Model):
    """Observación de auditoría sobre un registro (denuncia o intervención)."""

    __tablename__ = "auditoria_obs"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    modulo = db.Column(db.String(40), nullable=False, default=MODULO_DENUNCIAS, index=True)
    # ID interno del registro en su tabla (denuncia o intervención)
    registro_id = db.Column(db.Integer, nullable=True, index=True)
    # Legacy denuncias (se mantiene por compatibilidad; preferir modulo+registro_id)
    denuncia_id = db.Column(db.Integer, nullable=True, index=True)
    intervencion_id = db.Column(db.Integer, nullable=True, index=True)
    # Clave de negocio para sobrevivir reimportaciones
    causas_id = db.Column(db.String(80), nullable=True, index=True)
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
        db.Index("ix_auditoria_obs_unidad_estado", "unidad_id", "estado"),
        db.Index("ix_auditoria_obs_unidad_causas", "unidad_id", "causas_id"),
        db.Index("ix_auditoria_obs_modulo_reg", "unidad_id", "modulo", "registro_id"),
    )

    @property
    def es_general(self) -> bool:
        return self.campo == CAMPO_GENERAL

    @property
    def campo_label(self) -> str:
        if self.es_general:
            return "Observación general"
        if self.modulo == MODULO_INTERVENCIONES:
            return CAMPOS_INTERV_MAP.get(self.campo, self.campo)
        return CAMPOS_AUDITABLES_MAP.get(self.campo, self.campo)

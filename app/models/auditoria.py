"""
Modelos para el sistema de auditoría.
Permite a auditores agregar observaciones sobre registros sin modificar los datos originales.
"""
from datetime import datetime

from app.extensions import db


class AuditoriaObservacion(db.Model):
    """
    Observaciones de auditoría sobre registros de cualquier módulo.
    Permite observaciones generales o específicas por campo.
    """
    __tablename__ = "auditoria_observaciones"

    id = db.Column(db.Integer, primary_key=True)
    
    # Identificación del registro auditado
    modulo = db.Column(db.String(50), nullable=False, index=True)  # 'denuncias_web', 'intervenciones', etc.
    registro_id = db.Column(db.Integer, nullable=False, index=True)  # ID del registro en su tabla
    
    # Observación
    campo = db.Column(db.String(100), nullable=True, index=True)  # Campo específico o NULL para observación general
    observacion = db.Column(db.Text, nullable=False)
    
    # Metadata
    auditor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    fecha_modificacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Estado
    resuelta = db.Column(db.Boolean, nullable=False, default=False, index=True)
    fecha_resolucion = db.Column(db.DateTime, nullable=True)
    resuelto_por_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    nota_resolucion = db.Column(db.Text, nullable=True)
    
    # Relaciones
    auditor = db.relationship("User", foreign_keys=[auditor_id], backref="observaciones_creadas")
    resuelto_por = db.relationship("User", foreign_keys=[resuelto_por_id], backref="observaciones_resueltas")
    unidad = db.relationship("Unidad", backref="auditoria_observaciones")

    __table_args__ = (
        db.Index("ix_auditoria_modulo_registro", "modulo", "registro_id"),
        db.Index("ix_auditoria_unidad_modulo", "unidad_id", "modulo"),
    )

    def __repr__(self):
        return f"<AuditoriaObservacion {self.id} - {self.modulo}:{self.registro_id}>"


class AuditoriaResumen(db.Model):
    """
    Resúmenes de auditoría generados para grupos/secciones.
    Permite generar reportes consolidados de auditoría.
    """
    __tablename__ = "auditoria_resumenes"

    id = db.Column(db.Integer, primary_key=True)
    
    # Identificación
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    modulo = db.Column(db.String(50), nullable=False, index=True)
    
    # Agrupación (ej: por dependencia, por actuario, etc.)
    tipo_agrupacion = db.Column(db.String(50), nullable=False, index=True)  # 'dependencia', 'actuario', 'estado', etc.
    valor_agrupacion = db.Column(db.String(255), nullable=False, index=True)  # Valor concreto del agrupamiento
    
    # Período
    fecha_desde = db.Column(db.DateTime, nullable=True, index=True)
    fecha_hasta = db.Column(db.DateTime, nullable=True, index=True)
    
    # Resumen
    titulo = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    total_registros = db.Column(db.Integer, nullable=False, default=0)
    registros_con_observaciones = db.Column(db.Integer, nullable=False, default=0)
    total_observaciones = db.Column(db.Integer, nullable=False, default=0)
    observaciones_resueltas = db.Column(db.Integer, nullable=False, default=0)
    
    # Metadata
    generado_por_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    fecha_generacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Relaciones
    generado_por = db.relationship("User", backref="resumenes_auditoria")
    unidad = db.relationship("Unidad", backref="resumenes_auditoria")

    __table_args__ = (
        db.Index("ix_auditoria_resumen_agrupacion", "tipo_agrupacion", "valor_agrupacion"),
    )

    def __repr__(self):
        return f"<AuditoriaResumen {self.id} - {self.modulo}:{self.tipo_agrupacion}>"

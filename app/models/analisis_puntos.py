"""
Modelos del módulo Análisis de Puntos.
Este módulo es independiente de Sabana de Llamadas para evitar mezclar datasets.
"""
from datetime import datetime

from app.extensions import db


class AnalisisPuntoCaso(db.Model):
    __tablename__ = "ap_casos"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    codigo = db.Column(db.String(64), nullable=False, index=True)
    titulo = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    # Referencia administrativa / judicial (expediente, carpeta, Nº de causa)
    referencia_carpeta = db.Column(db.String(120), nullable=True, index=True)
    # Fecha de los hechos o inicio operativo (no confundir con created_at del sistema)
    fecha_referencia = db.Column(db.Date, nullable=True, index=True)
    estado = db.Column(db.String(20), nullable=False, default="ACTIVO", index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    unidad = db.relationship("Unidad", backref="ap_casos")
    user = db.relationship("User", backref="ap_casos")

    __table_args__ = (
        db.UniqueConstraint("unidad_id", "codigo", name="uq_ap_casos_unidad_codigo"),
    )


class AnalisisPuntoCasoCompartido(db.Model):
    """Comparte un caso de análisis con otro usuario de la misma unidad."""
    __tablename__ = "ap_casos_compartidos"

    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), primary_key=True, nullable=False)
    shared_with_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True, nullable=False, index=True)
    shared_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="compartidos", foreign_keys=[caso_id])
    shared_with = db.relationship("User", foreign_keys=[shared_with_user_id])
    shared_by = db.relationship("User", foreign_keys=[shared_by_user_id])


class AnalisisPuntoFuente(db.Model):
    __tablename__ = "ap_fuentes"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    source_type = db.Column(db.String(20), nullable=False, index=True)  # VOZ / GPRS
    operadora = db.Column(db.String(30), nullable=True, index=True)  # PERSONAL / MOVISTAR / CLARO / OTRA
    nombre_archivo = db.Column(db.String(255), nullable=False)
    sha256 = db.Column(db.String(128), nullable=True, index=True)
    mime_type = db.Column(db.String(120), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)

    date_from = db.Column(db.DateTime, nullable=True, index=True)
    date_to = db.Column(db.DateTime, nullable=True, index=True)
    upload_status = db.Column(db.String(20), nullable=False, default="PENDING", index=True)
    error_detail = db.Column(db.Text, nullable=True)
    # Nota en pantalla Relaciones (unificada con sábana; antes vivía en ap_caso_fuentes)
    relaciones_nota = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="fuentes", foreign_keys=[caso_id])
    unidad = db.relationship("Unidad", backref="ap_fuentes")
    user = db.relationship("User", backref="ap_fuentes")


class AnalisisPuntoCelda(db.Model):
    __tablename__ = "ap_celdas"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)

    cell_code = db.Column(db.String(100), nullable=False, index=True)
    address = db.Column(db.String(255), nullable=True)
    locality = db.Column(db.String(200), nullable=True, index=True)
    province = db.Column(db.String(200), nullable=True, index=True)

    lat = db.Column(db.Float, nullable=True, index=True)
    lon = db.Column(db.Float, nullable=True, index=True)
    coverage_radius_m = db.Column(db.Integer, nullable=True)
    azimuth_deg = db.Column(db.Integer, nullable=True)
    aperture_h_deg = db.Column(db.Integer, nullable=True)
    aperture_v_deg = db.Column(db.Integer, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    unidad = db.relationship("Unidad", backref="ap_celdas")

    __table_args__ = (
        db.UniqueConstraint("unidad_id", "cell_code", name="uq_ap_celdas_unidad_code"),
    )


class AnalisisPuntoEvento(db.Model):
    __tablename__ = "ap_eventos"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    fuente_id = db.Column(db.Integer, db.ForeignKey("ap_fuentes.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    source_type = db.Column(db.String(20), nullable=False, index=True)
    event_dt = db.Column(db.DateTime, nullable=True, index=True)
    event_date = db.Column(db.String(10), nullable=True, index=True)
    event_hour = db.Column(db.String(2), nullable=True, index=True)

    origin_msisdn = db.Column(db.String(64), nullable=True, index=True)
    target_msisdn = db.Column(db.String(64), nullable=True, index=True)
    imei = db.Column(db.String(64), nullable=True, index=True)
    imsi = db.Column(db.String(64), nullable=True, index=True)
    event_type = db.Column(db.String(50), nullable=True, index=True)
    duration_sec = db.Column(db.Integer, nullable=True)
    bytes_up = db.Column(db.BigInteger, nullable=True)
    bytes_down = db.Column(db.BigInteger, nullable=True)

    cell_id = db.Column(db.Integer, db.ForeignKey("ap_celdas.id"), nullable=True, index=True)
    raw_cell_code = db.Column(db.String(100), nullable=True, index=True)
    distance_to_cell_m = db.Column(db.Integer, nullable=True)
    inside_filter_radius = db.Column(db.Boolean, nullable=True)

    raw_payload_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="eventos", foreign_keys=[caso_id])
    fuente = db.relationship("AnalisisPuntoFuente", backref="eventos", foreign_keys=[fuente_id])
    unidad = db.relationship("Unidad", backref="ap_eventos")
    user = db.relationship("User", backref="ap_eventos")
    celda = db.relationship("AnalisisPuntoCelda", backref="eventos", foreign_keys=[cell_id])


class AnalisisPuntoTitular(db.Model):
    __tablename__ = "ap_titulares"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    fuente_id = db.Column(db.Integer, db.ForeignKey("ap_fuentes.id"), nullable=True, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)

    msisdn = db.Column(db.String(64), nullable=False, index=True)
    holder_name = db.Column(db.String(255), nullable=True)
    doc_number = db.Column(db.String(64), nullable=True, index=True)
    service_type = db.Column(db.String(100), nullable=True)
    market_type = db.Column(db.String(100), nullable=True)
    billing_address = db.Column(db.String(255), nullable=True)
    contact_phone = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="titulares", foreign_keys=[caso_id])
    fuente = db.relationship("AnalisisPuntoFuente", backref="titulares", foreign_keys=[fuente_id])
    unidad = db.relationship("Unidad", backref="ap_titulares")

    __table_args__ = (
        db.UniqueConstraint("caso_id", "msisdn", name="uq_ap_titulares_caso_msisdn"),
    )


class AnalisisPuntoCasoSujeto(db.Model):
    """Vínculo N:M entre caso Record y sujeto de Sábana."""
    __tablename__ = "ap_caso_sujetos"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    sujeto_id = db.Column(db.Integer, db.ForeignKey("sabana_sujetos.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    nota = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="caso_sujetos", foreign_keys=[caso_id])
    sujeto = db.relationship("Sujeto", backref="ap_caso_links", foreign_keys=[sujeto_id])
    unidad = db.relationship("Unidad", backref="ap_caso_sujetos")
    user = db.relationship("User", backref="ap_caso_sujetos")

    __table_args__ = (
        db.UniqueConstraint("caso_id", "sujeto_id", name="uq_ap_caso_sujetos"),
    )


class AnalisisPuntoCasoFuente(db.Model):
    """Legado: notas de relación migradas a ap_fuentes.relaciones_nota. Tabla conservada por compatibilidad."""
    __tablename__ = "ap_caso_fuentes"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    fuente_id = db.Column(db.Integer, db.ForeignKey("ap_fuentes.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    nota = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="caso_fuentes", foreign_keys=[caso_id])
    fuente = db.relationship("AnalisisPuntoFuente", backref="caso_links", foreign_keys=[fuente_id])
    unidad = db.relationship("Unidad", backref="ap_caso_fuentes")
    user = db.relationship("User", backref="ap_caso_fuentes")

    __table_args__ = (
        db.UniqueConstraint("caso_id", "fuente_id", name="uq_ap_caso_fuentes"),
    )


class AnalisisPuntoCasoNumero(db.Model):
    """Números de interés vinculados al caso (con opcional referencia a sujeto/fuente)."""
    __tablename__ = "ap_caso_numeros"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    msisdn = db.Column(db.String(64), nullable=False, index=True)
    sujeto_id = db.Column(db.Integer, db.ForeignKey("sabana_sujetos.id"), nullable=True, index=True)
    fuente_id = db.Column(db.Integer, db.ForeignKey("ap_fuentes.id"), nullable=True, index=True)
    nota = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="caso_numeros", foreign_keys=[caso_id])
    sujeto = db.relationship("Sujeto", backref="ap_numero_links", foreign_keys=[sujeto_id])
    fuente = db.relationship("AnalisisPuntoFuente", backref="numero_links", foreign_keys=[fuente_id])
    unidad = db.relationship("Unidad", backref="ap_caso_numeros")
    user = db.relationship("User", backref="ap_caso_numeros")

    __table_args__ = (
        db.UniqueConstraint("caso_id", "msisdn", "sujeto_id", "fuente_id", name="uq_ap_caso_numeros"),
    )


class AnalisisPuntoCasoMapaPunto(db.Model):
    """
    Punto de referencia geográfico vinculado a un caso (domicilio, encuentro, lugar del hecho, etc.).
    Visible en el mapa de Sábana/Record para el mismo caso.
    """

    __tablename__ = "ap_caso_mapa_puntos"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    # domicilio | encuentro | hecho | otro
    tipo = db.Column(db.String(40), nullable=False, index=True)
    etiqueta = db.Column(db.String(120), nullable=True)
    nota = db.Column(db.Text, nullable=True)
    # sabana | record — contexto en que se creó (informativo)
    origen_contexto = db.Column(db.String(20), nullable=True)
    # pin | casa | hecho | encuentro | auto | tienda | cruz — icono en mapa (clave corta)
    icono = db.Column(db.String(40), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    caso = db.relationship("AnalisisPuntoCaso", backref="mapa_puntos", foreign_keys=[caso_id])
    unidad = db.relationship("Unidad", backref="ap_caso_mapa_puntos")
    user = db.relationship("User", backref="ap_caso_mapa_puntos")

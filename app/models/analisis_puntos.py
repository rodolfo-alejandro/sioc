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
    estado = db.Column(db.String(20), nullable=False, default="ACTIVO", index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    unidad = db.relationship("Unidad", backref="ap_casos")
    user = db.relationship("User", backref="ap_casos")

    __table_args__ = (
        db.UniqueConstraint("unidad_id", "codigo", name="uq_ap_casos_unidad_codigo"),
    )


class AnalisisPuntoFuente(db.Model):
    __tablename__ = "ap_fuentes"

    id = db.Column(db.Integer, primary_key=True)
    caso_id = db.Column(db.Integer, db.ForeignKey("ap_casos.id"), nullable=False, index=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    source_type = db.Column(db.String(20), nullable=False, index=True)  # VOZ / GPRS
    nombre_archivo = db.Column(db.String(255), nullable=False)
    sha256 = db.Column(db.String(128), nullable=True, index=True)
    mime_type = db.Column(db.String(120), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)

    date_from = db.Column(db.DateTime, nullable=True, index=True)
    date_to = db.Column(db.DateTime, nullable=True, index=True)
    upload_status = db.Column(db.String(20), nullable=False, default="PENDING", index=True)
    error_detail = db.Column(db.Text, nullable=True)

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

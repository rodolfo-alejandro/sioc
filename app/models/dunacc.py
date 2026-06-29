"""
Modelos del módulo DUNACC.

Carga de planillas (Excel) que envía la unidad DUNACC. Cada fila se importa como
un registro georreferenciable. Algunas planillas traen latitud/longitud y otras no:
para esas últimas se permite cargar las coordenadas a mano (mapa Leaflet, pegado
manual o copiando desde Google Maps).
"""
from datetime import datetime

from app.extensions import db


class DunaccLote(db.Model):
    """Archivo Excel subido (respaldo descargable + agrupador de registros)."""

    __tablename__ = "dunacc_lotes"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    nombre_archivo = db.Column(db.String(255), nullable=False)  # nombre guardado en disco
    nombre_original = db.Column(db.String(255), nullable=True)
    sha1 = db.Column(db.String(64), nullable=True, index=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    total_registros = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    unidad = db.relationship("Unidad", backref="dunacc_lotes")
    user = db.relationship("User", backref="dunacc_lotes")


class DunaccLoteCompartido(db.Model):
    """Comparte una planilla (lote) con otra área/unidad para ver y editar coordenadas."""

    __tablename__ = "dunacc_lotes_compartidos"
    __table_args__ = (
        db.UniqueConstraint("lote_id", "unidad_destino_id", name="uq_dunacc_lote_compartido"),
    )

    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(
        db.Integer, db.ForeignKey("dunacc_lotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unidad_destino_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    compartido_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    lote = db.relationship("DunaccLote", backref=db.backref("compartidos", passive_deletes=True))
    unidad_destino = db.relationship("Unidad")


class DunaccRegistro(db.Model):
    """Una fila de la planilla DUNACC, georreferenciable."""

    __tablename__ = "dunacc_registros"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    lote_id = db.Column(
        db.Integer,
        db.ForeignKey("dunacc_lotes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    numero = db.Column(db.String(40), nullable=True)
    numero_ap = db.Column(db.String(60), nullable=True, index=True)
    dependencia = db.Column(db.String(255), nullable=True, index=True)
    caratula = db.Column(db.String(255), nullable=True, index=True)
    fecha = db.Column(db.Date, nullable=True, index=True)
    hora = db.Column(db.String(20), nullable=True)
    lugar = db.Column(db.Text, nullable=True)
    informante = db.Column(db.String(255), nullable=True)
    acusado = db.Column(db.String(255), nullable=True)
    relato = db.Column(db.Text, nullable=True)
    anio = db.Column(db.Integer, nullable=True, index=True)

    lat = db.Column(db.Float, nullable=True, index=True)
    lon = db.Column(db.Float, nullable=True, index=True)
    # Origen de las coordenadas: importadas | manual | mapa | geocode
    geo_origen = db.Column(db.String(20), nullable=True)

    # Hash de contenido para evitar reimportar la misma fila dentro de la unidad.
    dedupe_hash = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    unidad = db.relationship("Unidad", backref="dunacc_registros")
    user = db.relationship("User", backref="dunacc_registros")
    lote = db.relationship("DunaccLote", backref=db.backref("registros", passive_deletes=True))

    @property
    def tiene_coords(self) -> bool:
        return self.lat is not None and self.lon is not None

"""
Modelos del Monitor de Noticias (media monitoring por palabras clave).
"""
from datetime import datetime

from sqlalchemy import UniqueConstraint

from app.extensions import db


class TemaNoticia(db.Model):
    """Tema de búsqueda con sus palabras clave (ej. 'Droga - Resultados')."""

    __tablename__ = "monitor_noticias_temas"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    nombre = db.Column(db.String(120), nullable=False, index=True)
    palabras_clave = db.Column(db.Text, nullable=True)  # separadas por coma
    palabras_excluir = db.Column(db.Text, nullable=True)  # separadas por coma
    region = db.Column(db.String(120), nullable=True, default="Salta")
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def lista_claves(self) -> list[str]:
        return [p.strip() for p in (self.palabras_clave or "").split(",") if p.strip()]

    @property
    def lista_excluir(self) -> list[str]:
        return [p.strip() for p in (self.palabras_excluir or "").split(",") if p.strip()]


class FuenteNoticia(db.Model):
    """
    Origen de noticias.
    tipo = 'google_news' (busca con las palabras del tema) o 'rss' (feed directo a filtrar).
    """

    __tablename__ = "monitor_noticias_fuentes"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    nombre = db.Column(db.String(150), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False, default="google_news", index=True)
    url = db.Column(db.String(500), nullable=True)  # solo para tipo rss
    activo = db.Column(db.Boolean, nullable=False, default=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class Noticia(db.Model):
    """Resultado guardado de una búsqueda."""

    __tablename__ = "monitor_noticias_resultados"
    __table_args__ = (
        UniqueConstraint("unidad_id", "link_hash", name="uq_monitor_noticias_link"),
    )

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    tema_id = db.Column(
        db.Integer,
        db.ForeignKey("monitor_noticias_temas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    titulo = db.Column(db.String(600), nullable=False)
    link = db.Column(db.String(1000), nullable=False)
    link_hash = db.Column(db.String(64), nullable=False, index=True)
    medio = db.Column(db.String(200), nullable=True, index=True)
    resumen = db.Column(db.Text, nullable=True)
    publicado_en = db.Column(db.DateTime, nullable=True, index=True)

    estado = db.Column(db.String(20), nullable=False, default="nueva", index=True)  # nueva | relevante | descartada
    fuente_origen = db.Column(db.String(30), nullable=True)  # google_news | rss

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    tema = db.relationship("TemaNoticia", backref=db.backref("noticias", lazy="dynamic"))

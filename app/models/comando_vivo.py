"""
Centro de Comando / Operativos en vivo (piloto GPS + audio + video).
"""
from datetime import datetime

from app.extensions import db


class ComandoOperativo(db.Model):
    __tablename__ = "comando_operativos"

    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey("unidades.id"), nullable=False, index=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    nombre = db.Column(db.String(200), nullable=False)
    codigo = db.Column(db.String(12), nullable=False, unique=True, index=True)
    tipo = db.Column(db.String(80), nullable=True)  # allanamiento, procedimiento, etc.
    notas = db.Column(db.Text, nullable=True)
    # activo | cerrado
    estado = db.Column(db.String(20), nullable=False, default="activo", index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    participantes = db.relationship(
        "ComandoParticipante",
        backref="operativo",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    pings = db.relationship(
        "ComandoGpsPing",
        backref="operativo",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    audios = db.relationship(
        "ComandoAudioClip",
        backref="operativo",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    videos = db.relationship(
        "ComandoVideoClip",
        backref="operativo",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class ComandoParticipante(db.Model):
    __tablename__ = "comando_participantes"

    id = db.Column(db.Integer, primary_key=True)
    operativo_id = db.Column(
        db.Integer, db.ForeignKey("comando_operativos.id"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    alias = db.Column(db.String(120), nullable=False)
    device_id = db.Column(db.String(80), nullable=True, index=True)
    # Token para API móvil (sin sesión web)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)

    # online | offline | panico
    estado = db.Column(db.String(20), nullable=False, default="online", index=True)
    last_lat = db.Column(db.Float, nullable=True)
    last_lon = db.Column(db.Float, nullable=True)
    last_accuracy = db.Column(db.Float, nullable=True)
    last_battery = db.Column(db.Float, nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True, index=True)
    last_audio_at = db.Column(db.DateTime, nullable=True, index=True)
    last_video_at = db.Column(db.DateTime, nullable=True, index=True)
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    pings = db.relationship(
        "ComandoGpsPing",
        backref="participante",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    audios = db.relationship(
        "ComandoAudioClip",
        backref="participante",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    videos = db.relationship(
        "ComandoVideoClip",
        backref="participante",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class ComandoGpsPing(db.Model):
    __tablename__ = "comando_gps_pings"

    id = db.Column(db.Integer, primary_key=True)
    operativo_id = db.Column(
        db.Integer, db.ForeignKey("comando_operativos.id"), nullable=False, index=True
    )
    participante_id = db.Column(
        db.Integer, db.ForeignKey("comando_participantes.id"), nullable=False, index=True
    )

    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    accuracy = db.Column(db.Float, nullable=True)
    speed = db.Column(db.Float, nullable=True)
    heading = db.Column(db.Float, nullable=True)
    battery = db.Column(db.Float, nullable=True)
    # ping | panico
    evento = db.Column(db.String(20), nullable=False, default="ping", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index("ix_comando_gps_op_created", "operativo_id", "created_at"),
    )


class ComandoAudioClip(db.Model):
    """Fragmentos de audio subidos desde la app de campo (~3–5 s)."""

    __tablename__ = "comando_audio_clips"

    id = db.Column(db.Integer, primary_key=True)
    operativo_id = db.Column(
        db.Integer, db.ForeignKey("comando_operativos.id"), nullable=False, index=True
    )
    participante_id = db.Column(
        db.Integer, db.ForeignKey("comando_participantes.id"), nullable=False, index=True
    )

    # Ruta relativa bajo UPLOAD_FOLDER
    rel_path = db.Column(db.String(500), nullable=False)
    mime = db.Column(db.String(80), nullable=False, default="audio/webm")
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    duration_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index("ix_comando_audio_op_created", "operativo_id", "created_at"),
        db.Index("ix_comando_audio_part_created", "participante_id", "created_at"),
    )


class ComandoVideoClip(db.Model):
    """Fragmentos de video subidos desde la app de campo (~3–4 s)."""

    __tablename__ = "comando_video_clips"

    id = db.Column(db.Integer, primary_key=True)
    operativo_id = db.Column(
        db.Integer, db.ForeignKey("comando_operativos.id"), nullable=False, index=True
    )
    participante_id = db.Column(
        db.Integer, db.ForeignKey("comando_participantes.id"), nullable=False, index=True
    )

    rel_path = db.Column(db.String(500), nullable=False)
    mime = db.Column(db.String(80), nullable=False, default="video/webm")
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    duration_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index("ix_comando_video_op_created", "operativo_id", "created_at"),
        db.Index("ix_comando_video_part_created", "participante_id", "created_at"),
    )

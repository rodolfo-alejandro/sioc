"""
Modelos para el módulo de Entrevistas
"""
from datetime import datetime
from ..database.db import db


class EntrevistaPuertaPuerta(db.Model):
    """Entrevistas puerta a puerta realizadas por el personal"""
    __tablename__ = 'entrevistas_puerta_puerta'

    id = db.Column(db.Integer, primary_key=True)
    intervencion_id = db.Column(db.Integer, db.ForeignKey('intervenciones.id'), nullable=False)
    tipo_entrevista = db.Column(db.String(50), nullable=False)  # individual, grupal, reunion_vecinal
    nombre_reunion = db.Column(db.String(255))
    tema_principal = db.Column(db.String(100))
    lugar = db.Column(db.String(255))
    barrio_entrevista_id = db.Column(db.Integer, db.ForeignKey('barrios.id'))
    lat_entrevista = db.Column(db.Float)
    lng_entrevista = db.Column(db.Float)
    lugar_problematica = db.Column(db.String(255))
    barrio_problematica_id = db.Column(db.Integer, db.ForeignKey('barrios.id'))
    lat_problematica = db.Column(db.Float)
    lng_problematica = db.Column(db.Float)
    cantidad_personas = db.Column(db.Integer, default=1)
    observaciones = db.Column(db.Text)
    percepcion_seguridad = db.Column(db.String(50))
    consideracion_inseguridad = db.Column(db.Text)
    calificacion_servicio = db.Column(db.Integer)
    fecha_entrevista = db.Column(db.DateTime, default=datetime.utcnow)
    activa = db.Column(db.Boolean, default=True)

    barrio_entrevista = db.relationship(
        'Barrio',
        foreign_keys=[barrio_entrevista_id],
        backref='entrevistas_entrevista'
    )
    barrio_problematica = db.relationship(
        'Barrio',
        foreign_keys=[barrio_problematica_id],
        backref='entrevistas_problematica'
    )
    intervencion = db.relationship('Intervencion', backref='entrevistas_puerta_puerta')

    def __repr__(self) -> str:
        return f'<EntrevistaPuertaPuerta {self.tipo_entrevista} - {self.fecha_entrevista}>'


class PersonaEntrevista(db.Model):
    """Personas entrevistadas en entrevistas puerta a puerta"""
    __tablename__ = 'personas_entrevista'

    id = db.Column(db.Integer, primary_key=True)
    entrevista_id = db.Column(db.Integer, db.ForeignKey('entrevistas_puerta_puerta.id'), nullable=False)
    persona_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=True)
    nombre_anonimo = db.Column(db.String(255))
    apellido_anonimo = db.Column(db.String(255))
    telefono_anonimo = db.Column(db.String(20))
    sexo = db.Column(db.String(10))
    rango_edad = db.Column(db.String(50))
    rol_en_entrevista = db.Column(db.String(50))
    aportes = db.Column(db.Text)
    nivel_confianza = db.Column(db.String(20))
    fue_victima = db.Column(db.Boolean, default=False)
    radico_denuncia = db.Column(db.Boolean, default=False)
    llamo_911 = db.Column(db.Boolean, default=False)
    fecha_entrevista = db.Column(db.DateTime, default=datetime.utcnow)

    persona = db.relationship('Persona', backref='entrevistas_participadas')
    entrevista = db.relationship('EntrevistaPuertaPuerta', backref='personas_entrevistadas')

    def __repr__(self) -> str:
        return f'<PersonaEntrevista {self.id}>'


class CodigoQR(db.Model):
    """Códigos QR para formularios anónimos"""
    __tablename__ = 'codigos_qr'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(100), unique=True, nullable=False)
    tipo_formulario = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.String(255))
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_expiracion = db.Column(db.DateTime)
    intervencion_id = db.Column(db.Integer, db.ForeignKey('intervenciones.id'), nullable=True)

    intervencion = db.relationship('Intervencion', backref='codigos_qr')

    def __repr__(self) -> str:
        return f'<CodigoQR {self.codigo} - {self.tipo_formulario}>'


class RespuestaQR(db.Model):
    """Respuestas de formularios QR anónimos"""
    __tablename__ = 'respuestas_qr'

    id = db.Column(db.Integer, primary_key=True)
    codigo_qr_id = db.Column(db.Integer, db.ForeignKey('codigos_qr.id'), nullable=False)
    nombre_anonimo = db.Column(db.String(255))
    telefono_anonimo = db.Column(db.String(20))
    email_anonimo = db.Column(db.String(255))
    lugar_problematica = db.Column(db.String(255))
    lat_problematica = db.Column(db.Float)
    lng_problematica = db.Column(db.Float)
    tema_problematica = db.Column(db.String(100))
    sospechosos = db.Column(db.Text)
    aportes = db.Column(db.Text)
    nivel_confianza = db.Column(db.String(20))
    percepcion_seguridad = db.Column(db.String(50))
    frecuencia_problema = db.Column(db.String(50))
    horario_problema = db.Column(db.String(50))
    testigos = db.Column(db.String(50))
    acciones_previas = db.Column(db.String(100))
    efectividad_acciones = db.Column(db.String(50))
    sugerencias = db.Column(db.Text)
    calificacion_servicio = db.Column(db.Integer)
    archivos_adjuntos = db.Column(db.Text)
    cantidad_archivos = db.Column(db.Integer, default=0)
    fecha_respuesta = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))

    codigo_qr = db.relationship('CodigoQR', backref='respuestas')

    def __repr__(self) -> str:
        return f'<RespuestaQR {self.codigo_qr_id} - {self.fecha_respuesta}>'



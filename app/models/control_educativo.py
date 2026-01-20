"""
Modelos para Control Educativo
"""
from datetime import datetime
from ..database.db import db

class TipoEstablecimiento(db.Model):
    """Tipos de establecimientos educativos"""
    __tablename__ = 'tipos_establecimientos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TipoEstablecimiento {self.nombre}>'

class EstablecimientoEducativo(db.Model):
    """Establecimientos educativos"""
    __tablename__ = 'establecimientos_educativos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    cue = db.Column(db.String(20), unique=True)  # Código Único de Establecimiento
    tipo_establecimiento_id = db.Column(db.Integer, db.ForeignKey('tipos_establecimientos.id'))
    barrio_id = db.Column(db.Integer, db.ForeignKey('barrios.id'))
    domicilio = db.Column(db.String(200))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    latitud = db.Column(db.Float)
    longitud = db.Column(db.Float)
    nivel_educativo = db.Column(db.String(50))  # primario, secundario, terciario, universitario, mixto
    turnos = db.Column(db.String(100))  # mañana, tarde, noche, vespertino
    matricula_aproximada = db.Column(db.Integer)
    observaciones = db.Column(db.Text)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    tipo_establecimiento = db.relationship('TipoEstablecimiento', backref='establecimientos')
    barrio = db.relationship('Barrio', backref='establecimientos_educativos')
    unidad = db.relationship('Unidad', backref='establecimientos_educativos')
    controles = db.relationship('ControlEducativo', backref='establecimiento', lazy='dynamic')
    personal = db.relationship('PersonalEducativo', backref='establecimiento')
    
    @property
    def tipo_nombre(self):
        return self.tipo_establecimiento.nombre if self.tipo_establecimiento else 'Sin tipo'
    
    @property
    def barrio_nombre(self):
        return self.barrio.nombre if self.barrio else 'Sin barrio'

class CargoEducativo(db.Model):
    """Cargos en establecimientos educativos"""
    __tablename__ = 'cargos_educativos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<CargoEducativo {self.nombre}>'

class PersonalEducativo(db.Model):
    """Personal de establecimientos educativos"""
    __tablename__ = 'personal_educativo'
    
    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(20), nullable=False, unique=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    direccion = db.Column(db.String(200))
    cargo_id = db.Column(db.Integer, db.ForeignKey('cargos_educativos.id'))
    establecimiento_id = db.Column(db.Integer, db.ForeignKey('establecimientos_educativos.id'))
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    cargo = db.relationship('CargoEducativo', backref='personal')
    unidad = db.relationship('Unidad', backref='personal_educativo')
    
    @property
    def cargo_nombre(self):
        return self.cargo.nombre if self.cargo else 'Sin cargo'
    
    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"

class ControlEducativo(db.Model):
    """Controles en establecimientos educativos"""
    __tablename__ = 'controles_educativos'
    
    id = db.Column(db.Integer, primary_key=True)
    establecimiento_id = db.Column(db.Integer, db.ForeignKey('establecimientos_educativos.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    fecha_control = db.Column(db.DateTime, nullable=False)
    personal_presente = db.Column(db.Text)  # Personal presente durante el control
    observaciones = db.Column(db.Text)
    resultado = db.Column(db.String(50))  # Normal, Irregularidades, Clausura, etc.
    infracciones = db.Column(db.Text)  # Infracciones detectadas
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    usuario = db.relationship('User', backref='controles_educativos')
    unidad = db.relationship('Unidad', backref='controles_educativos')
    personal_entrevistado = db.relationship('PersonalEntrevistado', backref='control', cascade='all, delete-orphan')

class PersonalEntrevistado(db.Model):
    """Personal entrevistado durante controles educativos"""
    __tablename__ = 'personal_entrevistado'
    
    id = db.Column(db.Integer, primary_key=True)
    control_id = db.Column(db.Integer, db.ForeignKey('controles_educativos.id'), nullable=False)
    personal_id = db.Column(db.Integer, db.ForeignKey('personal_educativo.id'), nullable=False)
    declaracion = db.Column(db.Text)  # Declaración del entrevistado
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    personal = db.relationship('PersonalEducativo', backref='entrevistas')


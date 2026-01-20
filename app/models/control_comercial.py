"""
Modelos para Control Comercial
"""
from datetime import datetime, date, timedelta
from ..database.db import db

class RubroComercial(db.Model):
    """Rubros comerciales (restaurante, kiosco, farmacia, etc.)"""
    __tablename__ = 'rubros_comerciales'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<RubroComercial {self.nombre}>'

class Comercio(db.Model):
    """Comercios registrados en el sistema"""
    __tablename__ = 'comercios'
    
    id = db.Column(db.Integer, primary_key=True)
    denominacion = db.Column(db.String(200), nullable=False)
    rubro_id = db.Column(db.Integer, db.ForeignKey('rubros_comerciales.id'), nullable=False)
    domicilio = db.Column(db.String(300), nullable=False)
    latitud = db.Column(db.Float, nullable=False)
    longitud = db.Column(db.Float, nullable=False)
    barrio_id = db.Column(db.Integer, db.ForeignKey('barrios.id'))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    
    # Habilitaciones
    habilitacion_municipal = db.Column(db.Boolean, default=False)
    habilitacion_municipal_numero = db.Column(db.String(50))
    habilitacion_municipal_vencimiento = db.Column(db.Date)
    
    habilitacion_bomberos = db.Column(db.Boolean, default=False)
    habilitacion_bomberos_numero = db.Column(db.String(50))
    habilitacion_bomberos_vencimiento = db.Column(db.Date)
    
    habilitacion_bebidas = db.Column(db.Boolean, default=False)
    habilitacion_bebidas_numero = db.Column(db.String(50))
    habilitacion_bebidas_vencimiento = db.Column(db.Date)
    
    # Metadatos
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    rubro = db.relationship('RubroComercial', backref='comercios')
    barrio = db.relationship('Barrio', backref='comercios')
    unidad = db.relationship('Unidad', backref='comercios')
    propietarios = db.relationship('ComercioPropietario', backref='comercio', cascade='all, delete-orphan')
    encargados = db.relationship('ComercioEncargado', backref='comercio', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Comercio {self.denominacion}>'
    
    def tiene_habilitaciones_vencidas(self):
        """Verificar si tiene habilitaciones vencidas"""
        hoy = date.today()
        vencidas = []
        
        if self.habilitacion_municipal and self.habilitacion_municipal_vencimiento:
            if self.habilitacion_municipal_vencimiento < hoy:
                vencidas.append('Municipal')
        
        if self.habilitacion_bomberos and self.habilitacion_bomberos_vencimiento:
            if self.habilitacion_bomberos_vencimiento < hoy:
                vencidas.append('Bomberos')
        
        if self.habilitacion_bebidas and self.habilitacion_bebidas_vencimiento:
            if self.habilitacion_bebidas_vencimiento < hoy:
                vencidas.append('Bebidas Alcohólicas')
        
        return vencidas

class ComercioPropietario(db.Model):
    """Propietarios de comercios"""
    __tablename__ = 'comercios_propietarios'
    
    id = db.Column(db.Integer, primary_key=True)
    comercio_id = db.Column(db.Integer, db.ForeignKey('comercios.id'), nullable=False)
    persona_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=False)
    porcentaje = db.Column(db.Float, default=100.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    persona = db.relationship('Persona', backref='comercios_como_propietario')

class ComercioEncargado(db.Model):
    """Encargados de comercios"""
    __tablename__ = 'comercios_encargados'
    
    id = db.Column(db.Integer, primary_key=True)
    comercio_id = db.Column(db.Integer, db.ForeignKey('comercios.id'), nullable=False)
    persona_id = db.Column(db.Integer, db.ForeignKey('personas.id'), nullable=False)
    fecha_desde = db.Column(db.Date)
    fecha_hasta = db.Column(db.Date)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    persona = db.relationship('Persona', backref='comercios_como_encargado')

class InfraccionContravencional(db.Model):
    """Infracciones y contravenciones"""
    __tablename__ = 'infracciones_contravencionales'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(50))  # 'Infracción', 'Contravención'
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<InfraccionContravencional {self.codigo}>'

class ControlComercial(db.Model):
    """Controles realizados a comercios"""
    __tablename__ = 'controles_comerciales'
    
    id = db.Column(db.Integer, primary_key=True)
    comercio_id = db.Column(db.Integer, db.ForeignKey('comercios.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False)
    fecha_control = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    observaciones_control = db.Column(db.Text)
    resultado = db.Column(db.String(20))  # 'Conforme', 'Infracción', 'Clausura', etc.
    persona_presente_id = db.Column(db.Integer, db.ForeignKey('personas.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    comercio = db.relationship('Comercio', backref='controles')
    usuario = db.relationship('User', backref='controles_comerciales')
    unidad = db.relationship('Unidad', backref='controles_comerciales')
    persona_presente = db.relationship('Persona', foreign_keys=[persona_presente_id], backref='controles_comerciales_presente')
    infracciones = db.relationship('ControlComercialInfraccion', backref='control', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ControlComercial {self.comercio.denominacion} - {self.fecha_control}>'

class ControlComercialInfraccion(db.Model):
    """Infracciones detectadas en un control"""
    __tablename__ = 'controles_comerciales_infracciones'
    
    id = db.Column(db.Integer, primary_key=True)
    control_id = db.Column(db.Integer, db.ForeignKey('controles_comerciales.id'), nullable=False)
    infraccion_id = db.Column(db.Integer, db.ForeignKey('infracciones_contravencionales.id'), nullable=False)
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    infraccion = db.relationship('InfraccionContravencional', backref='aplicaciones')


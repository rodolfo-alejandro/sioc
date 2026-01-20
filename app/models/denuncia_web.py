"""
Modelo de Denuncia Web - Dirección General de Drogas Peligrosas
"""
from datetime import datetime
from app.extensions import db
import json


class DenunciaWeb(db.Model):
    """Modelo de denuncia web del sistema"""
    __tablename__ = 'denuncias_web'
    
    # Identificación
    id = db.Column(db.Integer, primary_key=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Campos principales del Excel
    id_excel = db.Column(db.String(50), nullable=True, index=True)  # ID del Excel
    numero_ap = db.Column(db.Float, nullable=True)
    
    # Fechas
    fecha_carga = db.Column(db.DateTime, nullable=True)
    fecha_registro = db.Column(db.DateTime, nullable=False, index=True)
    fecha_hecho = db.Column(db.DateTime, nullable=True)
    hora_hecho = db.Column(db.String(20), nullable=True)
    fecha_elevacion = db.Column(db.DateTime, nullable=True, index=True)
    fecha_ultima_actualizacion = db.Column(db.DateTime, nullable=True)
    
    # Organización
    departamento = db.Column(db.String(200), nullable=True, index=True)
    division = db.Column(db.String(200), nullable=True, index=True)
    sinar_a_cargo_ap = db.Column(db.String(100), nullable=True)
    sinar_a_cargo = db.Column(db.String(200), nullable=True)
    sector = db.Column(db.String(100), nullable=True)
    jurisdiccion = db.Column(db.String(200), nullable=True)
    distrito_prevencion = db.Column(db.String(100), nullable=True)
    localidad = db.Column(db.String(100), nullable=True)
    municipio = db.Column(db.String(100), nullable=True)
    t_departamental = db.Column(db.String(100), nullable=True)
    
    # Tipo y origen
    tipo_origen = db.Column(db.String(100), nullable=True, index=True)  # Denuncia Web, Informe Policial, Oficio Judicial
    
    # Ubicación
    lugar_hecho = db.Column(db.String(500), nullable=True)
    latitud_longitud = db.Column(db.String(100), nullable=True)
    barrio_id = db.Column(db.Float, nullable=True, index=True)  # ID del barrio
    nombre_barrio = db.Column(db.String(200), nullable=True, index=True)
    
    # Día y mes
    dia = db.Column(db.String(20), nullable=True)
    mes = db.Column(db.String(20), nullable=True, index=True)
    
    # Contenido
    caratula = db.Column(db.String(500), nullable=True)
    relato_hecho = db.Column(db.Text, nullable=True)
    
    # Judicial
    fiscalia = db.Column(db.String(200), nullable=True)
    juzgado = db.Column(db.String(200), nullable=True)
    causa_numero = db.Column(db.String(100), nullable=True)
    
    # Acusados (simplificado - guardar como JSON si hay múltiples)
    acusado = db.Column(db.String(200), nullable=True)
    edad = db.Column(db.Float, nullable=True)
    dni = db.Column(db.String(50), nullable=True)
    dlio = db.Column(db.String(500), nullable=True)  # Aumentado para direcciones largas
    alias = db.Column(db.String(200), nullable=True)
    acusados_json = db.Column(db.Text, nullable=True)  # Para acusado2, acusado3, etc.
    
    # Estado y avance
    estados = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.Float, nullable=True)
    estado_nombre = db.Column(db.String(200), nullable=True, index=True)
    avance = db.Column(db.Float, nullable=True, index=True)  # Porcentaje
    
    # Vinculaciones
    vinculada_a = db.Column(db.String(200), nullable=True)
    vinculada_con_ap = db.Column(db.String(200), nullable=True)
    
    # Acciones
    acciones_desplegadas = db.Column(db.Text, nullable=True)
    archivo_adjunto = db.Column(db.String(500), nullable=True)
    
    # Actuario
    actuario_id = db.Column(db.Float, nullable=True, index=True)  # ID del actuario
    nombre_actuario = db.Column(db.String(200), nullable=True, index=True)
    
    # Observaciones
    observaciones = db.Column(db.Text, nullable=True)
    
    # Campos calculados
    dias_investigacion = db.Column(db.Integer, nullable=True, index=True)  # Calculado
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relaciones
    unidad = db.relationship('Unidad', backref='denuncias_web')
    user = db.relationship('User', backref='denuncias_web')
    
    def calcular_dias_investigacion(self):
        """Calcula los días de investigación"""
        if not self.fecha_registro:
            return None
        
        try:
            fecha_fin = self.fecha_elevacion if self.fecha_elevacion else datetime.utcnow()
            if isinstance(fecha_fin, str):
                from dateutil import parser
                fecha_fin = parser.parse(fecha_fin)
            if isinstance(self.fecha_registro, str):
                from dateutil import parser
                fecha_registro = parser.parse(self.fecha_registro)
            else:
                fecha_registro = self.fecha_registro
            
            delta = fecha_fin - fecha_registro
            return max(0, delta.days)  # No permitir días negativos
        except Exception as e:
            return None
    
    def get_acusados(self):
        """Obtiene todos los acusados como lista"""
        acusados = []
        if self.acusado:
            acusados.append({
                'nombre': self.acusado,
                'edad': self.edad,
                'dni': self.dni,
                'dlio': self.dlio,
                'alias': self.alias
            })
        
        if self.acusados_json:
            try:
                otros = json.loads(self.acusados_json)
                acusados.extend(otros)
            except:
                pass
        
        return acusados
    
    def __repr__(self):
        return f'<DenunciaWeb {self.id_excel or self.id}>'
    
    def to_dict(self):
        """Convierte a diccionario para JSON"""
        return {
            'id': self.id,
            'id_excel': self.id_excel,
            'numero_ap': self.numero_ap,
            'fecha_registro': self.fecha_registro.isoformat() if self.fecha_registro else None,
            'departamento': self.departamento,
            'division': self.division,
            'tipo_origen': self.tipo_origen,
            'estado_nombre': self.estado_nombre,
            'avance': self.avance,
            'dias_investigacion': self.dias_investigacion,
            'nombre_barrio': self.nombre_barrio,
            'barrio_id': self.barrio_id,
            'nombre_actuario': self.nombre_actuario,
            'actuario_id': self.actuario_id
        }


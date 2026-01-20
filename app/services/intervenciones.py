"""
Servicio para lógica de negocio de Intervenciones
Toda la lógica pesada va aquí, no en las rutas
"""
from datetime import datetime
from sqlalchemy import and_, func
from ..database.db import db
from ..models.intervencion import Intervencion
from ..models.persona import Persona
from ..models.vehiculo import Vehiculo
from ..models.ubicacion import Ubicacion
from ..models.referencias import Sexo, Nacionalidad, EstadoCivil, Ocupacion, TipoContactoEmergencia
from ..models.vehiculos import MarcaVehiculo, ModeloVehiculo, ColorVehiculo, TipoVehiculo
from ..utils.datetime_utils import get_argentina_now

class IntervencionesService:
    """Servicio para operaciones de intervenciones"""
    
    def obtener_datos_referencia(self):
        """Obtiene todos los datos de referencia para formularios"""
        return {
            'sexos': Sexo.query.filter_by(activo=True).all(),
            'nacionalidades': Nacionalidad.query.filter_by(activo=True).all(),
            'estados_civiles': EstadoCivil.query.filter_by(activo=True).all(),
            'ocupaciones': Ocupacion.query.filter_by(activo=True).all(),
            'tipos_contacto': TipoContactoEmergencia.query.filter_by(activo=True).all()
        }
    
    def obtener_datos_referencia_vehiculos(self):
        """Obtiene datos de referencia para controles vehiculares"""
        return {
            'marcas': MarcaVehiculo.query.filter_by(activo=True).all(),
            'modelos': ModeloVehiculo.query.filter_by(activo=True).all(),
            'colores': ColorVehiculo.query.filter_by(activo=True).all(),
            'tipos_vehiculo': TipoVehiculo.query.filter_by(activo=True).all()
        }
    
    def crear_identificacion_persona(self, form_data, usuario_id, unidad_id):
        """
        Crea una identificación de persona
        Retorna: {'success': bool, 'dni': str, 'error': str}
        """
        try:
            dni = form_data.get('dni', '').strip()
            if not dni:
                return {'success': False, 'error': 'DNI es obligatorio'}
            
            # Validar coordenadas
            try:
                latitud = float(form_data.get('latitud', 0))
                longitud = float(form_data.get('longitud', 0))
            except (ValueError, TypeError):
                return {'success': False, 'error': 'Coordenadas inválidas'}
            
            if not latitud or not longitud:
                return {'success': False, 'error': 'Debe seleccionar ubicación en el mapa'}
            
            # Buscar o crear persona
            persona = Persona.query.filter_by(dni=dni).first()
            
            if not persona:
                # Crear nueva persona
                persona = Persona(
                    dni=dni,
                    nombre=form_data.get('nombre', '').strip(),
                    apellido=form_data.get('apellido', '').strip(),
                    fecha_nacimiento=self._parse_date(form_data.get('fecha_nacimiento')),
                    sexo_id=self._parse_int(form_data.get('sexo_id')),
                    nacionalidad_id=self._parse_int(form_data.get('nacionalidad_id')) or 1,  # Argentina por defecto
                    estado_civil_id=self._parse_int(form_data.get('estado_civil_id')),
                    ocupacion_id=self._parse_int(form_data.get('ocupacion_id')),
                    direccion=form_data.get('domicilio_persona', '').strip(),
                    telefono=form_data.get('telefono', '').strip(),
                    email=form_data.get('email', '').strip(),
                    contacto_emergencia_nombre=form_data.get('contacto_emergencia_nombre', '').strip(),
                    contacto_emergencia_telefono=form_data.get('contacto_emergencia_telefono', '').strip(),
                    contacto_emergencia_relacion_id=self._parse_int(form_data.get('contacto_emergencia_relacion_id'))
                )
                db.session.add(persona)
                db.session.flush()
            else:
                # Actualizar datos existentes
                self._actualizar_persona(persona, form_data)
            
            # Crear ubicación
            ubicacion = Ubicacion(
                latitud=latitud,
                longitud=longitud,
                barrio_id=self._parse_int(form_data.get('barrio_id'))
            )
            db.session.add(ubicacion)
            db.session.flush()
            
            # Crear intervención
            intervencion = Intervencion(
                tipo_intervencion='Identificación de Persona',
                usuario_id=usuario_id,
                unidad_id=unidad_id,
                persona_id=persona.id,
                ubicacion_id=ubicacion.id,
                fecha_hora=get_argentina_now(),
                observaciones=form_data.get('observaciones', '').strip()
            )
            db.session.add(intervencion)
            db.session.commit()
            
            return {'success': True, 'dni': dni, 'intervencion_id': intervencion.id}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': f'Error al crear identificación: {str(e)}'}
    
    def crear_control_vehicular(self, form_data, usuario_id, unidad_id):
        """
        Crea un control vehicular
        Retorna: {'success': bool, 'patente': str, 'error': str}
        """
        try:
            patente = form_data.get('patente', '').strip().upper()
            if not patente:
                return {'success': False, 'error': 'Patente es obligatoria'}
            
            # Validar coordenadas
            try:
                latitud = float(form_data.get('latitud', 0))
                longitud = float(form_data.get('longitud', 0))
            except (ValueError, TypeError):
                return {'success': False, 'error': 'Coordenadas inválidas'}
            
            # Buscar o crear vehículo
            vehiculo = Vehiculo.query.filter_by(patente=patente).first()
            
            if not vehiculo:
                vehiculo = Vehiculo(
                    patente=patente,
                    marca_id=self._parse_int(form_data.get('marca_id')),
                    modelo_id=self._parse_int(form_data.get('modelo_id')),
                    color_id=self._parse_int(form_data.get('color_id')),
                    tipo_vehiculo_id=self._parse_int(form_data.get('tipo_vehiculo_id'))
                )
                db.session.add(vehiculo)
                db.session.flush()
            
            # Si hay conductor, buscar o crear persona
            persona_id = None
            dni_conductor = form_data.get('dni_conductor', '').strip()
            if dni_conductor:
                persona = Persona.query.filter_by(dni=dni_conductor).first()
                if persona:
                    persona_id = persona.id
            
            # Crear ubicación
            ubicacion = Ubicacion(
                latitud=latitud,
                longitud=longitud,
                barrio_id=self._parse_int(form_data.get('barrio_id'))
            )
            db.session.add(ubicacion)
            db.session.flush()
            
            # Crear intervención
            intervencion = Intervencion(
                tipo_intervencion='Control Vehicular',
                usuario_id=usuario_id,
                unidad_id=unidad_id,
                vehiculo_id=vehiculo.id,
                persona_id=persona_id,
                ubicacion_id=ubicacion.id,
                fecha_hora=get_argentina_now(),
                observaciones=form_data.get('observaciones', '').strip()
            )
            db.session.add(intervencion)
            db.session.commit()
            
            return {'success': True, 'patente': patente, 'intervencion_id': intervencion.id}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': f'Error al crear control vehicular: {str(e)}'}
    
    def listar_intervenciones(self, unidad_id, usuario_id=None, tipo=None, fecha_desde=None, fecha_hasta=None):
        """Lista intervenciones con filtros"""
        query = Intervencion.query.filter_by(unidad_id=unidad_id)
        
        if usuario_id:
            query = query.filter_by(usuario_id=usuario_id)
        
        if tipo:
            query = query.filter_by(tipo_intervencion=tipo)
        
        if fecha_desde:
            query = query.filter(func.date(Intervencion.fecha_hora) >= fecha_desde)
        
        if fecha_hasta:
            query = query.filter(func.date(Intervencion.fecha_hora) <= fecha_hasta)
        
        return query.order_by(Intervencion.fecha_hora.desc()).all()
    
    def obtener_intervencion_por_id(self, intervencion_id, unidad_id):
        """Obtiene una intervención por ID (con verificación de unidad)"""
        return Intervencion.query.filter_by(
            id=intervencion_id,
            unidad_id=unidad_id
        ).first()
    
    def _actualizar_persona(self, persona, form_data):
        """Actualiza datos de una persona existente"""
        if form_data.get('nombre'):
            persona.nombre = form_data.get('nombre').strip()
        if form_data.get('apellido'):
            persona.apellido = form_data.get('apellido').strip()
        if form_data.get('domicilio_persona'):
            persona.direccion = form_data.get('domicilio_persona').strip()
        if form_data.get('telefono'):
            persona.telefono = form_data.get('telefono').strip()
        if form_data.get('email'):
            persona.email = form_data.get('email').strip()
        # ... más campos según necesidad
    
    def _parse_date(self, value):
        """Parsea una fecha desde string"""
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except:
            return None
    
    def _parse_int(self, value):
        """Parsea un entero desde string"""
        if not value:
            return None
        try:
            return int(value)
        except:
            return None


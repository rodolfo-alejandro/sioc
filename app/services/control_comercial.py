"""
Servicio para lógica de negocio de Control Comercial
Toda la lógica pesada va aquí, no en las rutas
"""
from datetime import datetime, date
from sqlalchemy import or_, func
from ..database.db import db
from ..models.control_comercial import (
    RubroComercial, Comercio, ComercioPropietario, ComercioEncargado,
    ControlComercial, InfraccionContravencional, ControlComercialInfraccion
)
from ..models.persona import Persona
from ..models.territorial import Barrio
from ..utils.datetime_utils import get_argentina_now

class ControlComercialService:
    """Servicio para operaciones de control comercial"""
    
    def obtener_datos_referencia(self):
        """Obtiene todos los datos de referencia para formularios"""
        return {
            'rubros': RubroComercial.query.filter_by(activo=True).all(),
            'barrios': Barrio.query.filter_by(activo=True).all(),
            'infracciones': InfraccionContravencional.query.filter_by(activo=True).all()
        }
    
    def crear_comercio(self, form_data, usuario_id, unidad_id):
        """
        Crea un nuevo comercio
        Retorna: {'success': bool, 'comercio_id': int, 'error': str}
        """
        try:
            # Validar coordenadas
            try:
                latitud = float(form_data.get('latitud', 0))
                longitud = float(form_data.get('longitud', 0))
            except (ValueError, TypeError):
                return {'success': False, 'error': 'Coordenadas inválidas'}
            
            if not latitud or not longitud:
                return {'success': False, 'error': 'Debe seleccionar ubicación en el mapa'}
            
            # Crear comercio
            comercio = Comercio(
                denominacion=form_data.get('denominacion', '').strip(),
                rubro_id=self._parse_int(form_data.get('rubro_id')),
                domicilio=form_data.get('domicilio', '').strip(),
                latitud=latitud,
                longitud=longitud,
                barrio_id=self._parse_int(form_data.get('barrio_id')),
                telefono=form_data.get('telefono', '').strip(),
                email=form_data.get('email', '').strip(),
                observaciones=form_data.get('observaciones', '').strip(),
                unidad_id=unidad_id,
                habilitacion_municipal=self._parse_bool(form_data.get('habilitacion_municipal')),
                habilitacion_municipal_numero=form_data.get('habilitacion_municipal_numero', '').strip(),
                habilitacion_municipal_vencimiento=self._parse_date(form_data.get('habilitacion_municipal_vencimiento')),
                habilitacion_bomberos=self._parse_bool(form_data.get('habilitacion_bomberos')),
                habilitacion_bomberos_numero=form_data.get('habilitacion_bomberos_numero', '').strip(),
                habilitacion_bomberos_vencimiento=self._parse_date(form_data.get('habilitacion_bomberos_vencimiento')),
                habilitacion_bebidas=self._parse_bool(form_data.get('habilitacion_bebidas')),
                habilitacion_bebidas_numero=form_data.get('habilitacion_bebidas_numero', '').strip(),
                habilitacion_bebidas_vencimiento=self._parse_date(form_data.get('habilitacion_bebidas_vencimiento'))
            )
            db.session.add(comercio)
            db.session.flush()
            
            # Agregar propietarios si hay
            dni_propietario = form_data.get('dni_propietario', '').strip()
            if dni_propietario:
                persona = Persona.query.filter_by(dni=dni_propietario).first()
                if persona:
                    propietario = ComercioPropietario(
                        comercio_id=comercio.id,
                        persona_id=persona.id,
                        porcentaje=float(form_data.get('porcentaje_propietario', 100))
                    )
                    db.session.add(propietario)
            
            db.session.commit()
            
            return {'success': True, 'comercio_id': comercio.id, 'denominacion': comercio.denominacion}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': f'Error al crear comercio: {str(e)}'}
    
    def crear_control(self, comercio_id, form_data, usuario_id, unidad_id):
        """
        Crea un control comercial
        Retorna: {'success': bool, 'control_id': int, 'error': str}
        """
        try:
            control = ControlComercial(
                comercio_id=comercio_id,
                usuario_id=usuario_id,
                unidad_id=unidad_id,
                fecha_control=get_argentina_now(),
                observaciones_control=form_data.get('observaciones_control', '').strip(),
                resultado=form_data.get('resultado', '').strip()
            )
            
            # Persona presente
            dni_presente = form_data.get('dni_presente', '').strip()
            if dni_presente:
                persona = Persona.query.filter_by(dni=dni_presente).first()
                if persona:
                    control.persona_presente_id = persona.id
            
            db.session.add(control)
            db.session.flush()
            
            # Agregar infracciones si hay
            infracciones_ids = form_data.getlist('infracciones[]')
            for infraccion_id in infracciones_ids:
                if infraccion_id:
                    control_infraccion = ControlComercialInfraccion(
                        control_id=control.id,
                        infraccion_id=int(infraccion_id),
                        observaciones=form_data.get(f'obs_infraccion_{infraccion_id}', '').strip()
                    )
                    db.session.add(control_infraccion)
            
            db.session.commit()
            
            return {'success': True, 'control_id': control.id}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': f'Error al crear control: {str(e)}'}
    
    def listar_comercios(self, unidad_id, rubro_id=None, barrio_id=None, buscar=None):
        """Lista comercios con filtros"""
        query = Comercio.query.filter_by(unidad_id=unidad_id, activo=True)
        
        if rubro_id:
            query = query.filter_by(rubro_id=rubro_id)
        
        if barrio_id:
            query = query.filter_by(barrio_id=barrio_id)
        
        if buscar:
            query = query.filter(
                or_(
                    Comercio.denominacion.ilike(f'%{buscar}%'),
                    Comercio.domicilio.ilike(f'%{buscar}%')
                )
            )
        
        return query.order_by(Comercio.denominacion).all()
    
    def obtener_comercio_por_id(self, comercio_id, unidad_id):
        """Obtiene un comercio por ID (con verificación de unidad)"""
        return Comercio.query.filter_by(
            id=comercio_id,
            unidad_id=unidad_id
        ).first()
    
    def listar_controles_comercio(self, comercio_id):
        """Lista controles de un comercio"""
        return ControlComercial.query.filter_by(
            comercio_id=comercio_id
        ).order_by(ControlComercial.fecha_control.desc()).all()
    
    def obtener_alertas(self, unidad_id):
        """Obtiene alertas de comercios (habilitaciones vencidas, etc.)"""
        comercios = Comercio.query.filter_by(unidad_id=unidad_id, activo=True).all()
        
        alertas = []
        hoy = date.today()
        
        for comercio in comercios:
            vencidas = comercio.tiene_habilitaciones_vencidas()
            if vencidas:
                alertas.append({
                    'comercio': comercio,
                    'tipo': 'habilitaciones_vencidas',
                    'detalle': vencidas
                })
        
        return alertas
    
    def _parse_int(self, value):
        """Parsea un entero desde string"""
        if not value:
            return None
        try:
            return int(value)
        except:
            return None
    
    def _parse_bool(self, value):
        """Parsea un booleano"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    
    def _parse_date(self, value):
        """Parsea una fecha desde string"""
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except:
            return None


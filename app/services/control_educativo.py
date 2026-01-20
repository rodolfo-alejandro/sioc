"""
Servicio para lógica de negocio de Control Educativo
Toda la lógica pesada va aquí, no en las rutas
"""
from datetime import datetime, date, timedelta
from sqlalchemy import or_, and_
from ..database.db import db
from ..models.control_educativo import (
    TipoEstablecimiento, EstablecimientoEducativo, CargoEducativo,
    PersonalEducativo, ControlEducativo, PersonalEntrevistado
)
from ..models.territorial import Barrio
from ..utils.datetime_utils import get_argentina_now

class ControlEducativoService:
    """Servicio para operaciones de control educativo"""
    
    def obtener_datos_referencia(self):
        """Obtiene todos los datos de referencia para formularios"""
        return {
            'tipos': TipoEstablecimiento.query.filter_by(activo=True).all(),
            'barrios': Barrio.query.filter_by(activo=True).all(),
            'cargos': CargoEducativo.query.filter_by(activo=True).all()
        }
    
    def crear_establecimiento(self, form_data, usuario_id, unidad_id):
        """
        Crea un nuevo establecimiento educativo
        Retorna: {'success': bool, 'establecimiento_id': int, 'error': str}
        """
        try:
            establecimiento = EstablecimientoEducativo(
                nombre=form_data.get('nombre', '').strip(),
                cue=form_data.get('cue', '').strip() or None,
                tipo_establecimiento_id=self._parse_int(form_data.get('tipo_establecimiento_id')),
                barrio_id=self._parse_int(form_data.get('barrio_id')),
                domicilio=form_data.get('domicilio', '').strip(),
                telefono=form_data.get('telefono', '').strip(),
                email=form_data.get('email', '').strip(),
                latitud=self._parse_float(form_data.get('latitud')),
                longitud=self._parse_float(form_data.get('longitud')),
                nivel_educativo=form_data.get('nivel_educativo', '').strip(),
                turnos=form_data.get('turnos', '').strip(),
                matricula_aproximada=self._parse_int(form_data.get('matricula_aproximada')),
                observaciones=form_data.get('observaciones', '').strip(),
                unidad_id=unidad_id
            )
            db.session.add(establecimiento)
            db.session.commit()
            
            return {'success': True, 'establecimiento_id': establecimiento.id}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': f'Error al crear establecimiento: {str(e)}'}
    
    def crear_control(self, establecimiento_id, form_data, usuario_id, unidad_id):
        """
        Crea un control educativo
        Retorna: {'success': bool, 'control_id': int, 'error': str}
        """
        try:
            control = ControlEducativo(
                establecimiento_id=establecimiento_id,
                usuario_id=usuario_id,
                unidad_id=unidad_id,
                fecha_control=get_argentina_now(),
                personal_presente=form_data.get('personal_presente', '').strip(),
                observaciones=form_data.get('observaciones', '').strip(),
                resultado=form_data.get('resultado', '').strip(),
                infracciones=form_data.get('infracciones', '').strip()
            )
            db.session.add(control)
            db.session.flush()
            
            # Agregar personal entrevistado si hay
            personal_ids = form_data.getlist('personal_entrevistado[]')
            for personal_id in personal_ids:
                if personal_id:
                    entrevistado = PersonalEntrevistado(
                        control_id=control.id,
                        personal_id=int(personal_id),
                        declaracion=form_data.get(f'declaracion_{personal_id}', '').strip(),
                        observaciones=form_data.get(f'obs_personal_{personal_id}', '').strip()
                    )
                    db.session.add(entrevistado)
            
            db.session.commit()
            
            return {'success': True, 'control_id': control.id}
            
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': f'Error al crear control: {str(e)}'}
    
    def listar_establecimientos(self, unidad_id, busqueda=None, tipo_id=None, barrio_id=None, nivel=None):
        """Lista establecimientos con filtros"""
        query = EstablecimientoEducativo.query.filter_by(unidad_id=unidad_id, activo=True)
        
        if busqueda:
            query = query.filter(
                or_(
                    EstablecimientoEducativo.nombre.ilike(f'%{busqueda}%'),
                    EstablecimientoEducativo.cue.ilike(f'%{busqueda}%'),
                    EstablecimientoEducativo.domicilio.ilike(f'%{busqueda}%')
                )
            )
        
        if tipo_id:
            query = query.filter_by(tipo_establecimiento_id=tipo_id)
        
        if barrio_id:
            query = query.filter_by(barrio_id=barrio_id)
        
        if nivel:
            query = query.filter_by(nivel_educativo=nivel)
        
        return query.order_by(EstablecimientoEducativo.nombre).all()
    
    def obtener_establecimiento_por_id(self, establecimiento_id, unidad_id):
        """Obtiene un establecimiento por ID (con verificación de unidad)"""
        return EstablecimientoEducativo.query.filter_by(
            id=establecimiento_id,
            unidad_id=unidad_id
        ).first()
    
    def listar_controles_establecimiento(self, establecimiento_id):
        """Lista controles de un establecimiento"""
        return ControlEducativo.query.filter_by(
            establecimiento_id=establecimiento_id
        ).order_by(ControlEducativo.fecha_control.desc()).all()
    
    def listar_personal_establecimiento(self, establecimiento_id):
        """Lista personal de un establecimiento"""
        return PersonalEducativo.query.filter_by(
            establecimiento_id=establecimiento_id,
            activo=True
        ).order_by(PersonalEducativo.apellido, PersonalEducativo.nombre).all()
    
    def _parse_int(self, value):
        """Parsea un entero desde string"""
        if not value:
            return None
        try:
            return int(value)
        except:
            return None
    
    def _parse_float(self, value):
        """Parsea un float desde string"""
        if not value:
            return None
        try:
            return float(value)
        except:
            return None


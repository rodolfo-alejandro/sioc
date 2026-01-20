"""
Servicio para lógica de negocio de Operativos Activos
"""
from ..database.db import db
from ..models.operativos import OperativoActivo, TipoOperativo
from ..utils.datetime_utils import get_argentina_now


class OperativosService:
    """Servicio para iniciar / finalizar operativos activos"""

    def obtener_tipos_operativo(self):
        return TipoOperativo.query.filter_by(activo=True).all()

    def obtener_operativo_activo(self, usuario_id: int):
        return OperativoActivo.query.filter_by(usuario_id=usuario_id, activo=True).first()

    def iniciar_operativo(self, usuario_id: int, tipo_operativo_id, nombre_operativo: str, descripcion: str):
        try:
            existente = self.obtener_operativo_activo(usuario_id)
            if existente:
                return {'success': False, 'error': 'Ya hay un operativo activo para este usuario.'}

            operativo = OperativoActivo(
                usuario_id=usuario_id,
                tipo_operativo_id=int(tipo_operativo_id) if tipo_operativo_id else None,
                nombre_operativo=nombre_operativo.strip(),
                descripcion=descripcion.strip() if descripcion else '',
                fecha_inicio=get_argentina_now()
            )
            db.session.add(operativo)
            db.session.commit()
            return {'success': True, 'operativo_id': operativo.id}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    def finalizar_operativo(self, usuario_id: int):
        try:
            operativo = self.obtener_operativo_activo(usuario_id)
            if not operativo:
                return {'success': False, 'error': 'No hay operativo activo.'}
            operativo.activo = False
            operativo.fecha_fin = get_argentina_now()
            db.session.commit()
            return {'success': True}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}



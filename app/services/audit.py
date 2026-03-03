"""
Servicio de Auditoría
"""
from flask import request, has_request_context
from flask_login import current_user
from app.extensions import db
from app.models.audit_log import AuditLog


def audit_log(action, details=None, user_id=None):
    """
    Registra una acción en el log de auditoría.
    
    Args:
        action: Nombre de la acción (ej: 'LOGIN', 'USER_CREATED', 'DATASET_UPLOADED')
        details: Detalles adicionales (opcional)
        user_id: ID del usuario (si None, usa current_user)
    """
    try:
        if user_id is None:
            # current_user requiere request context; fuera de request (scripts/CLI) dejamos user_id=None
            if has_request_context():
                user_id = current_user.id if current_user.is_authenticated else None
            else:
                user_id = None
        
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            details=details,
            ip=request.remote_addr if has_request_context() else None
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        # No fallar si la auditoría falla, pero registrar el error
        db.session.rollback()
        print(f"Error al registrar auditoría: {e}")


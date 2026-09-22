"""
Blueprint de auditoría de calidad (Denuncias Web + Intervenciones + Base Operativa).
"""
from flask import Blueprint

bp = Blueprint("auditoria", __name__, url_prefix="/auditoria")

from app.blueprints.auditoria import routes  # noqa: E402, F401
from app.blueprints.auditoria import intervenciones_routes  # noqa: E402, F401
from app.blueprints.auditoria import base_operativa_routes  # noqa: E402, F401

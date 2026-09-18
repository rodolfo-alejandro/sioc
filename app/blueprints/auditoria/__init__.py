"""
Blueprint para el módulo de auditoría.
Permite a auditores revisar y agregar observaciones sobre registros cargados.
"""
from flask import Blueprint

bp = Blueprint(
    "auditoria",
    __name__,
    template_folder="templates",
    url_prefix="/auditoria"
)

from app.blueprints.auditoria import routes

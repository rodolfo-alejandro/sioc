"""
Blueprint de auditoría de calidad (Denuncias Web).
"""
from flask import Blueprint

bp = Blueprint("auditoria", __name__, url_prefix="/auditoria")

from app.blueprints.auditoria import routes  # noqa: E402, F401

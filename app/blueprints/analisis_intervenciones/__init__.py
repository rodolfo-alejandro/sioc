"""
Blueprint de análisis de intervenciones.
"""
from flask import Blueprint

bp = Blueprint("analisis_intervenciones", __name__, url_prefix="/analisis-intervenciones")

from app.blueprints.analisis_intervenciones import routes

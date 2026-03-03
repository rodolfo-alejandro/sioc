"""
Blueprint Sabana de Llamadas - Análisis GPRS y VOZ
"""
from flask import Blueprint

bp = Blueprint('sabana_llamadas', __name__, url_prefix='/sabana-llamadas')

from app.blueprints.sabana_llamadas import routes

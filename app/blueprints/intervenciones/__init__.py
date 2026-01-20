"""
Blueprint para el módulo de Intervenciones
Maneja identificaciones de personas, controles vehiculares, etc.
"""
from flask import Blueprint

bp = Blueprint('intervenciones', __name__, url_prefix='/intervenciones')

from . import routes


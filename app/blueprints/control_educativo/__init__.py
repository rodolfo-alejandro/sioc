"""
Blueprint para el módulo de Control Educativo
Maneja registro de establecimientos educativos y controles
"""
from flask import Blueprint

bp = Blueprint('control_educativo', __name__, url_prefix='/control-educativo')

from . import routes


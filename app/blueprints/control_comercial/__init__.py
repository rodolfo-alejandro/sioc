"""
Blueprint para el módulo de Control Comercial
Maneja registro de comercios, controles e infracciones
"""
from flask import Blueprint

bp = Blueprint('control_comercial', __name__, url_prefix='/control-comercial')

from . import routes


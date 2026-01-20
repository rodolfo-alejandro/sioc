"""
Blueprint para el módulo de Relaciones
"""
from flask import Blueprint

bp = Blueprint('relaciones', __name__, url_prefix='/relaciones')

from . import routes



"""
Blueprint para el módulo de Operativos Activos
"""
from flask import Blueprint

bp = Blueprint('operativos', __name__, url_prefix='/operativos')

from . import routes



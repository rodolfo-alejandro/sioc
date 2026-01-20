"""
Blueprint para el módulo de Entrevistas
"""
from flask import Blueprint

bp = Blueprint('entrevistas', __name__, url_prefix='/entrevistas')

from . import routes



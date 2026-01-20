"""
Blueprint para el módulo de Grupos
"""
from flask import Blueprint

bp = Blueprint('grupos', __name__, url_prefix='/grupos')

from . import routes



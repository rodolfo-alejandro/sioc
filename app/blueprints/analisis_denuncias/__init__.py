"""
Blueprint de análisis de denuncias web.
"""
from flask import Blueprint

bp = Blueprint("analisis_denuncias", __name__, url_prefix="/analisis-denuncias")

from app.blueprints.analisis_denuncias import routes


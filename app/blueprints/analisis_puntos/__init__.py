from flask import Blueprint

bp = Blueprint("analisis_puntos", __name__, url_prefix="/analisis-puntos")

from app.blueprints.analisis_puntos import routes

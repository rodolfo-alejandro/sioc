from flask import Blueprint

bp = Blueprint("analisis_llamadas_se", __name__, url_prefix="/analisis-llamadas-se")

from app.blueprints.analisis_llamadas_se import routes


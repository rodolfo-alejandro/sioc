from flask import Blueprint

bp = Blueprint("oficios_judiciales", __name__, url_prefix="/oficios-judiciales")

from app.blueprints.oficios_judiciales import routes


from flask import Blueprint

bp = Blueprint("monitor_noticias", __name__, url_prefix="/monitor-noticias")

from app.blueprints.monitor_noticias import routes  # noqa: E402,F401

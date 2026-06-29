from flask import Blueprint

bp = Blueprint("dunacc", __name__, url_prefix="/dunacc")

from app.blueprints.dunacc import routes  # noqa: E402,F401

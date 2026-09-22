"""
Blueprint Base Operativa (Excel manual Capital / Interior).
"""
from flask import Blueprint

bp = Blueprint("base_operativa", __name__, url_prefix="/base-operativa")

from app.blueprints.base_operativa import routes  # noqa: E402, F401

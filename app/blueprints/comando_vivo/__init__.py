"""
Centro de Comando — Operativos en vivo (piloto GPS).
"""
from flask import Blueprint

bp = Blueprint("comando_vivo", __name__, url_prefix="/comando-vivo")

from app.blueprints.comando_vivo import routes  # noqa: E402, F401

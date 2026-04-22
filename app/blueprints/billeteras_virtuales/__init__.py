"""
Blueprint de billeteras virtuales.
"""
from flask import Blueprint

bp = Blueprint("billeteras_virtuales", __name__, url_prefix="/billeteras-virtuales")

from app.blueprints.billeteras_virtuales import routes

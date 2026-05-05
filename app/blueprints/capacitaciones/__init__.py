"""Módulo Capacitaciones / seminarios / control de asistencia."""

from flask import Blueprint

bp = Blueprint("capacitaciones", __name__, url_prefix="/capacitaciones")

from . import routes  # noqa: E402, F401

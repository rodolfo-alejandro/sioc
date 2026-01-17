"""
Blueprint de DataLab
"""
from flask import Blueprint

bp = Blueprint('datalab', __name__)

from app.blueprints.datalab import routes


"""
Utilidades de base de datos
"""
from app.extensions import db


def init_db():
    """Inicializa las tablas de la base de datos si no existen"""
    try:
        db.create_all()
    except Exception as e:
        print(f"Error al crear tablas: {e}")
        raise


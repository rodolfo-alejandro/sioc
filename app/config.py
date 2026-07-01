"""
Configuración de la aplicación SIOC
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Configuración base"""
    # Seguridad
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Base de datos
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://root:password@localhost/sioc_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pool_pre_ping: comprueba la conexión antes de usarla.
    # pool_recycle: recicla conexiones antes de que MySQL las cierre por inactividad.
    # Timeouts más altos para evitar 2013 (Lost connection / timed out) con MySQL en Docker o red lenta.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'connect_args': {
            'connect_timeout': 30,
            'read_timeout': 300,
            'write_timeout': 300,
        },
    }
    
    # Sesiones seguras
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hora
    
    # Uploads
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB (records grandes)
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'instance/uploads')
    ALLOWED_EXTENSIONS = {'xlsx', 'xlsm', 'csv'}
    
    # Admin por defecto
    DEFAULT_ADMIN_USERNAME = os.environ.get('DEFAULT_ADMIN_USERNAME', 'admin')
    DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'Admin123!')
    DEFAULT_ADMIN_EMAIL = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@sioc.local')


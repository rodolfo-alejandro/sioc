"""
SIOC - Sistema Integrado de Registro, Prevención, Investigación y Operaciones Conjuntas
"""
from flask import Flask
from flask_migrate import Migrate
from app.config import Config
from app.extensions import db, login_manager, csrf
from app.database.db import init_db
import os


def create_app(config_class=Config):
    """Factory function para crear la aplicación Flask"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Inicializar extensiones
    db.init_app(app)
    migrate = Migrate(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    
    # Configurar login manager
    from app.models.user import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor, inicia sesión para acceder a esta página.'
    login_manager.login_message_category = 'info'
    
    # Registrar blueprints
    from app.blueprints.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    from app.blueprints.core import bp as core_bp
    app.register_blueprint(core_bp, url_prefix='/')
    
    from app.blueprints.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
    from app.blueprints.datalab import bp as datalab_bp
    app.register_blueprint(datalab_bp, url_prefix='/datalab')
    
    # Crear directorios necesarios
    upload_folder = app.config.get('UPLOAD_FOLDER', 'instance/uploads')
    os.makedirs(upload_folder, exist_ok=True)
    
    # Agregar filtros personalizados de Jinja2
    @app.template_filter('number_format')
    def number_format_filter(value):
        """Formatea un número con separadores de miles"""
        try:
            return "{:,}".format(int(value))
        except (ValueError, TypeError):
            return str(value)
    
    # NO inicializar base de datos aquí - se hace con Flask-Migrate o create_admin.py
    # Esto evita problemas al importar la app antes de que la DB esté lista
    
    return app


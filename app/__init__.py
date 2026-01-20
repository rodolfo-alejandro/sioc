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
    
    from app.blueprints.intervenciones import bp as intervenciones_bp
    app.register_blueprint(intervenciones_bp, url_prefix='/intervenciones')
    
    from app.blueprints.control_comercial import bp as control_comercial_bp
    app.register_blueprint(control_comercial_bp, url_prefix='/control-comercial')
    
    from app.blueprints.control_educativo import bp as control_educativo_bp
    app.register_blueprint(control_educativo_bp, url_prefix='/control-educativo')

    from app.blueprints.entrevistas import bp as entrevistas_bp
    app.register_blueprint(entrevistas_bp, url_prefix='/entrevistas')

    from app.blueprints.grupos import bp as grupos_bp
    app.register_blueprint(grupos_bp, url_prefix='/grupos')

    from app.blueprints.relaciones import bp as relaciones_bp
    app.register_blueprint(relaciones_bp, url_prefix='/relaciones')

    from app.blueprints.operativos import bp as operativos_bp
    app.register_blueprint(operativos_bp, url_prefix='/operativos')
    
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
    
    # Agregar helper CSRF al contexto de templates
    @app.context_processor
    def inject_csrf_token():
        from flask import request
        from flask_wtf.csrf import generate_csrf
        def get_csrf_token():
            return generate_csrf()
        return dict(csrf_token=get_csrf_token)
    
    # NO inicializar base de datos aquí - se hace con Flask-Migrate o create_admin.py
    # Esto evita problemas al importar la app antes de que la DB esté lista
    
    return app


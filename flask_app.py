"""
Archivo para comandos Flask CLI (Flask-Migrate, etc.)
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run()


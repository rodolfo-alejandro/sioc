#!/usr/bin/env python
"""Script de prueba para iniciar el servidor y ver errores"""
import sys
from app import create_app

try:
    print("Creando aplicación...")
    app = create_app()
    print("Aplicación creada exitosamente")
    print("Iniciando servidor en http://127.0.0.1:5001")
    app.run(debug=True, host='127.0.0.1', port=5001, use_reloader=False)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)


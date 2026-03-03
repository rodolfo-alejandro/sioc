"""
Script para agregar la columna celda_id a sabana_datos_tecnicos (vista de impactos en el mapa).
Ejecutar desde la raíz del proyecto: python scripts/upgrade_sabana_impactos.py
"""
import sys
import os

# Raíz del proyecto = carpeta sioc
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from sqlalchemy import text


def main():
    app = create_app()
    with app.app_context():
        try:
            # Verificar si la columna ya existe (MySQL)
            r = db.session.execute(text("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'sabana_datos_tecnicos'
                  AND COLUMN_NAME = 'celda_id'
            """))
            exists = r.scalar() > 0
            if exists:
                print("La columna sabana_datos_tecnicos.celda_id ya existe. Nada que hacer.")
                return 0

            print("Agregando columna celda_id a sabana_datos_tecnicos...")
            db.session.execute(text("""
                ALTER TABLE sabana_datos_tecnicos
                ADD COLUMN celda_id VARCHAR(100) NULL AFTER tipo
            """))
            db.session.commit()
            print("Columna celda_id creada.")

            # Índice (puede fallar si ya existe)
            try:
                db.session.execute(text("""
                    CREATE INDEX ix_sabana_datos_tecnicos_celda_id
                    ON sabana_datos_tecnicos(celda_id)
                """))
                db.session.commit()
                print("Índice ix_sabana_datos_tecnicos_celda_id creado.")
            except Exception as e:
                if "Duplicate key name" in str(e) or "1061" in str(e):
                    print("El índice ya existía, se omite.")
                else:
                    raise

            print("Listo. La vista de impactos en el mapa ya puede usar celda_id.")
            return 0
        except Exception as e:
            db.session.rollback()
            print("Error:", e, file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())

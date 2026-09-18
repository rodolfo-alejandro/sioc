#!/usr/bin/env python3
"""
Script para agregar permisos del módulo de auditoría al sistema SIOC.
"""
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db
from app.models.permission import Permission
from app.models.role import Role

def add_auditoria_permissions():
    """Agrega los permisos necesarios para el módulo de auditoría"""
    app = create_app()
    
    with app.app_context():
        # Definir permisos de auditoría
        auditoria_permissions = [
            {
                'code': 'AUDITORIA_VIEW',
                'description': 'Ver panel de auditoría y observaciones'
            },
            {
                'code': 'AUDITORIA_CREATE',
                'description': 'Crear observaciones de auditoría'
            },
            {
                'code': 'AUDITORIA_RESOLVE',
                'description': 'Resolver y reabrir observaciones de auditoría'
            },
        ]
        
        print("=" * 60)
        print("Agregando permisos del módulo de auditoría...")
        print("=" * 60)
        
        added = 0
        existing = 0
        
        for perm_data in auditoria_permissions:
            # Verificar si ya existe
            existing_perm = Permission.query.filter_by(code=perm_data['code']).first()
            
            if existing_perm:
                print(f"✓ Permiso ya existe: {perm_data['code']}")
                existing += 1
            else:
                # Crear el permiso
                new_perm = Permission(
                    code=perm_data['code'],
                    description=perm_data['description']
                )
                db.session.add(new_perm)
                print(f"+ Agregado permiso: {perm_data['code']}")
                added += 1
        
        # Commit de los cambios
        db.session.commit()
        
        print("\n" + "=" * 60)
        print(f"Resumen:")
        print(f"  - Permisos nuevos agregados: {added}")
        print(f"  - Permisos ya existentes: {existing}")
        print("=" * 60)
        
        # Asignar permisos al rol SUPERADMIN
        superadmin_role = Role.query.filter_by(name='SUPERADMIN').first()
        if superadmin_role:
            print("\nAsignando permisos a rol SUPERADMIN...")
            for perm_data in auditoria_permissions:
                perm = Permission.query.filter_by(code=perm_data['code']).first()
                if perm and perm not in superadmin_role.permissions:
                    superadmin_role.permissions.append(perm)
                    print(f"  + {perm.code} → SUPERADMIN")
            db.session.commit()
            print("✓ Permisos asignados a SUPERADMIN")
        
        print("\n¡Permisos de auditoría configurados exitosamente!")
        print("\nPróximos pasos:")
        print("1. Asigne los permisos a los roles que correspondan")
        print("2. Los usuarios con permisos podrán acceder a /auditoria")
        print("\nPermisos disponibles:")
        print("  - AUDITORIA_VIEW: Ver panel y observaciones")
        print("  - AUDITORIA_CREATE: Crear observaciones")
        print("  - AUDITORIA_RESOLVE: Resolver observaciones")

if __name__ == '__main__':
    add_auditoria_permissions()

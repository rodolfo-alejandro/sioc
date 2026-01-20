"""
Script para crear usuarios con permisos para Denuncias Web
"""
import sys
from app import create_app
from app.extensions import db
from app.models.unidad import Unidad
from app.models.user import User
from app.models.role import Role


def create_users():
    """Crea dos usuarios con permisos para Denuncias Web"""
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("SIOC - Creación de usuarios para Denuncias Web")
        print("=" * 60)
        
        # Obtener o crear unidad Central
        unidad = Unidad.query.filter_by(nombre='Central').first()
        if not unidad:
            unidad = Unidad(nombre='Central', activo=True)
            db.session.add(unidad)
            db.session.commit()
            print("✓ Unidad 'Central' creada")
        else:
            print("✓ Unidad 'Central' ya existe")
        
        # Obtener rol ANALISTA (tiene DATALAB_UPLOAD y DATALAB_VIEW)
        analista_role = Role.query.filter_by(name='ANALISTA').first()
        if not analista_role:
            print("✗ Error: El rol 'ANALISTA' no existe. Ejecutá primero 'python create_admin.py'")
            return False
        
        print(f"✓ Rol 'ANALISTA' encontrado (tiene permisos DATALAB_UPLOAD y DATALAB_VIEW)")
        
        # Crear usuario 1
        print("\n[1/2] Creando usuario 1...")
        username1 = "analista1"
        password1 = "Analista123!"
        email1 = "analista1@sioc.local"
        
        user1 = User.query.filter_by(username=username1).first()
        if user1:
            print(f"  ⚠ Usuario '{username1}' ya existe. Actualizando contraseña...")
            user1.set_password(password1)
            user1.email = email1
            user1.active = True
            # Asegurar que tenga el rol ANALISTA
            if analista_role not in user1.roles:
                user1.roles.append(analista_role)
        else:
            user1 = User(
                username=username1,
                email=email1,
                unidad_id=unidad.id,
                active=True
            )
            user1.set_password(password1)
            user1.roles.append(analista_role)
            db.session.add(user1)
        
        db.session.commit()
        print(f"✓ Usuario '{username1}' creado/actualizado")
        
        # Crear usuario 2
        print("\n[2/2] Creando usuario 2...")
        username2 = "analista2"
        password2 = "Analista123!"
        email2 = "analista2@sioc.local"
        
        user2 = User.query.filter_by(username=username2).first()
        if user2:
            print(f"  ⚠ Usuario '{username2}' ya existe. Actualizando contraseña...")
            user2.set_password(password2)
            user2.email = email2
            user2.active = True
            # Asegurar que tenga el rol ANALISTA
            if analista_role not in user2.roles:
                user2.roles.append(analista_role)
        else:
            user2 = User(
                username=username2,
                email=email2,
                unidad_id=unidad.id,
                active=True
            )
            user2.set_password(password2)
            user2.roles.append(analista_role)
            db.session.add(user2)
        
        db.session.commit()
        print(f"✓ Usuario '{username2}' creado/actualizado")
        
        # Mostrar resumen
        print("\n" + "=" * 60)
        print("✓ Usuarios creados correctamente")
        print("=" * 60)
        print("\nCredenciales de acceso:")
        print("\n--- Usuario 1 ---")
        print(f"  Usuario: {username1}")
        print(f"  Contraseña: {password1}")
        print(f"  Email: {email1}")
        print(f"  Rol: ANALISTA")
        print(f"  Permisos: DATALAB_UPLOAD, DATALAB_VIEW")
        print("\n--- Usuario 2 ---")
        print(f"  Usuario: {username2}")
        print(f"  Contraseña: {password2}")
        print(f"  Email: {email2}")
        print(f"  Rol: ANALISTA")
        print(f"  Permisos: DATALAB_UPLOAD, DATALAB_VIEW")
        print("\n▲ IMPORTANTE: Cambien las contraseñas después del primer inicio de sesión")
        print("=" * 60)
        
        return True


if __name__ == '__main__':
    try:
        success = create_users()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


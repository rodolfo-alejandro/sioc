"""
Script para crear usuario administrador y datos semilla del sistema SIOC
"""
import os
import sys
import time
from app import create_app
from app.extensions import db
from app.models.unidad import Unidad
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.config import Config


def wait_for_db(app, max_attempts=30):
    """Espera a que la base de datos esté disponible"""
    print("Esperando a que la base de datos esté disponible...")
    for attempt in range(max_attempts):
        try:
            with app.app_context():
                db.engine.connect()
            print("✓ Base de datos disponible")
            return True
        except Exception as e:
            if attempt < max_attempts - 1:
                print(f"  Intento {attempt + 1}/{max_attempts}...")
                time.sleep(2)
            else:
                print(f"✗ No se pudo conectar a la base de datos: {e}")
                print("\nVerifique que:")
                print("  1. MySQL esté ejecutándose (docker compose up -d mysql)")
                print("  2. Las credenciales en .env sean correctas")
                print("  3. El contenedor MySQL esté saludable (docker compose ps)")
                return False
    return False


def create_seed_data():
    """Crea los datos semilla del sistema"""
    app = create_app()
    
    # Esperar a que la base de datos esté lista
    if not wait_for_db(app):
        return False
    
    with app.app_context():
        print("=" * 60)
        print("SIOC - Creación de datos semilla")
        print("=" * 60)
        
        # Crear tablas si no existen
        print("\n[1/6] Creando tablas de base de datos...")
        try:
            db.create_all()
            print("✓ Tablas creadas correctamente")
        except Exception as e:
            print(f"✗ Error al crear tablas: {e}")
            print("\nDetalles del error:")
            import traceback
            traceback.print_exc()
            return False
        
        # Crear unidad "Central"
        print("\n[2/6] Creando unidad 'Central'...")
        unidad = Unidad.query.filter_by(nombre='Central').first()
        if not unidad:
            unidad = Unidad(nombre='Central', activo=True)
            db.session.add(unidad)
            db.session.commit()
            print("✓ Unidad 'Central' creada")
        else:
            print("✓ Unidad 'Central' ya existe")
        
        # Crear permisos
        print("\n[3/6] Creando permisos...")
        permisos = [
            ('CORE_VIEW', 'Ver dashboard principal'),
            ('DATALAB_UPLOAD', 'Subir datasets al DataLab'),
            ('DATALAB_VIEW', 'Ver datasets del DataLab'),
            ('ADMIN_USERS', 'Administrar usuarios'),
            ('ADMIN_ROLES', 'Administrar roles'),
            # Permisos de Intervenciones
            ('INTERVENCIONES_CREATE', 'Crear intervenciones'),
            ('INTERVENCIONES_VIEW', 'Ver intervenciones propias'),
            ('INTERVENCIONES_VIEW_ALL', 'Ver todas las intervenciones de la unidad'),
            # Permisos de Control Comercial
            ('CONTROL_COMERCIAL_CREATE', 'Crear comercios y controles'),
            ('CONTROL_COMERCIAL_VIEW', 'Ver comercios y controles'),
            # Permisos de Control Educativo
            ('CONTROL_EDUCATIVO_CREATE', 'Crear establecimientos y controles educativos'),
            ('CONTROL_EDUCATIVO_VIEW', 'Ver establecimientos y controles educativos'),
            # Permisos de Entrevistas
            ('ENTREVISTAS_VIEW', 'Ver entrevistas'),
            ('ENTREVISTAS_CREATE', 'Crear entrevistas'),
            # Permisos de Grupos
            ('GRUPOS_VIEW', 'Ver grupos'),
            ('GRUPOS_CREATE', 'Crear grupos'),
            # Permisos de Relaciones
            ('RELACIONES_VIEW', 'Ver relaciones entre personas'),
            # Permisos de Operativos
            ('OPERATIVOS_VIEW', 'Ver estado de operativos'),
            ('OPERATIVOS_CREATE', 'Iniciar y finalizar operativos'),
        ]
        
        permisos_creados = {}
        for code, description in permisos:
            perm = Permission.query.filter_by(code=code).first()
            if not perm:
                perm = Permission(code=code, description=description)
                db.session.add(perm)
                permisos_creados[code] = perm
            else:
                permisos_creados[code] = perm
                print(f"  - Permiso '{code}' ya existe")
        
        db.session.commit()
        print(f"✓ {len(permisos_creados)} permisos creados/verificados")
        
        # Crear roles
        print("\n[4/6] Creando roles...")
        
        # SUPERADMIN - todos los permisos
        superadmin_role = Role.query.filter_by(name='SUPERADMIN').first()
        if not superadmin_role:
            superadmin_role = Role(name='SUPERADMIN', description='Administrador con todos los permisos')
            db.session.add(superadmin_role)
            for perm in permisos_creados.values():
                superadmin_role.permissions.append(perm)
            db.session.commit()
            print("✓ Rol 'SUPERADMIN' creado con todos los permisos")
        else:
            print("✓ Rol 'SUPERADMIN' ya existe")
        
        # ADMIN - permisos de administración y datalab
        admin_role = Role.query.filter_by(name='ADMIN').first()
        if not admin_role:
            admin_role = Role(name='ADMIN', description='Administrador de unidad')
            db.session.add(admin_role)
            admin_perms = ['CORE_VIEW', 'DATALAB_UPLOAD', 'DATALAB_VIEW', 'ADMIN_USERS', 
                          'INTERVENCIONES_CREATE', 'INTERVENCIONES_VIEW', 'INTERVENCIONES_VIEW_ALL',
                          'CONTROL_COMERCIAL_CREATE', 'CONTROL_COMERCIAL_VIEW',
                          'CONTROL_EDUCATIVO_CREATE', 'CONTROL_EDUCATIVO_VIEW',
                          'ENTREVISTAS_VIEW', 'ENTREVISTAS_CREATE',
                          'GRUPOS_VIEW', 'GRUPOS_CREATE',
                          'RELACIONES_VIEW',
                          'OPERATIVOS_VIEW', 'OPERATIVOS_CREATE']
            for perm_code in admin_perms:
                if perm_code in permisos_creados:
                    admin_role.permissions.append(permisos_creados[perm_code])
            db.session.commit()
            print("✓ Rol 'ADMIN' creado")
        else:
            print("✓ Rol 'ADMIN' ya existe")
        
        # ANALISTA - solo datalab
        analista_role = Role.query.filter_by(name='ANALISTA').first()
        if not analista_role:
            analista_role = Role(name='ANALISTA', description='Analista de datos')
            db.session.add(analista_role)
            analista_perms = ['CORE_VIEW', 'DATALAB_VIEW', 'DATALAB_UPLOAD']
            for perm_code in analista_perms:
                if perm_code in permisos_creados:
                    analista_role.permissions.append(permisos_creados[perm_code])
            db.session.commit()
            print("✓ Rol 'ANALISTA' creado")
        else:
            print("✓ Rol 'ANALISTA' ya existe")
        
        # Crear usuario administrador
        print("\n[5/6] Creando usuario administrador...")
        admin_username = Config.DEFAULT_ADMIN_USERNAME
        admin_password = Config.DEFAULT_ADMIN_PASSWORD
        admin_email = Config.DEFAULT_ADMIN_EMAIL
        
        admin_user = User.query.filter_by(username=admin_username).first()
        if not admin_user:
            admin_user = User(
                username=admin_username,
                email=admin_email,
                unidad_id=unidad.id,
                active=True,
                must_change_password=True
            )
            admin_user.set_password(admin_password)
            admin_user.roles.append(superadmin_role)
            db.session.add(admin_user)
            db.session.commit()
            print(f"✓ Usuario '{admin_username}' creado")
        else:
            # Actualizar contraseña si es necesario
            if not admin_user.check_password(admin_password):
                admin_user.set_password(admin_password)
                admin_user.must_change_password = True
                db.session.commit()
                print(f"✓ Contraseña de '{admin_username}' actualizada")
            else:
                print(f"✓ Usuario '{admin_username}' ya existe")
        
        # Verificar que tiene el rol SUPERADMIN
        if not admin_user.has_role('SUPERADMIN'):
            admin_user.roles.append(superadmin_role)
            db.session.commit()
            print(f"✓ Rol SUPERADMIN asignado a '{admin_username}'")
        
        # Resumen
        print("\n[6/6] Resumen:")
        print("=" * 60)
        print(f"Unidad creada: {Unidad.query.count()}")
        print(f"Permisos creados: {Permission.query.count()}")
        print(f"Roles creados: {Role.query.count()}")
        print(f"Usuarios creados: {User.query.count()}")
        print("\n" + "=" * 60)
        print("✓ Datos semilla creados correctamente")
        print("=" * 60)
        print(f"\nCredenciales de acceso:")
        print(f"  Usuario: {admin_username}")
        print(f"  Contraseña: {admin_password}")
        print(f"  Email: {admin_email}")
        print("\n⚠️  IMPORTANTE: Cambie la contraseña después del primer inicio de sesión")
        print("=" * 60)
        
        return True


if __name__ == '__main__':
    try:
        success = create_seed_data()
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


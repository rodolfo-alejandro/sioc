# Guía de Instalación del Módulo de Auditoría

## Estado Actual

✅ **Código completado y commiteado localmente**
- Commit hash: `1e7cec6`
- Branch: `main`
- Archivos: 14 archivos creados/modificados
- Líneas: 2,165 líneas de código agregadas

## Pasos para Despliegue en Servidor

### 1. Subir Cambios a GitHub

Desde tu PC con acceso al repositorio, ejecuta:

```bash
cd /ruta/a/tu/proyecto/sioc
git pull origin main
git push origin main
```

O si estás trabajando directamente en el servidor:

```bash
cd /workspace/sioc
# Configura tus credenciales de GitHub si no lo has hecho
git config user.name "Tu Nombre"
git config user.email "tu@email.com"

# Intenta push nuevamente
git push origin main
```

### 2. En el Servidor de Producción

```bash
# Navegar al directorio del proyecto
cd /ruta/a/sioc

# Hacer backup de la base de datos
# (recomendado antes de cualquier cambio)

# Traer los cambios
git pull origin main

# Activar entorno virtual si usas uno
source venv/bin/activate  # o el comando correspondiente

# Instalar dependencias (si hubiera nuevas)
pip install -r requirements.txt

# Ejecutar script de permisos
python scripts/add_auditoria_permissions.py

# Reiniciar la aplicación
# Depende de cómo esté corriendo (systemd, docker, etc.)
# Ejemplos:
sudo systemctl restart sioc
# o
docker-compose restart
# o
sudo supervisorctl restart sioc
```

### 3. Crear las Tablas de Auditoría

Si usas Flask-Migrate:

```bash
flask db migrate -m "Agregar tablas de auditoría"
flask db upgrade
```

Si NO usas Flask-Migrate, las tablas se crearán automáticamente la primera vez que accedas al módulo (gracias a `_ensure_schema()`).

### 4. Configurar Permisos de Usuarios

1. **Acceder al Panel de Administración**
   - URL: `https://tu-servidor/admin/roles`
   - Login como SUPERADMIN

2. **Asignar Permisos a Roles**
   
   **Para Jefes/Auditores:**
   - ✅ AUDITORIA_VIEW
   - ✅ AUDITORIA_CREATE
   - ✅ AUDITORIA_RESOLVE
   
   **Para Personal Operativo (opcional):**
   - ✅ AUDITORIA_VIEW (solo si necesitan ver observaciones)

### 5. Verificar la Instalación

1. **Login con usuario que tenga permisos**
2. **Verificar menú lateral**: Debe aparecer "Auditoría" con icono de clipboard
3. **Acceder a** `/auditoria`
4. **Verificar que carguen:**
   - Panel principal
   - Denuncias Web
   - Intervenciones
   - Estadísticas

### 6. Pruebas Funcionales

1. **Ir a Auditoría → Denuncias Web**
2. **Seleccionar agrupación** (ej: por Dependencia)
3. **Ver detalle de un grupo**
4. **Entrar al detalle de una denuncia**
5. **Agregar una observación general**
6. **Agregar una observación sobre un campo específico**
7. **Resolver la observación**
8. **Verificar en Estadísticas** que aparezcan los contadores

## Estructura de Archivos Nuevos

```
sioc/
├── app/
│   ├── blueprints/
│   │   └── auditoria/
│   │       ├── __init__.py
│   │       ├── routes.py
│   │       └── templates/
│   │           └── auditoria/
│   │               ├── index.html
│   │               ├── denuncias_web.html
│   │               ├── denuncias_web_grupo.html
│   │               ├── denuncias_web_detalle.html
│   │               ├── intervenciones.html
│   │               └── estadisticas.html
│   └── models/
│       └── auditoria.py
├── scripts/
│   └── add_auditoria_permissions.py
├── AUDITORIA_README.md
└── INSTALACION_AUDITORIA.md (este archivo)
```

## Archivos Modificados

```
app/__init__.py                              -> Registro del blueprint
app/models/__init__.py                       -> Importación de modelos
app/templates/layouts/partials_sidebar.html  -> Menú de auditoría
```

## Rollback (en caso de problemas)

Si necesitas revertir los cambios:

```bash
cd /workspace/sioc

# Ver los últimos commits
git log --oneline

# Revertir al commit anterior
git revert 1e7cec6

# O hacer reset (más drástico)
git reset --hard HEAD~1

# Hacer push del rollback
git push origin main --force
```

## Solución de Problemas Comunes

### Error: "No module named 'app.blueprints.auditoria'"
**Solución**: Asegúrate de reiniciar la aplicación después de hacer pull.

### Error: "Table doesn't exist"
**Solución**: 
1. Ejecuta las migraciones o
2. Accede a `/auditoria` para que se creen automáticamente

### Error: "No tiene permisos para acceder a auditoría"
**Solución**: 
1. Ejecuta `python scripts/add_auditoria_permissions.py`
2. Asigna los permisos al rol del usuario en `/admin/roles`

### El menú no aparece
**Solución**:
1. Verifica que el usuario tenga el permiso `AUDITORIA_VIEW`
2. Limpia la caché del navegador (Ctrl+F5)
3. Revisa los logs de la aplicación

## Soporte

Para consultas o problemas:
1. Revisar logs de la aplicación
2. Verificar configuración de base de datos
3. Consultar `AUDITORIA_README.md` para documentación completa

---

**Fecha de instalación**: 18/09/2026
**Desarrollado para**: SIOC - Sistema Integrado

# SIOC - Sistema Integrado de Registro, Prevención, Investigación y Operaciones Conjuntas

Sistema web modular, profesional, seguro y escalable para gestión operativa y análisis de datos.

## 🎯 Características Principales

- **Registro Operativo**: Módulos para identificaciones, controles vehiculares, comercios, establecimientos e intervenciones
- **Prevención**: Estadísticas, alertas y reportes
- **Investigación**: Módulos para escuchas, relaciones y evidencias (futuro)
- **Operaciones Conjuntas**: Gestión de recursos y seguimiento en tiempo real (futuro)
- **DataLab**: Módulo funcional para subir archivos Excel/CSV y generar estadísticas y gráficos automáticamente

## 🛠️ Stack Tecnológico

### Backend
- Python 3.11+
- Flask (con Blueprints)
- SQLAlchemy + Flask-Migrate
- Flask-Login (autenticación)
- Flask-WTF (CSRF protection)
- Werkzeug (password hashing)

### Base de Datos
- MySQL/MariaDB (con PyMySQL)

### Frontend
- Jinja2 (templates)
- Bootstrap 5
- Bootstrap Icons
- JavaScript vanilla
- Plotly (gráficos)

### Procesamiento de Datos
- pandas
- openpyxl
- python-dateutil

## 📋 Requisitos Previos

- **Python 3.11+** instalado
- **Docker** y **Docker Compose** instalados
- **Git** (opcional, para clonar el repositorio)

## 🚀 Instalación y Ejecución

### Opción 1: Ejecutar TODO con Docker (Más Simple) ⭐

Ejecuta MySQL y Flask en contenedores Docker:

**Linux/Mac:**
```bash
cd sioc
chmod +x scripts/run_docker.sh
./scripts/run_docker.sh
```

**Windows (PowerShell):**
```powershell
cd sioc
.\scripts\run_docker.ps1
```

O manualmente:
```bash
docker compose up -d --build
docker compose exec flask python create_admin.py
```

La aplicación estará disponible en: **http://localhost:5001**

**Ver logs:**
```bash
docker compose logs -f flask
```

**Detener servicios:**
```bash
docker compose down
```

### Opción 2: MySQL en Docker + Flask Local (Desarrollo)

**Linux/Mac:**
```bash
cd sioc
chmod +x scripts/dev_up.sh
./scripts/dev_up.sh
```

**Windows (PowerShell):**
```powershell
cd sioc
.\scripts\dev_up.ps1
```

El script automático:
1. ✅ Crea el archivo `.env` desde `env.example`
2. ✅ Levanta MySQL en Docker
3. ✅ Crea el entorno virtual de Python
4. ✅ Instala todas las dependencias
5. ✅ Inicializa la base de datos y crea datos semilla

**Luego ejecuta Flask localmente:**
```bash
# Activar entorno virtual
.\venv\Scripts\Activate.ps1  # Windows
source venv/bin/activate     # Linux/Mac

# Ejecutar aplicación
python run.py
```

La aplicación estará disponible en: **http://localhost:5001**

### Opción B: Instalación Manual

#### 1. Configurar variables de entorno

**Linux/Mac:**
```bash
cp env.example .env
```

**Windows:**
```powershell
copy env.example .env
```

Edite `.env` y ajuste los valores si es necesario (por defecto funciona con Docker).

#### 2. Levantar MySQL en Docker

```bash
docker compose up -d mysql
```

Esto crea un contenedor MySQL 8.0 con:
- Base de datos: `sioc_db`
- Usuario: `sioc_user`
- Contraseña: `sioc_password`
- Root password: `sioc_root_password`
- Puerto: `3306`
- Volumen persistente: `mysql_data`

#### 3. Crear entorno virtual

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

#### 4. Instalar dependencias

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 5. Inicializar base de datos

```bash
python create_admin.py
```

Este script:
- ✅ Espera a que MySQL esté disponible
- ✅ Crea todas las tablas necesarias
- ✅ Crea la unidad "Central"
- ✅ Crea los permisos del sistema
- ✅ Crea los roles (SUPERADMIN, ADMIN, ANALISTA)
- ✅ Crea el usuario administrador por defecto

#### 6. Ejecutar la aplicación

```bash
python run.py
```

La aplicación estará disponible en: **http://localhost:5001**

## 🔐 Credenciales por Defecto

- **Usuario**: `admin`
- **Contraseña**: `Admin123!`
- **Email**: `admin@sioc.local`

⚠️ **IMPORTANTE**: Cambie la contraseña después del primer inicio de sesión.

## 📁 Estructura del Proyecto

```
sioc/
├── app/
│   ├── __init__.py          # Factory de la aplicación
│   ├── config.py             # Configuración
│   ├── extensions.py         # Extensiones de Flask
│   ├── database/
│   │   └── db.py            # Utilidades de BD
│   ├── models/               # Modelos de datos
│   │   ├── user.py
│   │   ├── role.py
│   │   ├── permission.py
│   │   ├── unidad.py
│   │   ├── audit_log.py
│   │   └── dataset.py
│   ├── services/             # Lógica de negocio
│   │   ├── rbac.py          # Control de acceso
│   │   ├── audit.py         # Auditoría
│   │   ├── file_storage.py  # Almacenamiento
│   │   ├── datalab_profiler.py
│   │   ├── datalab_charts.py
│   │   └── utils.py
│   ├── blueprints/          # Módulos (blueprints)
│   │   ├── auth/           # Autenticación
│   │   ├── core/           # Dashboard
│   │   ├── admin/          # Administración
│   │   └── datalab/        # DataLab
│   ├── templates/          # Templates Jinja2
│   │   ├── layouts/
│   │   ├── auth/
│   │   ├── core/
│   │   ├── admin/
│   │   └── datalab/
│   └── static/             # Archivos estáticos
│       ├── css/
│       └── js/
├── instance/
│   └── uploads/            # Archivos subidos (creado automáticamente)
├── create_admin.py          # Script de bootstrap
├── run.py                   # Punto de entrada
├── requirements.txt         # Dependencias
└── README.md               # Este archivo
```

## 🔒 Sistema de Permisos (RBAC)

### Permisos Disponibles

- `CORE_VIEW`: Ver dashboard principal
- `DATALAB_UPLOAD`: Subir datasets al DataLab
- `DATALAB_VIEW`: Ver datasets del DataLab
- `ADMIN_USERS`: Administrar usuarios
- `ADMIN_ROLES`: Administrar roles

### Roles Predefinidos

- **SUPERADMIN**: Todos los permisos
- **ADMIN**: CORE_VIEW, DATALAB_*, ADMIN_USERS
- **ANALISTA**: CORE_VIEW, DATALAB_VIEW, DATALAB_UPLOAD

## 📊 Módulo DataLab

El módulo DataLab permite:

1. **Subir archivos**: Excel (.xlsx, .xlsm) o CSV (máx. 20MB)
2. **Procesamiento automático**:
   - Normalización de nombres de columnas
   - Detección automática de fechas
   - Generación de perfil estadístico
   - Generación de gráficos automáticos
3. **Visualización**:
   - Vista previa de datos (primeras 100 filas)
   - Gráficos interactivos con Plotly
   - Perfil de columnas (tipos, nulos, estadísticas)

### Características del Procesamiento

- **Normalización de columnas**: Espacios → guiones bajos, minúsculas, eliminación de caracteres especiales
- **Detección de fechas**: Basada en nombres de columnas (fecha, date, datetime, etc.)
- **Perfil estadístico**: Tipos, nulos, valores únicos, estadísticas numéricas, top valores categóricos
- **Gráficos automáticos**: Barras (categóricas), histogramas (numéricas), líneas temporales (fecha + numérica)

## 🏢 Modelo Organizacional

El sistema está organizado por **Unidades**:

- Cada usuario pertenece a una unidad
- Los datasets están aislados por unidad (solo se ven los de la misma unidad)
- Los administradores pueden gestionar usuarios de su unidad (o globalmente si son SUPERADMIN)

## 🔍 Auditoría

El sistema registra automáticamente:

- Inicios y cierres de sesión
- Creación y edición de usuarios
- Subida de datasets
- Acceso a datasets
- Cambios de contraseña

Los logs se almacenan en la tabla `audit_logs`.

## 🎨 Interfaz de Usuario

- **Diseño consistente**: Todas las páginas heredan un layout único
- **Responsive**: Adaptado para desktop y mobile
- **Sidebar colapsable**: En desktop y offcanvas en mobile
- **Buscador global**: Filtra elementos del menú en tiempo real
- **Tema institucional**: Gris/azul suave, profesional

## 📞 Módulo Sabana de Llamadas

Módulo para análisis de tráfico GPRS y VOZ (sabanas de llamadas):

- **Sujetos**: Personas de interés (apodo, nombre, DNI, imagen). Se pueden crear sin identificación previa y completar datos después.
- **Cargas**: Importación de archivos Excel (.xls, .xlsx) GPRS o VOZ, con vinculación opcional a un sujeto.
- **Mapa**: Visualización de geolocalización (lat/long) de datos técnicos, con **filtros de múltiple selección** (checkboxes por sujetos, cargas y tipo GPRS/VOZ).

- **Mapa (vista impactos)**: Cada pin es una celda (antena). Al hacer clic se listan todos los registros de tráfico en esa celda; al elegir "Ver" en uno se muestra el detalle completo del registro.

Permisos: `SABANA_LLAMADAS_VIEW`, `SABANA_LLAMADAS_UPLOAD`. Rutas bajo `/sabana-llamadas/`. HTML, JS y CSS en archivos separados (sin inline).

Si la base de datos ya existía antes de añadir la vista de impactos, agregar la columna para enlazar celdas con tráfico:  
`ALTER TABLE sabana_datos_tecnicos ADD COLUMN celda_id VARCHAR(100) NULL AFTER tipo;`  
(opcional: `CREATE INDEX ix_sabana_datos_tecnicos_celda_id ON sabana_datos_tecnicos(celda_id);`). Las cargas nuevas rellenan `celda_id` automáticamente desde la hoja "Datos Tecnicos" (columna CeldaID).

## 🚧 Módulos Futuros (Placeholders)

Los siguientes módulos están preparados en el menú pero aún no implementados:

- **Registro**: Personas, Vehículos, Comercios, Establecimientos, Intervenciones
- **Prevención**: Estadísticas, Alertas, Reportes
- **Investigación**: Escuchas, Relaciones, Evidencias
- **Operaciones**: Recursos, Seguimiento

## 🐳 Gestión de Docker

### Comandos útiles

**Ver estado de los contenedores:**
```bash
docker compose ps
```

**Ver logs de MySQL:**
```bash
docker compose logs mysql
```

**Detener MySQL:**
```bash
docker compose stop mysql
```

**Iniciar MySQL:**
```bash
docker compose start mysql
```

**Si la app demora mucho o sale "Lost connection to MySQL" (2013 / timed out):**
- Comprobar que MySQL esté en marcha: `docker compose ps` (o Docker Desktop).
- Si usas Flask local, levantar primero MySQL: `docker compose up -d mysql` y esperar unos segundos.
- En `app/config.py` los timeouts están en 30 s (conexión) y 60 s (lectura/escritura); si sigue fallando, se pueden subir.
- La API de ruta limita a 5000 puntos (si hay más, se muestrean de todo el recorrido). En el mapa se dibujan como máximo ~600 marcadores numerados para no saturar; la línea y el Play usan todos los puntos. La API de celdas limita a 1500.

**Eliminar contenedor y datos (⚠️ CUIDADO):**
```bash
docker compose down -v
```

**Acceder a MySQL directamente:**
```bash
# Linux/Mac
./scripts/db_shell.sh

# Windows
.\scripts\db_shell.ps1
```

O manualmente:
```bash
docker compose exec mysql mysql -u root -psioc_root_password sioc_db
```

## 🔧 Configuración Avanzada

### Migraciones de Base de Datos

El proyecto usa `db.create_all()` en `create_admin.py` para crear las tablas inicialmente.

Si desea usar Flask-Migrate para gestionar cambios en el esquema:

```bash
# Activar entorno virtual primero
source venv/bin/activate  # Linux/Mac
# o
.\venv\Scripts\Activate.ps1  # Windows

# Inicializar migraciones (solo la primera vez)
flask db init

# Crear migración
flask db migrate -m "Descripción del cambio"

# Aplicar migración
flask db upgrade
```

**Nota**: Si usa Flask-Migrate, comente la línea `db.create_all()` en `create_admin.py` después de la primera ejecución.

### Producción

Para producción, considere:

1. Cambiar `SECRET_KEY` a una clave segura y aleatoria
2. Configurar `SESSION_COOKIE_SECURE=True` (requiere HTTPS)
3. Usar un servidor WSGI (Gunicorn, uWSGI)
4. Configurar un servidor web (Nginx, Apache)
5. Configurar SSL/TLS
6. Ajustar límites de upload según necesidades
7. Implementar backups regulares de la base de datos

## 🐛 Solución de Problemas

### Error de conexión a la base de datos

**Síntoma**: `OperationalError`, `Can't connect to MySQL server`

**Soluciones**:
1. Verifique que el contenedor MySQL esté ejecutándose:
   ```bash
   docker compose ps
   ```
   Debe mostrar `sioc_mysql` como `Up`.

2. Si no está ejecutándose, inícielo:
   ```bash
   docker compose up -d mysql
   ```

3. Verifique los logs si hay errores:
   ```bash
   docker compose logs mysql
   ```

4. Verifique que las credenciales en `.env` coincidan con `docker-compose.yml`:
   - Usuario: `sioc_user`
   - Contraseña: `sioc_password`
   - Base de datos: `sioc_db`
   - Host: `localhost`
   - Puerto: `3306`

5. Pruebe la conexión manualmente:
   ```bash
   docker compose exec mysql mysql -u sioc_user -psioc_password sioc_db -e "SELECT 1;"
   ```

### Error al crear tablas

**Síntoma**: `create_admin.py` falla al crear tablas

**Soluciones**:
1. Asegúrese de que MySQL esté completamente iniciado (espere 10-15 segundos después de `docker compose up`)
2. Verifique que la base de datos exista:
   ```bash
   docker compose exec mysql mysql -u root -psioc_root_password -e "SHOW DATABASES;"
   ```
3. Si la base de datos no existe, recree el contenedor:
   ```bash
   docker compose down -v
   docker compose up -d mysql
   # Esperar 15 segundos
   python create_admin.py
   ```

### Error al subir archivos

**Síntoma**: Error 413 o "Archivo demasiado grande"

**Soluciones**:
1. Verifique que el directorio `instance/uploads` exista y tenga permisos de escritura
2. Verifique el tamaño del archivo (máx. 20MB por defecto, configurable en `.env`)
3. Verifique que el formato sea .xlsx, .xlsm o .csv
4. Aumente `MAX_CONTENT_LENGTH` en `.env` si es necesario (en bytes)

### Error de permisos (RBAC)

**Síntoma**: "403 Forbidden" o "Sin permisos"

**Soluciones**:
1. Verifique que el usuario tenga los permisos necesarios:
   - Inicie sesión como `admin` (SUPERADMIN tiene todos los permisos)
   - Vaya a Admin > Usuarios y verifique los roles asignados
2. Verifique que el rol tenga los permisos correctos:
   - Vaya a Admin > Roles
   - Verifique que el rol tenga los permisos necesarios asignados

### Error "ModuleNotFoundError" o importaciones

**Síntoma**: `ModuleNotFoundError: No module named 'app'`

**Soluciones**:
1. Asegúrese de estar en el directorio raíz del proyecto (`sioc/`)
2. Asegúrese de tener el entorno virtual activado:
   ```bash
   source venv/bin/activate  # Linux/Mac
   .\venv\Scripts\Activate.ps1  # Windows
   ```
3. Verifique que todas las dependencias estén instaladas:
   ```bash
   pip install -r requirements.txt
   ```

### Puerto 3306 ya en uso

**Síntoma**: `Error: bind: address already in use` al levantar MySQL

**Soluciones**:
1. Verifique si hay otra instancia de MySQL ejecutándose:
   ```bash
   # Linux/Mac
   lsof -i :3306
   
   # Windows
   netstat -ano | findstr :3306
   ```
2. Detenga el servicio MySQL local o cambie el puerto en `docker-compose.yml`:
   ```yaml
   ports:
     - "3307:3306"  # Cambiar 3306 a 3307
   ```
   Y actualice `DATABASE_URL` en `.env` a `localhost:3307`

### El contenedor MySQL se reinicia constantemente

**Síntoma**: `docker compose ps` muestra `Restarting`

**Soluciones**:
1. Verifique los logs:
   ```bash
   docker compose logs mysql
   ```
2. Verifique que no haya conflictos de volúmenes:
   ```bash
   docker compose down -v
   docker compose up -d mysql
   ```
3. Verifique permisos del volumen (Linux/Mac):
   ```bash
   sudo chown -R $USER:$USER .
   ```

## ✅ Verificación Rápida

Para verificar que todo esté configurado correctamente:

**Linux/Mac:**
```bash
chmod +x scripts/verify_setup.sh
./scripts/verify_setup.sh
```

**Windows:**
```powershell
# Ejecutar manualmente las verificaciones o usar el script de PowerShell
```

## 📝 Notas Importantes

1. **Primera ejecución**: El script `create_admin.py` espera automáticamente a que MySQL esté disponible (hasta 60 segundos).

2. **Volúmenes Docker**: Los datos de MySQL se almacenan en un volumen Docker persistente. Si elimina el contenedor con `docker compose down -v`, perderá todos los datos.

3. **Archivos subidos**: Los archivos del DataLab se guardan en `instance/uploads/` organizados por `unidad_id`. Este directorio se crea automáticamente.

4. **Flask-Migrate**: El proyecto usa `db.create_all()` para la inicialización. Si desea usar Flask-Migrate, ejecute:
   ```bash
   flask db init
   flask db migrate -m "Initial migration"
   flask db upgrade
   ```

## 📝 Licencia

Este proyecto es de uso interno.

## 👥 Soporte

Para soporte o consultas, contacte al equipo de desarrollo.

---

**Versión**: 1.0.0  
**Última actualización**: 2024


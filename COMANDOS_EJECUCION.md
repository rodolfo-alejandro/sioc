# Comandos para ejecutar SIOC

## Build colgado en `pip install` (recomendado: no usar build en local)

Si el build se queda mucho rato en **`RUN pip install -r requirements.txt`** (por ejemplo 15–30 min), suele ser porque **dentro del contenedor** la descarga de PyPI va muy lenta (~25 kB/s). Eso pasa a veces en Docker Desktop en Windows (red del contenedor lenta).

**Por qué antes no pasaba:** puede ser que antes tenías la imagen ya construida (caché), que cambiaron actualizaciones de Docker/Windows, o que la red/PyPI desde el contenedor ahora va más lenta.

**Solución recomendada en local:** no construyas la imagen de Flask. Usá solo MySQL en Docker y corré la app en tu PC (Opción 2 abajo). Así `pip install` lo hacés una vez en tu máquina, que suele ir mucho más rápido, y no volvés a construir la imagen.

```powershell
# Cortar el build si sigue corriendo: Ctrl+C

cd C:\Dev\MSA_SIOC\sioc
docker compose up -d mysql
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python create_admin.py
python run.py
```

App en http://localhost:5001. Para el servidor (Digital Ocean) el build suele ir bien porque la red del VPS es estable; en local esta opción evita el problema.

---

## ¿Por qué el build de Docker puede tardar?

- **Primera vez:** se descarga la imagen base `python:3.11-slim` (~150 MB) y se instalan las dependencias de Python. Puede llevar varios minutos según tu conexión.
- **Este proyecto ya no instala** `gcc` ni `libmysqlclient-dev` (usamos PyMySQL, que es puro Python), así que el build es más liviano.
- **Alternativa sin build:** corré solo MySQL en Docker y Flask en tu PC con un venv (ver Opción 2). Así no construís la imagen de la app en local.

---

## Local (tu PC con Docker Desktop)

### Opción 1: Todo con Docker (MySQL + Flask en contenedores)

Desde la carpeta del proyecto:

```powershell
cd C:\Dev\MSA_SIOC\sioc

# Levantar MySQL y Flask
docker compose up -d --build

# Primera vez (o tras agregar modelos): crear tablas y admin
docker compose exec flask python create_admin.py

# Ver logs de la app
docker compose logs -f flask
```

- **App:** http://localhost:5001  
- **MySQL:** localhost:3308 (usuario `sioc_user`, contraseña `sioc_password`, base `sioc_db`)

**Detener:**
```powershell
docker compose down
```

### Opción 2: Solo MySQL en Docker + Flask en tu PC (más rápido, sin build)

No construís la imagen de Flask; solo levantás la base de datos y corrés la app con tu entorno virtual. Ideal para desarrollo y para evitar builds lentos.

```powershell
cd C:\Dev\MSA_SIOC\sioc

# Solo MySQL
docker compose up -d mysql

# Una sola vez: crear venv y .env si no existen
if (-not (Test-Path venv)) { python -m venv venv }
if (-not (Test-Path .env)) { copy env.example .env }
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python create_admin.py

# Ejecutar la app (cada vez que quieras trabajar)
.\venv\Scripts\Activate.ps1
python run.py
```

App en http://localhost:5001. El `.env` debe apuntar a `localhost:3308` (puerto de MySQL en tu PC).

---

## Servidor (Digital Ocean) – otros proyectos en el mismo servidor

Para no mezclar con otros proyectos, usá un **nombre de proyecto** distinto y, si hace falta, **otros puertos**.

### Actualización en producción (lo que usan hoy: `systemd`)

En el VPS de SIOC (ej. `https://sioc.sistemas-msa.com`) la app **no** se actualiza con Docker Compose: el servicio corre bajo **systemd** y el repo vive en `/opt/sioc`.

**Cada vez que subís cambios a `main` en GitHub y querés que el sitio los tome:**

```bash
ssh tu_usuario@TU_IP_DEL_SERVIDOR

cd /opt/sioc
git pull origin main
sudo systemctl restart sioc.service
```

Eso es el flujo que usaron, por ejemplo, tras el commit de vista móvil (`e63064d`) y el de carga manual de oficios (u otro push posterior a `main`). Si `git pull` falla por permisos, ejecutalo con el usuario que sea dueño del repo o con `sudo` según cómo lo tengan montado.

---

### Entrar al servidor y clonar/actualizar (desde GitHub)

```bash
ssh root@TU_IP_DIGITAL_OCEAN
# o: ssh usuario@TU_IP

cd /var/www
# o la carpeta donde tengas los proyectos

# Si ya tenés el repo:
cd MSA_SIOC
git pull
cd sioc

# Si es la primera vez:
git clone https://github.com/TU_USUARIO/MSA_SIOC.git
cd MSA_SIOC/sioc
```

En el servidor el **primer** `docker compose -p sioc up -d --build` puede tardar (descarga imagen base + pip install). Los siguientes son rápidos si no cambiaste el Dockerfile ni requirements. Si preferís no usar Docker para la app en el servidor: dejá solo MySQL en Docker y corré Flask con `gunicorn` (venv + `pip install -r requirements.txt`).

### Ejecutar SIOC con Docker en el servidor

Usar proyecto `sioc` para que los contenedores se llamen `sioc_mysql` y `sioc_flask` y no choquen con otros:

```bash
cd /var/www/sioc
# o: cd /var/www/MSA_SIOC/sioc

# Levantar solo los servicios de este proyecto (nombre de proyecto: sioc)
docker compose -p sioc up -d --build

# Primera vez: crear tablas y admin
docker compose -p sioc exec flask python create_admin.py

# Ver que estén corriendo
docker compose -p sioc ps
```

Si en el mismo servidor otro proyecto ya usa el puerto **5001**, cambialo en `docker-compose.yml` (por ejemplo a `5002:5001`) o usá un override:

```bash
# Ejemplo: puerto 5002 en el host
docker compose -p sioc up -d --build
# y en docker-compose.yml en la sección flask, ports: "5002:5001"
```

**Producción:** en el servidor conviene usar variables de entorno más seguras. Creá un `.env` en `sioc`:

```bash
cd /var/www/sioc
nano .env
```

Contenido mínimo recomendado:

```
SECRET_KEY=una-clave-muy-larga-y-aleatoria-aqui
DATABASE_URL=mysql+pymysql://sioc_user:sioc_password@mysql:3306/sioc_db
FLASK_ENV=production
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=True
```

Luego:

```bash
docker compose -p sioc up -d --build
docker compose -p sioc exec flask python create_admin.py
```

### Comandos útiles en el servidor

```bash
# Ver logs de la app
docker compose -p sioc logs -f flask

# Detener SIOC (no borra datos)
docker compose -p sioc down

# Entrar al contenedor de la app
docker compose -p sioc exec flask bash

# Reiniciar solo la app
docker compose -p sioc restart flask
```

### Nginx como proxy (opcional)

Si querés que SIOC responda en un dominio (ej. `sioc.tudominio.com`) en el puerto 80/443:

```nginx
server {
    listen 80;
    server_name sioc.tudominio.com;
    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Resumen rápido

| Dónde        | Comando principal |
|-------------|--------------------|
| **Local**   | `cd C:\Dev\MSA_SIOC\sioc` → `docker compose up -d --build` → `docker compose exec flask python create_admin.py` |
| **Servidor (producción systemd)** | `cd /opt/sioc` → `git pull origin main` → `sudo systemctl restart sioc.service` |
| **Servidor (alternativa Docker)** | `cd /ruta/sioc` → `docker compose -p sioc up -d --build` → `docker compose -p sioc exec flask python create_admin.py` |

Siempre que agregues nuevos modelos o permisos, volvé a ejecutar `create_admin.py` (local o servidor) para crear tablas y datos iniciales.

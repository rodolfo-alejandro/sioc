#!/bin/bash
# Script para levantar el entorno de desarrollo SIOC

set -e

echo "=========================================="
echo "SIOC - Levantando entorno de desarrollo"
echo "=========================================="

# Verificar que Docker esté instalado
if ! command -v docker &> /dev/null; then
    echo "❌ Docker no está instalado. Por favor instálelo primero."
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose no está instalado. Por favor instálelo primero."
    exit 1
fi

# Verificar que Python esté instalado
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 no está instalado. Por favor instálelo primero."
    exit 1
fi

# 1. Crear .env si no existe
if [ ! -f .env ]; then
    echo ""
    echo "[1/5] Creando archivo .env desde env.example..."
    cp env.example .env
    echo "✓ Archivo .env creado. Revise y ajuste los valores si es necesario."
else
    echo ""
    echo "[1/5] Archivo .env ya existe, omitiendo..."
fi

# 2. Levantar MySQL en Docker
echo ""
echo "[2/5] Levantando MySQL en Docker..."
docker compose up -d mysql

# Esperar a que MySQL esté listo
echo "Esperando a que MySQL esté listo..."
timeout=60
counter=0
while ! docker compose exec -T mysql mysqladmin ping -h localhost --silent 2>/dev/null; do
    sleep 2
    counter=$((counter + 2))
    if [ $counter -ge $timeout ]; then
        echo "❌ Timeout esperando a MySQL"
        exit 1
    fi
    echo -n "."
done
echo ""
echo "✓ MySQL está listo"

# 3. Crear entorno virtual si no existe
echo ""
echo "[3/5] Configurando entorno virtual de Python..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Entorno virtual creado"
else
    echo "✓ Entorno virtual ya existe"
fi

# Activar entorno virtual
source venv/bin/activate

# 4. Instalar dependencias
echo ""
echo "[4/5] Instalando dependencias de Python..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Dependencias instaladas"

# 5. Inicializar base de datos
echo ""
echo "[5/5] Inicializando base de datos y creando datos semilla..."
python create_admin.py

echo ""
echo "=========================================="
echo "✓ Entorno de desarrollo listo!"
echo "=========================================="
echo ""
echo "Para iniciar la aplicación:"
echo "  source venv/bin/activate"
echo "  python run.py"
echo ""
echo "La aplicación estará disponible en: http://localhost:5000"
echo ""
echo "Credenciales por defecto:"
echo "  Usuario: admin"
echo "  Contraseña: Admin123!"
echo ""


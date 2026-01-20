#!/bin/bash
# Script para ejecutar SIOC completamente con Docker (Linux/Mac)

set -e

echo "=========================================="
echo "SIOC - Ejecutando con Docker"
echo "=========================================="

# Verificar que Docker esté instalado
if ! command -v docker &> /dev/null; then
    echo "❌ Docker no está instalado. Por favor instálelo primero."
    exit 1
fi

# Verificar que docker-compose esté disponible
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose no está instalado. Por favor instálelo primero."
    exit 1
fi

# Verificar que existe .env
if [ ! -f .env ]; then
    if [ -f env.example ]; then
        cp env.example .env
        echo "✓ Archivo .env creado desde env.example"
    else
        echo "❌ No se encontró .env ni env.example"
        exit 1
    fi
fi

# Construir y levantar servicios
echo ""
echo "Construyendo y levantando servicios..."
docker compose up -d --build

# Esperar a que MySQL esté listo
echo "Esperando a que MySQL esté listo..."
timeout=60
counter=0
ready=false
while [ $counter -lt $timeout ]; do
    sleep 2
    counter=$((counter + 2))
    if docker compose exec -T mysql mysqladmin ping -h localhost &> /dev/null; then
        ready=true
        break
    fi
    echo -n "."
done

if [ "$ready" = false ]; then
    echo ""
    echo "❌ Timeout esperando a MySQL"
    exit 1
fi

echo ""
echo "✓ MySQL está listo"

# Inicializar base de datos
echo ""
echo "Inicializando base de datos..."
docker compose exec flask python create_admin.py

echo ""
echo "=========================================="
echo "✓ SIOC está ejecutándose con Docker!"
echo "=========================================="
echo ""
echo "La aplicación está disponible en: http://localhost:5001"
echo ""
echo "Para ver los logs:"
echo "  docker compose logs -f flask"
echo ""
echo "Para detener los servicios:"
echo "  docker compose down"
echo ""
echo "Credenciales por defecto:"
echo "  Usuario: admin"
echo "  Contraseña: Admin123!"
echo ""




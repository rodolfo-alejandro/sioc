#!/bin/bash
# Script para verificar que el entorno esté correctamente configurado

echo "=========================================="
echo "SIOC - Verificación del Entorno"
echo "=========================================="

ERRORS=0

# Verificar Docker
echo ""
echo "[1/6] Verificando Docker..."
if command -v docker &> /dev/null; then
    echo "✓ Docker instalado"
    if docker ps &> /dev/null; then
        echo "✓ Docker está ejecutándose"
    else
        echo "✗ Docker no está ejecutándose"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "✗ Docker no está instalado"
    ERRORS=$((ERRORS + 1))
fi

# Verificar contenedor MySQL
echo ""
echo "[2/6] Verificando contenedor MySQL..."
if docker compose ps mysql 2>/dev/null | grep -q "Up"; then
    echo "✓ Contenedor MySQL está ejecutándose"
else
    echo "✗ Contenedor MySQL no está ejecutándose"
    echo "  Ejecute: docker compose up -d mysql"
    ERRORS=$((ERRORS + 1))
fi

# Verificar .env
echo ""
echo "[3/6] Verificando archivo .env..."
if [ -f .env ]; then
    echo "✓ Archivo .env existe"
    if grep -q "DATABASE_URL" .env; then
        echo "✓ DATABASE_URL configurado"
    else
        echo "✗ DATABASE_URL no encontrado en .env"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "✗ Archivo .env no existe"
    echo "  Ejecute: cp env.example .env"
    ERRORS=$((ERRORS + 1))
fi

# Verificar entorno virtual
echo ""
echo "[4/6] Verificando entorno virtual..."
if [ -d "venv" ]; then
    echo "✓ Entorno virtual existe"
    if [ -f "venv/bin/activate" ] || [ -f "venv/Scripts/activate" ]; then
        echo "✓ Entorno virtual es válido"
    else
        echo "✗ Entorno virtual parece corrupto"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "✗ Entorno virtual no existe"
    echo "  Ejecute: python3 -m venv venv"
    ERRORS=$((ERRORS + 1))
fi

# Verificar dependencias
echo ""
echo "[5/6] Verificando dependencias de Python..."
if [ -d "venv" ]; then
    source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null
    if pip show Flask &> /dev/null; then
        echo "✓ Flask instalado"
    else
        echo "✗ Flask no está instalado"
        echo "  Ejecute: pip install -r requirements.txt"
        ERRORS=$((ERRORS + 1))
    fi
    deactivate 2>/dev/null
fi

# Verificar conexión a base de datos
echo ""
echo "[6/6] Verificando conexión a base de datos..."
if [ -f .env ] && [ -d "venv" ]; then
    source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null
    python -c "
import sys
sys.path.insert(0, '.')
from app import create_app
from app.extensions import db
app = create_app()
try:
    with app.app_context():
        db.engine.connect()
    print('✓ Conexión a base de datos exitosa')
    sys.exit(0)
except Exception as e:
    print(f'✗ Error de conexión: {e}')
    sys.exit(1)
" 2>/dev/null
    if [ $? -ne 0 ]; then
        ERRORS=$((ERRORS + 1))
    fi
    deactivate 2>/dev/null
else
    echo "⚠ Saltando verificación (requiere .env y venv)"
fi

# Resumen
echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo "✓ Entorno verificado correctamente"
    echo "=========================================="
    exit 0
else
    echo "✗ Se encontraron $ERRORS error(es)"
    echo "=========================================="
    exit 1
fi


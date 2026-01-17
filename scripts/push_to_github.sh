#!/bin/bash
# Script para subir el proyecto SIOC a GitHub
# Uso: ./scripts/push_to_github.sh REPO_NAME GITHUB_USER

set -e

if [ $# -lt 2 ]; then
    echo "Uso: $0 REPO_NAME GITHUB_USER"
    echo "Ejemplo: $0 sioc tu-usuario"
    exit 1
fi

REPO_NAME=$1
GITHUB_USER=$2
REPO_URL="https://github.com/$GITHUB_USER/$REPO_NAME.git"

echo "=========================================="
echo "SIOC - Subir a GitHub"
echo "=========================================="
echo ""

# Verificar que estamos en un repositorio Git
if [ ! -d .git ]; then
    echo "❌ No se encontró un repositorio Git. Ejecute 'git init' primero."
    exit 1
fi

# Verificar que hay commits
if ! git log --oneline > /dev/null 2>&1; then
    echo "❌ No hay commits en el repositorio. Haga un commit primero."
    exit 1
fi

echo "✓ Repositorio Git verificado"
echo ""

echo "Configuración:"
echo "  Repositorio: $REPO_NAME"
echo "  Usuario: $GITHUB_USER"
echo "  URL: $REPO_URL"
echo ""

# Verificar si ya existe el remote
if git remote get-url origin > /dev/null 2>&1; then
    EXISTING_REMOTE=$(git remote get-url origin)
    echo "⚠️  Ya existe un remote 'origin': $EXISTING_REMOTE"
    read -p "¿Desea reemplazarlo? (s/n): " response
    if [ "$response" = "s" ] || [ "$response" = "S" ]; then
        git remote remove origin
        echo "✓ Remote 'origin' eliminado"
    else
        echo "Operación cancelada."
        exit 0
    fi
fi

echo ""
echo "PASO 1: Crear el repositorio en GitHub"
echo "----------------------------------------"
echo "1. Ve a: https://github.com/new"
echo "2. Nombre del repositorio: $REPO_NAME"
echo "3. Descripción: 'SIOC - Sistema Integrado de Registro, Prevención, Investigación y Operaciones Conjuntas'"
echo "4. Elige: Público o Privado"
echo "5. NO marques 'Initialize with README' (ya tenemos uno)"
echo "6. Click en 'Create repository'"
echo ""

read -p "¿Ya creaste el repositorio en GitHub? (s/n): " continue
if [ "$continue" != "s" ] && [ "$continue" != "S" ]; then
    echo "Operación cancelada. Crea el repositorio y vuelve a ejecutar este script."
    exit 0
fi

echo ""
echo "PASO 2: Agregar remote y subir código"
echo "----------------------------------------"

# Agregar remote
echo "Agregando remote 'origin'..."
if git remote add origin "$REPO_URL" 2>/dev/null; then
    echo "✓ Remote agregado"
else
    echo "⚠️  Error al agregar remote (puede que ya exista)"
fi

# Verificar rama actual
CURRENT_BRANCH=$(git branch --show-current)
if [ -z "$CURRENT_BRANCH" ]; then
    echo "Creando rama 'main'..."
    git branch -M main
    CURRENT_BRANCH="main"
fi

echo "Rama actual: $CURRENT_BRANCH"

# Push
echo ""
echo "Subiendo código a GitHub..."
echo "Esto puede pedirte credenciales de GitHub."
echo ""

if git push -u origin "$CURRENT_BRANCH"; then
    echo ""
    echo "=========================================="
    echo "✓ ¡Código subido exitosamente a GitHub!"
    echo "=========================================="
    echo ""
    echo "Repositorio: $REPO_URL"
    echo ""
else
    echo ""
    echo "❌ Error al subir el código."
    echo ""
    echo "Posibles soluciones:"
    echo "1. Verifica que el repositorio exista en GitHub"
    echo "2. Verifica tus credenciales de GitHub"
    echo "3. Si usas autenticación por token, configúralo:"
    echo "   git remote set-url origin https://TU_TOKEN@github.com/$GITHUB_USER/$REPO_NAME.git"
    echo ""
    exit 1
fi


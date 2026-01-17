#!/bin/bash
# Script para acceder a la shell de MySQL en Docker

echo "Conectando a MySQL en Docker..."
echo "Base de datos: sioc_db"
echo "Usuario: root"
echo ""
echo "Para salir, escriba: exit"
echo ""

docker compose exec mysql mysql -u root -psioc_root_password sioc_db


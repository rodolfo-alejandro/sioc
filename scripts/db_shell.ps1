# Script para acceder a la shell de MySQL en Docker (Windows)

Write-Host "Conectando a MySQL en Docker..." -ForegroundColor Cyan
Write-Host "Base de datos: sioc_db" -ForegroundColor Yellow
Write-Host "Usuario: root" -ForegroundColor Yellow
Write-Host ""
Write-Host "Para salir, escriba: exit" -ForegroundColor Yellow
Write-Host ""

docker compose exec mysql mysql -u root -psioc_root_password sioc_db


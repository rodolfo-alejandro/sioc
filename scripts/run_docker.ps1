# Script para ejecutar SIOC completamente con Docker (Windows PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "SIOC - Ejecutando con Docker" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Verificar que Docker esté instalado
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker no está instalado. Por favor instálelo primero." -ForegroundColor Red
    exit 1
}

# Verificar que docker-compose esté disponible
if (-not (Get-Command docker-compose -ErrorAction SilentlyContinue) -and 
    -not (docker compose version 2>$null)) {
    Write-Host "❌ Docker Compose no está instalado. Por favor instálelo primero." -ForegroundColor Red
    exit 1
}

# Verificar que existe .env
if (-not (Test-Path .env)) {
    if (Test-Path env.example) {
        Copy-Item env.example .env
        Write-Host "✓ Archivo .env creado desde env.example" -ForegroundColor Green
    } else {
        Write-Host "❌ No se encontró .env ni env.example" -ForegroundColor Red
        exit 1
    }
}

# Construir y levantar servicios
Write-Host ""
Write-Host "Construyendo y levantando servicios..." -ForegroundColor Yellow
docker compose up -d --build

# Esperar a que MySQL esté listo
Write-Host "Esperando a que MySQL esté listo..." -ForegroundColor Yellow
$timeout = 60
$counter = 0
$ready = $false
while ($counter -lt $timeout) {
    Start-Sleep -Seconds 2
    $counter += 2
    try {
        $result = docker compose exec -T mysql mysqladmin ping -h localhost 2>$null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
    } catch {
        # Continuar esperando
    }
    Write-Host "." -NoNewline
}

if (-not $ready) {
    Write-Host ""
    Write-Host "❌ Timeout esperando a MySQL" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "✓ MySQL está listo" -ForegroundColor Green

# Inicializar base de datos
Write-Host ""
Write-Host "Inicializando base de datos..." -ForegroundColor Yellow
docker compose exec flask python create_admin.py

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "✓ SIOC está ejecutándose con Docker!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "La aplicación está disponible en: http://localhost:5001" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para ver los logs:" -ForegroundColor Yellow
Write-Host "  docker compose logs -f flask" -ForegroundColor White
Write-Host ""
Write-Host "Para detener los servicios:" -ForegroundColor Yellow
Write-Host "  docker compose down" -ForegroundColor White
Write-Host ""
Write-Host "Credenciales por defecto:" -ForegroundColor Yellow
Write-Host "  Usuario: admin" -ForegroundColor White
Write-Host "  Contraseña: Admin123!" -ForegroundColor White
Write-Host ""




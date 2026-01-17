# Script para levantar el entorno de desarrollo SIOC (Windows PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "SIOC - Levantando entorno de desarrollo" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Verificar que Docker esté instalado
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker no está instalado. Por favor instálelo primero." -ForegroundColor Red
    exit 1
}

if (-not (Get-Command docker-compose -ErrorAction SilentlyContinue) -and 
    -not (docker compose version 2>$null)) {
    Write-Host "❌ Docker Compose no está instalado. Por favor instálelo primero." -ForegroundColor Red
    exit 1
}

# Verificar que Python esté instalado
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python no está instalado. Por favor instálelo primero." -ForegroundColor Red
    exit 1
}

# 1. Crear .env si no existe
Write-Host ""
Write-Host "[1/5] Verificando archivo .env..." -ForegroundColor Yellow
if (-not (Test-Path .env)) {
    if (Test-Path env.example) {
        Copy-Item env.example .env
        Write-Host "✓ Archivo .env creado desde env.example" -ForegroundColor Green
        Write-Host "  Revise y ajuste los valores si es necesario." -ForegroundColor Yellow
    } else {
        Write-Host "⚠️  Archivo env.example no encontrado. Creando .env básico..." -ForegroundColor Yellow
        @"
SECRET_KEY=dev-secret-key-change-in-production
DATABASE_URL=mysql+pymysql://sioc_user:sioc_password@localhost:3306/sioc_db
MAX_CONTENT_LENGTH=20971520
UPLOAD_FOLDER=instance/uploads
SESSION_COOKIE_SECURE=False
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=Admin123!
DEFAULT_ADMIN_EMAIL=admin@sioc.local
"@ | Out-File -FilePath .env -Encoding utf8
    }
} else {
    Write-Host "✓ Archivo .env ya existe" -ForegroundColor Green
}

# 2. Levantar MySQL en Docker
Write-Host ""
Write-Host "[2/5] Levantando MySQL en Docker..." -ForegroundColor Yellow
docker compose up -d mysql

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

# 3. Crear entorno virtual si no existe
Write-Host ""
Write-Host "[3/5] Configurando entorno virtual de Python..." -ForegroundColor Yellow
if (-not (Test-Path venv)) {
    python -m venv venv
    Write-Host "✓ Entorno virtual creado" -ForegroundColor Green
} else {
    Write-Host "✓ Entorno virtual ya existe" -ForegroundColor Green
}

# Activar entorno virtual
& .\venv\Scripts\Activate.ps1

# 4. Instalar dependencias
Write-Host ""
Write-Host "[4/5] Instalando dependencias de Python..." -ForegroundColor Yellow
python -m pip install --upgrade pip
pip install -r requirements.txt
Write-Host "✓ Dependencias instaladas" -ForegroundColor Green

# 5. Inicializar base de datos
Write-Host ""
Write-Host "[5/5] Inicializando base de datos y creando datos semilla..." -ForegroundColor Yellow
python create_admin.py

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "✓ Entorno de desarrollo listo!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para iniciar la aplicación:" -ForegroundColor Yellow
Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  python run.py" -ForegroundColor White
Write-Host ""
Write-Host "La aplicación estará disponible en: http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Write-Host "Credenciales por defecto:" -ForegroundColor Yellow
Write-Host "  Usuario: admin" -ForegroundColor White
Write-Host "  Contraseña: Admin123!" -ForegroundColor White
Write-Host ""


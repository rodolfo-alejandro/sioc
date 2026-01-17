# Script para subir el proyecto SIOC a GitHub
# Uso: .\scripts\push_to_github.ps1 -RepoName "sioc" -GitHubUser "tu-usuario"

param(
    [Parameter(Mandatory=$true)]
    [string]$RepoName,
    
    [Parameter(Mandatory=$true)]
    [string]$GitHubUser
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "SIOC - Subir a GitHub" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Verificar que estamos en un repositorio Git
if (-not (Test-Path .git)) {
    Write-Host "❌ No se encontró un repositorio Git. Ejecute 'git init' primero." -ForegroundColor Red
    exit 1
}

# Verificar que hay commits
$commits = git log --oneline 2>$null
if (-not $commits) {
    Write-Host "❌ No hay commits en el repositorio. Haga un commit primero." -ForegroundColor Red
    exit 1
}

Write-Host "✓ Repositorio Git verificado" -ForegroundColor Green
Write-Host ""

# URL del repositorio
$repoUrl = "https://github.com/$GitHubUser/$RepoName.git"

Write-Host "Configuración:" -ForegroundColor Yellow
Write-Host "  Repositorio: $RepoName" -ForegroundColor White
Write-Host "  Usuario: $GitHubUser" -ForegroundColor White
Write-Host "  URL: $repoUrl" -ForegroundColor White
Write-Host ""

# Verificar si ya existe el remote
$existingRemote = git remote get-url origin 2>$null
if ($existingRemote) {
    Write-Host "⚠️  Ya existe un remote 'origin': $existingRemote" -ForegroundColor Yellow
    $response = Read-Host "¿Desea reemplazarlo? (s/n)"
    if ($response -eq "s" -or $response -eq "S") {
        git remote remove origin
        Write-Host "✓ Remote 'origin' eliminado" -ForegroundColor Green
    } else {
        Write-Host "Operación cancelada." -ForegroundColor Yellow
        exit 0
    }
}

Write-Host ""
Write-Host "PASO 1: Crear el repositorio en GitHub" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Cyan
Write-Host "1. Ve a: https://github.com/new" -ForegroundColor White
Write-Host "2. Nombre del repositorio: $RepoName" -ForegroundColor White
Write-Host "3. Descripción: 'SIOC - Sistema Integrado de Registro, Prevención, Investigación y Operaciones Conjuntas'" -ForegroundColor White
Write-Host "4. Elige: Público o Privado" -ForegroundColor White
Write-Host "5. NO marques 'Initialize with README' (ya tenemos uno)" -ForegroundColor White
Write-Host "6. Click en 'Create repository'" -ForegroundColor White
Write-Host ""

$continue = Read-Host "¿Ya creaste el repositorio en GitHub? (s/n)"
if ($continue -ne "s" -and $continue -ne "S") {
    Write-Host "Operación cancelada. Crea el repositorio y vuelve a ejecutar este script." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "PASO 2: Agregar remote y subir código" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Cyan

# Agregar remote
Write-Host "Agregando remote 'origin'..." -ForegroundColor Yellow
git remote add origin $repoUrl
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Remote agregado" -ForegroundColor Green
} else {
    Write-Host "⚠️  Error al agregar remote (puede que ya exista)" -ForegroundColor Yellow
}

# Verificar rama actual
$currentBranch = git branch --show-current
if (-not $currentBranch) {
    Write-Host "Creando rama 'main'..." -ForegroundColor Yellow
    git branch -M main
    $currentBranch = "main"
}

Write-Host "Rama actual: $currentBranch" -ForegroundColor White

# Push
Write-Host ""
Write-Host "Subiendo código a GitHub..." -ForegroundColor Yellow
Write-Host "Esto puede pedirte credenciales de GitHub." -ForegroundColor Yellow
Write-Host ""

git push -u origin $currentBranch

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host "✓ ¡Código subido exitosamente a GitHub!" -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Repositorio: $repoUrl" -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "❌ Error al subir el código." -ForegroundColor Red
    Write-Host ""
    Write-Host "Posibles soluciones:" -ForegroundColor Yellow
    Write-Host "1. Verifica que el repositorio exista en GitHub" -ForegroundColor White
    Write-Host "2. Verifica tus credenciales de GitHub" -ForegroundColor White
    Write-Host "3. Si usas autenticación por token, configúralo:" -ForegroundColor White
    Write-Host "   git remote set-url origin https://TU_TOKEN@github.com/$GitHubUser/$RepoName.git" -ForegroundColor Gray
    Write-Host ""
}


# 🚀 Guía para Subir SIOC a GitHub

## Opción 1: Usar el Script Automático (Recomendado)

### Windows (PowerShell):
```powershell
.\scripts\push_to_github.ps1 -RepoName "sioc" -GitHubUser "tu-usuario-github"
```

### Linux/Mac:
```bash
chmod +x scripts/push_to_github.sh
./scripts/push_to_github.sh sioc tu-usuario-github
```

El script te guiará paso a paso.

---

## Opción 2: Manual (Paso a Paso)

### 1. Crear el Repositorio en GitHub

1. Ve a: https://github.com/new
2. **Repository name**: `sioc` (o el nombre que prefieras)
3. **Description**: `SIOC - Sistema Integrado de Registro, Prevención, Investigación y Operaciones Conjuntas`
4. Elige **Público** o **Privado**
5. ⚠️ **NO marques** "Initialize with README" (ya tenemos uno)
6. Click en **"Create repository"**

### 2. Conectar tu Repositorio Local con GitHub

```bash
# Agregar el remote (reemplaza TU_USUARIO con tu usuario de GitHub)
git remote add origin https://github.com/TU_USUARIO/sioc.git

# Verificar que se agregó correctamente
git remote -v
```

### 3. Subir el Código

```bash
# Asegurarte de estar en la rama main/master
git branch -M main

# Subir el código
git push -u origin main
```

### 4. Autenticación

Si te pide credenciales:

**Opción A: Personal Access Token (Recomendado)**
1. Ve a: https://github.com/settings/tokens
2. Click en "Generate new token (classic)"
3. Dale un nombre (ej: "SIOC Local")
4. Selecciona el scope `repo`
5. Click en "Generate token"
6. Copia el token (solo se muestra una vez)
7. Cuando Git pida contraseña, usa el token en lugar de tu contraseña

**Opción B: GitHub CLI**
```bash
# Instalar GitHub CLI si no lo tienes
# Windows: winget install GitHub.cli
# Mac: brew install gh
# Linux: ver https://cli.github.com/

# Autenticarse
gh auth login

# Luego hacer push normalmente
git push -u origin main
```

**Opción C: SSH (Avanzado)**
```bash
# Cambiar el remote a SSH
git remote set-url origin git@github.com:TU_USUARIO/sioc.git

# Necesitas tener configurada una clave SSH en GitHub
```

---

## Verificar que Funcionó

Después de hacer push, ve a tu repositorio en GitHub:
```
https://github.com/TU_USUARIO/sioc
```

Deberías ver todos los archivos del proyecto.

---

## Comandos Útiles para el Futuro

```bash
# Ver el estado
git status

# Agregar cambios
git add .

# Hacer commit
git commit -m "Descripción de los cambios"

# Subir cambios
git push

# Bajar cambios (si trabajas en otra máquina)
git pull
```

---

## ⚠️ Importante

- **NUNCA subas el archivo `.env`** (ya está en `.gitignore`)
- **NUNCA subas `venv/`** (ya está en `.gitignore`)
- **NUNCA subas archivos de uploads** (ya está en `.gitignore`)

El `.gitignore` ya está configurado para proteger información sensible.

---

## 🆘 Problemas Comunes

### Error: "remote origin already exists"
```bash
# Ver el remote actual
git remote -v

# Eliminarlo si es necesario
git remote remove origin

# Agregarlo de nuevo
git remote add origin https://github.com/TU_USUARIO/sioc.git
```

### Error: "Authentication failed"
- Verifica que el token/contraseña sea correcta
- Si usas token, asegúrate de tener el scope `repo` habilitado
- Considera usar GitHub CLI: `gh auth login`

### Error: "Repository not found"
- Verifica que el repositorio exista en GitHub
- Verifica que tengas permisos de escritura
- Verifica que la URL sea correcta

---

¡Listo! Tu proyecto SIOC ahora está en GitHub 🎉


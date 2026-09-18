# Módulo de Auditoría - SIOC

## Descripción

El módulo de auditoría permite a los jefes y auditores revisar los datos cargados por diferentes secciones, actuarios y grupos sin modificar los datos originales. Pueden agregar observaciones generales o específicas por campo que quedan registradas aparte para seguimiento y control de calidad.

## Características Principales

### 1. **Observaciones Sin Modificar Datos Reales**
- Las observaciones se guardan en tablas separadas
- No afectan los datos operativos originales
- Mantienen trazabilidad completa (quién, cuándo, qué)

### 2. **Tipos de Observaciones**
- **Observaciones Generales**: Comentarios sobre todo el registro
- **Observaciones por Campo**: Comentarios específicos sobre campos particulares (ej: fecha, estado, localidad, etc.)

### 3. **Gestión de Observaciones**
- Crear observaciones nuevas
- Resolver observaciones cuando se corrija el problema
- Reabrir observaciones resueltas si es necesario
- Eliminar observaciones (solo el creador o superadmin)

### 4. **Vistas Agrupadas**
- **Denuncias Web**: Agrupar por dependencia, actuario, estado, localidad
- **Intervenciones**: Agrupar por DINAR, SINAR, departamento operativo
- Ver estadísticas por grupo (total registros, observaciones, pendientes)

### 5. **Estadísticas**
- Dashboard con métricas consolidadas
- Top auditores más activos
- Observaciones pendientes vs resueltas

## Instalación y Configuración

### Paso 1: Ejecutar Script de Permisos

```bash
cd /workspace/sioc
python scripts/add_auditoria_permissions.py
```

Este script creará los siguientes permisos:
- `AUDITORIA_VIEW`: Ver panel de auditoría y observaciones
- `AUDITORIA_CREATE`: Crear observaciones de auditoría
- `AUDITORIA_RESOLVE`: Resolver y reabrir observaciones

### Paso 2: Asignar Permisos a Roles

1. Acceda al panel de administración en `/admin/roles`
2. Edite los roles que necesiten acceso a auditoría
3. Asigne los permisos según corresponda:
   - **Auditores/Jefes**: Todos los permisos (VIEW, CREATE, RESOLVE)
   - **Personal**: Solo VIEW si necesitan ver observaciones
   - **SUPERADMIN**: Ya tiene todos los permisos asignados automáticamente

### Paso 3: Verificar Instalación

1. Acceda al sistema con un usuario que tenga permisos de auditoría
2. Verifique que aparezca el menú "Auditoría" en el sidebar
3. Navegue a `/auditoria` para ver el panel principal

## Estructura de la Base de Datos

### Tabla `auditoria_observaciones`
```sql
- id: Integer (PK)
- modulo: String (denuncias_web, intervenciones)
- registro_id: Integer (ID del registro auditado)
- campo: String (NULL para observaciones generales)
- observacion: Text
- auditor_id: Integer (FK a users)
- unidad_id: Integer (FK a unidades)
- fecha_creacion: DateTime
- fecha_modificacion: DateTime
- resuelta: Boolean
- fecha_resolucion: DateTime
- resuelto_por_id: Integer (FK a users)
- nota_resolucion: Text
```

### Tabla `auditoria_resumenes`
```sql
- id: Integer (PK)
- unidad_id: Integer (FK a unidades)
- modulo: String
- tipo_agrupacion: String
- valor_agrupacion: String
- fecha_desde: DateTime
- fecha_hasta: DateTime
- titulo: String
- descripcion: Text
- total_registros: Integer
- registros_con_observaciones: Integer
- total_observaciones: Integer
- observaciones_resueltas: Integer
- generado_por_id: Integer (FK a users)
- fecha_generacion: DateTime
```

## Uso del Módulo

### Para Auditores/Jefes

1. **Acceder al módulo**
   - Ir a `/auditoria` desde el menú lateral

2. **Seleccionar módulo a auditar**
   - Denuncias Web
   - Intervenciones

3. **Seleccionar agrupación**
   - Por dependencia, actuario, estado, localidad, etc.
   - Ver estadísticas de cada grupo

4. **Revisar grupo específico**
   - Click en "Ver Detalle" para ver registros del grupo
   - Ver observaciones existentes por registro

5. **Auditar registro individual**
   - Click en "Ver Detalle" de un registro
   - Ver todos los campos con sus valores
   - Agregar observaciones generales o por campo

6. **Gestionar observaciones**
   - Crear: Escribir observación y enviar
   - Resolver: Marcar como resuelta con nota opcional
   - Reabrir: Si se necesita revisar nuevamente
   - Eliminar: Solo el creador puede eliminar

### Para Personal Operativo

1. Los datos cargados NO se modifican
2. Las observaciones son visibles solo en el módulo de auditoría
3. Si un jefe/auditor encuentra un problema, lo comunicará por los canales habituales
4. Las correcciones se hacen en el módulo original (Denuncias Web, Intervenciones, etc.)

## Rutas Disponibles

```
/auditoria                                  -> Panel principal
/auditoria/denuncias-web                    -> Auditoría denuncias web agrupadas
/auditoria/denuncias-web/grupo/<grupo>      -> Detalle de un grupo específico
/auditoria/denuncias-web/detalle/<id>       -> Detalle completo con observaciones
/auditoria/intervenciones                   -> Auditoría intervenciones agrupadas
/auditoria/estadisticas                     -> Dashboard de estadísticas
/auditoria/observacion/crear                -> Crear observación (POST)
/auditoria/observacion/<id>/resolver        -> Resolver observación (POST)
/auditoria/observacion/<id>/reabrir         -> Reabrir observación (POST)
/auditoria/observacion/<id>/eliminar        -> Eliminar observación (POST)
```

## Archivos Creados/Modificados

### Nuevos Archivos
```
app/models/auditoria.py                             -> Modelos de auditoría
app/blueprints/auditoria/__init__.py                -> Blueprint
app/blueprints/auditoria/routes.py                  -> Rutas y lógica
app/blueprints/auditoria/templates/auditoria/
  - index.html                                      -> Panel principal
  - denuncias_web.html                              -> Vista agrupada denuncias
  - denuncias_web_grupo.html                        -> Detalle de grupo
  - denuncias_web_detalle.html                      -> Detalle completo con observaciones
  - intervenciones.html                             -> Vista intervenciones
  - estadisticas.html                               -> Dashboard estadísticas
scripts/add_auditoria_permissions.py                -> Script de instalación
AUDITORIA_README.md                                 -> Este archivo
```

### Archivos Modificados
```
app/__init__.py                                     -> Registro del blueprint
app/models/__init__.py                              -> Importación de modelos
app/templates/layouts/partials_sidebar.html         -> Menú de auditoría
```

## Próximas Mejoras

1. **Notificaciones**: Alertar cuando se crea una observación
2. **Reportes**: Exportar reportes de auditoría en PDF/Excel
3. **Workflow**: Estados de observación (nueva, en revisión, resuelta)
4. **Comentarios**: Permitir hilos de conversación en observaciones
5. **Auditoría de Intervenciones Completa**: Implementar vistas detalladas similares a denuncias
6. **Filtros Avanzados**: Filtrar por fecha, auditor, estado
7. **API REST**: Endpoints para integraciones externas

## Soporte y Consultas

Para consultas sobre el módulo de auditoría, contacte al administrador del sistema o revise la documentación técnica en el código fuente.

---

**Desarrollado para SIOC - Sistema Integrado de Registro, Prevención, Investigación y Operaciones Conjuntas**

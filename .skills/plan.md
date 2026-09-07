---
id: "skill.plan"
name: "Plan Diario"
version: "1.0.0"
description: "CRUD de prioridades diarias en wiki/plan_hoy.md con foco, tareas, bloqueos"
author: "jarvis-os team"
license: "MIT"
capabilities:
  - "plan.create"
  - "plan.read"
  - "plan.update"
  - "plan.delete"
  - "plan.list"
  - "plan.add_task"
  - "plan.complete_task"
  - "plan.set_focus"
  - "plan.add_blocker"
  - "plan.archive"
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["create", "read", "update", "delete", "list", "add_task", "complete_task", "set_focus", "add_blocker", "archive"]
      description: "Acción a ejecutar"
    task:
      type: "string"
      description: "Texto de la tarea (para add_task, complete_task)"
    task_id:
      type: "string"
      description: "ID de tarea existente (para complete_task, update)"
    priority:
      type: "string"
      enum: ["low", "medium", "high", "critical"]
      default: "medium"
      description: "Prioridad de la tarea"
    focus:
      type: "string"
      description: "Foco principal del día (para set_focus)"
    blocker:
      type: "string"
      description: "Descripción del bloqueo (para add_blocker)"
    blocker_id:
      type: "string"
      description: "ID de bloqueo existente (para delete blocker)"
    date:
      type: "string"
      format: "date"
      description: "Fecha objetivo (YYYY-MM-DD), default: hoy"
    replace_all:
      type: "boolean"
      default: false
      description: "Si true en update, reemplaza todo el contenido"
  required: ["action"]
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
      properties:
        task_id:
          type: "string"
          description: "ID generado para nueva tarea (tsk-XXX)"
        task:
          type: "object"
          properties:
            id:
              type: "string"
            text:
              type: "string"
            priority:
              type: "string"
            completed:
              type: "boolean"
            created_at:
              type: "string"
              format: "date-time"
            completed_at:
              type: "string"
              format: "date-time"
        focus:
          type: "string"
        blockers:
          type: "array"
          items:
            type: "object"
            properties:
              id:
                type: "string"
              text:
                type: "string"
              created_at:
                  type: "string"
                  format: "date-time"
        tasks:
          type: "array"
          items:
            type: "object"
            properties:
              id:
                type: "string"
              text:
                type: "string"
              priority:
                type: "string"
              completed:
                type: "boolean"
              created_at:
                type: "string"
                format: "date-time"
              completed_at:
                type: "string"
                format: "date-time"
        message:
          type: "string"
    vault_changes:
      type: "array"
      items:
        type: "object"
        properties:
          path:
            type: "string"
          operation:
            type: "string"
            enum: ["CREATE", "UPDATE", "DELETE", "APPEND"]
          content:
            type: "string"
          frontmatter:
            type: "object"
  required: ["success"]
depends_on: []
execution:
  timeout_seconds: 15
  memory_limit_mb: 128
  cpu_limit_percent: 30
  sandbox: true
  retries: 1
  retry_backoff_ms: 1000
---

## Instrucciones de Ejecución

```bash
# Agregar tarea
curl -X POST http://host.docker.internal:PORT_OC/jarvis/adapter \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "plan",
    "input": {
      "action": "add_task",
      "task": "Revisar PR #42 - autenticación",
      "priority": "high"
    },
    "context": { "vault_path": "/app/vault", "skills_path": "/app/.skills", "session_id": "uuid" }
  }'

# Leer plan de hoy
curl -X POST ... -d '{"skill":"plan","input":{"action":"read"},"context":{...}}'

# Completar tarea
curl -X POST ... -d '{"skill":"plan","input":{"action":"complete_task","task_id":"tsk-001"},"context":{...}}'

# Establecer foco principal
curl -X POST ... -d '{"skill":"plan","input":{"action":"set_focus","focus":"Release v1.2.0 - testing y docs"},"context":{...}}'

# Agregar bloqueo
curl -X POST ... -d '{"skill":"plan","input":{"action":"add_blocker","blocker":"Esperando approval de security team"},"context":{...}}'

# Archivar plan de ayer
curl -X POST ... -d '{"skill":"plan","input":{"action":"archive","date":"2026-08-07"},"context":{...}}'
```

## Lógica de Negocio

### Estructura del Archivo `wiki/plan_YYYY-MM-DD.md`

```markdown
---
id: plan_2026-08-08
tags: [plan, daily]
created: "2026-08-08T08:00:00Z"
modified: "2026-08-08T15:30:00Z"
source: "skill.plan"
date: "2026-08-08"
focus: "Release v1.2.0 - testing y docs"
task_counter: 3
blocker_counter: 1
---
# Plan de Hoy — 2026-08-08

## 🎯 Foco Principal
- Release v1.2.0 - testing y docs

## ✅ Tareas
- [x] **tsk-001** 🟢 Standup matutino — *2026-08-08T08:15:00Z*
- [ ] **tsk-002** 🔴 Revisar PR #42 - autenticación — *2026-08-08T09:30:00Z*
- [ ] **tsk-003** 🟡 Actualizar CHANGELOG.md — *2026-08-08T10:00:00Z*

## 🚫 Bloqueos
- **blk-001** ⏳ Esperando approval de security team — *2026-08-08T11:00:00Z*

## 📝 Notas
> Agregado via voice: "Recordar revisar logs de staging"
```

### Emojis de Prioridad
- `critical` → 🟣 (purple)
- `high` → 🔴 (red)
- `medium` → 🟡 (yellow)
- `low` → 🟢 (green)
- `completed` → ✅ (check)

### Generación de IDs
- Tareas: `tsk-XXX` (contador incremental por día, persistido en frontmatter `task_counter`)
- Bloqueos: `blk-XXX` (contador `blocker_counter`)

---

### 1. `create` — Crear plan nuevo (o resetear)
1. Verificar si `wiki/plan_YYYY-MM-DD.md` existe
2. Si existe y no `replace_all`: error `PLAN_EXISTS`
3. Crear estructura base con frontmatter:
   - `id: plan_YYYY-MM-DD`
   - `tags: [plan, daily]`
   - `created: now()`, `modified: now()`
   - `date: YYYY-MM-DD`
   - `task_counter: 0`, `blocker_counter: 0`
   - `focus: ""`
4. Escribir archivo (CREATE)
5. Retornar `success: true, message: "Plan creado para YYYY-MM-DD"`

### 2. `read` — Leer plan
1. Leer `wiki/plan_YYYY-MM-DD.md` (date o hoy)
2. Si no existe: crear vía `create` y retornar vacío
3. Parsear Markdown → estructura de datos:
   - Extraer `focus` de sección "## 🎯 Foco Principal"
   - Parsear tareas de "## ✅ Tareas" (checkbox + ID + prioridad + texto + timestamp)
   - Parsear bloqueos de "## 🚫 Bloqueos" (ID + texto + timestamp)
4. Retornar `data: {focus, tasks:[], blockers:[]}`

### 3. `add_task` — Agregar tarea
1. Leer plan (crear si no existe)
2. Incrementar `task_counter` → `tsk-XXX` (zero-padded 3 dígitos)
3. Determinar emoji por `priority`
4. Formatear línea: `- [ ] **tsk-XXX** 🔴 Texto de la tarea — *timestamp*`
5. Insertar en sección "## ✅ Tareas" (antes de "## 🚫 Bloqueos" o al final)
6. Actualizar `modified: now()` en frontmatter
7. Escribir archivo (UPDATE atómico: temp + rename)
8. Retornar `task_id` y task object

### 4. `complete_task` — Marcar tarea completada
1. Leer plan
2. Buscar tarea por `task_id` (o por texto si no se da ID)
3. Si no encontrada: error `TASK_NOT_FOUND` con lista de IDs válidos
4. Cambiar `- [ ]` → `- [x]`
5. Agregar `completed_at` en línea: `— *created* ✅ *completed*`
6. Actualizar `modified`
8. Escribir UPDATE
9. Retornar `success: true, data: {task_id, completed: true}`

### 5. `set_focus` — Establecer foco principal
1. Leer plan
2. Reemplazar contenido de "## 🎯 Foco Principal" con nueva línea
3. Actualizar `focus` en frontmatter
4. Actualizar `modified`
5. Escribir UPDATE
6. Retornar `focus` actualizado

### 6. `add_blocker` — Agregar bloqueo
1. Leer plan
2. Incrementar `blocker_counter` → `blk-XXX`
3. Formatear: `- **blk-XXX** ⏳ Texto del bloqueo — *timestamp*`
4. Insertar en "## 🚫 Bloqueos"
5. Actualizar `modified`, `blocker_counter`
6. Escribir UPDATE

### 7. `list` — Listar tareas (para UI/voice)
1. Leer plan
2. Retornar array `tasks` con: id, text, priority, completed, created_at, completed_at
3. Opcional: filtrar `completed: false` por defecto

### 8. `update` — Actualización masiva
1. Si `replace_all=true`: reemplazar todo el contenido (excepto frontmatter base)
2. Si `replace_all=false`: aplicar cambios parciales (no implementado en v1, usar acciones específicas)
3. Retornar plan actualizado

### 9. `archive` — Archivar plan anterior
1. Leer `wiki/plan_YYYY-MM-DD.md` (date especificado, default: ayer)
2. Mover a `wiki/archive/plan_YYYY-MM-DD.md` (CREATE)
3. Opcional: comprimir si > 30 días
4. Retornar `archived: true, path: "wiki/archive/plan_...md"`

### 10. `delete` — Eliminar plan (peligroso)
1. Confirmar con flag `confirm: true` en input (no en schema, validar en lógica)
2. Mover a `.trash/` en vault
3. Retornar `deleted: true`

---

## Estructura de Datos (Vault)

| Archivo | Descripción |
|---------|-------------|
| `wiki/plan_YYYY-MM-DD.md` | Plan activo del día |
| `wiki/archive/plan_YYYY-MM-DD.md` | Planes archivados (histórico) |

**Frontmatter:**
```yaml
---
id: plan_2026-08-08
tags: [plan, daily]
created: "2026-08-08T08:00:00Z"
modified: "2026-08-08T15:30:00Z"
source: "skill.plan"
date: "2026-08-08"
focus: "Release v1.2.0 - testing y docs"
task_counter: 3
blocker_counter: 1
---
```

---

## Manejo de Errores

| Error | Causa | Recuperación |
|-------|-------|--------------|
| `PLAN_EXISTS` | `create` sin `replace_all` y plan existe | Usar `update` o `read`; o pasar `replace_all=true` |
| `TASK_NOT_FOUND` | `task_id` no existe en complete_task | Retornar lista de task_ids válidos en error |
| `BLOCKER_NOT_FOUND` | `blocker_id` no existe | Retornar lista de blocker_ids válidos |
| `INVALID_PRIORITY` | Priority no en enum | Validar en schema; default "medium" |
| `VAULT_WRITE_FAILED` | Permisos / disco lleno | Verificar bind mount; reintentar |
| `PARSE_ERROR` | Formato plan corrupto | Backup corrupto → `.trash/`; recrear desde template |

---

## Pruebas

| Input | Expected Output | Vault Changes |
|-------|----------------|---------------|
| `{"action":"add_task","task":"Test task","priority":"high"}` | `success:true, data:{task_id:"tsk-001",task:{id:"tsk-001",text:"Test task",priority:"high",completed:false}}` | `wiki/plan_...md` UPDATE (nueva tarea 🔴) |
| `{"action":"read"}` | `success:true, data:{focus:"...",tasks:[...],blockers:[...]}` | None (o CREATE si no existe) |
| `{"action":"complete_task","task_id":"tsk-001"}` | `success:true, data:{task_id:"tsk-001",completed:true}` | `wiki/plan_...md` UPDATE (`[x]` + timestamp) |
| `{"action":"set_focus","focus":"Nuevo foco"}` | `success:true, data:{focus:"Nuevo foco"}` | `wiki/plan_...md` UPDATE (sección foco + frontmatter) |
| `{"action":"add_blocker","blocker":"Bloqueo test"}` | `success:true, data:{blocker_id:"blk-001"}` | `wiki/plan_...md` UPDATE (nuevo bloqueo) |
| `{"action":"archive","date":"2026-08-07"}` | `success:true, data:{archived:true,path:"wiki/archive/plan_2026-08-07.md"}` | `wiki/archive/plan_...md` CREATE |
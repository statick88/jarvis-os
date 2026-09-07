---
id: "skill.bandeja"
name: "Bandeja de Entrada"
version: "1.0.0"
description: "Procesamiento de inputs matutinos/resúmenes (voz, texto, web clips) → raw/inbox_<fecha>.md"
author: "jarvis-os team"
license: "MIT"
capabilities:
  - "bandeja.capture"
  - "bandeja.process"
  - "bandeja.summarize"
  - "bandeja.list"
  - "bandeja.clear"
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["capture", "process", "summarize", "list", "clear"]
      description: "Acción a ejecutar"
    content:
      type: "string"
      description: "Contenido raw a capturar (texto, transcripción, URL)"
    source:
      type: "string"
      enum: ["voice", "text", "web_clip", "email", "manual"]
      default: "manual"
      description: "Origen del input"
    metadata:
      type: "object"
      description: "Metadatos adicionales (tags, URLs, contexto)"
      properties:
        tags:
          type: "array"
          items:
            type: "string"
        url:
          type: "string"
          format: "uri"
        author:
          type: "string"
        priority:
          type: "string"
          enum: ["low", "medium", "high", "urgent"]
          default: "medium"
    date:
      type: "string"
      format: "date"
      description: "Fecha objetivo (YYYY-MM-DD), default: hoy"
    max_items:
      type: "integer"
      minimum: 1
      maximum: 100
      default: 50
      description: "Máximo items a listar"
  required: ["action"]
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
      properties:
        item_id:
          type: "string"
          description: "ID único del item capturado (UUIDv4)"
        action:
          type: "string"
        items:
          type: "array"
          items:
            type: "object"
            properties:
              id:
                type: "string"
              timestamp:
                type: "string"
                format: "date-time"
              source:
                type: "string"
              content_preview:
                type: "string"
              tags:
                type: "array"
                items:
                  type: "string"
              priority:
                type: "string"
              processed:
                type: "boolean"
        summary:
          type: "string"
          description: "Resumen generado (solo action=summarize)"
        count:
          type: "integer"
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
  timeout_seconds: 30
  memory_limit_mb: 128
  cpu_limit_percent: 30
  sandbox: true
  retries: 1
  retry_backoff_ms: 1000
---

## Instrucciones de Ejecución

```bash
# Capturar input de voz (desde voice-pipeline → orchestrator → adapter)
curl -X POST http://host.docker.internal:PORT_OC/jarvis/adapter \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "bandeja",
    "input": {
      "action": "capture",
      "content": "Recordar revisar el PR de autenticación antes del deploy",
      "source": "voice",
      "metadata": { "tags": ["trabajo", "pr", "urgente"], "priority": "high" }
    },
    "context": { "vault_path": "/app/vault", "skills_path": "/app/.skills", "session_id": "uuid" }
  }'

# Capturar web clip
curl -X POST ... -d '{
  "skill": "bandeja",
  "input": {
    "action": "capture",
    "content": "Artículo sobre nuevos patrones de arquitectura en microservicios",
    "source": "web_clip",
    "metadata": { "url": "https://example.com/arch-patterns", "tags": ["arquitectura", "lectura"] }
  },
  "context": { ... }
}'

# Procesar bandeja (clasificar, extraer tareas, mover a plan/tendencias)
curl -X POST ... -d '{"skill":"bandeja","input":{"action":"process"},"context":{...}}'

# Generar resumen matutino
curl -X POST ... -d '{"skill":"bandeja","input":{"action":"summarize"},"context":{...}}'
```

## Lógica de Negocio

### 1. `capture` — Capturar entrada raw
1. Generar `item_id` (UUIDv4) y `timestamp` (ISO 8601 UTC)
2. Validar `content` no vacío
3. Normalizar `source` y `metadata` (tags array, priority enum)
4. Determinar archivo destino: `raw/inbox_YYYY-MM-DD.md` (basado en `date` o hoy)
5. Formatear entrada como bloque Markdown:
   ```markdown
   ### 📥 2026-08-08T08:15:32Z — voice — 🔴 high
   **ID:** `a1b2c3d4-e5f6-7890-abcd-ef1234567890`
   **Tags:** `#trabajo #pr #urgente`
   **Contenido:** Recordar revisar el PR de autenticación antes del deploy
   ---
   ```
6. Hacer APPEND atómico al archivo (crear con frontmatter si no existe)
7. Retornar `item_id` y confirmación

### 2. `process` — Procesar bandeja (clasificación y enrutamiento)
1. Leer `raw/inbox_YYYY-MM-DD.md` (hoy)
2. Parsear cada entrada no procesada (`processed: false` en metadata o ausencia de marca)
3. Para cada entrada, aplicar heurísticas:
   - **Tareas accionables** (verbos: revisar, hacer, crear, arreglar) → encolar en `skill.plan` via `add_task`
   - **Lecturas/Artículos** (web_clip, tags: lectura, articulo) → encolar en `skill.tendencias` via SQS
   - **Ideas/Notas** → mover a `wiki/ideas_YYYY-MM-DD.md` o `raw/ideas/`
   - **Recordatorios** → crear en `plan` con fecha
4. Marcar entrada como `processed: true` (actualizar bloque en archivo)
5. Retornar resumen: `processed: N, to_plan: X, to_tendencias: Y, to_ideas: Z`

### 3. `summarize` — Resumen matutino
1. Leer `raw/inbox_YYYY-MM-DD.md` (hoy + ayer si es temprano)
2. Agrupar por: `source`, `priority`, `tags`
3. Generar resumen estructurado:
   - Total items
   - Por prioridad (urgent/high/medium/low)
   - Por origen (voice/text/web_clip/email)
   - Top tags
   - Items sin procesar
4. Opcional: enviar a `voice-pipeline` para TTS (vía SQS event)
5. Retornar `summary` en markdown

### 4. `list` — Listar items
1. Leer archivo inbox de `date` (default hoy)
2. Parsear y retornar array de items con: id, timestamp, source, content_preview (primeros 100 chars), tags, priority, processed
3. Limitar a `max_items`

### 5. `clear` — Limpiar procesados
1. Leer archivo, filtrar items con `processed: true`
2. Mover a `raw/archive/inbox_YYYY-MM-DD.md` (con frontmatter)
3. Reescribir archivo actual solo con no procesados
4. Retornar count de archivados

## Estructura de Datos (Vault)

**Archivo principal:** `raw/inbox_YYYY-MM-DD.md`

Frontmatter:
```yaml
---
id: inbox_2026-08-08
tags: [inbox, raw, daily]
created: "2026-08-08T00:00:00Z"
modified: "2026-08-08T15:30:00Z"
source: "skill.bandeja"
date: "2026-08-08"
---
```

**Estructura de cada entrada (bloque Markdown):**
```markdown
### 📥 2026-08-08T08:15:32Z — voice — 🔴 high
**ID:** `a1b2c3d4-e5f6-7890-abcd-ef1234567890`
**Source:** voice
**Tags:** `#trabajo #pr #urgente`
**Priority:** high
**Processed:** false
**Content:** Recordar revisar el PR de autenticación antes del deploy
---

### 📥 2026-08-08T09:30:01Z — web_clip — 🟡 medium
**ID:** `b2c3d4e5-f6a7-8901-bcde-f12345678901`
**Source:** web_clip
**Tags:** `#arquitectura #lectura`
**Priority:** medium
**URL:** https://example.com/arch-patterns
**Processed:** true
**Content:** Artículo sobre nuevos patrones de arquitectura en microservicios
---
```

**Archivo de resumen:** `wiki/inbox_summary_YYYY-MM-DD.md` (generado por `summarize`)

**Archivo de archivo:** `raw/archive/inbox_YYYY-MM-DD.md` (movidos por `clear`)

## Manejo de Errores

| Error | Causa | Recuperación |
|-------|-------|--------------|
| `EMPTY_CONTENT` | `content` vacío en capture | Retornar error 400: "Content cannot be empty" |
| `INVALID_SOURCE` | Source no en enum | Validar en schema; default "manual" |
| `INBOX_NOT_FOUND` | Archivo inbox no existe | Crear con frontmatter base (CREATE) |
| `PARSE_ERROR` | Formato de entrada inválido | Log warning; saltar entrada corrupta; continuar |
| `VAULT_WRITE_FAILED` | Permisos en bind mount | Verificar montaje; reintentar con backoff |
| `SQS_ENQUEUE_FAILED` | Fallo al encolar en process | Retornar en `sqs_events` para retry por orchestrator |

## Pruebas

| Input | Expected Output | Vault Changes |
|-------|----------------|---------------|
| `{"action":"capture","content":"Test","source":"voice","metadata":{"tags":["test"],"priority":"high"}}` | `success:true, data:{item_id:"uuid",...}` | `raw/inbox_YYYY-MM-DD.md` APPEND |
| `{"action":"list","date":"2026-08-08"}` | `success:true, data:{items:[...],count:3}` | None |
| `{"action":"summarize"}` | `success:true, data:{summary:"## Resumen...",count:5}` | `wiki/inbox_summary_YYYY-MM-DD.md` CREATE |
| `{"action":"process"}` | `success:true, data:{processed:3,to_plan:1,to_tendencias:1,to_ideas:1}` | Inbox UPDATE (processed=true), SQS events |
| `{"action":"clear"}` | `success:true, data:{archived:2}` | Inbox UPDATE, `raw/archive/inbox_...` CREATE |
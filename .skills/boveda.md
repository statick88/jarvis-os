---
id: "skill.boveda"
name: "Indexación Bóveda (Zettelkasten)"
version: "1.0.0"
description: "Indexación tipo Zettelkasten de notas en vault/ → wiki/index.md, graph JSON, links bidireccionales"
author: "jarvis-os team"
license: "MIT"
capabilities:
  - "boveda.index"
  - "boveda.rebuild"
  - "boveda.graph"
  - "boveda.links"
  - "boveda.search"
  - "boveda.stats"
  - "boveda.validate"
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["index", "rebuild", "graph", "links", "search", "stats", "validate"]
      description: "Acción a ejecutar"
    paths:
      type: "array"
      items:
        type: "string"
      description: "Rutas relativas en vault a indexar (default: [\"raw\", \"wiki\", \"outputs\"])"
      default: ["raw", "wiki", "outputs"]
    note_id:
      type: "string"
      description: "ID de nota específica (para links, validate)"
    query:
      type: "string"
      description: "Término de búsqueda (para search)"
    tags:
      type: "array"
      items:
        type: "string"
      description: "Filtrar por tags (para search, stats)"
    date_from:
      type: "string"
      format: "date"
      description: "Fecha desde (para search, stats)"
    date_to:
      type: "string"
      format: "date"
      description: "Fecha hasta (para search, stats)"
    output_format:
      type: "string"
      enum: ["markdown", "json", "graphml", "dot"]
      default: "markdown"
      description: "Formato de salida (graph, stats)"
    max_depth:
      type: "integer"
      minimum: 1
      maximum: 5
      default: 2
      description: "Profundidad máxima de links para graph"
    include_orphans:
      type: "boolean"
      default: true
      description: "Incluir notas sin links (para graph, stats)"
  required: ["action"]
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
      properties:
        indexed_count:
          type: "integer"
        updated_count:
          type: "integer"
        errors:
          type: "array"
          items:
            type: "object"
            properties:
              path:
                type: "string"
              error:
                type: "string"
        graph:
          type: "object"
          properties:
            nodes:
              type: "array"
              items:
                type: "object"
                properties:
                  id:
                    type: "string"
                  title:
                    type: "string"
                  path:
                    type: "string"
                  tags:
                    type: "array"
                    items:
                      type: "string"
                  links_out:
                    type: "array"
                    items:
                      type: "string"
                  links_in:
                    type: "array"
                    items:
                      type: "string"
                  created:
                    type: "string"
                    format: "date-time"
                  modified:
                    type: "string"
                    format: "date-time"
                  word_count:
                    type: "integer"
            edges:
              type: "array"
              items:
                type: "object"
                properties:
                  source:
                    type: "string"
                  target:
                    type: "string"
                  type:
                    type: "string"
                    enum: ["wiki_link", "tag", "date", "reference"]
            stats:
              type: "object"
              properties:
                total_nodes:
                  type: "integer"
                total_edges:
                  type: "integer"
                orphan_nodes:
                  type: "integer"
                max_degree:
                  type: "integer"
                avg_degree:
                  type: "number"
                clusters:
                  type: "integer"
        search_results:
          type: "array"
          items:
            type: "object"
            properties:
              id:
                type: "string"
              title:
                type: "string"
              path:
                type: "string"
              snippet:
                type: "string"
              score:
                type: "number"
              tags:
                type: "array"
                items:
                  type: "string"
        stats:
          type: "object"
          properties:
            total_notes:
              type: "integer"
            by_directory:
              type: "object"
            by_tag:
              type: "object"
            by_date:
              type: "object"
            total_words:
              type: "integer"
            total_links:
              type: "integer"
            broken_links:
              type: "integer"
            orphan_notes:
              type: "integer"
        validation_report:
          type: "object"
          properties:
            valid:
              type: "boolean"
            issues:
              type: "array"
              items:
                type: "object"
                properties:
                  path:
                    type: "string"
                  severity:
                    type: "string"
                    enum: ["error", "warning", "info"]
                  message:
                    type: "string"
                  line:
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
  timeout_seconds: 120
  memory_limit_mb: 512
  cpu_limit_percent: 50
  sandbox: true
  retries: 1
  retry_backoff_ms: 5000
---

## Instrucciones de Ejecución

```bash
# Indexar toda la bóveda (incremental - solo cambios)
curl -X POST http://host.docker.internal:PORT_OC/jarvis/adapter \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "boveda",
    "input": { "action": "index" },
    "context": { "vault_path": "/app/vault", "skills_path": "/app/.skills", "session_id": "uuid" }
  }'

# Reconstruir índice completo (force full scan)
curl -X POST ... -d '{"skill":"boveda","input":{"action":"rebuild"},"context":{...}}'

# Generar grafo de conocimiento
curl -X POST ... -d '{"skill":"boveda","input":{"action":"graph","output_format":"json","max_depth":3},"context":{...}}'

# Ver links de una nota
curl -X POST ... -d '{"skill":"boveda","input":{"action":"links","note_id":"plan_2026-08-08"},"context":{...}}'

# Buscar en la bóveda
curl -X POST ... -d '{"skill":"boveda","input":{"action":"search","query":"Kubernetes","tags":["tech"],"date_from":"2026-08-01"},"context":{...}}'

# Estadísticas de la bóveda
curl -X POST ... -d '{"skill":"boveda","input":{"action":"stats","output_format":"markdown"},"context":{...}}'

# Validar integridad (links rotos, frontmatter, etc.)
curl -X POST ... -d '{"skill":"boveda","input":{"action":"validate"},"context":{...}}'
```

## Lógica de Negocio

### Formato de Nota Zettelkasten (Requerido)
Todas las notas en `vault/` **DEBEN** tener frontmatter YAML:
```yaml
---
id: "unique-id"              # Obligatorio: identificador único (kebab-case)
title: "Título de la nota"   # Obligatorio
tags: [tag1, tag2]           # Opcional: array de tags
links: [[id1], [id2]]        # Opcional: links bidireccionales estilo wiki
created: "2026-08-08T08:00:00Z"  # Obligatorio: ISO 8601
modified: "2026-08-08T15:30:00Z" # Obligatorio: ISO 8601
source: "skill.plan"         # Opcional: skill que la creó
---
# Contenido Markdown...
```

### 1. `index` — Indexación Incremental
1. Calcular hash (SHA256) de cada archivo en `paths` (default: raw, wiki, outputs)
2. Comparar con índice previo en `wiki/.boveda_index.json`:
   ```json
   {
     "version": 1,
     "updated": "2026-08-08T15:30:00Z",
     "files": {
       "wiki/plan_hoy.md": {"hash": "sha256...", "id": "plan_hoy", "tags": ["plan"], "links": [], "mtime": 1234567890}
     }
   }
   ```
3. Solo procesar archivos nuevos o modificados (hash distinto)
4. Para cada archivo:
   - Parsear frontmatter (validar campos obligatorios)
   - Extraer `id`, `tags`, `links` (wiki-style `[[id]]` en contenido)
   - Extraer links implícitos: menciones de otros IDs en texto
   - Contar palabras (split por whitespace, excluir frontmatter)
   - Actualizar entrada en índice
4. Detectar archivos eliminados (en índice pero no en FS) → marcar `deleted: true`
5. Escribir índice actualizado
6. Generar/actualizar `wiki/index.md` (ver abajo)
7. Retornar `indexed_count`, `updated_count`, `errors`

### 2. `rebuild` — Reconstrucción Completa
1. Borrar `wiki/.boveda_index.json`
2. Ejecutar `index` con `force_full=true`
3. Retornar mismos campos

### 3. `graph` — Generar Grafo de Conocimiento
1. Leer índice completo
2. Construir nodos: cada nota = nodo con metadatos
3. Construir aristas:
   - **wiki_link**: `[[id]]` explícito en contenido o frontmatter `links`
   - **tag**: notas que comparten tag (peso = tags en común)
   - **date**: notas del mismo día/semana
   - **reference**: mención de ID en texto sin `[[ ]]`
4. Filtrar por `max_depth` desde nodos de entrada (o todos)
5. Exportar según `output_format`:
   - `json`: `{nodes:[], edges:[], stats:{}}`
   - `graphml`: XML para Gephi/yEd
   - `dot`: Graphviz DOT
   - `markdown`: `wiki/graph_YYYY-MM-DD.md` legible
6. Si `output_format != json`: escribir archivo en vault
7. Retornar `graph` object + `vault_changes` si aplica

### 4. `links` — Links de una Nota
1. Leer índice
2. Buscar nota por `note_id` (campo `id` en frontmatter)
3. Retornar:
   - `outgoing`: IDs en `links` frontmatter + `[[ ]]` en contenido
   - `incoming`: IDs de otras notas que enlazan a esta (backlinks)
   - `tag_neighbors`: notas con tags en común
   - `date_neighbors`: notas mismo día
   - `broken`: links salientes a IDs que no existen

### 5. `search` — Búsqueda Full-Text
1. Leer índice
2. Filtrar por: `query` (substring en title + contenido), `tags` (intersección), `date_from/to`
3. Calcular score simple:
   - +10 por match en title
   - +5 por match en tag
   - +1 por match en contenido
   - +3 por match en ID
4. Ordenar por score descendente
5. Retornar top 50 con `snippet` (contexto ±50 chars alrededor del match)

### 6. `stats` — Estadísticas de la Bóveda
1. Leer índice
2. Calcular:
   - `total_notes`: count
   - `by_directory`: count por `raw/`, `wiki/`, `outputs/`
   - `by_tag`: frecuencia de tags (top 20)
   - `by_date`: notas por día (últimos 30 días)
   - `total_words`: suma word_count
   - `total_links`: suma outgoing links
   - `broken_links`: count de links a IDs inexistentes
   - `orphan_notes`: notas sin links in/out
   - `clusters`: componentes conexos en grafo (opcional)
3. Formatear según `output_format` (markdown table o JSON)
4. Si markdown: escribir `wiki/stats_YYYY-MM-DD.md`

### 7. `validate` — Validación de Integridad
1. Leer índice
2. Verificar cada nota:
   - Frontmatter válido YAML
   - Campos obligatorios: `id`, `title`, `created`, `modified`
   - `id` único global
   - `created` ≤ `modified`
   - `tags` es array de strings
   - `links` array de strings (IDs existentes o no)
   - Enlaces `[[id]]` en contenido → IDs válidos
3. Verificar archivos en FS vs índice (huérfanos, faltantes)
4. Generar reporte con `issues[]`: `{path, severity, message, line}`
5. `valid: true` si 0 errors (warnings OK)
6. Retornar `validation_report`

---

## Estructura de Datos (Vault)

| Archivo | Descripción |
|---------|-------------|
| `wiki/.boveda_index.json` | Índice interno (JSON, no versionado en git) |
| `wiki/index.md` | Índice maestro legible (Markdown) |
| `wiki/graph_YYYY-MM-DD.md` | Grafo exportado (markdown) |
| `wiki/graph_YYYY-MM-DD.json` | Grafo para tools (JSON) |
| `wiki/graph_YYYY-MM-DD.graphml` | Grafo para Gephi |
| `wiki/stats_YYYY-MM-DD.md` | Estadísticas legibles |
| `wiki/validation_YYYY-MM-DD.md` | Reporte de validación |

### `wiki/index.md` (Índice Maestro)
```markdown
---
id: vault_index
tags: [index, vault, master]
created: "2026-08-08T06:00:00Z"
modified: "2026-08-08T15:30:00Z"
source: "skill.boveda"
total_notes: 147
last_indexed: "2026-08-08T15:30:00Z"
---
# Índice Maestro de la Bóveda — 2026-08-08

> Generado automáticamente por `skill.boveda` — Última actualización: 2026-08-08 15:30

## 📁 Por Directorio
### `wiki/` (89 notas)
- [plan_hoy](wiki/plan_hoy.md) — *plan, daily* — 2026-08-08
- [metricas_2026-08-08](wiki/metricas_2026-08-08.md) — *metricas, system* — 2026-08-08
- [tendencias_2026-08-08](wiki/tendencias_2026-08-08.md) — *tendencias, tech, IA* — 2026-08-08
...

### `raw/` (42 notas)
- [inbox_2026-08-08](raw/inbox_2026-08-08.md) — *inbox, daily* — 2026-08-08
- [tendencias_2026-08-08](raw/tendencias_2026-08-08.json) — *tendencias, raw* — 2026-08-08
...

### `outputs/` (16 notas)
- [report_semanal_2026-W32](outputs/report_semanal_2026-W32.md) — *report, weekly* — 2026-08-08
...

## 🏷️ Por Tag (Top 15)
| Tag | Count | Notas |
|-----|-------|-------|
| daily | 34 | plan_hoy, inbox_..., metricas_... |
| tech | 28 | tendencias_..., k8s_notes, ... |
| plan | 12 | plan_hoy, plan_2026-08-07, ... |
| metricas | 10 | metricas_2026-08-*, ... |
| IA | 8 | tendencias_..., research_llm_... |
...

## 🔗 Notas con Más Conexiones
1. **plan_hoy** (12 links) — hub central diario
2. **tendencias_2026-08-08** (8 links) — conecta tech/IA/infra
3. **metricas_2026-08-08** (5 links) — referenciado por reports
...

## ⚠️ Notas Huérfanas (sin links)
- `raw/quick_note_2026-08-05.md` — *consolidar o linkar*
- `outputs/old_export.md` — *archivar*

## 📊 Estadísticas Rápidas
- **Total notas:** 147
- **Total palabras:** ~45,200
- **Total links:** 312
- **Links rotos:** 3
- **Notas huérfanas:** 7
- **Clusters:** 4 componentes principales
```

---

## Manejo de Errores

| Error | Causa | Recuperación |
|-------|-------|--------------|
| `INVALID_FRONTMATTER` | YAML inválido o campos faltantes | Log error; saltar nota; reportar en `errors[]` |
| `DUPLICATE_ID` | Mismo `id` en dos notas | Mantener la más reciente por `modified`; renombrar otra con sufijo `-N` |
| `BROKEN_LINK` | `[[id]]` apunta a nota inexistente | Marcar en `validation_report`; no bloquear indexación |
| `INDEX_CORRUPT` | `.boveda_index.json` inválido | Backup corrupto → `.trash/`; ejecutar `rebuild` |
| `VAULT_WRITE_FAILED` | Permisos / espacio | Verificar bind mount; reintentar |
| `PARSE_ERROR` | Markdown malformado | Usar parser tolerante (markdown-it); extraer lo posible |

---

## Pruebas

| Input | Expected Output | Vault Changes |
|-------|----------------|---------------|
| `{"action":"index"}` | `success:true, data:{indexed_count:5,updated_count:2,errors:[]}` | `.boveda_index.json` UPDATE, `wiki/index.md` UPDATE |
| `{"action":"rebuild"}` | `success:true, data:{indexed_count:147,updated_count:0,errors:[]}` | Índice completo regenerado |
| `{"action":"graph","output_format":"json","max_depth":2}` | `success:true, data:{graph:{nodes:147,edges:312,stats:{...}}}` | None (o CREATE si markdown) |
| `{"action":"links","note_id":"plan_hoy"}` | `success:true, data:{outgoing:["tendencias_..."],incoming:["inbox_..."],broken:[]}` | None |
| `{"action":"search","query":"Kubernetes","tags":["tech"]}` | `success:true, data:{search_results:[{id:"tendencias_...",score:15,...}]}` | None |
| `{"action":"stats","output_format":"markdown"}` | `success:true, data:{stats:{total_notes:147,...}}` | `wiki/stats_...md` CREATE |
| `{"action":"validate"}` | `success:true, data:{validation_report:{valid:false,issues:[{path:"raw/note.md",severity:"warning",message:"missing tags"}]}}` | `wiki/validation_...md` CREATE |
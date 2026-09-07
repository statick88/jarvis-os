---
id: "skill-obsidian"
name: "Obsidian Vault"
version: "1.0.0"
description: "CRUD de notas Markdown en la bóveda Obsidian, búsqueda full-text y resúmenes automáticos"
author: "jarvis-os team"
license: "MIT"
capabilities:
  - "obsidian.create_note"
  - "obsidian.read_note"
  - "obsidian.update_note"
  - "obsidian.delete_note"
  - "obsidian.search_vault"
  - "obsidian.append_to_note"
  - "obsidian.summarize_note"
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["create_note", "read_note", "update_note", "delete_note", "search_vault", "append_to_note", "summarize_note"]
      description: "Acción a ejecutar"
    path:
      type: "string"
      description: "Ruta relativa desde la raíz de la bóveda"
    title:
      type: "string"
      description: "Título de la nota"
    content:
      type: "string"
      description: "Contenido Markdown"
    query:
      type: "string"
      description: "Consulta de búsqueda"
    limit:
      type: "integer"
      default: 10
      description: "Límite de resultados"
    separator:
      type: "string"
      default: "\n\n---\n\n"
      description: "Separador al appendear contenido"
  required:
    - action
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
    error:
      type: "string"
execution:
  timeout_seconds: 30
  memory_limit_mb: 256
  cpu_limit_percent: 50
  sandbox: true
  retries: 0
  retry_backoff_ms: 1000
execution_type: "python"
entrypoint: "obsidian"
---

# Obsidian Vault

Gestiona notas Markdown en la bóveda local de Obsidian.

## Acciones

- `create_note`: crea una nota nueva con frontmatter y body
- `read_note`: lee una nota por ruta
- `update_note`: reemplaza el contenido de una nota
- `delete_note`: elimina una nota
- `search_vault`: búsqueda full-text en `.md`
- `append_to_note`: agrega contenido al final de una nota
- `summarize_note`: genera un resumen automático de una nota

## Uso

```bash
python -m jarvis_os.skills.handlers.obsidian '{"action":"create_note","path":"notes/example.md","title":"Example","content":"Hello"}'
```

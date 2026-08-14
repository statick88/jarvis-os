# Habilidades (Skills)

Las skills son módulos extensibles que encapsulan capacidades específicas de jarvis-os. Cada skill se define mediante un archivo Markdown con frontmatter YAML y un handler Python opcional.

## Skills base

### 1. metricas

Extrae métricas de Docker (CPU, RAM, red) y las guarda en `wiki/metricas_<fecha>.md`.

### 2. bandeja

Procesa inputs matutinos (correo, mensajes, recordatorios) y los guarda en `raw/inbox_<fecha>.md`.

### 3. tendencias

Lee RSS/feeds, genera resúmenes en `wiki/tendencias_<fecha>.md` y encola eventos en SQS.

### 4. plan

CRUD de prioridades diarias en `wiki/plan_hoy.md`.

### 5. boveda

Indexación Zettelkasten: actualiza `wiki/index.md` y genera graph JSON.

## Estructura de una skill

```yaml
---
id: metricas
name: Métricas
description: Extracción de métricas Docker
tags: [docker, metrics, infra]
version: 1.0.0
---

# Métricas

## Instrucciones
...
```

## Desarrollar una nueva skill

1. Crea el archivo `.skills/<nombre>.md` con el frontmatter YAML.
2. Implementa el handler en `jarvis_os/skills/handlers/<nombre>.py`.
3. Registra la skill en el catálogo de skills.
4. Ejecuta `bash scripts/test_jarvis_pipeline.sh` para validar.

## Estándares

- Todos los handlers deben exponer `run(input: dict) -> dict`.
- Usa `from __future__ import annotations` y tipado estricto.
- Documenta con docstrings y logging estructurado.

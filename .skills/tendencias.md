---
id: "skill.tendencias"
name: "Análisis de Tendencias"
version: "1.0.0"
description: "Lectura de fuentes RSS/Atom/JSON → wiki/tendencias_<fecha>.md + encolar en SQS para procesamiento asíncrono"
author: "jarvis-os team"
license: "MIT"
capabilities:
  - "tendencias.fetch"
  - "tendencias.analyze"
  - "tendencias.report"
  - "tendencias.configure"
  - "tendencias.list_feeds"
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["fetch", "analyze", "report", "configure", "list_feeds"]
      description: "Acción a ejecutar"
    feed_urls:
      type: "array"
      items:
        type: "string"
        format: "uri"
      description: "URLs de feeds a procesar (override config)"
    max_items_per_feed:
      type: "integer"
      minimum: 1
      maximum: 100
      default: 20
      description: "Máximo items a leer por feed"
    hours_back:
      type: "integer"
      minimum: 1
      maximum: 168
      default: 24
      description: "Ventana temporal hacia atrás (horas)"
    keywords:
      type: "array"
      items:
        type: "string"
      description: "Palabras clave para filtrar/relevancia"
    min_relevance_score:
      type: "number"
      minimum: 0
      maximum: 1
      default: 0.3
      description: "Umbral mínimo de relevancia (0-1)"
    output_format:
      type: "string"
      enum: ["markdown", "json"]
      default: "markdown"
    enqueue_async:
      type: "boolean"
      default: true
      description: "Si true, encolar análisis profundo en SQS (jarvis-async-tasks)"
  required: ["action"]
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
      properties:
        fetched_count:
          type: "integer"
        analyzed_count:
          type: "integer"
        enqueued_count:
          type: "integer"
        feeds_processed:
          type: "array"
          items:
            type: "object"
            properties:
              url:
                type: "string"
              title:
                type: "string"
              items_fetched:
                type: "integer"
              items_relevant:
                type: "integer"
              error:
                type: "string"
        top_topics:
          type: "array"
          items:
            type: "object"
            properties:
              topic:
                type: "string"
              count:
                type: "integer"
              avg_relevance:
                type: "number"
        report_path:
          type: "string"
          description: "Ruta del reporte generado en vault"
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
    sqs_events:
      type: "array"
      items:
        type: "object"
        properties:
          queue:
            type: "string"
            enum: ["jarvis-async-tasks"]
          message:
            type: "object"
          delay_seconds:
            type: "integer"
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
# Fetch y análisis diario (programado via cron en orchestrator)
curl -X POST http://host.docker.internal:PORT_OC/jarvis/adapter \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "tendencias",
    "input": {
      "action": "fetch",
      "hours_back": 24,
      "max_items_per_feed": 20,
      "keywords": ["IA", "LLM", "Kubernetes", "Rust", "WebAssembly", "Apple Silicon", "seguridad", "observabilidad"],
      "enqueue_async": true
    },
    "context": { "vault_path": "/app/vault", "skills_path": "/app/.skills", "session_id": "uuid" }
  }'

# Generar reporte de tendencias
curl -X POST ... -d '{"skill":"tendencias","input":{"action":"report"},"context":{...}}'

# Configurar feeds
curl -X POST ... -d '{
  "skill":"tendencias",
  "input":{
    "action":"configure",
    "feeds": [
      {"url":"https://news.ycombinator.com/rss","name":"Hacker News","category":"tech"},
      {"url":"https://lobste.rs/rss","name":"Lobsters","category":"tech"},
      {"url":"https://www.reddit.com/r/programming/.rss","name":"Reddit Programming","category":"tech"},
      {"url":"https://blog.golang.org/feed.atom","name":"Go Blog","category":"lang"},
      {"url":"https://rust-lang.org/blog/feed.xml","name":"Rust Blog","category":"lang"},
      {"url":"https://kubernetes.io/blog/feed.xml","name":"Kubernetes Blog","category":"infra"}
    ]
  },
  "context":{...}
}'
```

## Lógica de Negocio

### Configuración Persistente
Los feeds se guardan en `vault/wiki/tendencias_feeds.yaml`:
```yaml
feeds:
  - url: "https://news.ycombinator.com/rss"
    name: "Hacker News"
    category: "tech"
    enabled: true
    fetch_interval_hours: 6
  - url: "https://lobste.rs/rss"
    name: "Lobsters"
    category: "tech"
    enabled: true
    fetch_interval_hours: 6
updated: "2026-08-08T15:30:00Z"
```

### 1. `fetch` — Obtener y parsear feeds
1. Leer feeds configurados desde `wiki/tendencias_feeds.yaml` (o usar `feed_urls` del input)
2. Para cada feed habilitado:
   - HTTP GET con timeout 10s, headers `User-Agent: jarvis-os/1.0`
   - Parsear según Content-Type: RSS 2.0, Atom 1.0, JSON Feed
   - Extraer: title, link, published, author, summary/content, categories/tags
   - Filtrar por `hours_back` (comparar `published` vs now)
   - Limitar a `max_items_per_feed`
3. Calcular **relevance_score** por item:
   - Base: 0.1
   - +0.2 por cada `keyword` en title (case-insensitive)
   - +0.15 por cada `keyword` en summary
   - +0.1 si category coincide con keywords conocidos (tech, IA, infra, lang)
   - +0.05 si source es "high-value" (HN, Lobsters, blogs oficiales)
   - Normalizar a 0-1
4. Filtrar items con `relevance_score >= min_relevance_score`
5. Si `enqueue_async=true` y items relevantes > 0:
   - Encolar en SQS `jarvis-async-tasks` mensaje tipo `deep_analyze` con batch de items
   - `delay_seconds: 0` (procesar ASAP)
6. Guardar items crudos en `raw/tendencias_YYYY-MM-DD.json` (JSON Lines)
7. Retornar conteos por feed

### 2. `analyze` — Análisis profundo (ejecutado desde SQS worker)
1. Recibir mensaje SQS con batch de items
2. Para cada item:
   - Fetch contenido completo (HTTP GET al link, parsear HTML → texto)
   - Extraer entidades: tecnologías, empresas, personas, productos (NER simple con keywords)
   - Clasificar tópico principal (clustering por keywords + embeddings si disponible)
   - Generar resumen 2-3 frases (extractive: primeras frases + key sentences)
   - Calcular sentiment (positivo/neutral/negativo para tech news)
3. Agrupar por tópico, ordenar por relevance_score
4. Guardar análisis en `raw/tendencias_analysis_YYYY-MM-DD.json`

### 3. `report` — Generar reporte diario en vault
1. Leer `raw/tendencias_analysis_YYYY-MM-DD.json` (o crudo si no hay análisis)
2. Generar `wiki/tendencias_YYYY-MM-DD.md` con estructura:
   ```markdown
   ---
   id: tendencias_2026-08-08
   tags: [tendencias, daily, tech, IA, kubernetes, rust]
   created: "2026-08-08T06:00:00Z"
   modified: "2026-08-08T06:15:00Z"
   source: "skill.tendencias"
   feeds_processed: 6
   items_analyzed: 47
   top_topics: ["IA/LLM", "Kubernetes", "Rust", "WebAssembly", "Seguridad"]
   ---
   # Tendencias Tecnológicas — 2026-08-08

   ## 📊 Resumen Ejecutivo
   - **Feeds procesados:** 6 / 6
   - **Items totales:** 124
   - **Relevantes (score ≥ 0.3):** 47
   - **Encolados para análisis profundo:** 47
   - **Tópicos principales:** IA/LLM (12), Kubernetes (8), Rust (6), WebAssembly (5), Seguridad (4)

   ## 🔥 Top 5 Artículos
   ### 1. "Nuevo modelo de razonamiento de OpenAI supera benchmarks" — *Hacker News* 🔴 0.92
   **Tópico:** IA/LLM | **Publicado:** 2026-08-08T04:30:00Z
   **Resumen:** OpenAI anuncia o1-pro con capacidades de razonamiento chain-of-thought...
   **Link:** https://news.ycombinator.com/item?id=12345678
   **Keywords:** #OpenAI #razonamiento #benchmarks #o1

   ### 2. "Kubernetes 1.31: Sidecars nativos y mejoras de seguridad" — *Kubernetes Blog* 🟠 0.85
   **Tópico:** Kubernetes | **Publicado:** 2026-08-08T02:15:00Z
   **Resumen:** La versión 1.31 introduce sidecar containers nativos...
   **Link:** https://kubernetes.io/blog/2026/08/08/k8s-1-31-release
   **Keywords:** #Kubernetes #sidecars #seguridad #1.31

   ...

   ## 📈 Por Categoría
   ### IA / LLM (12 artículos)
   - [ ] Nuevo modelo razonamiento OpenAI — HN — 0.92
   - [ ] Fine-tuning eficiente con LoRA — Rust Blog — 0.78
   ...

   ### Kubernetes / Infra (8 artículos)
   - [ ] K8s 1.31 sidecars — K8s Blog — 0.85
   - [ ] Cilium 1.16: eBPF para network policies — CNCF — 0.72
   ...

   ## 🔗 Enlaces para Profundizar (cola SQS)
   - Análisis profundo encolado: 47 items → `jarvis-async-tasks`
   - Tiempo estimado procesamiento: ~15 min
   ```
3. Calcular `top_topics` (agrupar por topic, contar, ordenar)
4. Escribir archivo (CREATE o UPDATE)

### 4. `configure` — Gestionar feeds
1. Validar array `feeds` (url, name, category, enabled, fetch_interval_hours)
2. Escribir `wiki/tendencias_feeds.yaml` atómicamente
3. Retornar feeds configurados

### 5. `list_feeds` — Listar feeds actuales
1. Leer `wiki/tendencias_feeds.yaml`
2. Retornar array con status (último fetch, items, errores)

## Estructura de Datos (Vault)

| Archivo | Descripción |
|---------|-------------|
| `wiki/tendencias_feeds.yaml` | Configuración persistente de feeds |
| `raw/tendencias_YYYY-MM-DD.json` | Items crudos (JSON Lines, uno por línea) |
| `raw/tendencias_analysis_YYYY-MM-DD.json` | Análisis profundo (desde SQS worker) |
| `wiki/tendencias_YYYY-MM-DD.md` | Reporte diario legible (Markdown) |

**Frontmatter reporte:**
```yaml
---
id: tendencias_2026-08-08
tags: [tendencias, daily, tech, IA, kubernetes, rust, wasm, seguridad]
created: "2026-08-08T06:00:00Z"
modified: "2026-08-08T06:15:00Z"
source: "skill.tendencias"
feeds_processed: 6
items_total: 124
items_relevant: 47
items_enqueued: 47
top_topics: ["IA/LLM", "Kubernetes", "Rust", "WebAssembly", "Seguridad"]
---
```

## Manejo de Errores

| Error | Causa | Recuperación |
|-------|-------|--------------|
| `FEED_FETCH_FAILED` | HTTP error / timeout / parse error | Log error por feed; continuar con otros; marcar feed con error |
| `FEED_PARSE_ERROR` | Formato RSS/Atom/JSON inválido | Intentar parseo tolerante (feedparser); fallback a regex |
| `CONTENT_FETCH_FAILED` | No se puede obtener artículo completo | Usar solo summary del feed; marcar `content_fetched: false` |
| `SQS_ENQUEUE_FAILED` | Fallo al encolar análisis | Retornar en `sqs_events` para retry por orchestrator; reintentar 3x |
| `NO_FEEDS_CONFIGURED` | `tendencias_feeds.yaml` no existe o vacío | Usar feeds por defecto (HN, Lobsters, Reddit, Go, Rust, K8s) |
| `VAULT_WRITE_FAILED` | Permisos en bind mount | Verificar montaje; reintentar |

## Pruebas

| Input | Expected Output | Vault Changes |
|-------|----------------|---------------|
| `{"action":"fetch","hours_back":24,"enqueue_async":true}` | `success:true, data:{fetched_count:124,analyzed_count:0,enqueued_count:47,feeds_processed:6}` | `raw/tendencias_...json` CREATE, SQS events |
| `{"action":"report"}` | `success:true, data:{report_path:"wiki/tendencias_...md",top_topics:[...]}` | `wiki/tendencias_...md` CREATE |
| `{"action":"configure","feeds":[{"url":"https://example.com/rss","name":"Test","category":"test"}]}` | `success:true, data:{feeds:[...]}` | `wiki/tendencias_feeds.yaml` CREATE/UPDATE |
| `{"action":"list_feeds"}` | `success:true, data:{feeds:[{url,name,category,enabled,last_fetch,error}]}` | None |
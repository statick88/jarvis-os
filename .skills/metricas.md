---
id: "skill.metricas"
name: "Métricas del Sistema"
version: "1.0.0"
description: "Extracción de métricas de Docker, CPU, RAM y disco → wiki/metricas_<fecha>.md"
author: "jarvis-os team"
license: "MIT"
capabilities:
  - "metricas.collect"
  - "metricas.report"
  - "metricas.docker_stats"
  - "metricas.host_stats"
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["collect", "report", "docker_stats", "host_stats"]
      description: "Acción a ejecutar"
    interval_seconds:
      type: "integer"
      minimum: 1
      maximum: 3600
      default: 60
      description: "Intervalo de muestreo para collect continuo"
    duration_seconds:
      type: "integer"
      minimum: 1
      maximum: 86400
      default: 300
      description: "Duración total de collect continuo"
    include_containers:
      type: "array"
      items:
        type: "string"
      description: "Filtrar contenedores específicos (vacío = todos)"
    output_format:
      type: "string"
      enum: ["markdown", "json", "prometheus"]
      default: "markdown"
      description: "Formato de salida del reporte"
  required: ["action"]
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
      properties:
        timestamp:
          type: "string"
          format: "date-time"
        docker:
          type: "object"
          properties:
            containers_total:
              type: "integer"
            containers_running:
              type: "integer"
            containers_stopped:
              type: "integer"
            images_count:
              type: "integer"
            networks_count:
              type: "integer"
            volumes_count:
              type: "integer"
            containers:
              type: "array"
              items:
                type: "object"
                properties:
                  name:
                    type: "string"
                  id:
                    type: "string"
                  status:
                    type: "string"
                  cpu_percent:
                    type: "number"
                  memory_usage_mb:
                    type: "number"
                  memory_limit_mb:
                    type: "number"
                  memory_percent:
                    type: "number"
                  net_io_mb:
                    type: "number"
                  block_io_mb:
                    type: "number"
                  pids:
                    type: "integer"
        host:
          type: "object"
          properties:
            cpu_percent:
              type: "number"
            cpu_count:
              type: "integer"
            load_average:
              type: "array"
              items:
                type: "number"
            memory_total_gb:
              type: "number"
            memory_used_gb:
              type: "number"
            memory_percent:
              type: "number"
            swap_total_gb:
              type: "number"
            swap_used_gb:
              type: "number"
            disk_total_gb:
              type: "number"
            disk_used_gb:
              type: "number"
            disk_percent:
              type: "number"
            disk_io_read_mb_s:
              type: "number"
            disk_io_write_mb_s:
              type: "number"
            network_interfaces:
              type: "array"
              items:
                type: "object"
                properties:
                  name:
                    type: "string"
                  bytes_sent_mb:
                    type: "number"
                  bytes_recv_mb:
                    type: "number"
                  packets_sent:
                    type: "integer"
                  packets_recv:
                    type: "integer"
        vault_path:
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
  timeout_seconds: 60
  memory_limit_mb: 256
  cpu_limit_percent: 50
  sandbox: true
  retries: 1
  retry_backoff_ms: 2000
health:
  endpoint: "/health"
  interval_seconds: 60
  timeout_seconds: 5
  expected_status: 200
---

## Instrucciones de Ejecución

La skill se invoca mediante el adapter OpenCode:

```bash
# Desde orchestrator (Docker) → OpenCode (Host)
curl -X POST http://host.docker.internal:PORT_OC/jarvis/adapter \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "metricas",
    "input": {
      "action": "collect",
      "interval_seconds": 60,
      "duration_seconds": 300,
      "output_format": "markdown"
    },
    "context": {
      "vault_path": "/app/vault",
      "skills_path": "/app/.skills",
      "session_id": "uuid-v4"
    }
  }'
```

También puede ejecutarse directamente en el host (macOS) para pruebas:

```bash
python -m jarvis_os.skills.metricas collect --interval 60 --duration 300 --format markdown
```

## Lógica de Negocio

### 1. `collect` — Recolección continua de métricas
1. Validar `interval_seconds` y `duration_seconds`
2. Calcular número de muestras: `n = duration_seconds / interval_seconds`
3. Para cada muestra (con sleep `interval_seconds` entre iteraciones):
   - Ejecutar `docker stats --no-stream --format json` para contenedores
   - Ejecutar `psutil` para métricas de host (CPU, RAM, disco, red)
   - Agregar timestamp ISO 8601 a cada muestra
   - Acumular en array `samples`
4. Al finalizar, generar reporte agregado (promedios, máximos, mínimos)
5. Escribir en `wiki/metricas_YYYY-MM-DD.md` con frontmatter Zettelkasten

### 2. `report` — Generar reporte único (snapshot)
1. Tomar una sola muestra de Docker (`docker stats --no-stream`) y host (`psutil`)
2. Formatear según `output_format` (markdown por defecto)
3. Retornar datos + opcionalmente escribir en vault

### 3. `docker_stats` — Solo métricas de contenedores
1. Ejecutar `docker stats --no-stream --format json`
2. Parsear JSON por línea
3. Filtrar por `include_containers` si se proporciona
4. Retornar array de objetos con: name, id, status, cpu_percent, memory_usage_mb, memory_limit_mb, memory_percent, net_io_mb, block_io_mb, pids

### 4. `host_stats` — Solo métricas del host (macOS)
1. Usar `psutil` para: CPU (percent, count, loadavg), memoria (virtual, swap), disco (usage, io counters), red (io counters por interfaz)
2. Retornar objeto estructurado

### Formato de salida Markdown (para vault)
```markdown
---
id: metricas_2026-08-08
tags: [metricas, system, docker, host]
created: "2026-08-08T15:30:00Z"
modified: "2026-08-08T15:35:00Z"
source: "skill.metricas"
session_id: "uuid-v4"
---
# Métricas del Sistema — 2026-08-08

## Resumen Ejecutivo
- **Muestras recolectadas:** 5 (intervalo 60s, duración 300s)
- **Contenedores totales:** 3 (3 running, 0 stopped)
- **CPU Host promedio:** 12.3% (máx: 28.1%)
- **RAM Host promedio:** 45.2% (16.4 GB / 36.0 GB)
- **Disco Host:** 62.1% (1.2 TB / 2.0 TB)

## Docker — Contenedores
| Contenedor | CPU % | RAM MB | RAM % | Net I/O MB | Block I/O MB |
|------------|-------|--------|-------|------------|--------------|
| jarvis_orchestrator | 2.1 | 145.3 | 12.4 | 1.2 / 0.8 | 5.4 / 2.1 |
| jarvis_voice | 8.7 | 2048.0 | 55.2 | 0.5 / 0.3 | 12.1 / 0.0 |
| jarvis_floci | 0.3 | 128.5 | 3.1 | 0.1 / 0.1 | 0.2 / 0.1 |

## Host — Sistema
| Métrica | Valor |
|---------|-------|
| CPU (promedio) | 12.3% |
| CPU (máx) | 28.1% |
| Load Average (1m/5m/15m) | 1.42 / 1.28 / 1.15 |
| RAM Total | 36.0 GB |
| RAM Usada | 16.4 GB (45.2%) |
| Swap Total | 8.0 GB |
| Swap Usada | 0.2 GB (2.5%) |
| Disco Total | 2.0 TB |
| Disco Usado | 1.2 TB (62.1%) |
| Disco Lectura | 12.4 MB/s |
| Disco Escritura | 8.7 MB/s |

## Red — Interfaces
| Interfaz | Enviado (MB) | Recibido (MB) | Paquetes Out | Paquetes In |
|----------|--------------|---------------|--------------|-------------|
| en0 | 145.2 | 892.1 | 128450 | 234120 |
| lo0 | 12.4 | 12.4 | 5678 | 5678 |
```

## Estructura de Datos (Vault)

**Archivo:** `wiki/metricas_YYYY-MM-DD.md` (uno por día, se hace APPEND si ya existe)

Frontmatter:
```yaml
---
id: metricas_2026-08-08
tags: [metricas, system, docker, host]
created: "2026-08-08T15:30:00Z"
modified: "2026-08-08T15:35:00Z"
source: "skill.metricas"
session_id: "uuid-v4"
---
```

## Manejo de Errores

| Error | Causa | Recuperación |
|-------|-------|--------------|
| `DOCKER_NOT_AVAILABLE` | Docker daemon no responde | Verificar socket `/var/run/docker.sock` montado; reintentar con backoff |
| `PERMISSION_DENIED` | Sin permisos para `docker stats` o `/proc` | Verificar user en grupo `docker`; capacidades `SYS_RESOURCE` |
| `PSUTIL_ERROR` | Fallo en psutil (host metrics) | Fallback a comandos `sysctl`, `vm_stat`, `df`; log warning |
| `VAULT_WRITE_FAILED` | No se puede escribir en `wiki/` | Verificar permisos en bind mount; reintentar |
| `INVALID_INTERVAL` | Intervalo < 1s o > 3600s | Validar en input_schema; retornar error 400 |

## Pruebas

| Input | Expected Output | Vault Changes |
|-------|----------------|---------------|
| `{"action":"report","output_format":"markdown"}` | `success:true, data:{docker:{...}, host:{...}}` | `wiki/metricas_YYYY-MM-DD.md` CREATE/APPEND |
| `{"action":"docker_stats"}` | `success:true, data:{containers:[...]}` | None (solo retorno) |
| `{"action":"host_stats"}` | `success:true, data:{cpu_percent:..., memory_percent:...}` | None |
| `{"action":"collect","interval_seconds":10,"duration_seconds":30}` | `success:true, data:{samples:3, aggregated:{...}}` | `wiki/metricas_YYYY-MM-DD.md` CREATE con 3 muestras |
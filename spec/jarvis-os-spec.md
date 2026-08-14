# Software Design Document (SDD): JARVIS-OS

## 1. Visión General
JARVIS-OS es un sistema operativo personal orquestado por voz y basado en texto (Markdown). Utiliza `gentle-ai` como núcleo dentro de Docker, comunicándose con procesos de Kilo Code y OpenCode que se ejecutan nativamente en el host (macOS Apple Silicon) para aprovechar el hardware local, mientras Floci emula servicios de AWS para persistencia en frío y colas de eventos.

**Objetivo:** Asistente personal proactivo que captura, procesa, organiza y devuelve información vía voz y Markdown, con arquitectura offline-first, contenedores aislados y validación continua mediante harness de `gentle-ai`.

---

## 2. Requisitos Funcionales (RF)

| ID | Requisito | Descripción | Prioridad |
|----|-----------|-------------|-----------|
| RF-01 | Captura de Voz (STT) | Audio → Texto vía Whisper.cpp local (ARM64 + Metal), latencia < 2s para 10s audio | P0 |
| RF-02 | Síntesis de Voz (TTS) | Texto → Audio vía Piper/Kokoro, voces español neutro, latencia < 1s | P0 |
| RF-03 | Orquestación de Eventos | Loop asíncrono en `gentle-orchestrator`: recibe texto, analiza intención, enruta a skill | P0 |
| RF-04 | Adapter OpenCode/Kilo | Protocolo JSON sobre HTTP/WebSocket contra daemons en host (`host.docker.internal`) | P0 |
| RF-05 | Ejecución de Skills | Carga dinámica `.skills/*.md`, parsing frontmatter YAML, ejecución sandboxed | P0 |
| RF-06 | Memoria Zettelkasten | CRUD notas en `vault/` con `id`, `tags`, `links[[...]]`, `created`, `modified` | P0 |
| RF-07 | Colas Asíncronas (SQS) | Skills de larga duración (`tendencias`) encolan trabajos en `jarvis-async-tasks` | P1 |
| RF-08 | Backup Frío (S3) | Versionado automático de `vault/` en `jarvis-vault-backups` con lifecycle policy | P1 |
| RF-09 | Health Checks | Todos los servicios exponen `/health` y `docker-compose` valida `depends_on` + healthcheck | P0 |
| RF-10 | Métricas Sistema | Skill `metricas` expone Docker stats, CPU, RAM, disco en `wiki/metricas_<fecha>.md` | P1 |
| RF-11 | Plan Diario | Skill `plan` CRUD prioridades en `wiki/plan_hoy.md` con secciones: foco, tareas, bloqueos | P0 |
| RF-12 | Bandeja Entrada | Skill `bandeja` procesa inputs raw (voz, texto, web clips) → `raw/inbox_<fecha>.md` | P1 |
| RF-13 | Tendencias/Feeds | Skill `tendencias` parsea RSS/Atom/JSON feeds configurados → `wiki/tendencias_<fecha>.md` + SQS | P1 |
| RF-14 | Indexación Bóveda | Skill `boveda` reconstruye `wiki/index.md` y graph JSON de enlaces Zettelkasten | P1 |
| RF-15 | Integración Gentle-AI | Harness evalúa código en `apply`/`verify`: SAST, pruebas, hardness, auto-fix | P0 |

---

## 3. Requisitos No Funcionales (RNF)

| ID | Requisito | Especificación |
|----|-----------|----------------|
| RNF-01 | Latencia STT | < 2 segundos para 10 segundos de audio (Whisper.cpp tiny/base en Metal) |
| RNF-02 | Latencia TTS | < 1 segundo para frase promedio (Piper en CPU ARM64) |
| RNF-03 | Latencia Orquestación | < 500ms end-to-end (texto → intención → enrutamiento skill) |
| RNF-04 | Aislamiento Contenedores | Red `jarvis-net` bridge; sin `network_mode: host`; capacidades mínimas (`CAP_DROP=ALL`) |
| RNF-05 | Offline-First | 100% local: sin API keys externas, modelos embebidos en imagen/volumen |
| RNF-06 | Arquitectura ARM64 | Dockerfiles `--platform=linux/arm64`, binarios compilados nativo (Metal/NEON) |
| RNF-07 | Persistencia Datos | Volúmenes Docker nombrados + bind mounts `./vault`, `./.skills`, `./jarvis_os` |
| RNF-08 | Observabilidad | Logs JSON estructurados, métricas Prometheus en `/metrics`, tracing OpenTelemetry opcional |
| RNF-09 | Seguridad | Sin secretos en código/imagen; LocalStack credenciales `test/test`; non-root user en contenedores |
| RNF-10 | Recuperación | `floci-localstack` volumen persistente; `voice_models` volumen nombrado; restart policy `unless-stopped` |
| RNF-11 | Validación Continua | Harness `gentle-ai` ejecuta en cada `sdd-apply`/`sdd-verify`: SAST, unit, integration, hardness |
| RNF-12 | Versionado Contratos | `spec/contracts/` versionados en git; breaking changes requieren nueva versión de contrato |

---

## 4. Diagrama de Arquitectura (Mermaid.js)

```mermaid
flowchart TD
    subgraph Host["🖥️ HOST (macOS M5)"]
        direction TB
        HUD["🎤 HUD / Voice Capture\n(Audio I/O)"]
        OC["🤖 OpenCode Daemon\n(localhost:PORT_OC)"]
        KC["⚡ Kilo Code Daemon\n(localhost:PORT_KC)"]
        VaultFS[("📁 ./vault/\nraw/ wiki/ outputs/")]
        SkillsFS[("📁 ./.skills/\n*.md")]
    end

    subgraph Docker["🐳 DOCKER NETWORK (jarvis-net)"]
        direction TB
        GO["🧠 gentle-orchestrator\n(Node/Python :3000)"]
        VP["🎙️ voice-pipeline\n(Whisper.cpp + Piper/Kokoro :8080)"]
        FL["☁️ floci-localstack\n(LocalStack S3+SQS :4566)"]
    end

    subgraph Volumes["💾 VOLÚMENES COMPARTIDOS"]
        VaultVol[("/app/vault ←→ ./vault")]
        SkillsVol[("/app/.skills ←→ ./.skills")]
        CodeVol[("/app/jarvis_os ←→ ./jarvis_os")]
        ModelsVol[("/models (voice_models)")]
    end

    %% Flujo principal
    HUD -->|Audio (PCM/WAV)| VP
    VP -->|STT: Texto transcrito| GO
    GO -->|Análisis intención + enrutamiento| OC
    OC -->|Lee .skills/SKILL.md| SkillsFS
    OC -->|Ejecuta lógica skill| GO
    GO -->|Resultado estructurado| VaultFS
    VaultFS -->|Detecta cambio (watch)| HUD
    HUD -->|Resumen para TTS| VP
    VP -->|TTS: Audio sintetizado| HUD

    %% Colas y backup
    GO -->|Encola tarea async (tendencias)| FL
    FL -->|SQS: jarvis-async-tasks| GO
    GO -->|Backup vault (programado)| FL
    FL -->|S3: jarvis-vault-backups| VaultFS

    %% Volúmenes
    GO -.-> VaultVol
    GO -.-> SkillsVol
    GO -.-> CodeVol
    VP -.-> ModelsVol

    %% Estilos
    classDef host fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef docker fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
    classDef vol fill:#fff3e0,stroke:#ef6c00,stroke-width:2px;
    class Host,Host fill:#e8f5e9,stroke:#2e7d32;
    class Docker,Docker fill:#e3f2fd,stroke:#1565c0;
    class Volumes,Volumes fill:#fff3e0,stroke:#ef6c00;
```

---

## 5. Contrato de Comunicación `voice-pipeline` (gRPC/REST)

### 5.1 Protobuf Definition (`spec/contracts/voice_api.proto`)

```protobuf
syntax = "proto3";

package jarvis.voice.v1;

option go_package = "github.com/jarvis-os/voice-bridge/gen/go";
option python_package = "jarvis_os.voice_bridge.gen";

service VoicePipeline {
  // Speech-to-Text: Audio streaming → Texto
  rpc StreamSTT(stream AudioChunk) returns (STTResponse) {}
  
  // Speech-to-Text: Archivo completo → Texto (unary)
  rpc Transcribe(TranscribeRequest) returns (STTResponse) {}
  
  // Text-to-Speech: Texto → Audio streaming
  rpc StreamTTS(TTSRequest) returns (stream AudioChunk) {}
  
  // Text-to-Speech: Texto → Archivo audio (unary)
  rpc Synthesize(TTSRequest) returns (SynthesizeResponse) {}
  
  // Health check
  rpc Health(HealthRequest) returns (HealthResponse) {}
  
  // Listar modelos disponibles
  rpc ListModels(ListModelsRequest) returns (ListModelsResponse) {}
}

// --- STT ---
message AudioChunk {
  bytes data = 1;           // PCM 16kHz 16-bit mono (chunk ~100ms)
  bool is_final = 2;        // true = último chunk
  string session_id = 3;    // ID de sesión para streaming
}

message TranscribeRequest {
  bytes audio_data = 1;     // Audio completo (WAV/PCM)
  string model = 2;         // "whisper-tiny", "whisper-base", "whisper-small"
  string language = 3;      // "es", "en", "auto"
  float temperature = 4;    // 0.0 - 1.0
}

message STTResponse {
  string text = 1;          // Texto transcrito
  float confidence = 2;     // 0.0 - 1.0
  string language = 3;      // Idioma detectado
  int64 duration_ms = 4;    // Duración audio procesado
  repeated WordTimestamp words = 5; // Opcional: timestamps por palabra
}

message WordTimestamp {
  string word = 1;
  float start_ms = 2;
  float end_ms = 3;
  float confidence = 4;
}

// --- TTS ---
message TTSRequest {
  string text = 1;          // Texto a sintetizar
  string voice = 2;         // "es_ES-pacifico", "es_ES-dave", "kokoro-es"
  float speed = 3;          // 0.5 - 2.0 (default 1.0)
  string format = 4;        // "wav", "mp3", "opus", "pcm"
  int32 sample_rate = 5;    // 16000, 22050, 44100 (default 22050)
}

message SynthesizeResponse {
  bytes audio_data = 1;     // Audio completo
  string format = 2;
  int32 sample_rate = 3;
  int64 duration_ms = 4;
}

// --- Health & Models ---
message HealthRequest {}
message HealthResponse {
  bool healthy = 1;
  string version = 2;
  string stt_model = 3;
  string tts_voice = 4;
  int64 uptime_ms = 5;
}

message ListModelsRequest {}
message ListModelsResponse {
  repeated ModelInfo stt_models = 1;
  repeated ModelInfo tts_voices = 2;
}

message ModelInfo {
  string id = 1;
  string name = 2;
  string language = 3;
  bool loaded = 4;
}
```

### 5.2 REST Fallback (HTTP/JSON)
Para compatibilidad con herramientas que no usan gRPC:

| Endpoint | Método | Request | Response |
|----------|--------|---------|----------|
| `/v1/stt/transcribe` | POST | `multipart/form-data`: `audio` (file), `model`, `language` | `{ "text", "confidence", "language", "duration_ms" }` |
| `/v1/tts/synthesize` | POST | JSON: `{ "text", "voice", "speed", "format" }` | `audio/*` (streaming) o JSON con `audio_data` (base64) |
| `/health` | GET | — | `{ "healthy": true, "version": "...", "stt_model": "...", "tts_voice": "..." }` |
| `/v1/models` | GET | — | `{ "stt_models": [...], "tts_voices": [...] }` |

---

## 6. Contrato Adapter OpenCode (`spec/contracts/opencode_adapter.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OpenCode Adapter Protocol",
  "version": "1.0.0",
  "description": "Protocolo de mensajería entre gentle-orchestrator (Docker) y OpenCode/Kilo Code (Host)",
  "type": "object",
  "definitions": {
    "Envelope": {
      "type": "object",
      "required": ["id", "timestamp", "type", "payload"],
      "properties": {
        "id": { "type": "string", "format": "uuid", "description": "ID único del mensaje (correlation ID)" },
        "timestamp": { "type": "string", "format": "date-time", "description": "ISO 8601 UTC" },
        "type": { "type": "string", "enum": ["REQUEST", "RESPONSE", "EVENT", "ERROR", "HEARTBEAT"] },
        "payload": { "type": "object" }
      }
    },
    "SkillExecutionRequest": {
      "type": "object",
      "required": ["skill", "input", "context"],
      "properties": {
        "skill": { "type": "string", "pattern": "^[a-z_]+$", "description": "Nombre skill sin extensión (ej: plan, bandeja)" },
        "input": { "type": "object", "description": "Entrada específica de la skill (texto, parámetros)" },
        "context": {
          "type": "object",
          "properties": {
            "vault_path": { "type": "string", "default": "/app/vault" },
            "skills_path": { "type": "string", "default": "/app/.skills" },
            "session_id": { "type": "string", "format": "uuid" },
            "user_id": { "type": "string" }
          },
          "required": ["vault_path", "skills_path"]
        }
      }
    },
    "SkillExecutionResponse": {
      "type": "object",
      "required": ["success", "output", "vault_changes"],
      "properties": {
        "success": { "type": "boolean" },
        "output": { "type": "object", "description": "Resultado estructurado de la skill" },
        "vault_changes": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["path", "operation", "content"],
            "properties": {
              "path": { "type": "string", "description": "Ruta relativa en vault (ej: wiki/plan_hoy.md)" },
              "operation": { "type": "string", "enum": ["CREATE", "UPDATE", "DELETE", "APPEND"] },
              "content": { "type": "string", "description": "Contenido nuevo (para CREATE/UPDATE/APPEND)" },
              "frontmatter": { "type": "object", "description": "YAML frontmatter para notas Zettelkasten" }
            }
          }
        },
        "sqs_events": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["queue", "message"],
            "properties": {
              "queue": { "type": "string", "enum": ["jarvis-async-tasks"] },
              "message": { "type": "object" },
              "delay_seconds": { "type": "integer", "minimum": 0, "default": 0 }
            }
          }
        },
        "error": { "type": "string" },
        "duration_ms": { "type": "integer" }
      }
    },
    "HealthCheck": {
      "type": "object",
      "properties": {
        "service": { "type": "string", "enum": ["opencode", "kilo"] },
        "status": { "type": "string", "enum": ["healthy", "degraded", "down"] },
        "version": { "type": "string" },
        "active_sessions": { "type": "integer" }
      }
    }
  },
  "oneOf": [
    { "$ref": "#/definitions/Envelope" },
    { "$ref": "#/definitions/SkillExecutionRequest" },
    { "$ref": "#/definitions/SkillExecutionResponse" },
    { "$ref": "#/definitions/HealthCheck" }
  ],
  "examples": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "timestamp": "2026-08-08T15:30:00Z",
      "type": "REQUEST",
      "payload": {
        "skill": "plan",
        "input": { "action": "add_task", "task": "Revisar PR #42", "priority": "high" },
        "context": { "vault_path": "/app/vault", "skills_path": "/app/.skills", "session_id": "abc-123" }
      }
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "timestamp": "2026-08-08T15:30:01Z",
      "type": "RESPONSE",
      "payload": {
        "success": true,
        "output": { "task_id": "tsk-001", "message": "Tarea agregada a plan_hoy.md" },
        "vault_changes": [
          { "path": "wiki/plan_hoy.md", "operation": "UPDATE", "content": "---\nid: plan_hoy\ntags: [plan, daily]\n---\n# Plan de Hoy\n\n## Foco Principal\n- Revisar PR #42 🔴\n\n## Tareas\n- [ ] Revisar PR #42\n\n## Bloqueos\n- Ninguno" }
        ],
        "duration_ms": 150
      }
    }
  ]
}
```

### 6.1 Transporte
- **Primario:** WebSocket sobre `ws://host.docker.internal:<PORT_OC>/jarvis/adapter`
- **Fallback:** HTTP POST a `http://host.docker.internal:<PORT_OC>/jarvis/adapter`
- **Autenticación:** Header `X-Jarvis-Token` (shared secret configurado en env vars)
- **Heartbeat:** Cada 30s tipo `HEARTBEAT` para detectar desconexión

---

## 7. Esquema de Skills (`.skills/*.md`)

### 7.1 Formato Frontmatter YAML Obligatorio

```yaml
---
# Metadatos obligatorios
id: "skill.plan"                    # Identificador único (namespace.skill)
name: "Plan Diario"                 # Nombre legible
version: "1.0.0"                    # SemVer
description: "CRUD de prioridades diarias en wiki/plan_hoy.md"
author: "jarvis-os team"
license: "MIT"

# Capabilities y contratos
capabilities:
  - "plan.create"
  - "plan.read"
  - "plan.update"
  - "plan.delete"
  - "plan.list"

# Entrada esperada (JSON Schema)
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["create", "read", "update", "delete", "list", "add_task", "complete_task"]
    task:
      type: "string"
    priority:
      type: "string"
      enum: ["low", "medium", "high", "critical"]
    task_id:
      type: "string"
  required: ["action"]

# Salida garantizada (JSON Schema)
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
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

# Dependencias
depends_on: []                      # Lista de skill IDs requeridos

# Configuración de ejecución
execution:
  timeout_seconds: 30
  memory_limit_mb: 256
  cpu_limit_percent: 50
  sandbox: true                     # Ejecutar en proceso aislado

# Health check
health:
  endpoint: "/health"               # Opcional: endpoint HTTP si skill expone servidor
  interval_seconds: 60
---
```

### 7.2 Cuerpo Markdown (Lógica de la Skill)

El cuerpo **DEBE** contener:
1. **`## Instrucciones de Ejecución`** — Cómo invocar la skill (CLI, función, API)
2. **`## Lógica de Negocio`** — Pseudocódigo o descripción algorítmica
3. **`## Estructura de Datos (Vault)`** — Qué archivos crea/modifica y su formato
4. **`## Manejo de Errores`** — Casos de fallo y recuperación
5. **`## Pruebas`** — Casos de prueba esperados (input → output + vault_changes)

### 7.3 Ejemplo: `plan.md` (Esqueleto)

```markdown
---
id: "skill.plan"
name: "Plan Diario"
version: "1.0.0"
description: "CRUD de prioridades diarias en wiki/plan_hoy.md"
capabilities: ["plan.create", "plan.read", "plan.update", "plan.delete", "plan.list", "plan.add_task", "plan.complete_task"]
input_schema:
  type: "object"
  properties:
    action: { type: "string", enum: ["create", "read", "update", "delete", "list", "add_task", "complete_task"] }
    task: { type: "string" }
    priority: { type: "string", enum: ["low", "medium", "high", "critical"] }
    task_id: { type: "string" }
  required: ["action"]
output_schema:
  type: "object"
  properties:
    success: { type: "boolean" }
    data: { type: "object" }
    vault_changes:
      type: "array"
      items:
        type: "object"
        properties:
          path: { type: "string" }
          operation: { type: "string", enum: ["CREATE", "UPDATE", "DELETE", "APPEND"] }
          content: { type: "string" }
          frontmatter: { type: "object" }
depends_on: []
execution:
  timeout_seconds: 15
  memory_limit_mb: 128
  sandbox: true
---

## Instrucciones de Ejecución
La skill se invoca mediante el adapter OpenCode:
```bash
# Desde orchestrator (Docker) → OpenCode (Host)
curl -X POST http://host.docker.internal:PORT_OC/jarvis/adapter \
  -H "Content-Type: application/json" \
  -d '{"skill":"plan","input":{"action":"add_task","task":"Revisar PR","priority":"high"},"context":{"vault_path":"/app/vault","skills_path":"/app/.skills"}}'
```

## Lógica de Negocio
1. Parsear `input.action` y validar contra `input_schema`
2. Leer `wiki/plan_hoy.md` (crear si no existe con template base)
3. Según action:
   - `add_task`: Agregar tarea a sección "Tareas" con checkbox y prioridad (🔴 high, 🟡 medium, 🟢 low)
   - `complete_task`: Marcar `[x]` tarea por `task_id` o texto
   - `read`: Retornar contenido parseado (foco, tareas, bloqueos)
   - `update`: Reemplazar sección completa
   - `list`: Retornar array de tareas con estado
4. Escribir cambios atómicos (temp file + rename) en `wiki/plan_hoy.md`
5. Retornar `SkillExecutionResponse` con `vault_changes`

## Estructura de Datos (Vault)
**Archivo:** `wiki/plan_hoy.md`
```markdown
---
id: plan_hoy
tags: [plan, daily]
created: "2026-08-08T08:00:00Z"
modified: "2026-08-08T15:30:00Z"
---
# Plan de Hoy — 2026-08-08

## Foco Principal
- Revisar PR #42 🔴

## Tareas
- [ ] Revisar PR #42 🔴
- [ ] Actualizar documentación 🟡
- [x] Standup matutino 🟢

## Bloqueos
- Esperando review de @team-lead
```

## Manejo de Errores
| Error | Causa | Recuperación |
|-------|-------|--------------|
| `VAULT_NOT_FOUND` | `wiki/plan_hoy.md` no existe | Crear desde template base |
| `INVALID_ACTION` | Action no en enum | Retornar error 400 con acciones válidas |
| `TASK_NOT_FOUND` | `task_id` no existe en complete_task | Retornar lista de tareas válidas |
| `PERMISSION_DENIED` | Sin write en vault | Log + alerta + retry con backoff |

## Pruebas
| Input | Expected Output | Vault Changes |
|-------|----------------|---------------|
| `{"action":"add_task","task":"Test","priority":"high"}` | `success:true, data:{task_id:"tsk-001"}` | `wiki/plan_hoy.md` UPDATE con nueva tarea 🔴 |
| `{"action":"read"}` | `success:true, data:{foco:[...], tareas:[...], bloqueos:[...]}` | None |
| `{"action":"complete_task","task_id":"tsk-001"}` | `success:true, data:{completed:true}` | `wiki/plan_hoy.md` UPDATE con `[x]` |
```

---

## 8. Integración Harness Gentle-AI (Validación Continua)

### 8.1 Puntos de Integración
| Fase SDD | Harness Action | Herramientas |
|----------|----------------|--------------|
| `sdd-apply` | Pre-commit: SAST (Semgrep), secrets (Gitleaks), deps (npm audit/pip-audit) | `gentle-ai scan` |
| `sdd-apply` | Tests unitarios + integración (pytest/vitest) | `gentle-ai test` |
| `sdd-verify` | Hardness: fuzzing (AFL++), property-based (hypothesis), chaos (Litmus) | `gentle-ai hardness` |
| `sdd-verify` | Contenedores: Docker Bench Security, Trivy scan imágenes | `gentle-ai container-scan` |
| `sdd-archive` | SBOM generation (Syft), firma (Cosign), attestation (in-toto) | `gentle-ai supply-chain` |

### 8.2 Criterios de Aprobación (Quality Gates)
- **CRITICAL:** 0 hallazgos (bloquea merge)
- **HIGH:** ≤ 2 hallazgos con plan de mitigación documentado
- **MEDIUM:** ≤ 5 hallazgos (tracking en backlog)
- **COVERAGE:** ≥ 80% líneas (unit), ≥ 60% branches (integration)

### 8.3 Auto-Fix Policy
- Harness aplica auto-fix solo para: formatting (Prettier/Black), imports, type hints triviales
- Cambios de lógica **NUNCA** auto-fix; requieren PR + review humano

---

## 9. Estructura de Directorios Final

```
jarvis-os/
├── .agents                 # Reglas, arquitectura, metas (este archivo fuente)
├── .progress               # Checklist vivo de estado
├── .skills/                # Skills base (5 iniciales)
│   ├── metricas.md
│   ├── bandeja.md
│   ├── tendencias.md
│   ├── plan.md
│   └── boveda.md
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.gentle
│   └── Dockerfile.voice
├── floci/
│   └── init-aws-resources.sh
├── jarvis_os/              # Código fuente principal
│   ├── voice_bridge/       # Cliente gRPC/REST voice-pipeline
│   ├── opencode_adapter/   # Protocolo JSON ↔ OpenCode/Kilo
│   ├── floci_client/       # Cliente SQS/S3 tipado
│   ├── vault/              # Operaciones Zettelkasten
│   ├── skills/             # Loader/ejecutor skills
│   └── hud/                # Interfaz HUD (TUI/WebSocket)
├── scripts/
│   └── test_jarvis_pipeline.sh
├── spec/
│   ├── jarvis-os-spec.md   # Este documento
│   └── contracts/
│       ├── voice_api.proto
│       ├── opencode_adapter.json
│       └── skill_schema.yaml
└── vault/
    ├── raw/                # Entradas crudas
    ├── wiki/               # Conocimiento estructurado
    └── outputs/            # Artefactos generados
```

---

## 10. Próximos Pasos (FASE 2 → 3)

1. **Crear contratos** en `spec/contracts/`:
   - `voice_api.proto` (desde sección 5.1)
   - `opencode_adapter.json` (desde sección 6)
   - `skill_schema.yaml` (esquema JSON Schema del frontmatter)

2. **Implementar skills** (`.skills/*.md`) con frontmatter completo y lógica

3. **Dockerfiles** optimizados ARM64 con healthchecks

4. **Script E2E** `scripts/test_jarvis_pipeline.sh`

---

*Documento generado bajo metodología SDD (Spec-Driven Development). Última actualización: 2026-08-08*
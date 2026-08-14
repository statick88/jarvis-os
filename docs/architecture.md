# Arquitectura del Sistema

## Visión general

jarvis-os utiliza una arquitectura híbrida donde el host macOS M5 ejecuta contenedores Docker aislados, mientras que los editores de código y herramientas de productividad permanecen en el host nativo para aprovechar el hardware local.

## Componentes principales

### Host macOS M5

- **Sistema operativo**: macOS
- **Arquitectura**: ARM64 / Apple Silicon
- **Motor de contenedores**: Colima o Docker Desktop
- **Herramientas nativas**: Kilo Code, OpenCode

### Red Docker

- **Bridge network**: `jarvis-net`
- **Aislamiento**: Los contenedores se comunican entre sí por nombres DNS internos.
- **Persistencia**: Volúmenes montados desde el host para vault, skills y modelos de voz.

### Gentle Orchestrator

- **Imagen base**: Alpine Linux + Node.js 20 + Python 3.12
- **Función**: Coordina skills, vault, health checks y adaptadores externos.
- **Puerto interno**: 3000/tcp

### Voice Pipeline

- **Imagen base**: Ubuntu 24.04
- **Función**: Servidor STT/TTS ligero para healthchecks y pruebas.
- **Puerto interno**: 8080/tcp

### Floci/LocalStack

- **Imagen base**: LocalStack 3.5
- **Función**: Emula AWS S3 y SQS para desarrollo y pruebas.
- **Puertos expuestos**: 4566, 4510-4559

## Protocolos

| Protocolo | Uso | Componentes |
|-----------|-----|-------------|
| HTTP/REST | Health checks, APIs ligeras | Voice Pipeline, Orchestrator |
| gRPC | Voice API (STT/TTS) | Voice Bridge |
| WebSocket | Protocolo OpenCode | Host ↔ Orchestrator |
| AWS SDK | S3/SQS operations | Floci Client |

## Vault Zettelkasten

El vault reside en `/app/vault` dentro del contenedor `gentle-orchestrator`, montado desde el host en `./vault/`. Se organiza en:

- `raw/`: entradas en crudo y conversaciones.
- `wiki/`: notas procesadas, planes, tendencias.
- `outputs/`: artefactos generados por skills.
- `index.json`: índice de búsqueda y graph JSON.

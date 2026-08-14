# Spec — Runtime Hardening y Estabilización de Microservicios

## Requirements

### RF-RUNTIME-01: Dual Docker Compose Compatibility
El sistema debe soportar tanto `docker-compose` (legacy v1) como `docker compose` (v2)
sin parches manuales en scripts o documentación.

### RF-RUNTIME-02: STT/TTS Binaries Availability
El contenedor `voice-pipeline` debe tener `whisper-cli`, Piper y Kokoro
disponibles en PATH para ejecución de tests de latencia sin skips.

### RF-RUNTIME-03: Contexto Vivo Sincronizado
Los archivos `.agents` y `.progress` deben reflejar el estado real de la
arquitectura post-FASE 9, incluyendo servicios健康, Definition of Done actualizada
y deuda técnica cerrada.

### RF-RUNTIME-04: Orchestrator WebSocket Integration
`gentle-orchestrator` debe exponer/consumir el endpoint WebSocket
`/v1/audio/stream` para orquestar sesiones de voz bidireccionales.

### RF-RUNTIME-05: E2E Pipeline 100% Verde
La suite `bash scripts/test_jarvis_pipeline.sh` debe reportar PASS sin
fallos ni warnings de severidad CRITICAL.

## Non-Functional Requirements

### RNF-RUNTIME-01: Backward Compatibility
Los cambios en scripts y entrypoints deben mantener compatibilidad con
configuraciones existentes de `docker-compose.yml`.

### RNF-RUNTIME-02: Minimal Image Bloat
La imagen `voice-pipeline` no debe crecer más del 20% por la inclusión de
binarios STT/TTS; usar multi-stage builds y volúmenes para modelos.

### RNF-RUNTIME-03: Observabilidad
Todos los servicios deben exponer métricas de health, latencia y estado de
conexiones WebSocket activas.

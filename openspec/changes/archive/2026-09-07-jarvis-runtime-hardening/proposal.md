# Propuesta: Runtime Hardening y Estabilización de Microservicios

## Problema
Tras el cierre de FASE 9, la pila Docker opera con 3 servicios healthy, pero
persisten deuda técnica y riesgos operativos:

1. **Entorno inestable**: `docker compose` v2 no funciona en este host; todo
   requiere sintaxis legacy `docker-compose`.
2. **Binarios STT/TTS ausentes**: `whisper-cli`, Piper y Kokoro no están
   disponibles en runtime, por lo que tests de latencia se saltan.
3. **Contexto desincronizado**: `.agents` y `.progress` no reflejan la
   arquitectura post-FASE 9 de forma consistente.
4. **`gentle-orchestrator` no integra streaming WebSocket**: expone REST pero
   no consume `/v1/audio/stream` activamente.

## Solución Propuesta
FASE 10 (`jarvis-runtime-hardening`):

1. **Compatibilidad Docker dual**: Actualizar entrypoints y scripts para
   soportar tanto `docker-compose` legacy como `docker compose` v2.
2. **Binarios STT/TTS en runtime**: Asegurar compilación/descarga de
   `whisper-cli`, Piper y Kokoro en imagen `voice-pipeline`; montar modelos
   por defecto en `/models/whisper` y `/models/kokoro`.
3. **Sincronización de contexto**: Actualizar `.agents` y `.progress` con
   arquitectura post-FASE 9, deuda técnica cerrada y Definition of Done.
4. **Integración WebSocket en orchestrator**: Agregar cliente/servicio
   `AudioStreamService` en `gentle-orchestrator` para consumir el endpoint
   `/v1/audio/stream` y orquestar sesiones de voz bidireccionales.
5. **E2E pipeline 100% verde**: Ejecutar `bash scripts/test_jarvis_pipeline.sh`
   y `bash scripts/test_audio_streaming.sh` sin skips ni warnings de severidad
   CRITICAL.

## Alcance
- **Incluye**: Dockerfiles, entrypoints, `.agents`, `.progress`,
  `gentle-orchestrator`, `jarvis_ui/lib/services/audio_stream_service.dart`,
  scripts E2E.
- **Excluye**: Cambios de especificación de protocolo, nuevas skills,
  modificaciones de contratos gRPC existentes.

## Criterios de Éxito
- [ ] `docker-compose` y `docker compose` ambos funcionan sin parches.
- [ ] `whisper-cli` y Piper/Kokoro disponibles en contenedor `voice-pipeline`.
- [ ] Tests STT/TTS latency pasan (no skipped).
- [ ] `.agents` y `.progress` 100% sincronizados.
- [ ] Suite E2E `test_jarvis_pipeline.sh` reporta PASS sin warnings CRITICAL.
- [ ] `gentle-orchestrator` expone/consume WebSocket streaming de audio.
# Proposal: Streaming de Audio Bidireccional y Baja Latencia (FASE 9)

## Intent
Elevar la experiencia multimodal de `jarvis-os` mediante streaming de audio en tiempo real y baja latencia, reemplazando el flujo request/response síncrono actual por un canal persistente bidireccional para STT y TTS.

## Scope
- **In scope:**
  - Canal WebSocket en `gentle-orchestrator` / `voice-pipeline` para chunks PCM/WAV en tiempo real desde Flutter
  - Transcripción incremental parcial con Whisper antes de finalización de captura
  - Envío de chunks de texto desde LLM hacia TTS conforme se generan
  - Reproducción de audio en buffer continuo en Flutter (`jarvis_ui`) con TTFB sub-segundo
  - Evaluación e integración de wake-word local liviano en Flutter
  - Fallback a REST HTTP cuando WebSocket no está disponible

- **Out of scope:**
  - Nuevos modelos STT/TTS propietarios
  - Soporte iOS/Web nativo (solo Android/Flutter en esta fase)
  - Cambios al motor de skills existente

## Approach
1. Definir protocolo WebSocket/gRPC para streaming bidireccional
2. Implementar servidor WebSocket en `voice-pipeline` con buffer de audio y transcripción incremental
3. Implementar cliente WebSocket en Flutter con buffer de reproducción continua
4. Integrar LLM streaming → TTS chunked pipeline
5. Evaluar wake-word engines (Porcupine, Snowboy alternativas) para Flutter
6. Implementar fallback REST HTTP para entornos sin WebSocket
7. Verificar latencia end-to-end y optimizar buffers

## Tradeoffs
- **Chosen:** WebSocket sobre gRPC bidireccional para menor overhead en mobile
- **Chosen:** Buffer circular en Flutter para latencia constante
- **Chosen:** Wake-word opcional en fase inicial para no bloquear entrega core
- **Deferred:** Soporte iOS/Web a FASE 10

## Rollback
- Revertir cambios en `voice-pipeline/server.py` y `jarvis_ui`
- Eliminar rutas WebSocket
- Mantener REST HTTP como fallback funcional

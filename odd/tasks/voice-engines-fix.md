# Feature: voice-engines-fix — Restaurar STT/TTS reales en voice-pipeline

## Objective
Que `test_audio_streaming.sh --quick` pase STT latency y TTS TTFB con respuestas reales (0 SKIP/FAIL) en la VM Colima.

## Problem
- `/models/piper/` no existe en el volumen `voice_models`; `entrypoint.voice.sh` descarga el binario Piper y los modelos Kokoro, pero nunca voces Piper. `server.py:278` invoca `piper --model /models/piper/<voice>.onnx`, falla siempre y cae al fallback Kokoro-per-call (carga 325MB por chunk, `timeout=10` en `server.py:312` → `kokoro synthesis timed out` en VM).
- REST `/stt` y `/tts` devuelven 200 con cuerpo vacío en ~0.01s (stubs), ocultando que los motores no responden por WS.
- STT por WS también da NO_RESPONSE con `whisper-cli` + `ggml-base.bin` presentes — causa pendiente de diagnóstico (T-3).

## Why
- `test_audio_streaming.sh --quick`: 11 pass, 2 fail (STT/TTS NO_RESPONSE — FAIL-HARD), 1 skip
- FASE 11 DoD exige suite E2E sin FAIL ni SKIP; el loop voz→voz no es real sin motores

## Scope
- **In scope**: descargar voz Piper es (`es_ES-pacifico`) al volumen, entrypoint la descarga si falta (fail-soft, Kokoro sigue fallback), diagnosticar STT, re-correr audio quick
- **Out of scope**: cambiar timeouts del servidor, retraining, nuevas voces, FASE 11 ya cerrada

## Constraints
- No subir modelos al repo (volumen Docker, no versionado)
- Entrypoint idempotente: si el modelo existe, no descargar
- No romper el fallback Kokoro
- Comandos con red (curl HF) pueden fallar → fail-soft con warning

## Acceptance Criteria
- [ ] `piper --model /models/piper/es_ES-pacifico.onnx` sintetiza OK dentro del contenedor
- [ ] `test_audio_streaming.sh --quick`: STT y TTS responden (0 FAIL por NO_RESPONSE)
- [ ] Entrypoint descarga la voz si falta y es no-op si existe
- [ ] Rama limpia (side-effects en `vault/notes/` revertidos)

## Applicable Checks
- `bash scripts/test_audio_streaming.sh --quick`
- `docker exec jarvis_voice piper --model /models/piper/es_ES-pacifico.onnx --output-raw < texto`
- `gentle-ai doctor`

## Progress & Verification
- Initial: 2026-10-04 diagnóstico, causa Piper confirmada, STT pendiente
- T-1 done: `es_MX-ald-medium` (63MB + json) en volumen; piper sintetiza OK tras symlink espeak-ng-data (123KB PCM)
- T-2 done: Dockerfile symlink multi-arch + `PIPER_VOICE=es_MX-ald-medium` (Dockerfile + compose) + `download_piper_voice()` idempotente en entrypoint
- T-3 done: whisper-cli OK directo (exit 0, 0.7s en silencio) PERO el build no soporta `--stream` (`error: unknown argument`) ni stdin — `WhisperSTTPipeline._spawn_process` invoca flags inexistentes → sin respuestas jamás. Requiere binario `stream` o rework batch por archivo (parciales se perderían) → DEUDA, fuera de este change
- **Deuda registrada**: STT streaming real pendiente (opciones: compilar ejemplo `stream` de whisper.cpp con SDL, o rework batch-a-archivo con solo transcripts finales)
- TTS verificado: `test_audio_streaming.sh --quick` TTS 10/10 con audio real (avg 2486ms en VM Colima, target 500ms solo alcanzable en hardware rápido); STT sigue FAIL-HARD por whisper sin `--stream`/stdin; además el harness tenía `break` en vez de `continue` ante timeouts recv (corregido 3×) y voz hardcodeada inexistente (ahora usa `tts_voice` del ack)
- Commits: rama `feat/voice-engines-fix` desde `d7ae4d1`
- T-5/T-6 done: STT batch al finalize + loopback verificado — `test_audio_streaming.sh --quick` **12 passed, 0 failed, 1 skip (EXIT=0)**; loopback 3/3 con transcripts reales; TTS avg ~1050ms en VM

---

## Task List

| ID | Task | Description | Status | Priority | Route | Trigger Evidence |
|----|------|-------------|--------|----------|-------|------------------|
| T-1 | Descargar voz Piper | curl HF `es_ES-pacifico` medium (.onnx + .onnx.json) → volumen `/models/piper/` vía `docker cp`; verificar síntesis en contenedor | pending | high | inline | 1 descarga mecánica + 1 verificación, sin research |
| T-2 | Entrypoint idempotente | `download_piper_voice()` en `docker/entrypoint.voice.sh`: si falta, descargar; si existe, no-op; fail-soft | pending | high | inline | 1 file mecánico ya comprendido |
| T-3 | Diagnosticar STT | whisper-cli directo en contenedor + logs WS; determinar si es lentitud VM o invocación rota | done | high | inline | diagnóstico read-only acotado |
| T-4 | Re-correr audio quick | `test_audio_streaming.sh --quick`, registrar resultado honesto | done | high | inline | suite con output acotado |
| T-5 | STT batch al finalize | Rework WhisperSTTPipeline sin spawn streaming; finalize escribe wav temporal, whisper-cli sobre archivo, retorna texto; session_close emite STTFinal directo | done | high | delegated direct | server.py + protocolo WS |
| T-6 | Test loopback habla real | Rework seccion STT del audio script: habla TTS, frames, close, espera stt_final con texto | done | high | inline | script ya comprendido |

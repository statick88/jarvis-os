# Tasks — Runtime Hardening y Estabilización (jarvis-runtime-hardening)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~250-350 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|---------------------|-----------------|-------------------|
| 1 | Docker fail-hard binaries + dual compose + context sync | `docker build -f docker/Dockerfile.voice -t voice-test .` | Build image, exec `whisper-cli --version` | `.agents`, `.progress`, `docker/*` |
| 2 | Orchestrator WS routes + `orchestrator_client.py` + health | `pytest jarvis_os/orchestrator.py` or `python -m jarvis_os.orchestrator` | `curl localhost:3000/health` + WS handshake | `jarvis_os/orchestrator.py`, `jarvis_os/voice_bridge/orchestrator_client.py` |
| 3 | E2E gates fail-hard + verification + `state.yaml` | `bash scripts/test_jarvis_pipeline.sh && bash scripts/test_audio_streaming.sh --quick` | Full docker-compose up | `scripts/*.sh`, `state.yaml` |

## Phase 1: Docker Dual Compatibility & Fail-Hard Binaries

- [x] 1.1 Edit `.agents` line 159: remove stale `docker-compose v1-only` restriction; document dual compose capability under Restricciones Técnicas
- [x] 1.2 Edit `docker/entrypoint.voice.sh` `verify_binaries()`: exit 1 if `whisper-cli` missing; exit 1 if both `piper` and kokoro models missing; propagate exit in main (line 112)
- [x] 1.3 Edit `docker/Dockerfile.voice` stages whisper-build and piper-build: remove `|| echo ...` fallbacks; fail build if `whisper-cli` or `piper` binary absent after build; add retry logic for kokoro model download (exponential backoff, 3 attempts)
- [x] 1.4 Edit `docker/docker-compose.yml` `voice-pipeline` volumes: add explicit bind paths for `/models/whisper` and `/models/kokoro` under `voice_models` volume
- [x] 1.5 Build `voice-pipeline` image, run container, exec `whisper-cli --version`, `piper --version`, verify `/models/kokoro/*.onnx` present; fail if any missing

## Phase 2: Orchestrator WebSocket Integration

- [x] 2.1 Create `jarvis_os/voice_bridge/orchestrator_client.py`: `OrchestratorVoiceClient` class wrapping `JarvisVoiceBridgeWS` with bounded session pool (max 10), idle timeout 300s, `open_session()`, `send_audio()`, `send_text()`, `close_session()`, `metrics()` methods
- [x] 2.2 Edit `jarvis_os/orchestrator.py`: add `POST /v1/audio/session/open`, `POST /v1/audio/session/{id}/send-audio`, `POST /v1/audio/session/{id}/send-text`, `DELETE /v1/audio/session/{id}`, `GET /v1/audio/sessions`; extend `GET /health` with `websocket_enabled` and `active_voice_sessions`
- [x] 2.3 Edit `jarvis_os/orchestrator.py`: integrate `OrchestratorVoiceClient.send_text()` into skill execution pipeline for TTS response streaming
- [x] 2.4 Edit `jarvis_os/orchestrator.py` `/health`: add `voice_pipeline_status` field reflecting STT/TTS binary availability

## Phase 3: E2E Gate Hardening

- [x] 3.1 Edit `scripts/test_audio_streaming.sh`: replace all `log_skip` calls with `log_fail` when `whisper-cli` or TTS engines missing; add pre-flight binary check at script start that fails fast
- [x] 3.2 Edit `scripts/test_jarvis_pipeline.sh`: add `test_stt_tts_binaries()` function that verifies `whisper-cli` and at least one TTS engine in `voice-pipeline` container; convert WARN severity on binary/model availability to FAIL
- [x] 3.3 Edit `scripts/test_jarvis_pipeline.sh` main(): treat missing critical dependencies (docker compose, voice-pipeline health) as hard FAIL, not warn; remove `|| true` masking on binary check tests
- [x] 3.4 Run validation harness (`gentle-ai doctor` or equivalent) and confirm 0 CRITICAL findings; document result

## Phase 5: Defect Correction (Retry after verify FAIL)

- [x] 5.1 Edit `docker/Dockerfile.voice`: add `SHELL ["/bin/bash", "-o", "pipefail", "-c"]` after FROM ubuntu:24.04 AS production to eliminate /bin/sh portability issues
- [x] 5.2 Edit `docker/Dockerfile.voice` piper-build stage (line 95): replace `RUN test -x /usr/local/bin/piper && /usr/local/bin/piper --help 2>&1 | head -3` with `RUN test -x /usr/local/bin/piper && /usr/local/bin/piper --help >/dev/null 2>&1` to fail-hard on runtime library errors
- [x] 5.3 Edit `docker/Dockerfile.voice` production stage: add explicit `libespeak-ng.so.1` presence check after COPY from piper-build; install `libespeak-ng1` via apt if missing from stage
- [x] 5.4 Edit `docker/Dockerfile.voice` kokoro-build stage: make model download best-effort (non-fatal in build); ensure entrypoint handles missing models at runtime with fail-hard
- [x] 5.5 Edit `docker/docker-compose.yml`: comment out or make conditional the `voice_models/kokoro` bind mount that overwrites baked models; prefer image-baked models with optional volume override
- [x] 5.6 Edit `docker/entrypoint.voice.sh`: add post-download verification that kokoro models are loadable (file size > 0, ONNX magic bytes present)
- [x] 5.7 Rebuild `voice-pipeline` image and verify `docker-compose -f docker/docker-compose.yml -p docker up -d --build` exits 0
- [x] 5.8 Re-run `bash scripts/test_jarvis_pipeline.sh` and `bash scripts/test_audio_streaming.sh --quick`; validate exit 0 with 0 FAIL, 0 SKIP
- [x] 5.9 Fix `docker/Dockerfile.voice` ggml library path: COPY from `/build/whisper.cpp/build/ggml/src/*.so` instead of `/build/whisper.cpp/build/src/*.so` (libraries are in ggml/src subdirectory)
- [x] 5.10 Fix test scripts `command -v` inside `docker-compose exec`: replace with `which` because `command` is a shell builtin not available as external command in exec context

## Phase 4: Context Sync & Verification

- [x] 4.1 Edit `.progress`: mark FASE 8 follow-up items (lines 185-190) as completed; add FASE 9 closure section and updated Definition of Done
- [x] 4.2 Edit `.progress`: add entry marking `2026-08-11-jarvis-ui-flutter` as COMPLETED with date 2026-08-11
- [x] 4.3 Execute `bash scripts/test_jarvis_pipeline.sh`; validate exit 0 with 0 FAIL, 0 SKIP, all PASS
- [x] 4.4 Execute `bash scripts/test_audio_streaming.sh --quick`; validate exit 0 with 0 FAIL, 0 SKIP (no missing-binary skips)
- [x] 4.5 Create `state.yaml` with verification results: test counts, binary availability matrix, service health status, timestamp

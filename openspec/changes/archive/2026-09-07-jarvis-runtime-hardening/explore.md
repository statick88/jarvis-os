# Explore — Runtime Hardening y Estabilización de Microservicios

## Current State Analysis

### Docker Compose Compatibility
- `docker-compose.yml` uses version `3.8`, compatible with both legacy `docker-compose` (v1) and `docker compose` (v2).
- Both E2E scripts (`test_jarvis_pipeline.sh`, `test_audio_streaming.sh`) already implement `run_compose()` auto-detection: try `docker compose` first, fallback to `docker-compose`.
- `.agents` documents a hard constraint: *"Este host requiere `docker-compose` (v1, hyphenated); `docker compose` (v2) no es compatible con flags `-f`"*. This may be stale; the scripts attempt v2 first, implying at least the binary exists. The actual host capability is unverified.

### STT/TTS Binaries Availability
- `Dockerfile.voice` compiles `whisper-cli` (Whisper.cpp v1.7.4 with Metal/NEON), downloads Piper binary, and installs Kokoro ONNX Python package in multi-stage build.
- All build stages use `|| echo "..." && continue` fallbacks, meaning the image can build even if compilation/download fails.
- `entrypoint.voice.sh` verifies binaries at startup but only emits warnings; it never exits non-zero for missing binaries.
- FASE 9 E2E results: 3 tests skipped because `whisper-cli` and TTS engines were not present at runtime.
- Model downloads (Whisper `ggml-base`, Kokoro ONNX + voices) are attempted in Dockerfile and entrypoint, but failure is non-fatal.

### Context Synchronization
- `.progress` is current through FASE 9 (Streaming de Audio Bidireccional), marking `jarvis-audio-streaming` as COMPLETADA and opening `jarvis-runtime-hardening`.
- `.agents` describes the target architecture correctly but contains stale notes:
  - Docker Compose v2 incompatibility claim (may be outdated).
  - Missing reference to orchestrator-side WebSocket integration requirement.
  - Missing post-FASE 9 skill registry state (`skill-obsidian`, `skill-os-control`, `skill-devsecops`).

### Orchestrator WebSocket Integration
- `voice-pipeline` exposes WebSocket `/v1/audio/stream` with full bidirectional streaming, session management, and STT/TTS pipelines (`jarvis_os/voice_bridge/server.py`).
- Flutter client (`jarvis_ui/lib/services/audio_stream_service.dart`) connects directly to `voice-pipeline:8080` with `CircularAudioBuffer`, exponential backoff reconnection, and stream getters.
- `gentle-orchestrator` (`jarvis_os/orchestrator.py`) is a FastAPI stub exposing `/health`, `/v1/execute`, and skills router. It does **not** consume `/v1/audio/stream`.
- `jarvis_os/voice_bridge/client.py` provides `JarvisVoiceBridgeWS` (WebSocket client library), but it is **not** imported or used by the orchestrator.

### E2E Pipeline Health
- `test_jarvis_pipeline.sh` and `test_audio_streaming.sh` both support dual compose detection.
- `test_audio_streaming.sh` skips STT/TTS latency tests silently when `whisper-cli` or TTS engines are unavailable.
- FASE 9 verdict: PASS WITH WARNINGS. The warnings are precisely the skips that this change must eliminate.

## Problem Statement

Post-FASE 9, the runtime exhibits four coupled problems:

1. **Optional Critical Binaries**: STT/TTS binaries are built with soft fallbacks and runtime warnings. The container can reach `healthy` state without functional voice engines, causing silent test skips and degraded production capability.
2. **Unverified Dual Compatibility**: Scripts auto-detect `docker compose` vs `docker-compose`, but `.agents` claims v2 is broken on this host. The real compatibility matrix is undocumented and untested.
3. **Orchestrator Blindness**: `gentle-orchestrator` cannot participate in voice sessions. It exposes REST but cannot initiate, monitor, or tear down bidirectional audio sessions via WebSocket, creating a single point of failure where the Flutter client must manage all voice state.
4. **Soft E2E Gates**: Tests skip on missing dependencies instead of failing. This masks regressions and violates the Definition of Done in `.agents` (*"Solo marcar `[x]` tras pasar validación"*).

## Stakeholders

- **jarvis-os maintainers**: Need reliable runtime and reproducible E2E gates.
- **gentle-orchestrator service**: Requires WebSocket client capability to orchestrate voice sessions and enforce health policies.
- **voice-pipeline service**: Must guarantee binary availability or fail fast; currently ships with optional binaries.
- **Flutter UI client (`jarvis_ui`)**: Depends on stable `/v1/audio/stream` endpoint and accurate `websocket_enabled` health flag.
- **CI/CD pipeline**: Needs deterministic E2E results without environment-dependent skips.

## Constraints

- **ARM64 (Apple Silicon M5)**: All Docker images target `linux/arm64` with Metal/NEON acceleration.
- **Offline-First**: No external API keys; Whisper.cpp and Piper run 100% local.
- **Zero Secrets in Code**: Environment variables + LocalStack `test/test` credentials only.
- **Non-Root Containers**: Both Dockerfiles create `jarvis` user (UID 1001).
- **Multi-Stage Builds**: Must keep `voice-pipeline` image growth under 20% (RNF-RUNTIME-02).
- **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
- **SDD Strict**: Phase gates `explore` → `propose` → `spec` → `design` → `tasks` → `apply` → `verify` → `archive`.
- **Review Budget**: 400 changed lines per PR default.

## Success Criteria

From `specs/runtime/spec.md`:

| ID | Requirement | Measurable Acceptance |
|----|-------------|----------------------|
| RF-RUNTIME-01 | Dual Docker Compose Compatibility | Both `docker-compose` and `docker compose` bring up the stack without manual patches. |
| RF-RUNTIME-02 | STT/TTS Binaries Availability | `whisper-cli`, `piper`, and Kokoro Python package present in `voice-pipeline` PATH; `entrypoint.sh` exits non-zero if missing. |
| RF-RUNTIME-03 | Contexto Vivo Sincronizado | `.agents` and `.progress` reflect post-FASE 9 architecture, closed debt, and updated DoD. |
| RF-RUNTIME-04 | Orchestrator WebSocket Integration | `gentle-orchestrator` exposes/consumes `/v1/audio/stream` for bidirectional voice sessions. |
| RF-RUNTIME-05 | E2E Pipeline 100% Verde | `test_jarvis_pipeline.sh` reports PASS with 0 CRITICAL warnings and 0 skipped tests. |

Non-functional:
- RNF-RUNTIME-01: Backward compatibility with existing `docker-compose.yml` configurations.
- RNF-RUNTIME-02: `voice-pipeline` image grows < 20%; models on named volume `voice_models`.
- RNF-RUNTIME-03: All services expose health, latency, and active WebSocket connection metrics.

## Open Questions

1. **Host Compose Capability**: Does this macOS M5 host actually support `docker compose` v2, or only legacy `docker-compose`? `.agents` asserts v2 is incompatible, but scripts try v2 first. Needs runtime verification (`docker compose version`).
2. **Orchestrator WS Topology**: Should the orchestrator maintain a persistent WebSocket connection pool to `voice-pipeline`, or connect on-demand per voice session? Persistent pool enables proactive health monitoring; on-demand reduces idle resource usage.
3. **Binary Failure Mode**: Should missing STT/TTS binaries prevent container startup (fail-hard in entrypoint) or allow startup with degraded REST-only mode? The current spec says "disponibles en PATH para ejecución de tests de latencia sin skips", implying fail-hard.
4. **Voice Session Ownership**: Who owns session lifecycle — the orchestrator (create → route → teardown) or the Flutter client (direct peer)? Current architecture has the Flutter client owning sessions directly; the change proposes orchestrator ownership.
5. **CI Stability Test**: Should the 30-minute continuous stream test be automated in CI, or kept as a manual/flagged test? Current `test_audio_streaming.sh` skips it entirely with `--quick`.

## Recommended Approach

### Layered Hardening (3 Phases)

**Phase 1: Fix Foundations (Low complexity)**
- **1.1 Dual Compose Lockdown**: Verify host capability. If `docker compose` v2 works, update `.agents` to remove the stale v1-only constraint. If not, document the exact failure mode and ensure scripts handle it gracefully. Add a `docker-compose.validator.sh` script that both E2E suites source.
- **1.2 Fail-Hard Binaries**: Update `entrypoint.voice.sh` to exit 1 if `whisper-cli` is missing (current behavior warns and continues). Piper remains optional if Kokoro is present, but at least one TTS engine must exist. Update Dockerfile to make model downloads non-optional or seed the `voice_models` volume.
- **1.3 Context Sync**: Update `.agents` with post-FASE 9 architecture (skills registry, WebSocket streaming, closed FASE 7/8/9 debt). Update `.progress` to mark `2026-08-11-jarvis-ui-flutter` COMPLETED and close FASE 8 follow-up items.

**Phase 2: Orchestrator Voice Integration (Medium complexity)**
- **2.1 New Module**: Create `jarvis_os/voice_bridge/orchestrator_client.py` wrapping `JarvisVoiceBridgeWS` with session lifecycle management, connection pooling, and event bus integration.
- **2.2 Orchestrator Endpoints**: Add FastAPI routes in `jarvis_os/orchestrator.py`:
  - `POST /v1/audio/session/open` — create bidirectional voice session
  - `POST /v1/audio/session/{session_id}/send-audio` — proxy PCM to voice-pipeline
  - `POST /v1/audio/session/{session_id}/send-text` — proxy TTS input
  - `DELETE /v1/audio/session/{session_id}` — teardown
  - `GET /v1/audio/sessions` — list active sessions (observability)
- **2.3 Health Extension**: Add `websocket_enabled`, `active_voice_sessions`, and `voice_pipeline_status` to orchestrator `/health`.

**Phase 3: E2E Gate Hardening (Low complexity)**
- **3.1 No Skips Policy**: Convert all `log_skip` in `test_audio_streaming.sh` to `log_fail` when binaries are missing. The pipeline must not pass if STT/TTS engines are unavailable.
- **3.2 CRITICAL Warning Escalation**: Update `test_jarvis_pipeline.sh` to treat any `WARN` on binary availability, model presence, or volume mounts as `FAIL`.
- **3.3 30-Minute Test in CI**: Implement the stability test as a backgrounded CI job rather than an inline skip, using `timeout` and log-based liveness checks.

### Why This Approach
- **Phase 1** removes the immediate risk of containers passing healthchecks while functionally degraded.
- **Phase 2** closes the architectural gap identified in the proposal: the orchestrator currently has no visibility into voice sessions.
- **Phase 3** enforces the Definition of Done without bloating the PR (estimated ~150 lines changed across scripts and entrypoints).
- Total estimated delta: ~400-600 lines across 4 phases, fitting within a single chained PR or two stacked PRs.

## Risks

- **Image Bloat**: Adding orchestrator WebSocket client dependencies (already present in `Dockerfile.gentle`: `websockets`, `grpcio`) is low risk, but session state in orchestrator increases memory footprint. Mitigation: bound session pool size and idle timeout.
- **Build Fragility**: `whisper-cli` compilation on ARM64 can fail silently due to Metal/NEON toolchain issues. Current fallbacks mask this. Mitigation: fail-hard in entrypoint + CI pre-flight build check.
- **Network Dependency for Models**: Kokoro ONNX model and Piper voices download from GitHub at build time. If GitHub is unreachable, the image builds without models. Mitigation: pre-seed `voice_models` volume in CI or make download retry logic explicit.
- **Orchestrator Complexity**: Adding session management to the orchestrator stub expands scope beyond "runtime hardening" into feature territory. Mitigation: keep Phase 2 implementation minimal — proxy + metrics only, no LLM routing logic.
- **Host Compose Incompatibility**: If `docker compose` v2 truly fails on this host, the auto-detection in scripts is cosmetic. Mitigation: explicit host capability test in Phase 1 before declaring dual compatibility done.

## Ready for Proposal

**Yes.** The exploration is complete. The problem is well-scoped, the affected areas are identified, and the approach is phased to protect the 400-line review budget. The orchestrator should proceed to `sdd-propose` (or `sdd-design` if the proposal is already approved) with the Layered Hardening approach.

**Specific guidance for the next phase:**
- Preserve the existing `docker-compose.yml` v3.8 format; no rewrite needed.
- Reuse `JarvisVoiceBridgeWS` from `jarvis_os/voice_bridge/client.py` rather than rewriting WebSocket logic.
- Keep `voice-pipeline` image delta under 20% by relying on multi-stage `COPY --from` and the existing `voice_models` named volume.
- Treat skipped E2E tests as failures; this is the hardest constraint change and will likely surface the missing-binaries problem immediately.

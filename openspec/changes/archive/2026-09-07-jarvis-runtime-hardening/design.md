# Design: Runtime Hardening y Estabilización de Microservicios

## Technical Approach

Layered hardening in three phases: (1) fail-hard voice binaries and dual-compose verification, (2) orchestrator WebSocket proxy using existing `JarvisVoiceBridgeWS`, (3) E2E gates that fail instead of skip. Keeps `docker-compose.yml` v3.8 unchanged; changes entrypoints, Dockerfile fallback semantics, orchestrator routes, and test scripts.

## Architecture Decisions

### Decision: Dual Compose Strategy
**Choice**: Preserve existing auto-detection in `run_compose()`; add CI pre-flight validation (`docker compose version` vs `docker-compose --version`) and update `.agents` to remove stale v1-only claim.
**Alternatives considered**: Force v2 only; pin to v1 only.
**Rationale**: v3.8 is compatible with both; the scripts already handle both. The only broken link is documentation.

### Decision: Fail-Hard Binaries
**Choice**: `entrypoint.voice.sh` exits 1 if `whisper-cli` is missing. Piper OR Kokoro must be present. Model downloads retry with explicit failure on final attempt.
**Alternatives considered**: Keep warnings-only; allow REST-only degraded mode.
**Rationale**: Tests must not skip. A healthy container without STT/TTS is a false positive.

### Decision: Orchestrator WS Topology
**Choice**: Persistent connection pool (one `JarvisVoiceBridgeWS` per active session) managed by a new `OrchestratorVoiceClient`. Orchestrator exposes REST proxy endpoints and owns session lifecycle.
**Alternatives considered**: On-demand connect per request; direct Flutter→voice-pipeline only.
**Rationale**: Persistent pool enables proactive health monitoring and keeps Flutter client thin. Pool size bounded with idle timeout.

### Decision: E2E Skip Policy
**Choice**: Convert `log_skip` to `log_fail` when dependencies (whisper-cli, TTS engines, python websockets) are missing. WARN severity on binary/model availability escalates to FAIL.
**Alternatives considered**: Keep skips but add coverage report.
**Rationale**: Definition of Done requires 100% verde; skips mask regressions.

## Data Flow

    Flutter UI ──WS──► Orchestrator (REST/WS proxy) ──WS──► voice-pipeline
                                                              │
                        ┌─────────────────────────────────────┘
                        ▼
                  whisper-cli / Piper / Kokoro
                        │
                        ▼
                  /models (named volume)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `docker/entrypoint.voice.sh` | Modify | `verify_binaries` returns 1 on missing whisper-cli or both TTS engines; propagate exit |
| `docker/Dockerfile.voice` | Modify | Remove `|| echo ... && continue` fallbacks in whisper/piper/kokoro build stages; fail build on missing artifacts |
| `docker/docker-compose.yml` | Modify | Add `voice_models` volume bind paths for `/models/whisper` and `/models/kokoro`; extend healthcheck |
| `jarvis_os/voice_bridge/orchestrator_client.py` | Create | Session-pooled WebSocket client wrapping `JarvisVoiceBridgeWS` with lifecycle and metrics |
| `jarvis_os/orchestrator.py` | Modify | Add `/v1/audio/session/*` routes and `websocket_enabled`, `active_voice_sessions` to `/health` |
| `scripts/test_audio_streaming.sh` | Modify | Replace `log_skip` with `log_fail` for missing binaries/engines |
| `scripts/test_jarvis_pipeline.sh` | Modify | Treat binary/model availability WARN as FAIL |
| `.agents` | Modify | Remove stale v1-only constraint; add orchestrator WS topology |
| `.progress` | Modify | Close FASE 9 debt, mark FASE 10 active |

## Interfaces / Contracts

```python
# orchestrator_client.py (new)
class OrchestratorVoiceClient:
    async def open_session(self, session_id: str) -> SessionAck: ...
    async def send_audio(self, session_id: str, pcm: bytes) -> None: ...
    async def send_text(self, session_id: str, text: str) -> None: ...
    async def close_session(self, session_id: str) -> None: ...
    def metrics(self) -> dict: ...

# New REST routes in orchestrator.py
POST /v1/audio/session/open
POST /v1/audio/session/{session_id}/send-audio
POST /v1/audio/session/{session_id}/send-text
DELETE /v1/audio/session/{session_id}
GET /v1/audio/sessions
GET /health  (extended with voice_pipeline_status, websocket_enabled, active_voice_sessions)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `verify_binaries` logic | Unit test with mocked PATH |
| Unit | `OrchestratorVoiceClient` pool | Async test with fake WS server |
| Integration | Dual compose up | CI matrix: v1 and v2 |
| Integration | Binary fail-hard | Build image, remove whisper-cli, assert container exits 1 |
| E2E | Pipeline green | `test_jarvis_pipeline.sh` → 0 FAIL, 0 SKIP |
| E2E | Audio streaming | `test_audio_streaming.sh` → STT/TTS latency tests run (no skip) |
| RED | Missing binary | Build without whisper-cli → entrypoint exits non-zero |
| RED | Missing TTS | Build without piper and kokoro → entrypoint exits non-zero |
| RED | Path traversal | Already covered in test_jarvis_pipeline.sh 3C |

## Threat Matrix

| Boundary | Minimum adversarial cases | Applicability | Design response | Planned RED tests |
|---|---|---|---|---|
| Documentation-like paths | README.sh, executable markdown | N/A — no new executable docs introduced | — | — |
| Git repository selection | git -C, relative/absolute paths | N/A — no git automation in this change | — | — |
| Commit state | staged, commit -a, empty index | N/A — no git commit automation | — | — |
| Push state | tracking branch, first push, refspec | N/A — no push automation | — | — |
| PR commands | --head, env prefix, composed commands | N/A — no PR automation | — | — |
| **Shell commands (entrypoints)** | **set -euo pipefail bypass, unbound vars, command injection** | **Applicable** | **Entrypoints use `set -euo pipefail`; all variables quoted; no user input in shell expansion** | **Test entrypoint with missing binary → exit 1; test with malformed WHISPER_MODEL → exit 1** |
| **Subprocesses (whisper-cli, piper, kokoro)** | **Missing binary, oversized input, timeout, zombie processes** | **Applicable** | **Fail-hard in entrypoint; subprocess timeouts in server.py (10s); cleanup on session close** | **Test server with no whisper-cli → WebSocket returns error frame; test timeout → process killed** |
| **Process integration (docker compose)** | **v1 vs v2 flag differences, missing compose, stale containers** | **Applicable** | **`run_compose()` auto-detects; CI pre-flight validates both binaries; scripts fail if neither present** | **Test with only docker-compose v1 → passes; test with only v2 → passes; test with none → fails** |
| **Executable-file classification** | **Dockerfile COPY of scripts, entrypoint permissions** | **Applicable** | **`chmod +x /entrypoint.sh` in Dockerfile; verify binaries in PATH, not just existence** | **Test entrypoint not executable → Docker build fails** |

## Migration / Rollout

No data migration required. Phased rollout:
1. **Phase 1** (foundations): update entrypoints, Dockerfile, `.agents`. CI validates dual compose.
2. **Phase 2** (orchestrator): add WS client and routes. Feature flag `VOICE_WS_ENABLED` defaults true.
3. **Phase 3** (E2E gates): update test scripts. Run in CI only after Phase 2 merged.

## Open Questions

- [ ] Does the host actually support `docker compose` v2? `.agents` asserts v1-only, but scripts try v2 first. Needs runtime verification.
- [ ] Should orchestrator WS pool be bounded (max sessions) or unbounded? Current design suggests bounded (e.g., 10 sessions) with idle timeout.
- [ ] Should Kokoro model download retry logic be exponential backoff or fixed interval? Current proposal suggests explicit retry; exact policy TBD.
- [ ] Should `test_audio_streaming.sh` 30-minute stability test run in CI as a backgrounded job, or remain manual? Budget and noise concerns.

## Defect Correction (Verify FAIL → Apply Retry)

### Decision: Bash Shell for Dockerfile RUN
**Choice**: Set `SHELL ["/bin/bash", "-o", "pipefail", "-c"]` in production stage of `Dockerfile.voice`. All subsequent RUN commands use bash, eliminating POSIX portability issues with arithmetic expansion and pipefail semantics.
**Alternatives considered**: Rewrite arithmetic to POSIX; use `#!/bin/sh` shebang in entrypoint only.
**Rationale**: The build already uses Ubuntu 24.04 where bash is installed. Enforcing bash in Dockerfile is simpler and more reliable than auditing every RUN command for POSIX compliance.

### Decision: Kokoro Model Download Strategy
**Choice**: Make kokoro model download best-effort in Dockerfile build stage. If download fails, build continues. Entrypoint performs runtime download with fail-hard verification. This decouples image build from external release availability.
**Alternatives considered**: Fail build on missing models; download only at runtime.
**Rationale**: GitHub release 404s should not block CI/CD pipeline. Runtime fallback ensures container starts even if models are not baked in.

### Decision: Piper Runtime Dependency Verification
**Choice**: After COPY from piper-build stage, run explicit `ldconfig -p | grep libespeak-ng.so.1` check in production stage. If missing, install `libespeak-ng1` via apt as fallback. Remove `| head -3` mask from piper-build verification.
**Alternatives considered**: Copy only specific .so files; rely on apt install only.
**Rationale**: Piper aarch64 binaries may bundle different libespeak-ng versions than Ubuntu 24.04 provides. Explicit verification catches version mismatches.

### Decision: voice_models/kokoro Bind Mount Override
**Choice**: In `docker-compose.yml`, comment out the `voice_models/kokoro` bind mount. Models are baked into the image at `/models/kokoro`. If runtime model updates are needed, use a named volume with init container pattern instead.
**Alternatives considered**: Keep bind mount and populate host directory; use emptyDir volume.
**Rationale**: Empty host directory silently overwrites baked models, causing TTS failure. Removing the bind mount makes the container self-contained.

```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:3f327a390f0987f13dd50dca163273b45e50b97324d9c7c64271bf23384ab856
verdict: fail
blockers: 4
critical_findings: 5
requirements: 5/8
scenarios: 2/5
test_command: bash scripts/test_jarvis_pipeline.sh
test_exit_code: 1
test_output_hash: sha256:996cf92a6f910b7ed76b44843aeb73660fecd4df18ef0bba7410add66f68a14e
build_command: docker-compose -f docker/docker-compose.yml -p docker up -d --build
build_exit_code: 1
build_output_hash: sha256:ec5e07e6da43f940ec163696d4dc265b5212b64864b4cc31a36f616e63223335
```

## Verification Report — `jarvis-runtime-hardening`

**Change root:** `openspec/changes/jarvis-runtime-hardening` · **Mode:** standard (Strict TDD not active) · **Phase:** verify · **Generated:** 2026-08-11T21:50:00Z
**Verdict:** **FAIL**

### Completeness

| Tasks total | Tasks completed | Tasks incomplete |
|-------------|-----------------|------------------|
| 18          | 18              | 0                |

All 18 tasks in `tasks.md` are marked `[x]`. Checkbox completion does NOT imply runtime correctness — the build and both E2E suites fail.

### Build / Test / Coverage Evidence

Primary build command: `docker-compose -f docker/docker-compose.yml -p docker up -d --build`
- **build_exit_code:** 1 · **build_output_hash:** `sha256:ec5e07e6da43f940ec163696d4dc265b5212b64864b4cc31a36f616e63223335`
- Root cause: `voice-pipeline` build fails at the `kokoro-build 3/3` stage. The Kokoro model download URLs reference release tag `model-files`, which returns HTTP **404** for `kokoro-v1.0.onnx`/`voices-v1.0.bin` (the assets live under tag `model-files-v1.0` — confirmed via the kokoro-onnx GitHub API). The retry backoff uses `$((2 ** attempt))`, a **bashism** not recognized by `/bin/sh` (dash) used by the Docker `RUN`: log `arithmetic expression: expecting primary: "2 ** attempt"`. Retry logic is therefore broken AND the URL is wrong.

Primary test command: `bash scripts/test_jarvis_pipeline.sh`
- **test_exit_code:** 1 · **test_output_hash:** `sha256:996cf92a6f910b7ed76b44843aeb73660fecd4df18ef0bba7410add66f68a14e`
- Result: `[FAIL] docker compose up falló` — build blocked at kokoro; pipeline never reached PASS state. FAIL=1, SKIP=0.

Secondary test command: `bash scripts/test_audio_streaming.sh --quick`
- exit_code: 1 · output_hash: `sha256:3cbb2b5eb8e0d993e7c3d80c330ff1e4d4e7678c7cd6424db7e70114000cd09a`
- Result: PRE-FLIGHT aborted — `whisper-cli`/`piper`/`kokoro` not available in `voice-pipeline`. (Note: this exec'd into a stale 2-hour-old `jarvis_voice` container predating hardening; the fresh image could not be built due to the kokoro failure above.)

Coverage: **N/A** — no coverage tooling present (no `.coveragerc`/`pytest.ini`/`coverage`); the E2E suite is shell-based.

### Spec Compliance Matrix (RF-RUNTIME-01..05, RNF-RUNTIME-01..03)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| RF-RUNTIME-01 Dual Docker Compose Compatibility | PASS | `run_compose()` (scripts/test_jarvis_pipeline.sh:49-58) tries `docker compose` v2 then falls back to `docker-compose` v1; build invoked via v1 fallback; `.agents:159` documents dual capability. |
| RF-RUNTIME-02 STT/TTS Binaries Availability | **FAIL (CRITICAL)** | `voice-pipeline` image build FAILS at `kokoro-build 3/3`. Kokoro URL tag `model-files` → 404 (correct tag `model-files-v1.0`). Retry backoff `$((2 ** attempt))` bashism invalid under `/bin/sh`. Piper binary built (targeted `piper-build` stage OK) but **non-functional** at runtime: `error while loading shared libraries: libespeak-ng.so.1`; the fail-hard check `test -x ... && piper --help 2>&1 | head -3` masks the non-zero exit via the pipe. |
| RF-RUNTIME-03 Contexto Vivo Sincronizado | PASS | `.agents:159` reflects dual compose + orchestrator WS topology; `.progress` shows FASE 9 closure + `jarvis-ui-flutter` COMPLETED 2026-08-11. |
| RF-RUNTIME-04 Orchestrator WebSocket Integration | **PASS (runtime-verified)** | Orchestrator force-recreated to load fresh `orchestrator.py` (stale process had pre-change code in memory): `GET /health` → `voice_pipeline_status{websocket_enabled:true,active_voice_sessions:0,voice_pipeline_available:true}`; `GET /v1/audio/sessions` → 200 `{sessions:{active_sessions:0,max_sessions:10,...},voice_client_available:true}`; `POST /v1/audio/session/open` → 200 `{session_id,websocket_enabled:true,stt_model:"base",tts_voice:"es_ES-pacifico",status:"opened"}`. `orchestrator_client.py` (OrchestratorVoiceClient) present. |
| RF-RUNTIME-05 E2E Pipeline 100% Verde | **FAIL (CRITICAL)** | `test_jarvis_pipeline.sh` exit 1; build blocked at kokoro; 0 PASS. |
| RNF-RUNTIME-01 Backward Compatibility | PASS | `docker-compose.yml` v3.8 unchanged; legacy v1 fallback works. |
| RNF-RUNTIME-02 Minimal Image Bloat | FAIL | Not measurable; image not produced (build fails). |
| RNF-RUNTIME-03 Observabilidad | PASS (runtime-verified) | `/health` exposes `voice_pipeline_status`; `/v1/audio/sessions` exposes `active`/`max`/`idle`/`available` pool metrics. |

Runtime evidence captured for RF-RUNTIME-04 (orchestrator on `127.0.0.1:3000`, after `--force-recreate`):
- `GET /health` → `{"status":"ok","service":"gentle-orchestrator","timestamp":"2026-08-11T21:47:20Z","voice_pipeline_status":{"websocket_enabled":true,"active_voice_sessions":0,"voice_pipeline_available":true}}`
- `GET /v1/audio/sessions` → `{"sessions":{"active_sessions":0,"max_sessions":10,"idle_sessions":0,"available_slots":10,"host":"jarvis-voice:8080"},"voice_client_available":true}`
- `POST /v1/audio/session/open` → `{"session_id":"verify-test","websocket_enabled":true,"stt_model":"base","tts_voice":"es_ES-pacifico","status":"opened"}`
- Uvicorn access log: `POST /v1/audio/session/open HTTP/1.1" 200 OK`

Build-stage evidence (targeted `docker build --target`):
- `whisper-build`: ✅ `git clone --branch v1.7.4` succeeded; cmake compiled; `whisper-cli` binary present at `/build/whisper.cpp/build/bin/whisper-cli`. (Minor: `whisper-cli --version` unsupported by v1.7.4 — uses `--help`; masked by `2>&1 | head -1` in `verify_binaries`.)
- `piper-build`: ⚠️ downloads OK via the `piper_linux_aarch64.tar.gz` fallback URL (tag `2023.11.14-2` exists; the `v`-prefixed URL 404s but `||` fallback works); `test -x /usr/local/bin/piper` passes BUT `piper --help` fails with `libespeak-ng.so.1: cannot open shared object file` — `libespeak-ng` is not installed; the `|| true` on the `.so` copy and the `| head -3` pipe mask the failure.
- `kokoro-build`: ❌ download fails (tag `model-files` 404; correct `model-files-v1.0`); retry backoff `$((2 ** attempt))` is a `/bin/sh` bashism.

### Design Coherence

| Design decision | Implementation | Status |
|-----------------|----------------|--------|
| Dual compose strategy (preserve `run_compose` auto-detection) | `run_compose()` present and functioning | OK |
| Fail-hard binaries (entrypoint exits 1 on missing) | `verify_binaries()` exits 1 on missing whisper-cli / both TTS | OK |
| Orchestrator WS topology (bounded pool max 10, idle timeout 300s) | `OrchestratorVoiceClient` present; pool metrics report `max_sessions=10` | OK |
| E2E skip policy (`log_skip` → `log_fail`) | `test_audio_streaming.sh` uses `log_fail` for missing binaries | OK |
| Kokoro retry (exponential backoff, 3 attempts) | URL wrong (tag `model-files` 404) + `$((2 ** attempt))` bashism invalid in `/bin/sh` | **DEVIATION (CRITICAL)** |
| Piper fail-hard check | `test -x ... && piper --help 2>&1 | head -3` — pipe masks non-zero exit of a broken binary | **DEVIATION (CRITICAL)** |
| Dockerfile COPY fallbacks | design calls for removal; lines 179-185 still use `|| true` on `COPY` | DEVIATION (WARNING) |

### Issues

**CRITICAL (verification blockers):**
- `voice-pipeline` image build fails at `kokoro-build 3/3` (`build_exit_code=1`).
- RF-RUNTIME-02 not met: no `voice-pipeline` image with working STT/TTS binaries.
- RF-RUNTIME-05 not met: `test_jarvis_pipeline.sh` exit 1; 0 PASS, build blocked.
- Kokoro download URLs reference nonexistent tag `model-files` (404; correct `model-files-v1.0`).
- Kokoro retry backoff `$((2 ** attempt))` is a bashism unsupported by `/bin/sh`, breaking retry.
- Piper binary non-functional (missing `libespeak-ng.so.1`); fail-hard check masked by `| head -3` pipe.
- `test_audio_streaming.sh --quick` exit 1 (PRE-FLIGHT abort).

**WARNING (environmental / partial):**
- Port 8080 occupied by `ssh` (PID 14681) — environmental. A stale `jarvis_voice` container (image `88e739a3d07c`, 2h pre-hardening) is also bound to 8080.
- `docker compose` v2 plugin absent on host; legacy `docker-compose` v1 used via `run_compose()` fallback (functions).
- RNF-RUNTIME-02 (image bloat ≤20%) not measurable (build fails before image produced).
- `Dockerfile.voice` lines 179-185 retain `COPY ... || true` despite design change intent (fail-hard still enforced at build-stage `test -x` checks).
- `whisper-cli --version` unsupported by whisper.cpp v1.7.4; masked by `2>&1 | head -1` in `verify_binaries`.

**SUGGESTION (not applied — verification only):**
- Correct Kokoro model URLs: tag `model-files` → `model-files-v1.0`.
- Replace `$((2 ** attempt))` (bashism) with `/bin/sh`-safe `$((1 << attempt))` or `bash -c`.
- Install `libespeak-ng` in the voice image so the piper binary is functional.
- Strengthen piper fail-hard check to inspect the real exit code (avoid masking pipe).

### Final Verdict
**FAIL** — RF-RUNTIME-02 and RF-RUNTIME-05 not satisfied; the build exits non-zero and both E2E suites fail. RF-RUNTIME-01, RF-RUNTIME-03, RF-RUNTIME-04 (runtime-verified), RNF-RUNTIME-01, and RNF-RUNTIME-03 pass. Root-cause fixes (Kokoro URL `model-files` → `model-files-v1.0`, `/bin/sh`-safe backoff, `libespeak-ng` installation, un-mask piper check) are required before PASS.

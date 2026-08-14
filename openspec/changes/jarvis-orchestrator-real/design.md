# Design: jarvis-orchestrator-real

## Technical Approach

Replace the `/v1/execute` stub in `jarvis_os/orchestrator.py` with a real four-phase pipeline (intent analysis → skill resolution → execution → response formatting) implemented in a new `jarvis_os/orchestrator/` package. The pipeline reuses existing infrastructure: `SkillExecutor` for safe subprocess execution, `SkillRegistry` for capability lookup, and `OpenCodeClient` for code execution. Voice streaming via `OrchestratorVoiceClient` is triggered post-execution when `tts_text` is present in the payload. No LLM dependency — intent analysis is rule-based per RF-ORCH-01.

## Architecture Decisions

### Decision: Rule-based intent analysis (no LLM)

**Choice**: Keyword + capability-pattern matching in `IntentAnalyzer` (rule-based).
**Alternatives considered**: LLM-based classification (e.g., call OpenCode as classifier).
**Rationale**: Eliminates external model dependency, reduces latency, matches RF-ORCH-01's explicit requirement. Deterministic output simplifies testing and debugging.

### Decision: Registry-first skill resolution

**Choice**: Query `SkillRegistry` (in-memory, already populated at startup) before falling back to `SkillLoader.load_all()`.
**Alternatives considered**: Always reload from disk via `SkillLoader`.
**Rationale**: Registry is already populated in `lifespan()` and used by `/api/v1/skills/*`. Disk reload on every `/v1/execute` call adds unnecessary I/O. Registry-first matches existing FastAPI patterns.

### Decision: Direct `OpenCodeClient` integration (no adapter)

**Choice**: Pipeline instantiates `OpenCodeClient` directly with WS-primary + HTTP-fallback (already built into the client).
**Alternatives considered**: Wrap client in a separate `OpenCodeAdapter` class.
**Rationale**: `OpenCodeClient` already handles correlation, timeout, retry, reconnection, and graceful degradation (RF-OPEN-02 through RF-OPEN-05). Adding a wrapper would duplicate this logic without adding value.

### Decision: Structured exceptions in `errors.py`

**Choice**: Define `OrchestratorError`, `IntentAnalysisError`, `SkillResolutionError`, `SkillExecutionPipelineError` as structured subclasses with `status_code` and `detail` fields.
**Alternatives considered**: Return error code integers or bare strings.
**Rationale**: Matches FastAPI's exception handling pattern, maps directly to HTTP status codes per RF-SKILL-07 (400/404/422/500), and preserves the structured envelope format required by RF-ORCH-04.

### Decision: Push-based TTS streaming

**Choice**: After execution completes, `asyncio.create_task(vc.send_text(session_id, text))` fires TTS asynchronously (push).
**Alternatives considered**: Pull-based TTS where the voice pipeline requests text from the orchestrator.
**Rationale**: Matches the existing stub's pattern in `orchestrator.py` and OrchestratorVoiceClient's `send_text()` API. Push is simpler and doesn't require the voice pipeline to poll.

## Data Flow

```
HTTP POST /v1/execute
  │
  ▼
IntentAnalyzer.classify(payload)
  │  rule-based keyword/capability matching
  ▼
SkillResolver.resolve(intent, registry)
  │  registry.find_by_capability() → keyword fallback
  ▼
OrchestratorPipeline._execute_skill(skill, input)
  │  SkillExecutor.execute() or OpenCodeClient.execute_skill()
  ▼
ResponseFormatter.format(result)
  │  envelope: {id, timestamp, type, payload{success, result|error}}
  ▼
[optional] OrchestratorVoiceClient.send_text(session_id, tts_text)
  │  fire-and-forget async task
  ▼
HTTP 200 JSONResponse
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `jarvis_os/orchestrator/__init__.py` | Create | Package marker |
| `jarvis_os/orchestrator/errors.py` | Create | `OrchestratorError`, `IntentAnalysisError`, `SkillResolutionError`, `SkillExecutionPipelineError` with `status_code`/`detail` |
| `jarvis_os/orchestrator/intent.py` | Create | `IntentAnalyzer` — rule-based keyword + capability classifier; `classify(text) → IntentResult` |
| `jarvis_os/orchestrator/resolver.py` | Create | `SkillResolver` — registry-first capability lookup with keyword fallback; `resolve(intent) → ResolvedSkill` |
| `jarvis_os/orchestrator/pipeline.py` | Create | `OrchestratorPipeline` — ties analyze → resolve → execute → format; integrates `SkillExecutor` and `OpenCodeClient`; `execute(payload) → Envelope` |
| `jarvis_os/orchestrator.py` | Modify | Replace `/v1/execute` stub body with `pipeline.execute(payload)` + TTS trigger |

No files deleted. `jarvis_os/api/routes/skills.py` and `jarvis_os/skills/executor.py` are **not modified**.

## Interfaces / Contracts

```python
# jarvis_os/orchestrator/errors.py
class OrchestratorError(Exception):
    status_code: int = 500
    detail: str = ""

class IntentAnalysisError(OrchestratorError):
    status_code: int = 400

class SkillResolutionError(OrchestratorError):
    status_code: int = 404

class SkillExecutionPipelineError(OrchestratorError):
    status_code: int = 422
```

```python
# jarvis_os/orchestrator/intent.py
class IntentResult:
    intent: str          # e.g. "obsidian.create", "code.execute", "unknown"
    confidence: float    # 0.0–1.0
    entities: dict[str, Any]

class IntentAnalyzer:
    def __init__(self, capability_map: dict[str, list[str]]) -> None: ...
    def classify(self, text: str) -> IntentResult: ...
```

```python
# jarvis_os/orchestrator/resolver.py
class ResolvedSkill:
    skill: SkillMetadata
    confidence: float
    source: str          # "capability" | "keyword" | "opencode"

class SkillResolver:
    def __init__(self, registry: SkillRegistry, loader: SkillLoader) -> None: ...
    def resolve(self, intent: str, text: str) -> ResolvedSkill | None: ...
```

```python
# jarvis_os/orchestrator/pipeline.py
class OrchestratorPipeline:
    def __init__(
        self,
        registry: SkillRegistry,
        loader: SkillLoader,
        executor: SkillExecutor,
        voice_client: OrchestratorVoiceClient | None = None,
        opencode_client: OpenCodeClient | None = None,
    ) -> None: ...
    async def execute(self, payload: dict[str, Any]) -> JSONResponse: ...
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `IntentAnalyzer.classify()` — keyword mapping, unknown intent, confidence thresholds | pytest + parametrize with sample utterances |
| Unit | `SkillResolver.resolve()` — capability hit, keyword fallback, empty result | mock `SkillRegistry.find_by_capability` |
| Unit | `OrchestratorPipeline.execute()` — happy path, skill not found, executor failure, OpenCode unavailable | mock `SkillExecutor` and `OpenCodeClient` |
| Unit | Error classes — `status_code` mapping, serialization | direct instantiation + attribute checks |
| Integration | `/v1/execute` end-to-end with real `SkillRegistry` + `SkillExecutor` against test `.skills/` directory | TestClient with temporary skills dir |
| Integration | `OpenCodeClient` integration — WS primary, HTTP fallback, timeout handling | use `aioresponses` or test WS server |
| E2E | Full voice flow: `/v1/execute` with `tts_text` + `session_id` → `OrchestratorVoiceClient.send_text` invoked | mock voice client, assert `send_text` called |

## Threat Matrix

| Boundary | Minimum adversarial cases | Applicability | Design response | Planned RED tests |
|---|---|---|---|---|
| Documentation-like paths | `requirements.txt`, `README.sh`, executable Markdown | N/A — pipeline does not execute files from disk paths; `SkillExecutor` handles allowlist | `SkillExecutor._check_command_allowed` enforces `allowed_commands` | Deferred to SkillExecutor tests (existing) |
| Git repository selection | `git -C`, relative/absolute paths | N/A — no Git operations in this change | — | — |
| Commit state | staged, `commit -a`, empty index | N/A — no Git operations | — | — |
| Push state | tracking branch, first push | N/A — no Git operations | — | — |
| PR commands | explicit `--head`, composed commands | N/A — no PR automation | — | — |
| **Routing (intent → skill)** | ambiguous input, capability collision, spoofed intent string | **Applicable** | `IntentAnalyzer` uses deterministic keyword rules; unknown intent returns `unknown` with confidence 0.0; resolver falls back to keyword search, never executes on ambiguous match | Test: adversarial input ("delete everything", "sudo rm -rf") returns `unknown` or safe skill; never reaches executor |
| **Shell commands (SkillExecutor)** | `bash`/`hybrid` execution with injected commands, path traversal | **Applicable** | `SkillExecutor.allowed_commands` allowlist + `_check_command_allowed`; timeout enforced via `asyncio.wait_for` | Test: skill with `entrypoint="rm -rf /"` raises `SkillExecutionError`; test: command not in allowlist is rejected |
| **Subprocesses (whisper-cli, piper, kokoro, OpenCode)** | resource exhaustion, unbounded output, zombie processes | **Applicable** | `SkillExecutor` enforces `timeout_seconds` via `asyncio.wait_for`; `OpenCodeClient` uses `heartbeat_timeout`; subprocess uses `PIPE` with bounded buffer | Test: skill exceeding timeout returns TIMEOUT status; test: OpenCode unreachable returns structured error within deadline |
| **Process integration (Docker dependency)** | OpenCode runtime not running, wrong port, partial startup | **Applicable** | `OpenCodeClient` has built-in reconnection + HTTP fallback; pipeline catches `ConnectionError_` and returns backend-unavailable error | Test: WS connection refused → HTTP fallback attempted; both fail → graceful error response |

## Migration / Rollout

No data migration required. Phased rollout:

1. **New modules**: Add `jarvis_os/orchestrator/{errors,intent,resolver,pipeline}.py` — no runtime effect on existing routes.
2. **Integrate `/v1/execute`**: Replace stub body in `jarvis_os/orchestrator.py` with `pipeline.execute(payload)`. Existing `/api/v1/skills/*` endpoints are untouched.
3. **Deprecate stub path**: Once `/v1/execute` is verified, remove the inline voice-client bootstrap duplication (keep `_get_voice_client` since it's shared).

Rollback: revert `jarvis_os/orchestrator.py` and delete `jarvis_os/orchestrator/` package. `/api/v1/skills/*` endpoints remain functional throughout.

## Open Questions

- [ ] **Intent threshold tuning**: What minimum confidence should trigger routing vs. returning `unknown`? RF-ORCH-01 specifies >= 0.8 for known intents but does not define the routing threshold — needs empirical calibration against real command corpus.
- [ ] **OpenCode session lifecycle**: Should the pipeline create a persistent `OpenCodeClient` per request, or reuse a singleton? The current `OpenCodeClient` design supports `async with` context management, but the pipeline may need concurrent request handling — requires load testing to determine if connection pooling is needed.
- [ ] **Skill composition input merge strategy**: RF-ORCH-03 specifies "each skill's output is merged into the next skill's input" but does not define merge semantics (deep merge, shallow merge, override, append). Needs a decision before implementing `Resolver`.

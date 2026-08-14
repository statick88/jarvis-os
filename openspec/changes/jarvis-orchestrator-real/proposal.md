# Proposal: jarvis-orchestrator-real

## Intent

The orchestrator stub returns hardcoded responses and never routes requests to real skills or the OpenCode runtime. This blocks end-to-end execution of text and voice commands, making JARVIS-OS non-functional for actual users.

## Scope

### In Scope
- Replace `/v1/execute` stub with real pipeline: intent analysis → skill resolution → execution → response
- Integrate `OpenCodeClient` as the code execution backend
- Add skill composition/chaining (sequential pipeline execution)
- Add structured error handling with proper HTTP status codes
- Add request/response logging and metrics
- Maintain backward compatibility with existing `/api/v1/skills/*` REST endpoints

### Out of Scope
- New UI/Flutter changes (keep existing HUD)
- New skills (use existing `.skills/*.md` and handlers)
- Changes to voice pipeline server (`voice_bridge/server.py`)
- Changes to Docker infrastructure

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities
- `orchestrator-pipeline`: intent analysis, skill routing, execution, response formatting
- `opencode-integration`: WebSocket/HTTP fallback to OpenCode runtime

### Modified Capabilities
- `skill-execution`: enhanced with composition, metrics, and better error handling

## Approach

Create `jarvis_os/orchestrator/pipeline.py` with `OrchestratorPipeline` and `jarvis_os/orchestrator/intent.py` with `IntentAnalyzer` (rule-based, no LLM dependency). Modify `/v1/execute` to use the real pipeline. Integrate `OpenCodeClient` from `jarvis_os/opencode_adapter/client.py`. Reuse existing `SkillExecutor` and `SkillRegistry` from `jarvis_os/skills/`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `jarvis_os/orchestrator.py` | Modified | `/v1/execute` uses real pipeline |
| `jarvis_os/orchestrator/pipeline.py` | New | `OrchestratorPipeline` class |
| `jarvis_os/orchestrator/intent.py` | New | `IntentAnalyzer` rule-based classifier |
| `jarvis_os/orchestrator/errors.py` | New | Structured error types |
| `jarvis_os/opencode_adapter/client.py` | Modified | Integrated into pipeline |
| `openspec/specs/skills/spec.md` | Modified | Delta spec for skill-execution changes |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| OpenCode runtime unavailable at `host.docker.internal:8081` | Med | HTTP fallback already in client; graceful degradation to local execution |
| Intent analyzer misroutes requests | Low | Keyword + rule-based; deterministic fallback to skill search |
| Skill composition order breaks existing single-skill calls | Low | Pipeline accepts single skill natively; composition is additive |
| Voice pipeline session pool conflicts with new pipeline | Low | Pipeline only uses existing `OrchestratorVoiceClient` API |
| Performance regression from pipeline overhead | Low | Metrics will expose latency; targeted caching after baseline |

## Rollback Plan

Revert `jarvis_os/orchestrator.py` to the previous commit and remove `jarvis_os/orchestrator/pipeline.py`, `intent.py`, `errors.py`. Existing `/api/v1/skills/*` endpoints are untouched, so they remain functional during rollback.

## Dependencies

- OpenCode runtime must be reachable at `host.docker.internal:8081` (already detected in logs)

## Success Criteria

- [ ] `/v1/execute` routes text/voice requests to real skills instead of returning stub
- [ ] `OpenCodeClient` is invoked for code execution requests
- [ ] `/api/v1/skills/*` endpoints remain functional and backward compatible
- [ ] Skill composition chains execute sequentially with proper error propagation
- [ ] Request latency p95 < 2s for skill execution

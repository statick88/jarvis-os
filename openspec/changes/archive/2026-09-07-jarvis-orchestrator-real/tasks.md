# Tasks: jarvis-orchestrator-real

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~400-500 (6 new files ~350 lines, modify 1 file ~50 lines, tests ~150 lines) |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR #1 (foundation) → PR #2 (pipeline) → PR #3 (integration) |
| Delivery strategy | ask-on-risk |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | New orchestrator package (errors, intent, resolver) | PR #1 | `pytest tests/orchestrator/test_intent.py tests/orchestrator/test_resolver.py -v` | pytest unit tests with mock registry | Remove `jarvis_os/orchestrator/` package |
| 2 | Pipeline core + SkillExecutor/OpenCode integration | PR #2 | `pytest tests/orchestrator/test_pipeline.py -v` | pytest unit tests with mock executor/client | Revert `jarvis_os/orchestrator.py` `/v1/execute` |
| 3 | `/v1/execute` integration + TTS trigger + E2E tests | PR #3 | `bash scripts/test_jarvis_pipeline.sh` | Full E2E against running stack | Revert `jarvis_os/orchestrator.py` |

## Phase 1: Foundation (New orchestrator package)

- [x] 1.1 Create `jarvis_os/orchestrator/__init__.py` package marker
- [x] 1.2 Create `jarvis_os/orchestrator/errors.py` with `OrchestratorError`, `IntentAnalysisError` (400), `SkillResolutionError` (404), `SkillExecutionPipelineError` (422)
- [x] 1.3 Create `jarvis_os/orchestrator/intent.py` with `IntentResult` dataclass and `IntentAnalyzer` class; implement `classify(text) → IntentResult` with rule-based keyword matching
- [x] 1.4 Create `jarvis_os/orchestrator/resolver.py` with `ResolvedSkill` dataclass and `SkillResolver` class; implement registry-first capability lookup with keyword fallback

## Phase 2: Pipeline Core

- [x] 2.1 Create `jarvis_os/orchestrator/pipeline.py` with `OrchestratorPipeline` class; implement 4-phase flow: analyze → resolve → execute → format
- [x] 2.2 Integrate `SkillExecutor` into pipeline for PYTHON/BASH/HYBRID execution
- [x] 2.3 Integrate `OpenCodeClient` for code execution requests with WS-primary + HTTP-fallback
- [x] 2.4 Implement skill composition/chaining (sequential execution with output merging)
- [x] 2.5 Implement response formatting into `{id, timestamp, type, payload}` envelope

## Phase 3: Integration

- [x] 3.1 Modify `jarvis_os/orchestrator.py` `/v1/execute` to use `OrchestratorPipeline.execute()` instead of stub
- [x] 3.2 Add TTS streaming trigger via `OrchestratorVoiceClient.send_text()` when `tts_text` + `session_id` present
- [x] 3.3 Ensure backward compatibility — `/api/v1/skills/*` endpoints remain untouched

## Phase 4: Testing

- [x] 4.1 Unit: `IntentAnalyzer.classify()` — keyword mapping, unknown intent, confidence thresholds (pytest + parametrize)
- [x] 4.2 Unit: `SkillResolver.resolve()` — capability hit, keyword fallback, empty result (mock registry)
- [x] 4.3 Unit: `OrchestratorPipeline.execute()` — happy path, skill not found, executor failure, OpenCode unavailable (mock executor + client)
- [x] 4.4 Unit: Error classes — `status_code` mapping, serialization
- [x] 4.5 Integration: `/v1/execute` end-to-end with real SkillRegistry + SkillExecutor against test `.skills/` directory (TestClient)
- [x] 4.6 Integration: OpenCode WS primary + HTTP fallback + timeout handling (test WS server or aioresponses)
- [x] 4.7 RED test: adversarial routing input ("delete everything") returns `unknown` or safe skill
- [x] 4.8 RED test: command not in allowlist is rejected by SkillExecutor
- [x] 4.9 RED test: skill exceeding timeout returns TIMEOUT status
- [x] 4.10 RED test: OpenCode unreachable returns structured error within deadline
- [x] 4.11 E2E: voice flow — `/v1/execute` with `tts_text` + `session_id` triggers `OrchestratorVoiceClient.send_text`

## Phase 5: Verification

- [x] 5.1 Run `pytest jarvis_os/orchestrator/ -v` and verify all tests pass
- [x] 5.2 Run existing `bash scripts/test_jarvis_pipeline.sh` to verify no regression
- [x] 5.3 Verify `/api/v1/skills/*` endpoints still functional

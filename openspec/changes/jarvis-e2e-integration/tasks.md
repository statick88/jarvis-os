# Tasks — Integración Total E2E (jarvis-e2e-integration)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~400-500 |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | 2 PRs: (1) backend events+vault, (2) HUD+Flutter+E2E tests |
| Delivery strategy | chained-pr |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|---------------------|-----------------|-------------------|
| 1 | Event system + vault output logger + indexer links | `pytest tests/ -k "vault or event"` | pytest with tmpdir | `jarvis_os/orchestrator_impl/events.py`, `jarvis_os/vault/output_logger.py`, `jarvis_os/vault/indexer.py` |
| 2 | HUD broadcast + Flutter consumer + E2E test | `pytest tests/e2e_voice_to_hud_test.py` | docker-compose up | `jarvis_os/hud/`, `jarvis_ui/`, `tests/` |

## Phase 1: Event System and Vault Output Logger

 - [x] 1.1 Create `jarvis_os/orchestrator_impl/events.py`: `SkillExecutionStart`, `SkillExecutionComplete`, `VaultWriteEvent` models with JSON serialization
 - [x] 1.2 Create `jarvis_os/vault/output_logger.py`: `VaultOutputLogger` class with `write_execution(skill_id, input_data, result) -> str` returning output_ref path
 - [x] 1.3 Create `tests/vault/test_output_logger.py`: Test Markdown generation, frontmatter validity, Karpathy link format
 - [x] 1.4 Modify `jarvis_os/vault/indexer.py`: Add incremental link update for new `outputs/` entries; link `outputs/<file>` → related `wiki/<note>` based on skill metadata tags
 - [x] 1.5 Create `tests/vault/test_indexer_links.py`: Test bidirectional link consistency after vault write
 - [x] 1.6 Modify `jarvis_os/orchestrator_impl/pipeline.py`: Emit `SkillExecutionStart` before skill run, `SkillExecutionComplete` after, `VaultWriteEvent` after vault write
 - [x] 1.7 Modify `jarvis_os/orchestrator.py`: Wire pipeline events to HUD WebSocket broadcast via `HudWebSocketServer.publish_status()`

## Phase 2: HUD Real-Time Events and Flutter Consumer

- [x] 2.1 Create `jarvis_ui/lib/services/event_stream_service.dart`: `HudEvent`, `SkillExecutionEvent`, `VaultUpdateEvent` models with JSON serialization; `EventStreamService` WS client with auto-reconnect
- [x] 2.2 Create `jarvis_ui/lib/providers/hud_event_providers.dart`: `HudState`, `HudEventNotifier`, Riverpod providers for connection state, current skill, vault updates
- [x] 2.3 Modify `jarvis_ui/lib/screens/home_screen.dart`: Add `_buildHudVoiceVitalSigns` widget (connection dot, skill status, mic indicator) and `_buildObsidianLiveMemoryLog` widget (vault path, noteId, linksAdded)
- [x] 2.4 Create `jarvis_ui/test/hud_widgets_test.dart`: Unit tests for HudEvent parsing, SkillExecutionEvent.fromPayload, VaultUpdateEvent.fromPayload; widget tests for HomeScreen HUD rendering
- [x] 2.5 Modify `jarvis_ui/lib/providers/jarvis_providers.dart`: Add `eventStreamServiceProvider` for dependency injection

## Phase 3: E2E Test and Verification

- [x] 3.1 Create `tests/e2e_voice_to_hud_test.py`: Full closed-loop test with mocked voice-pipeline WS, orchestrator, and vault
- [x] 3.2 Add `test_skill_execution_tracing` to E2E suite: Verify vault/outputs/ file created with correct frontmatter
- [x] 3.3 Add `test_hud_event_broadcast` to E2E suite: Verify HUD receives SKILL_EXECUTION_COMPLETE event
- [x] 3.4 Add `test_latency_under_500ms` to E2E suite: Mock timing, assert total pipeline < 500ms
- [x] 3.5 Add `test_fallback_text_only` to E2E suite: Voice-pipeline unavailable, text-only pipeline works
- [x] 3.6 Add `test_vault_write_failure_resilience` to E2E suite: Readonly vault, pipeline continues, warning in response
- [x] 3.7 Update `.progress`: Add FASE 11 section, mark RC1 entry
- [x] 3.8 Update `.agents`: Add E2E loop description, HUD event protocol, vault output conventions
- [x] 3.9 Run `bash scripts/test_jarvis_pipeline.sh && bash scripts/test_audio_streaming.sh --quick && python tests/e2e_voice_to_hud_test.py`; validate 0 FAIL, 0 SKIP

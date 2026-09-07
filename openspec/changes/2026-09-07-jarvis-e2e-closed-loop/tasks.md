# Tasks: E2E Closed-Loop Integration

## Task 1: Wire Vault Output Logger into Pipeline

**Requirement**: REQ-1 (Vault Output Persistence)
**Files**: `jarvis_os/orchestrator_impl/pipeline.py`, `jarvis_os/orchestrator.py`

### Steps
1. Add `vault_root: Path | None = None` parameter to `OrchestratorPipeline.__init__()`
2. Instantiate `VaultOutputLogger(vault_root=vault_root)` in constructor when `vault_root` is provided
3. Implement `_on_skill_complete()` hook to call `self._vault_logger.write_execution(skill_id, input_data, result)` when `status == COMPLETED`
4. In `orchestrator.py`, pass `vault_root=settings.vault.vault_root` when constructing pipeline
5. Add `try/except VaultWriteError` around vault write to prevent pipeline failure on write errors

### Acceptance Criteria
- [ ] Successful skill execution creates `vault/outputs/YYYY-MM-DD/<skill>-<HHMMSS>.md`
- [ ] Failed skill execution does NOT write vault output
- [ ] Vault write failure does NOT break pipeline execution

---

## Task 2: Add TTS Auto-Trigger to Pipeline

**Requirement**: REQ-5 (Voice Loop Closure)
**Files**: `jarvis_os/orchestrator_impl/pipeline.py`, `jarvis_os/orchestrator.py`

### Steps
1. Add `tts_callback: Callable[[str], Awaitable[None]] | None = None` parameter to `OrchestratorPipeline.__init__()`
2. In `_on_skill_complete()`, when `event.tts_text is not None`, call `asyncio.create_task(self._tts_callback(event.tts_text))` (fire-and-forget)
3. In `orchestrator.py`, create an async TTS wrapper that calls `voice_client.synthesize()` and pass as `tts_callback`
4. Handle `tts_callback is None` gracefully (skip TTS, log debug)

### Acceptance Criteria
- [ ] When `tts_text` is populated, TTS callback is invoked with the text
- [ ] When `tts_text` is None, no TTS call is made
- [ ] TTS call is fire-and-forget (does not block pipeline response)
- [ ] TTS failure is logged but does not break pipeline

---

## Task 3: Deprecate PluginRegistry

**Requirement**: REQ-6 (Unified Skill Execution Path)
**Files**: `jarvis_os/skills/plugin_registry.py`, `jarvis_os/skills/plugin_registry_instance.py`, `jarvis_os/orchestrator.py`

### Steps
1. Add `warnings.warn("PluginRegistry is deprecated, use SkillRegistry", DeprecationWarning, stacklevel=2)` to `PluginRegistry.__init__()` and `discover_and_load()`
2. Remove `from jarvis_os.skills.plugin_registry_instance import shared_registry` from `orchestrator.py` (if present)
3. Verify pipeline only uses `SkillRegistry` + `SkillExecutor` (no `PluginRegistry` calls in execution path)
4. Add comment in `plugin_registry.py` marking it for deletion in next cycle

### Acceptance Criteria
- [ ] `PluginRegistry` emits DeprecationWarning on construction
- [ ] `orchestrator.py` does not import or use `PluginRegistry`
- [ ] Pipeline resolves skills exclusively via `SkillRegistry`

---

## Task 4: Write Full-Loop E2E Test

**Requirement**: REQ-7 (End-to-End Pipeline Test)
**Files**: `tests/e2e_voice_to_hud_test.py`

### Steps
1. Add `TestFullClosedLoop` class to existing E2E test file
2. Mock `VoiceClient` (STT returns transcript, TTS records call)
3. Create `OrchestratorPipeline` with mock vault root and TTS callback
4. Create mock `HudWebSocketServer` that records broadcast calls
5. Execute pipeline with skill ID `skill.test` and input `{"text": "check health"}`
6. Assert: vault output file exists with correct frontmatter
7. Assert: HUD `publish_status` was called with `SkillExecutionComplete` payload
8. Assert: TTS callback was invoked with response text
9. Assert: all existing tests still pass (run full suite)

### Acceptance Criteria
- [ ] Single test exercises Voice → Skill → Vault → HUD → TTS loop
- [ ] Vault file assertion passes
- [ ] HUD broadcast assertion passes
- [ ] TTS invocation assertion passes
- [ ] Full pytest suite passes (157+ tests)

---

## Task 5: Verify Flutter Event Stream Integration

**Requirement**: REQ-4 (Flutter Real-Time Event Display)
**Files**: No changes — verification only

### Steps
1. Confirm `EventStreamService` connects to `ws://host:8083/voice`
2. Confirm `HudEvent` model parses `SkillExecutionComplete` JSON correctly
3. Confirm `hud_event_providers.dart` renders skill status from HUD events
4. Document Flutter event handling in design.md (already covered by REQ-4)

### Acceptance Criteria
- [ ] Flutter WebSocket client receives `SkillExecutionComplete` events
- [ ] `HudEventNotifier` updates state on skill completion
- [ ] No Flutter code changes needed (existing implementation sufficient)

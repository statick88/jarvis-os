# Research: E2E Closed-Loop Integration

## Current Architecture Map

### Components (all exist, none fully connected)

| Component | File | Status |
|-----------|------|--------|
| OrchestratorPipeline | `jarvis_os/orchestrator_impl/pipeline.py` | ✅ Working — emits events |
| Event Models | `jarvis_os/orchestrator_impl/events.py` | ✅ `SkillExecutionStart`, `SkillExecutionComplete`, `VaultWriteEvent`, `VoiceEvent` |
| HudWebSocketServer | `jarvis_os/hud/websocket_server.py` | ✅ Working — broadcasts `WSMessage` |
| Pipeline → HUD wiring | `jarvis_os/orchestrator.py:_wire_pipeline_to_hud()` | ✅ Connected |
| Flutter EventStreamService | `jarvis_ui/lib/services/event_stream_service.dart` | ✅ Connects to `ws://host:8083/voice` |
| Flutter HUD providers | `jarvis_ui/lib/providers/hud_event_providers.dart` | ✅ Consumes `HudEvent` stream |
| VaultOutputLogger | `jarvis_os/vault/output_logger.py` | ⚠️ Exists but **not wired** |
| IdleScheduler | `jarvis_os/core/scheduler.py` | ⚠️ Starts with **zero tasks** |
| SkillRegistry | `jarvis_os/skills/registry.py` | ⚠️ Metadata-only, pipeline uses this |
| PluginRegistry | `jarvis_os/skills/plugin_registry.py` | ⚠️ Live instances, **unused by pipeline** |
| SkillExecutor | `jarvis_os/skills/executor.py` | ✅ Executes via metadata |

### Connection Gaps (what blocks the closed loop)

1. **VaultOutputLogger ↔ Pipeline** — Pipeline emits `SkillExecutionComplete` with `output_ref` but nobody calls `VaultOutputLogger.write_execution()`. The vault never records what skills did.

2. **SkillRegistry ↔ PluginRegistry** — Two parallel systems. Pipeline uses `SkillRegistry` (metadata) + `SkillExecutor`. `PluginRegistry` (live `BaseSkill` instances with `execute()`) is registered in `lifespan` but never consulted. This means skills run through the executor's generic handler, not through their `BaseSkill.execute()` method.

3. **Voice loop** — After `OrchestratorPipeline.execute()` returns a response, the voice pipeline doesn't automatically TTS the result. Voice → STT works. STT → Orchestrator works. But Orchestrator → TTS is missing.

4. **IdleScheduler** — No tasks registered. Should run vault indexing, nightly reports during idle hours.

### What Needs to Change

```
Voice Command
  → STT (WebSocket /v1/audio/stream)          [EXISTS]
  → OrchestratorPipeline.execute()              [EXISTS]
    → Intent Analysis                           [EXISTS - rule-based]
    → Skill Resolution (SkillRegistry)          [EXISTS]
    → Skill Execution (SkillExecutor)           [EXISTS]
    → ★ VaultOutputLogger.write_execution()     [MISSING - add listener]
    → ★ HudWebSocketServer.broadcast()          [EXISTS - wired]
  → TTS (WebSocket /v1/audio/stream)           [EXISTS - not auto-triggered]
  → Audio Response                              [MISSING - voice loop closure]
```

### Key Code Paths

**Pipeline event emission** (pipeline.py):
```python
self._emit(SkillExecutionStart(skill_id=..., session_id=..., input_preview=...))
# ... execution ...
self._emit(SkillExecutionComplete(skill_id=..., session_id=..., status=..., duration_ms=..., output_ref=...))
```

**HUD wiring** (orchestrator.py):
```python
def _wire_pipeline_to_hud(pipeline, hud_server):
    pipeline.add_event_listener(lambda e: hud_server.publish_status(...))
```

**VaultOutputLogger** (output_logger.py):
```python
async def write_execution(self, skill_id, input_data, result) -> str:
    # writes to vault_root/outputs/YYYY-MM-DD/<skill_id>_<timestamp>.json
```

### Recommendation

Wire the three missing connections in order:
1. Add `VaultOutputLogger` as a pipeline event listener (subscribes to `SkillExecutionComplete`)
2. Verify voice loop closure (TTS auto-trigger after pipeline response)
3. Register IdleScheduler tasks for vault indexing

This is low-risk wiring work — no new algorithms, no new protocols. Just connecting existing interfaces.

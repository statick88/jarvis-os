# Design: Jarvis E2E Closed Loop

## Technical Approach

Wire the existing pipeline components into a complete Voice → STT → Orchestrator → Skill → Vault → TTS → Voice loop. The pipeline already emits `SkillExecutionStart`/`SkillExecutionComplete` events and the HUD server already broadcasts them. The missing links are: (1) calling `VaultOutputLogger.write_execution()` after skill completion, (2) auto-triggering TTS when `tts_text` is present in the completion event, (3) eliminating `PluginRegistry` in favor of `SkillRegistry`, and (4) verifying Flutter receives the full event stream.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Vault write trigger | Hook into `_on_skill_complete()` in pipeline | Call from executor, call from orchestrator | Pipeline already has the hook pattern and event data; cleanest single integration point |
| TTS auto-trigger | Read `tts_text` from `SkillExecutionComplete`, call voice client | Poll-based, callback registry | Field already exists in the event model (line 68, events.py); push-based avoids polling |
| Registry unification | Deprecate `PluginRegistry`, keep `SkillRegistry` + `SkillExecutor` | Merge both into one, keep both | `SkillRegistry` (metadata) + `SkillExecutor` (run) is the intended architecture; `PluginRegistry` duplicates with live instances |
| HUD event wiring | Already done in `_wire_pipeline_to_hud()` | — | No change needed; just verify end-to-end |

## Data Flow

```
Voice Input (WS)
    │
    ▼
VoiceClient ──STT──▶ OrchestratorPipeline
                         │
                    ┌────┴────┐
                    │ Phase 1 │ SkillExecutionStart event ──▶ HUD broadcast
                    │ Phase 2 │ SkillExecutor.execute()
                    │ Phase 3 │ SkillExecutionComplete event
                    │         ├─▶ HUD broadcast
                    │         ├─▶ VaultOutputLogger.write_execution()  ← NEW
                    │         └─▶ VoiceClient.synthesize(tts_text)     ← NEW
                    │ Phase 4 │ (cleanup)
                    └─────────┘
                         │
                    VaultOutputLogger
                         │
                    vault/outputs/YYYY-MM-DD/<skill>-<HHMMSS>.md
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `jarvis_os/orchestrator_impl/pipeline.py` | Modify | Implement `_on_skill_complete()`: call vault logger + TTS |
| `jarvis_os/orchestrator.py` | Modify | Pass `VoiceClient` ref to pipeline, pass `vault_root` for logger |
| `jarvis_os/skills/plugin_registry.py` | Deprecate | Add deprecation warning; remove imports from orchestrator |
| `jarvis_os/skills/plugin_registry_instance.py` | Deprecate | Mark `shared_registry` as deprecated |
| `tests/e2e_voice_to_hud_test.py` | Modify | Add full loop test: skill → vault → HUD → TTS assertion |
| `tests/pipeline_vault_integration_test.py` | Create | Unit test for `_on_skill_complete` vault write + TTS trigger |

## Interfaces / Contracts

```python
# pipeline.py — new signature for _on_skill_complete
async def _on_skill_complete(self, event: SkillExecutionComplete) -> None:
    """Post-execution hook: vault write + TTS auto-trigger."""

# pipeline.py — constructor additions
class OrchestratorPipeline:
    def __init__(
        self,
        ...
        vault_root: Path | None = None,      # NEW: for VaultOutputLogger
        tts_callback: Callable | None = None, # NEW: async fn(text) -> None
    ) -> None:
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `_on_skill_complete` calls vault logger | Mock `VaultOutputLogger`, assert `write_execution` called with correct args |
| Unit | `_on_skill_complete` calls TTS when `tts_text` present | Mock TTS callback, assert invoked with text |
| Unit | `_on_skill_complete` skips TTS when `tts_text` is None | Mock TTS callback, assert NOT invoked |
| Integration | Vault file created after skill execution | Real `VaultOutputLogger` + temp dir, assert file exists with correct frontmatter |
| E2E | Full loop: skill → vault → HUD event → TTS | Mock voice input, assert vault file + HUD broadcast + TTS call |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No data migration required. Deprecation of `PluginRegistry`:
1. Add `warnings.warn()` to `PluginRegistry.__init__()` and `discover_and_load()`
2. Remove `shared_registry` usage from orchestrator.py (replace with `SkillRegistry` path)
3. Delete `plugin_registry.py` and `plugin_registry_instance.py` in a follow-up change

## Open Questions

- [ ] Should TTS auto-trigger be async-fire-and-forget or await before returning from `_on_skill_complete`? (Proposed: fire-and-forget to avoid blocking pipeline)
- [ ] Voice client reference: pass as constructor arg or import singleton? (Proposed: constructor arg for testability)

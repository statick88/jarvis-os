# Proposal: E2E Closed-Loop Integration (FASE 11)

## Intent

Wire the complete pipeline: **Voice → STT → Orchestrator → Skill → Vault → TTS → Voice** as a closed loop. The individual components exist (audio streaming, orchestrator pipeline, skills, vault, Flutter HUD) but are not connected end-to-end.

## Problem Statement

After 9 SDD cycles, JARVIS OS has:
- WebSocket audio streaming (STT/TTS)
- OrchestratorPipeline with intent → skill → execution → response
- 5 skills (Obsidian, OS Control, DevSecOps, Docker, Nightly Labs)
- Vault persistence layer
- Flutter HUD with EventStreamService

However, **no single flow connects all these pieces**. A voice command goes through STT, hits the orchestrator, executes a skill — but the result never reaches the vault, the HUD never broadcasts it, and the TTS never speaks the response back.

## Scope

### In Scope
1. **VaultOutputLogger integration** — Skill executions write structured outputs to `vault/outputs/YYYY-MM-DD/`
2. **Domain event bus** — Orchestrator emits events (skill_started, skill_completed, skill_failed, vault_updated)
3. **HUD WebSocket broadcast** — OrchestratorPipeline pushes domain events to `HudWebSocketServer`
4. **Flutter EventStreamService consumption** — Flutter HUD receives and displays real-time skill execution events
5. **Voice loop closure** — TTS speaks the orchestrator's response after skill execution
6. **E2E test** — Single test that exercises the full Voice → Response loop

### Out of Scope
- Authentication/authorization on skill endpoints (future cycle)
- LLM-based intent analysis (rule-based is sufficient for now)
- Metrics/observability pipeline (future cycle)
- OpenCode daemon full integration (fallback-only for now)

## Approach

1. Define a `DomainEvent` dataclass for the event bus
2. Add event emission to `OrchestratorPipeline.execute()` at key lifecycle points
3. Wire `OrchestratorPipeline` → `HudWebSocketServer` via event subscription
4. Create `VaultOutputLogger` that subscribes to `skill_completed` events
5. Update Flutter `EventStreamService` to handle skill execution events
6. Add voice loop: after orchestrator response, feed text to TTS endpoint
7. Write E2E test covering the full loop

## Success Criteria

- A voice command ("check system health") flows through the entire pipeline and produces:
  - A vault output file at `vault/outputs/YYYY-MM-DD/`
  - A HUD event displayed in Flutter
  - A TTS audio response
- E2E test passes covering the full loop
- All existing tests (157 pytest + 5 Flutter) remain green

## Risk Assessment

- **Low risk**: Wiring existing components, no new algorithms
- **Medium risk**: Event bus ordering — need to ensure events are processed in order
- **Mitigation**: Sequential event processing, no async races in the critical path

## Estimated Size

- ~400-600 changed lines across backend + Flutter
- 1 new file (event bus), 3-4 modified files, 1 new E2E test
- Fits within single-PR review budget

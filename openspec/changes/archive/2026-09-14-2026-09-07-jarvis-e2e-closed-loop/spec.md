# Spec: E2E Closed-Loop Integration

## Overview

This change wires the complete Voice → STT → Orchestrator → Skill → Vault → TTS → Voice pipeline into a closed loop. Individual components exist (audio streaming, orchestrator pipeline, skills, vault, Flutter HUD) but are not connected end-to-end. Four gaps block the loop: VaultOutputLogger is unwired, dual skill registries create confusion, TTS is not auto-triggered after orchestrator response, and the E2E test does not cover the full cycle. This spec defines requirements to close all gaps and validate with a single end-to-end test.

## Requirements

### REQ-1: Vault Output Persistence

The system MUST write structured skill execution outputs to the vault whenever a skill completes, using the existing `VaultOutputLogger.write_execution()` method.

#### Scenario: Successful skill execution creates vault output file

- GIVEN a skill executes successfully via `OrchestratorPipeline.execute()`
- WHEN `SkillExecutionComplete` event fires with `status=completed`
- THEN `VaultOutputLogger.write_execution()` is called with `skill_id`, input data, and result
- AND a JSON file exists at `vault/outputs/YYYY-MM-DD/<skill_id>_<timestamp>.json`

#### Scenario: Failed skill execution does not write vault output

- GIVEN a skill execution fails with `status=failed`
- WHEN `SkillExecutionComplete` event fires with an error message
- THEN `VaultOutputLogger.write_execution()` is NOT called
- AND no vault output file is created for that execution

### REQ-2: Domain Event Emission

The `OrchestratorPipeline` MUST emit `SkillExecutionStart` and `SkillExecutionComplete` events at lifecycle boundaries, with `tts_text` populated from the skill response when applicable.

#### Scenario: Pipeline emits SkillExecutionStart before execution

- GIVEN a user request reaches `OrchestratorPipeline.execute()`
- WHEN the pipeline begins skill resolution
- THEN a `SkillExecutionStart` event is emitted with `skill_id`, `session_id`, and `input_preview`

#### Scenario: Pipeline emits SkillExecutionComplete with tts_text

- GIVEN a skill finishes execution successfully
- WHEN the pipeline constructs the response envelope
- THEN a `SkillExecutionComplete` event is emitted with `status=completed`, `duration_ms`, `output_ref`, and `tts_text` containing the human-readable response

### REQ-3: HUD Event Broadcasting

The pipeline MUST forward all domain events to `HudWebSocketServer` so connected clients receive real-time execution state.

#### Scenario: HUD server receives skill execution events

- GIVEN `OrchestratorPipeline` is wired to `HudWebSocketServer` via `_wire_pipeline_to_hud()`
- WHEN a `SkillExecutionComplete` event is emitted
- THEN `HudWebSocketServer.publish_status()` is called with the event payload
- AND the WebSocket message is broadcast to all connected clients

#### Scenario: Multiple concurrent executions broadcast independently

- GIVEN two skills execute concurrently in separate sessions
- WHEN both emit `SkillExecutionComplete` events
- THEN each event is broadcast as a separate WebSocket message with its own `session_id`

### REQ-4: Flutter Real-Time Event Display

Flutter `EventStreamService` MUST receive and parse `SkillExecutionComplete` events from the WebSocket stream and expose them to HUD providers.

#### Scenario: Flutter receives skill completion event

- GIVEN `EventStreamService` is connected to `ws://host:8083/voice`
- WHEN a `SkillExecutionComplete` JSON message arrives on the WebSocket
- THEN the service parses it into a `HudEvent` and adds it to the event stream
- AND `hud_event_providers` renders the skill name and status in the HUD

### REQ-5: Voice Loop Closure

After `OrchestratorPipeline.execute()` returns a response, the voice pipeline MUST automatically invoke TTS synthesis using the `tts_text` from the `SkillExecutionComplete` event.

#### Scenario: TTS auto-triggered after successful skill execution

- GIVEN a voice command flows through STT → Orchestrator → Skill
- WHEN `OrchestratorPipeline.execute()` completes with `tts_text` populated
- THEN the voice pipeline sends `tts_text` to the TTS WebSocket endpoint
- AND synthesized audio is returned to the client

#### Scenario: TTS skipped when tts_text is None

- GIVEN a skill execution completes with `tts_text=None`
- WHEN the pipeline response is processed by the voice loop
- THEN no TTS request is made
- AND the client receives no audio response (text-only)

### REQ-6: Unified Skill Execution Path

The pipeline MUST use a single canonical execution path through `SkillExecutor`, eliminating the unused `PluginRegistry` dual system.

#### Scenario: Pipeline resolves skill via SkillRegistry only

- GIVEN a request arrives at `OrchestratorPipeline.execute()`
- WHEN skill resolution occurs
- THEN `SkillRegistry` is queried for metadata matching
- AND `SkillExecutor` performs the execution
- AND `PluginRegistry` is not consulted

### REQ-7: End-to-End Pipeline Test

The system MUST include a single E2E test that exercises the full Voice → Response loop, validating vault output, HUD event, and TTS response in one flow.

#### Scenario: E2E test covers full closed loop

- GIVEN the E2E test sends a voice command ("check system health")
- WHEN the command flows through STT → Orchestrator → Skill → Vault → TTS
- THEN the test asserts a vault output file exists
- AND the test asserts a HUD WebSocket event was broadcast
- AND the test asserts TTS audio was returned
- AND all 157 pytest + 5 Flutter tests remain green

## Non-Functional Requirements

- **Ordering**: Events MUST be processed sequentially within a session to prevent race conditions between `SkillExecutionStart` and `SkillExecutionComplete`.
- **Backward Compatibility**: All existing `/api/v1/skills/*` endpoints MUST remain fully functional unchanged.
- **Latency**: The vault write and HUD broadcast MUST NOT block the pipeline response; they SHOULD execute as fire-and-forget listeners.

## Out of Scope

- Authentication/authorization on skill endpoints (future cycle)
- LLM-based intent analysis (rule-based is sufficient for now)
- Metrics/observability pipeline (future cycle)
- OpenCode daemon full integration (fallback-only for now)

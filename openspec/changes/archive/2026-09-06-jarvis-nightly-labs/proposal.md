# Proposal: Nightly Labs & Idle Worker - JARVIS OS

**ID**: `jarvis-nightly-labs`
**Date**: 2026-09-06
**Status**: Research complete — ready for implementation
**Estimated scope**: ~300-400 lines changed (single PR)

---

## 1. Problem

JARVIS OS stays idle during off-hours (00:00–06:00) without leveraging
available CPU/RAM for low-priority autonomous operations. Specifically:

1. **Idle resources**: No scheduled mechanism for maintenance, auditing,
   or experimentation during nightly hours.
2. **No automatic auditing**: No regular process to assess code quality,
   verify security, or produce stability reports.
3. **Vault untapped**: Obsidian notes tagged `#idea`, `#todo`, `#research`
   are not automatically processed to extract value during idle periods.

## 2. Solution

FASE 10 (`jarvis-nightly-labs`) adds three integrated components:

### 2.1 Idle Scheduler (`jarvis_os/core/scheduler.py`)

- **Pattern**: `asyncio.create_task()` periodic loop following the HUD TUI
  render loop (`jarvis_os/hud/tui.py:94-102`) and WebSocket serve loop
  (`jarvis_os/hud/websocket_server.py:85`).
- **Lifecycle**: `start()` / `stop()` matching `HudWebSocketServer` pattern.
- **Scope**: Active window 00:00–06:00 with ±15min precision.
- **Throttling**: CPU max 15%, RAM max 256MB, enforced per-task.
- **Session safety**: Defers execution during active user sessions.
- **Control**: REST toggle `POST /v1/nightly/scheduler/toggle` following
  the FastAPI JSONResponse pattern (`orchestrator.py:207-289`).

### 2.2 Nightly Worker Skill (`jarvis_os/skills/nightly_labs.py`)

- **Pattern**: Subclass `BaseSkill` ABC (`jarvis_os/skills/base.py`)
  following the Obsidian plugin pattern (`jarvis_os/skills/obsidian/plugin.py`).
- **Pipeline**: `scan_vault()` → `extract_notes()` → `process_with_llm()`
  → `generate_report()`. Each stage has independent timeout and error handling.
- **Vault connector**: `VaultSearch.search(tags=["idea","todo","research"])`
  (`jarvis_os/vault/search.py:49-119`) for tag-based note discovery.
  `VaultStatsComputer` (`jarvis_os/vault/stats.py:98`) for aggregate metrics.
- **LLM engine**: Ollama primary (HTTP API, no binary deps), llama.cpp
  fallback. New `LLMSettings` in config.py following `VoicePipelineSettings`
  pattern (`config.py:19-53`). Graceful degradation: no LLM → task marked
  `skipped`.
- **Registration**: `await plugin_registry.register(NightlyLabsSkill())`
  in orchestrator lifespan (`orchestrator.py:138-140`).
- **REST exposure**: `POST /api/v1/skills/skill-nightly-labs/execute`
  (automatic via skills router).

### 2.3 Morning Briefing Widget (`jarvis_ui`)

- **Pattern**: Riverpod `ConsumerWidget` following `HomeScreen` structure
  (`jarvis_ui/lib/screens/home_screen.dart`).
- **State**: `NightlyState` + `NightlyNotifier` in `nightly_provider.dart`
  following `HudEventNotifier` pattern (`hud_event_providers.dart`).
- **Content**: Last nightly execution status, ideas/tasks processed count,
  direct link to daily report in vault.
- **Integration**: Added to HomeScreen header via `_build*` method pattern.

## 3. Scope

### Includes

| Component | File | Action |
|-----------|------|--------|
| Idle scheduler | `jarvis_os/core/scheduler.py` | Create |
| Scheduler config | `jarvis_os/config.py` | Edit (add `NightlySchedulerSettings`) |
| REST endpoints | `jarvis_os/orchestrator.py` | Edit (add `/v1/nightly/*`) |
| Nightly skill | `jarvis_os/skills/nightly_labs.py` | Create |
| LLM settings | `jarvis_os/config.py` | Edit (add `LLMSettings`) |
| Vault tag scan | `jarvis_os/vault/indexer.py` | Edit (add nightly tag filter) |
| Report format | `_Nightly_Reports/YYYY-MM-DD.md` | Convention |
| Flutter provider | `jarvis_ui/lib/providers/nightly_provider.dart` | Create |
| Morning Briefing | `jarvis_ui/lib/widgets/nightly_briefing.dart` | Create |
| HomeScreen integration | `jarvis_ui/lib/screens/home_screen.dart` | Edit |
| Tests | `tests/core/test_scheduler.py`, `tests/skills/test_nightly_labs.py`, `tests/widgets/nightly_briefing_test.dart` | Create |
| Progress tracking | `.progress`, `.agents` | Edit |

### Excludes

- Protocol specification changes (WebSocket/REST contracts unchanged)
- New unrelated skills
- Docker infrastructure modifications
- External API integrations (offline-first only)

## 4. Architecture (Research-Backed)

All decisions below are validated against the codebase with evidence
in `research.md`.

### 4.1 Scheduler

```
Decision: asyncio.create_task() periodic loop
Evidence:  jarvis_os/hud/tui.py:94-102, hud/websocket_server.py:85
Rejected:  Separate cron (process isolation), system crontab (no context sharing),
           supervisor (external dependency)
```

The scheduler shares process context with JARVIS OS, enabling direct access
to vault and skill infrastructure. Start/stop lifecycle matches existing
background task patterns.

### 4.2 LLM Engine

```
Decision: Ollama primary, llama.cpp fallback, LLMSettings in config
Evidence:  No existing LLM code; config.py VoicePipelineSettings pattern
Rejected:  Remote API fallback (offline-first requirement),
           Single engine (no graceful degradation)
```

Config prefix `LLM_` with pydantic-settings following `VoicePipelineSettings`.
Detection order: Ollama HTTP → llama.cpp binary → skip. Zero external deps
when no LLM available.

### 4.3 Vault Tag Query

```
Decision: VaultSearch.search(tags=["idea","todo","research"])
Evidence:  jarvis_os/vault/search.py:49-119, models.py IndexEntry.tags
Rejected:  Full-text only search (no tag filtering),
           Custom indexer (reinvents existing search)
```

`VaultStatsComputer` (`stats.py:98`) provides `notes_by_tag` aggregation
directly usable for nightly scan metrics.

### 4.4 Skill Pattern

```
Decision: BaseSkill ABC plugin, register in orchestrator lifespan
Evidence:  jarvis_os/skills/obsidian/plugin.py, orchestrator.py:138-140
Rejected:  Standalone script (no plugin lifecycle),
           Separate process (no context sharing)
```

Automatic REST exposure via skills router. Operations dispatch on
`operation` string, each returns `{"status": "success"|"error", "result": {...}}`.

### 4.5 Flutter Widget

```
Decision: Riverpod ConsumerWidget, NightlyState + NightlyNotifier
Evidence:  jarvis_ui/lib/providers/hud_event_providers.dart, home_screen.dart
Rejected:  Provider (older, less expressive), Bloc (too heavy for HUD)
```

Consistent with existing HUD event providers. `_build*` method pattern
in HomeScreen for widget composition.

### 4.6 REST Endpoint

```
Decision: @app.post("/v1/nightly/scheduler/toggle"), JSONResponse
Evidence:  jarvis_os/orchestrator.py:207-289
Rejected:  Separate router (inconsistent), GraphQL (no existing infra)
```

Follows existing endpoint pattern: `@app.post()` on `app`, returns
`JSONResponse` with consistent payload shape.

## 5. Alternatives Evaluated

| Alternative | Pros | Cons | Verdict |
|-------------|------|------|---------|
| System cron | Native scheduling | No process context, separate management | Rejected |
| Separate process | Isolation | No shared vault/skill access, complex IPC | Rejected |
| One-shot execution | Simpler | No recurring automation, manual trigger needed | Rejected |
| Polling-based detection | Reactive | Wastes CPU, misses schedule window | Rejected |
| Remote LLM API | More capable | Requires internet, violates offline-first | Rejected |
| Single LLM engine | Simpler | No fallback, blocks on missing binary | Rejected |
| Provider (Flutter) | Simpler | Less expressive than Riverpod | Rejected |
| Separate Flutter screen | More space | Violates single-screen philosophy | Rejected |

## 6. Impact & Dependencies

### Dependencies (all satisfied)

| Dependency | Status | Evidence |
|------------|--------|----------|
| asyncio background tasks | Available | HUD TUI, WebSocket, voice bridge patterns |
| VaultSearch.search(tags=) | Available | vault/search.py:49-119 |
| BaseSkill ABC | Available | skills/base.py |
| Plugin registry | Available | orchestrator.py:138-140 |
| Riverpod providers | Available | hud_event_providers.dart |
| FastAPI endpoints | Available | orchestrator.py:207-289 |

### Impact

- **No breaking changes** to existing protocols or infrastructure
- **Additive only**: new files + edits to existing for integration
- **Config overhead**: 2 new settings classes (`NightlySchedulerSettings`, `LLMSettings`)
- **Runtime overhead**: ~5-15% CPU during nightly window, <256MB RAM

### Risks

| Risk | Mitigation |
|------|------------|
| CPU/RAM throttling too aggressive | Configurable thresholds, monitoring via resource_metrics |
| LLM unavailable | Graceful skip, task marked `skipped`, no blocking |
| Vault corruption | Read-only scans, backup before write, strict frontmatter validation |
| Session interference | Active session detection, automatic deferral |

## 7. Success Criteria

- [ ] Scheduler executes tasks in 00:00–06:00 window with ±15min precision
- [ ] Vault connector extracts and processes notes `#idea`, `#todo`, `#research`
- [ ] Reports generated at `_Nightly_Reports/YYYY-MM-DD.md` with valid frontmatter
- [ ] Morning Briefing widget displays nightly summary in HomeScreen
- [ ] CPU/RAM throttling respects configured limits (max 15% CPU, 256MB RAM)
- [ ] LLM engine works offline without external API
- [ ] All tests pass: `pytest tests/ -k "nightly or scheduler"`, `flutter test`

## 8. Open Questions

- [ ] Should the scheduler use local host time or be timezone-configurable?
- [ ] Should the LLM engine fallback order be user-configurable?
- [ ] Should Morning Briefing be enabled by default or opt-in?
- [ ] What retention period for `_Nightly_Reports/` before automatic cleanup?

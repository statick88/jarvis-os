## Verification Report — jarvis-nightly-labs

**Date**: 2026-09-06
**Verifier**: sdd-verify
**Mode**: full (specs + design + tasks)

---

### Completeness

| Artifact | Status | Notes |
|----------|--------|-------|
| specs | ✅ Present | 6 functional requirements (RF-NIGHT-01–06), 4 non-functional (RNF-NIGHT-01–04) |
| design | ✅ Present | 5 architecture decisions, data flow, file changes table, threat matrix |
| tasks | ✅ Present | 20 tasks across 4 phases; 19/20 completed; 1 blocked (4.5 — Docker) |
| proposal | ⏭ Skipped | Not present per structured status |

---

### Test Evidence

**Python test suite** — `pytest tests/ -k "nightly or scheduler" -v --tb=short`:

```
96 passed, 69 deselected in 2.43s
```

Breakdown by module:
- `tests/core/test_scheduler.py` — IdleScheduler, throttling, task execution, resource snapshots
- `tests/skills/test_nightly_labs.py` — Init, load, detect LLM, execute, scan vault, extract notes, process with LLM, generate report, helpers, constants
- `tests/vault/test_nightly_indexer.py` — search_by_tags, deleted entries, structure validation, link consistency after nightly scan

**Flutter test suite** — `flutter test test/widgets/nightly_briefing_test.dart`:

```
00:00 +5: All tests passed!
```

Tests: renders nothing (no data), renders header, active status pill, inactive status, error message.

---

### Spec Compliance Matrix

| Requirement | Status | Evidence |
|-------------|--------|----------|
| **RF-NIGHT-01** Idle Scheduler | ✅ PASS | `jarvis_os/core/scheduler.py` — `IdleScheduler` class (line 55) with `start()`, `stop()`, `add_task()`, `get_status()`. Active hours 00:00–06:00, resource throttling, session-aware deferral. 15+ scheduler tests pass. |
| **RF-NIGHT-02** Obsidian Vault Nightly Connector | ✅ PASS | `jarvis_os/vault/indexer.py` — `search_by_tags()` (line 146) supports `#idea`, `#todo`, `#research`. `jarvis_os/skills/nightly_labs.py` — `NightlyLabsSkill.scan_vault()` uses vault search. 10+ vault indexer tests pass. |
| **RF-NIGHT-03** LLM Prompt Engine (Local) | ✅ PASS | `jarvis_os/skills/nightly_labs.py` — `detect_llm_engine()` checks llama.cpp, Ollama, local GGUF. `run_llm_prompt()` routes to detected engine. 30s timeout, graceful skip on unavailability. 8+ LLM tests pass. |
| **RF-NIGHT-04** Automatic Nightly Report | ✅ PASS | `_Nightly_Reports/2026-09-06.md` — valid frontmatter with date, tasks_executed, ideas_extracted, resource_metrics. Markdown body with sections for ideas, tasks, vault stats, system health. `generate_report()` tests pass. |
| **RF-NIGHT-05** REST Scheduler Control | ⚠️ PARTIAL | **Implemented**: `POST /v1/nightly/scheduler/toggle` (line 311), `GET /v1/nightly/scheduler/status` (line 349). **Missing**: `GET /v1/nightly/reports` and `GET /v1/nightly/reports/{date}`. Response shape uses `"status": "ok"` (not `"success"/"error"` per spec). |
| **RF-NIGHT-06** Morning Briefing Widget | ✅ PASS | `jarvis_ui/lib/widgets/nightly_briefing.dart` — `MorningBriefing` ConsumerWidget. `nightly_provider.dart` — `NightlyState` + `NightlyNotifier` via Riverpod. Integrated in `home_screen.dart` (line 208). 5/5 Flutter tests pass. |
| **RNF-NIGHT-01** Resource Throttling | ✅ PASS | `IdleScheduler` enforces `max_cpu_percent` and `max_ram_mb`. Tests verify high CPU/RAM skip ticks. |
| **RNF-NIGHT-02** Offline-First | ✅ PASS | LLM detection: llama.cpp → Ollama → local GGUF → skip. No external API calls in pipeline. |
| **RNF-NIGHT-03** User Session Protection | ✅ PASS | `_session_active` flag in scheduler; tasks deferred when session active. Tested. |
| **RNF-NIGHT-04** Idempotency | ✅ PASS | `scan_vault()` deduplicates notes (tested). Report overwrites by date path (natural idempotency). |

---

### Issues

| Severity | ID | Description |
|----------|----|-------------|
| **CRITICAL** | V-01 | **RF-NIGHT-05 missing endpoints**: `GET /v1/nightly/reports` and `GET /v1/nightly/reports/{date}` are not implemented in `orchestrator.py`. The spec requires 4 REST endpoints; only 2 exist (toggle + status). These report-listing endpoints are needed for the Morning Briefing to fetch report links and for API consumers to browse generated reports. |
| **WARNING** | V-02 | **Response shape mismatch**: Spec requires `{"status": "success"|"error", "result": {...}}`. Implementation uses `{"status": "ok", "scheduler": {...}}`. The toggle/status endpoints return `"ok"` instead of `"success"` and use a flat shape instead of nested `result`. |
| **WARNING** | V-03 | **Task 4.5 blocked**: E2E pipeline test (`bash scripts/test_jarvis_pipeline.sh`) cannot run due to Docker daemon (Colima) not being active. This is an infrastructure dependency, not an implementation gap. |
| **SUGGESTION** | V-04 | **Report frontmatter fields**: The sample report uses `status`, `scheduler_active`, `vault_scan` (non-standard). The design spec defines `tasks_executed` as a list of objects with `{id, status, duration_ms, prompt}` but the sample uses `tasks_executed: 2` (integer). Consider aligning the report generator output with the design's frontmatter contract. |

---

### Verdict

**FAIL** — CRITICAL issue V-01: two required REST endpoints from RF-NIGHT-05 are missing (`GET /v1/nightly/reports` and `GET /v1/nightly/reports/{date}`).

**Resolution path**: Implement the two missing report-listing endpoints in `orchestrator.py` and re-verify. The response shape (V-02) should also be aligned with the spec contract. Task 4.5 (V-03) can be deferred pending Docker availability.

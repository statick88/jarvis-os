# Design: Nightly Labs & Idle Worker

## Technical Approach

Extension of the JARVIS OS architecture to add autonomous nightly execution
capability. The design builds on existing components: scheduler, Obsidian
vault connector, local LLM engine, and Flutter frontend. No breaking changes
to existing protocols or infrastructures.

## Architecture Decisions

### Decision: Idle Scheduler Architecture
**Choice**: Modular scheduler in `jarvis_os/core/scheduler.py` using
asyncio with configurable crontab-like intervals. The scheduler runs as a
background daemon thread with start/stop control via REST endpoint
`POST /v1/nightly/scheduler/toggle`.

**Alternatives considered**: Separate cron job; system-level crontab;
separate process managed by supervisor.
**Rationale**: Integrated scheduler shares process context with JARVIS OS,
can access vault and skill infrastructure directly. No external dependency.

### Decision: Nightly Worker Skill Pipeline
**Choice**: New skill `skill-nightly-labs` following the `BaseSkill` ABC
pattern. Pipeline: `scan_vault()` → `extract_notes()` → `process_with_llm()`
→ `generate_report()`. Each stage is a separate operation with its own
timeout and error handling.

**Alternatives considered**: One-shot execution; polling-based detection.
**Rationale**: Modular pipeline enables independent testing, easy extension
with new note types, and clear error isolation.

### Decision: LLM Local Engine Integration
**Choice**: Motor de prompts que detecta y usa los motores LLM locales
disponibles en este orden de preferencia: `llama.cpp` (binario `llama-cli`),
`Ollama` (API local `/api/chat`), `Local Engines` (directorios de modelos
`.gguf`). Si ninguno está disponible, la ejecución se marca `skipped`.

**Alternatives considered**: Fallback a API remota; bloqueo total si sin LLM.
**Rationale**: Garantiza funcionamiento offline-first; el usuario tiene
control sobre qué modelo usar; degrade graceful evita bloqueos completos.

### Decision: Nightly Report Format & Path
**Choice**: Reportes en Markdown bajo `_Nightly_Reports/YYYY-MM-DD.md`
dentro del vault Obsidian. Frontmatter estandarizado con campos:
`date`, `tasks_executed`, `ideas_extracted`, `tasks_pending`,
`research_findings`, `resource_metrics`. Cuerpo del reporte con secciones
organizadas por tipo de nota.

**Alternatives considered**: JSON reports; separate reporting directory;
embedding in existing notes.
**Rationale**: Markdown keeps reports human-searchable and vault-compatible.
Daily path convention matches existing vault organization.

### Decision: Flutter Morning Briefing Widget
**Choice**: Widget integrado en `HomeScreen` de `jarvis_ui`, desplegable
desde el header. Muestra: estado de última ejecución nightly, contador de
ideas/tareas procesadas, y enlace directo al reporte del día en el vault.

**Alternatives considered**: Pantalla separada; notificación push;
overlay independiente.
**Rationale**: Integración "cero pestañas" consistente con la filosofía
de una sola pantalla del HUD. El widget es opcional y puede desactivarse.

## Data Flow

```text
┌──────────────────────────────────────────────────────────────┐
│                Nightly Labs Execution Flow                   │
├───────────────────────┬───────────────────────┬─────────────┤
│  00:00 Scheduler Start │                       │             │
│  ▼                     │                       │             │
│  scan_vault()         │   extract_notes()     │ process_    │
│  (Obsidian Vault)     │  (#idea, #todo, #res) │ with_LLM()  │
│  ▼                     │                       │             │
│  notes_to_process     │   prompt_templates    │ llm_engine  │
│  ▼                     │                       │             │
│  generate_report()    │   _Nightly_Reports/   │             │
│  (Markdown Output)    │   YYYY-MM-DD.md       │             │
│  ▼                     │                       │             │
│  Morning Briefing    │                       │             │
│  (Flutter Widget)     │                       │             │
└───────────────────────┴───────────────────────┴─────────────┘
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `jarvis_os/core/scheduler.py` | Create | Idle scheduler with crontab intervals, throttling, toggle API |
| `jarvis_os/skills/nightly_labs.py` | Create | Nightly Worker Skill: scan, extract, process, report |
| `jarvis_os/vault/nightly_indexer.py` | Modify | Incremental scan for #idea/#todo/#research tags |
| `jarvis_ui/lib/widgets/nightly_briefing.dart` | Create | Morning Briefing widget in HomeScreen |
| `jarvis_ui/lib/providers/nightly_provider.dart` | Create | Riverpod provider for nightly state |
| `.progress` | Modify | Add FASE 10 nightly labs entry |
| `.agents` | Modify | Add nightly worker capacity description |

## Interfaces / Contracts

### Scheduler API

```python
# jarvis_os/core/scheduler.py (new)
class IdleScheduler:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def add_task(self, task_func, interval_minutes: int, priority: str = "low") -> str: ...
    def get_status(self) -> dict: ...
```

### Nightly Worker Skill Operations

```python
# jarvis_os/skills/nightly_labs.py (new)
class NightlyLabsSkill(BaseSkill):
    async def scan_vault(self) -> list[dict]: ...
    async def extract_notes(self, notes: list[dict]) -> dict: ...
    async def process_with_llm(self, content: dict) -> dict: ...
    async def generate_report(self, results: dict) -> str:  # returns output_ref path
        ...
```

### Report Markdown Frontmatter

```markdown
---
date: "2026-09-06"
tasks_executed:
  - {id: "1", status: "completed", duration_ms: 1200, prompt: "extract_ideas"}
  - {id: "2", status: "skipped", reason: "no_llm_available"}
ideas_extracted:
  - {title: "Auto-optimizer", source: "notes/ideas/2026-08-20.md", confidence: 0.92}
tasks_pending:
  - {title: "Refactor auth", source: "notes/todo/2026-09-05.md"}
research_findings:
  - {topic: "Quantum caching", source: "notes/research/2026-09-03.md", summary: "Short summary"}
resource_metrics:
  cpu_average: 12.5
  ram_peak_mb: 180
---
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `IdleScheduler.start/stop` | pytest with mock asyncio, verify interval timing |
| Unit | `NightlyLabsSkill.scan_vault` | pytest with mock vault, verify tag detection |
| Unit | `VaultOutputLogger.write_execution` | pytest with tmpdir, verify frontmatter + body |
| Integration | Scheduler → skill → report | pytest with mocked LLM, verify full pipeline |
| E2E | Nightly cycle execution | `python tests/nightly_e2e_test.py` with mocked time |
| RED | Scheduler ignores active session | Mock user active, assert task deferred |
| RED | LLM unavailable → skip | Mock no LLM binary, assert task marked skipped |
| RED | Resource throttling abort | Mock high CPU, assert task aborted and logged |

## Threat Matrix

| Boundary | Adversarial cases | Applicability | Design response |
|----------|------------------|---------------|-----------------|
| Vault scans | Path traversal in tag detection | Applicable | Sanitize all file paths; restrict to vault root |
| LLM execution | Prompt injection via note content | Applicable | Sanitize content before prompt insertion; limit prompt length |
| Resource exhaustion | Unbounded task execution | Applicable | Enforce CPU/RAM throttling; max 30s per prompt; max 5 tasks/night |
| Report corruption | Invalid frontmatter written | Applicable | Strict frontmatter validation on read; backup before write |
| Session interference | Nightly tasks during user activity | Applicable | Session detection; defer during active sessions; idle detection |

## Migration / Rollout

Phased rollout:
1. **Phase 1** (core): Add scheduler, nightly skill, vault scanner, report generation.
2. **Phase 2** (HUD): Add Morning Briefing widget to Flutter HomeScreen.
3. **Phase 3** (E2E): Add automated tests; run in CI during nightly window.

## Open Questions

- [ ] Should the scheduler be configurable per-timezone or always use local host time?
- [ ] Should the LLM engine fallback order be user-configurable via settings?
- [ ] Should Morning Briefing be enabled by default or opt-in?
- [ ] What is the ideal retention period for `_Nightly_Reports/` before automatic cleanup?
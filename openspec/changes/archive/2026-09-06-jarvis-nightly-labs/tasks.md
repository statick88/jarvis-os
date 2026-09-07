# Tasks — Nightly Labs & Idle Worker (jarvis-nightly-labs)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~300-400 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |

### Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: N/A
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Focused test command | Runtime harness | Rollback boundary |
|------|------|---------------------|-----------------|-------------------|
| 1 | Idle scheduler + toggle API | `pytest tests/ -k "scheduler or nightly"` | pytest with mock asyncio | `jarvis_os/core/scheduler.py`, `jarvis_os/orchestrator.py` |
| 2 | Nightly Worker Skill + Vault connector | `pytest tests/ -k "nightly_labs or vault"` | pytest with mock vault | `jarvis_os/skills/nightly_labs.py`, `jarvis_os/vault/` |
| 3 | Flutter Morning Briefing + Report widget | `flutter test test/widgets/nightly_briefing_test.dart` | Flutter test runner | `jarvis_ui/lib/`, `tests/` |

## Phase 1: Idle Scheduler & Resource Throttling

- [x] 1.1 Create `jarvis_os/core/scheduler.py`: `IdleScheduler` class con métodos `start()`, `stop()`, `add_task()`, `get_status()`. Soporte intervalos crontab-like (00:00-06:00), throttling CPU/RAM, y toggle vía REST `POST /v1/nightly/scheduler/toggle`.
- [x] 1.2 Edit `jarvis_os/orchestrator.py`: Agregar endpoints `/v1/nightly/scheduler/toggle` y `/v1/nightly/scheduler/status` que deleguen al scheduler.
- [x] 1.3 Create `tests/core/test_scheduler.py`: Test de intervalos, throttling, toggle on/off, protección de sesiones activas.
- [x] 1.4 Ejecutar `pytest tests/core/test_scheduler.py`; validar 0 FAIL.

## Phase 2: Nightly Worker Skill & Obsidian Vault Connector

- [x] 2.1 Fix `jarvis_os/skills/nightly_labs.py`: super().__init__ wiring, permissions enum, load() accepts config param, get_schema() implementation. LLMSettings already in config.py (no changes needed).
- [x] 2.2 Edit `jarvis_os/vault/indexer.py`: Agregar funcionalidad de escaneo incremental por etiquetas nightly; soportar búsqueda por `#idea`, `#todo`, `#research`.
- [x] 2.3 Fix `tests/skills/test_nightly_labs.py`: Full rewrite — 61 tests, 0 FAIL. Root causes: 30 OSError (missing vault_root config), 1 timeout (wrong exception type).
- [x] 2.4 Create `tests/vault/test_nightly_indexer.py`: Test de etiquetado incremental, consistencia de links después de scan nightly.
- [x] 2.5 Ejecutar `pytest tests/`; validar 153/153 passed, 0 FAIL.

## Phase 3: Automatic Nightly Report Generation & Flutter Integration

- [x] 3.1 Create `jarvis_ui/lib/widgets/nightly_briefing.dart`: Widget `MorningBriefing` que muestra en el header del HomeScreen: última ejecución, contador de ideas/tareas, enlace al reporte day.
- [x] 3.2 Edit `jarvis_ui/lib/screens/home_screen.dart`: Integrar `MorningBriefing` widget en el área de salud superior derecha.
- [x] 3.3 Create `jarvis_ui/lib/providers/nightly_provider.dart`: Riverpod provider para estado nightly (última ejecución, estado, métricas).
- [x] 3.4 Create `tests/widgets/nightly_briefing_test.dart`: Unit tests for MorningBriefing widget rendering, state provider.
- [x] 3.5 Ejecutar `flutter test test/widgets/nightly_briefing_test.dart`; validar 0 FAIL.
- [x] 3.6 Crear reporte de prueba `_Nightly_Reports/2026-09-06.md` con estructura de frontmatter verificada.

## Phase 4: Verification and Cleanup

- [x] 4.1 Ejecutar suite completa: `pytest tests/ -k "nightly or scheduler"`; validar 0 FAIL, 0 SKIP. ✅ 96 passed, 0 failed.
- [x] 4.2 Ejecutar `flutter test test/widgets/nightly_briefing_test.dart`; validar 0 FAIL. ✅ 5/5 passed.
- [x] 4.3 Actualizar `.progress`: Agregar sección FASE 12 nightly labs, marcar RC1 entry. ✅ Updated.
- [x] 4.4 Actualizar `.agents`: Agregar descripción de capacidad worker nocturno, umbrales CPU/RAM, protocolo LLM local. ✅ Updated.
- [ ] 4.5 Ejecutar `bash scripts/test_jarvis_pipeline.sh`; validar 0 FAIL, 0 SKIP. ⚠️ BLOCKED: Docker daemon (Colima) not running. Deferred — infrastructure dependency, not implementation gap.
- [x] 4.6 Archive: Sync delta specs to main specs, move change folder to archive. ✅ Archived 2026-09-06.
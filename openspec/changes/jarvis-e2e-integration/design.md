# Design: jarvis-e2e-integration

## Prior Art
Reusa `2026-09-14-2026-09-07-jarvis-e2e-closed-loop/{proposal,design,spec}.md` y `openspec/specs/e2e-closed-loop/spec.md`. No duplicar event bus ni VaultOutputLogger.

## Changes

### T-2 Wire VaultIndexer
- `jarvis_os/orchestrator_impl/pipeline.py:189 _write_vault_and_emit`: aceptar `VaultIndexer | None`, tras `write_execution` OK llamar update incremental de links; envolver en try/except reusando `_VAULT_WRITE_FAILED` para nunca romper ejecución.
- `jarvis_os/orchestrator.py:132`: instanciar indexer y pasarlo al pipeline.
- Tests: regresión en `tests/orchestrator/` — vault OK genera backlink, vault FAIL no rompe pipeline.

### T-3 POST /v1/vault/rebuild
- Nueva ruta en `jarvis_os/orchestrator.py` junto a `:462 /v1/execute`, delega a `VaultIndexer.rebuild()` (`indexer.py:191`), retorna `VaultOperationResult`.
- Tests: `tests/vault/test_indexer_links.py` + caso live en E2E.

### T-4 Latency
- Timestamps en `pipeline.py:126-185` (STT-entry, TTS-dispatch), exponer en `SkillExecutionComplete` (`events.py`), consumir en `event_stream_service.dart:56`.
- Sin reloj externo; solo `time.perf_counter` / `DateTime.now` según lado.

## HUD Path Note
Runtime usa `/voice` (config.py:219 + Flutter :148). `.agents:181` dice `/hud/ws` — drift cosmético documentado, no renombrar en este change.

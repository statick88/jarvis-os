# Tasks: jarvis-e2e-integration

## T-1 Register (inline, done)
- [x] `odd/tasks/jarvis-e2e-integration.md` creado (5 tasks)
- [x] `openspec/changes/jarvis-e2e-integration/{proposal,design,tasks}.md`
- [ ] `state.yaml:active_change: jarvis-e2e-integration`
- [ ] checklist `.progress` FASE 11

## T-2 Wire VaultIndexer (delegated)
- Files: `jarvis_os/orchestrator_impl/pipeline.py`, `jarvis_os/orchestrator.py`, `tests/orchestrator/*`
- RED: test que falla sin llamada a indexer. GREEN: wire con fallback. REFACTOR con tests verdes.

## T-3 Rebuild endpoint (delegated)
- Files: `jarvis_os/orchestrator.py`, `tests/vault/test_indexer_links.py`
- RED: POST 404. GREEN: 200 con rebuild real.

## T-4 Latency (delegated)
- Files: `orchestrator_impl/events.py`, `pipeline.py`, `event_stream_service.dart`
- RED: payload sin timestamps. GREEN: p50 medible.

## T-5 E2E verify (delegated)
- `scripts/test_jarvis_pipeline.sh`: assert `vault/outputs/$(date +%F)/*.md` + backlink
- `tests/e2e_voice_to_hud_test.py`: casos live rebuild + latency + no-skip guard
- Runner: `pytest`, ambos `.sh --quick`, `gentle-ai doctor`

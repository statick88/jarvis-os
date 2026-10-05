# Proposal: jarvis-e2e-integration — FASE 11 Cierre Incremental

## Intent
Cerrar los 3 gaps runtime que quedaron tras `2026-09-14-2026-09-07-jarvis-e2e-closed-loop` (archivado PASS): wire `VaultIndexer` al pipeline, endpoint `POST /v1/vault/rebuild`, e instrumentación de latencia <500ms.

## Context
El loop base ya existe y está archivado: `VaultOutputLogger`, domain events, HUD WS en `/voice`, `tests/e2e_voice_to_hud_test.py` sin skips. `state.yaml` está en `idle/null` sin change activo. Este change es incremental, no greenfield.

## Scope
In: T-2 indexer-wire, T-3 rebuild endpoint, T-4 latency, T-5 E2E extend + verify.
Out: nuevos skills, cambio de puertos, re-entrenar STT/TTS.

## Success
Los 6 acceptance criteria de `odd/tasks/jarvis-e2e-integration.md`. `gentle-ai doctor` 0 CRITICAL.

## Risk
Bajo: wiring con fallback existente `_VAULT_WRITE_FAILED`; endpoint read-only sobre indexer; latencia solo añade timestamps.

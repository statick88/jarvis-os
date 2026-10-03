# Feature: jarvis-e2e-integration — FASE 11 Cierre Loop Cerrado

## Objective
Cerrar FASE 11 Integración Total E2E: voz→texto→skill→vault→voz con latencia <500ms, vault outputs con links bidireccionales, HUD realtime, suite E2E verde y doctor 0 CRITICAL.

## Problem
El loop existe pero con 3 brechas runtime: `VaultIndexer` nunca se invoca desde el pipeline (solo desde handler boveda y tests), falta endpoint `/v1/vault/rebuild`, y no hay instrumentación de latencia en el path productivo. Además no hay change registrado (`state.yaml:active_change: null`) ni checklist ejecutable en `.progress`.

## Why
- `.agents` FASE 11 define 5 criterios, los 5 pendientes
- `state.yaml` 2026-09-07 ya archivó runtime-hardening (18/18) y nightly-labs, dejando FASE 11 como único gap core
- Explorer 2026-10-02 confirmó: `VaultOutputLogger`, domain events, HUD WS y E2E base ya existen — es cierre, no greenfield

## Scope
- **In scope**: registrar change, wire VaultIndexer al pipeline, endpoint rebuild, instrumentación latencia, extender E2E y verificar
- **Out of scope**: nuevos skills, cambios de puertos (tailscale-only ya fijado en 8000/8080/3000/9000), retraining STT/TTS, mobile store release

## Constraints
- No romper ejecución si falla vault (reusar fallback `_VAULT_WRITE_FAILED` en `pipeline.py:57`)
- HUD WS path runtime es `/voice` (config.py:219 + Flutter :148); no renombrar a `/hud/ws` sin migrar ambos lados — documentar drift
- Conventional Commits por work-unit, tests + docs junto al behavior
- Test-first donde aplique: RED observable antes de GREEN para T-2/T-3/T-4

## Acceptance Criteria
- [ ] Pipeline voz→skill→vault→voz E2E con latencia p50 <500ms instrumentada
- [ ] Cada skill COMPLETED deja `vault/outputs/YYYY-MM-DD/<skill>-<HHMMSS>.md` con frontmatter válido
- [ ] `[[...]]` bidireccionales actualizados automáticamente post-skill
- [ ] HUD Flutter refleja SKILL_EXECUTION_* y VAULT_UPDATE en tiempo real
- [ ] `test_jarvis_pipeline.sh` + `test_audio_streaming.sh --quick` + `tests/e2e_voice_to_hud_test.py` sin FAIL ni SKIP
- [ ] `gentle-ai doctor` 0 CRITICAL

## Applicable Checks
- `pytest tests/e2e_voice_to_hud_test.py -v`
- `bash scripts/test_jarvis_pipeline.sh`
- `bash scripts/test_audio_streaming.sh --quick`
- `gentle-ai doctor`
- `python3 -m compileall jarvis_os`

## Dependency Graph
```
jarvis-e2e-integration → T-1 register → T-2 indexer-wire → T-3 rebuild-endpoint → T-4 latency → T-5 e2e-verify → archive
```

## Progress & Verification
- Initial: 2026-10-02 explorer handoff, 0/5 tasks, base 38/38 PASS heredada
- Per-task: checkoff solo con outcome + checks observados; commit work-unit registrado aquí

## Rationale
Cerrar en vez de expandir: la evidencia muestra que el 90% ya está construido. El riesgo no es construir, es probar el loop de forma determinista.

## Delivery Strategy
- Strategy: `ask-on-risk` (default)
- Forecast: ~350 authored changed lines (excl. generados), bajo el budget de 400 por slice — un solo PR si se requiere
- Slice boundary: un work-unit commit por task (T-1..T-5)

---

## Task List

| ID | Task | Description | Status | Priority | Route | Trigger Evidence |
|----|------|-------------|--------|----------|-------|------------------|
| T-1 | Register change | Crear `openspec/changes/jarvis-e2e-integration/{proposal,design,tasks}.md`, set `state.yaml:active_change`, checklist `.progress` FASE 11, este doc | done | high | inline | 1 doc mecánico, sin research, <10k tokens |
| T-2 | Wire VaultIndexer | Inyectar `VaultIndexer` en `pipeline.py:189 _write_vault_and_emit`, update incremental con try/except + fallback; instanciar en `orchestrator.py:132`; test regresión | done | high | delegated direct | 2+ files no-triviales + lectura prepara escritura |
| T-3 | Add rebuild endpoint | `POST /v1/vault/rebuild` en `orchestrator.py` junto a `:462 /v1/execute` → `indexer.py:191 rebuild()`; test links | done | high | delegated direct | 2+ files, endpoint + tests |
| T-4 | Latency instrumentation | timestamps STT-entry y TTS-dispatch en `pipeline.py:126-185`, exponer en `SkillExecutionComplete` (`events.py`), render en `event_stream_service.dart:56` | pending | high | delegated direct | 3 files cross-stack (py+dart) |
| T-5 | Extend E2E + verify | asserts `vault/outputs/$(date +%F)/*.md` + backlinks en `test_jarvis_pipeline.sh`; casos live en `e2e_voice_to_hud_test.py`; correr full suite + doctor | pending | high | delegated direct | full suite, output no acotado a --stat |

## Allowed Edit Surfaces (para writers delegados)
- `jarvis_os/orchestrator.py`
- `jarvis_os/orchestrator_impl/pipeline.py`
- `jarvis_os/orchestrator_impl/events.py`
- `jarvis_os/vault/indexer.py`
- `jarvis_os/vault/output_logger.py`
- `jarvis_ui/lib/services/event_stream_service.dart`
- `jarvis_ui/lib/providers/hud_event_providers.dart`
- `tests/e2e_voice_to_hud_test.py`
- `tests/orchestrator/*`
- `tests/vault/test_indexer_links.py`
- `scripts/test_jarvis_pipeline.sh`
- `openspec/changes/jarvis-e2e-integration/*`
- `state.yaml`
- `.progress`

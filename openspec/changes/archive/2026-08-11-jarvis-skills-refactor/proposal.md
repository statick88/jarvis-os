# Proposal: Refactor y Cierre de Skills

## Intent
Close FASE 8 gaps identified in verification: unify the duplicated skills architecture, fix runtime dependencies, complete partial requirements, and replace placeholder implementations with real clients.

## Scope
- **In scope:**
  - Unify `.skills/*.md` handlers with `jarvis_os/skills/*/plugin.py` plugins into a single execution path
  - Add `psutil` to `docker/Dockerfile.gentle` and enable real metrics in `skill-os-control`
  - Implement `summarize_note` in `ObsidianSkill`
  - Replace `skill-devsecops` placeholders with real `boto3` LocalStack client and `docker-py` integration
  - Extend `scripts/test_jarvis_pipeline.sh` to cover `/api/v1/skills/*` endpoints
  - Centralize port configuration for orchestrator/voice

- **Out of scope:**
  - iOS/Web support
  - New skills beyond the three expanded in FASE 8
  - UI integration for skills in `jarvis_ui`

## Approach
1. Audit current dual skills system and choose single canonical path
2. Add `psutil` to Dockerfile and validate metrics end-to-end
3. Implement missing `summarize_note` operation
4. Wire real LocalStack/Docker clients with fallback to mock when unavailable
5. Add E2E coverage for skills API
6. Update documentation and close verification gaps

## Tradeoffs
- **Chosen:** Unify under existing `.skills/*.md` + handlers system, since it already works and is wired into the orchestrator
- **Chosen:** Real clients with mock fallback rather than pure mock, to enable both development and production
- **Deferred:** UI skill discovery until next phase

## Rollback
- Revert Dockerfile changes
- Revert skill implementations to previous archived state
- Remove E2E coverage additions

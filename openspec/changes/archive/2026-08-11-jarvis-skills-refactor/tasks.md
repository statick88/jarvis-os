# Tasks — Refactor y Cierre de Skills (jarvis-skills-refactor)

## Phase 1: Unification
- [x] 1.1 Audit dual skills systems and document canonical path
- [x] 1.2 Rewrite `jarvis_os/api/routes/skills.py` to use `SkillExecutor` + `SkillLoader` instead of `PluginRegistry`
- [x] 1.3 Add deprecation notice to `PluginRegistry` and plugin wrappers
- [x] 1.4 Verify existing `.skills/*.md` handlers still load and execute via new routes

## Phase 2: Runtime Fixes
- [x] 2.1 Add `psutil` to `docker/Dockerfile.gentle` python-deps
- [x] 2.2 Rebuild orchestrator image and verify metrics collection
- [x] 2.3 Implement `summarize_note` operation in `jarvis_os/skills/handlers/obsidian.py`
- [x] 2.4 Register summarize operation in skill frontmatter/schema

## Phase 3: Real Clients
- [x] 3.1 Add `boto3` to `docker/Dockerfile.gentle`
- [x] 3.2 Implement LocalStack S3/DynamoDB/SQS clients in `jarvis_os/skills/handlers/devsecops.py`
- [x] 3.3 Add `docker-py` to `docker/Dockerfile.gentle`
- [x] 3.4 Implement Docker management operations with read-only default
- [x] 3.5 Add mock fallback when clients unavailable

## Phase 4: Testing & Config
- [x] 4.1 Extend `scripts/test_jarvis_pipeline.sh` with skills API coverage
- [x] 4.2 Centralize port configuration via env vars in `orchestrator.py` and `docker-compose.yml`
- [x] 4.3 Run full E2E suite and verify all checks pass
- [x] 4.4 Run `flutter analyze` and `flutter test`

## Phase 5: Verification
- [x] 5.1 Re-run `bash scripts/test_jarvis_pipeline.sh`
- [x] 5.2 Manual API verification for all skills
- [x] 5.3 Update `.progress` and `.agents` with closure

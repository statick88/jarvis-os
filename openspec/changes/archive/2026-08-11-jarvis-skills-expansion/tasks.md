# Tasks — Expansión de Skills (jarvis-skills-expansion)

## Phase 1: Foundation (Core Framework & Sandbox)
- [x] 1.1 Create `BaseSkill` abstract class in `jarvis_os/skills/base.py` with lifecycle methods
- [x] 1.2 Implement `PluginRegistry` with autodiscovery in `jarvis_os/skills/plugin_registry.py`
- [x] 1.3 Build `CommandSandbox` with whitelist and timeouts in `jarvis_os/skills/sandbox.py`
- [x] 1.4 Add orchestrator REST routes in `jarvis_os/api/routes/skills.py` and register in `orchestrator.py`
- [x] 1.5 Verify plugin loading without breaking existing `.skills/*.md` system

## Phase 2: Obsidian Skill
- [x] 2.1 Implement `ObsidianSkill` plugin with CRUD operations in `jarvis_os/skills/obsidian/plugin.py`
- [x] 2.2 Add full-text search across vault notes
- [x] 2.3 Implement automatic summarization of note contents
- [x] 2.4 Register skill and verify via REST endpoint

## Phase 3: OS Control Skill
- [x] 3.1 Implement `OSControlSkill` with resource monitoring using `psutil` in `jarvis_os/skills/os_control/plugin.py`
- [x] 3.2 Build command sandbox integration for whitelisted commands
- [x] 3.3 Add audit logging for executed commands
- [x] 3.4 Register skill and verify via REST endpoint

## Phase 4: DevSecOps Skill
- [x] 4.1 Implement `DevSecOpsSkill` with LocalStack clients in `jarvis_os/skills/devsecops/plugin.py`
- [x] 4.2 Add Docker management operations
- [x] 4.3 Implement safety guards and confirmation flows
- [x] 4.4 Register skill and verify via REST endpoint

## Phase 5: Verification
- [x] 5.1 Run `flutter analyze` and ensure no new warnings
- [x] 5.2 Run `flutter test` and verify skill UI components
- [x] 5.3 Run `bash scripts/test_jarvis_pipeline.sh` for backend compatibility
- [x] 5.4 Manual verification: execute each skill via orchestrator API

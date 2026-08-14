# Tasks — JD Critical Fixes for Skills (jarvis-skills-jd-fixes)

## Phase 1: Security Fixes
- [x] 1.1 Add path containment to `jarvis_os/skills/handlers/obsidian.py`
- [x] 1.2 Fix YAML tags serialization in `jarvis_os/skills/handlers/obsidian.py`
- [x] 1.3 Add regression tests for path traversal and YAML tags

## Phase 2: Contract/Performance Fixes
- [x] 2.1 Forward `request.operation` in canonical route `jarvis_os/api/routes/skills.py`
- [x] 2.2 Make `psutil.cpu_percent` nonblocking in `jarvis_os/skills/os_control/plugin.py`
- [x] 2.3 Add regression tests for operation routing and nonblocking metrics

## Phase 3: Verification
- [x] 3.1 Run `bash scripts/test_jarvis_pipeline.sh`
- [x] 3.2 Update `.progress` and `state.yaml`
- [x] 3.3 Run Judgment Day scoped re-judgment

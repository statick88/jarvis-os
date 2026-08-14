# Proposal: JD Critical Fixes for Skills

## Intent
Fix 4 CRITICAL findings from Judgment Day round 1 on `jarvis-skills-refactor`: path traversal, operation routing mismatch, blocking event-loop call, and invalid YAML frontmatter serialization.

## Scope
- **In scope:**
  - Fix path traversal in `jarvis_os/skills/handlers/obsidian.py`
  - Fix canonical route to forward `request.operation` in `jarvis_os/api/routes/skills.py`
  - Fix blocking `psutil.cpu_percent(interval=1)` in `jarvis_os/skills/os_control/plugin.py`
  - Fix YAML tags serialization in `jarvis_os/skills/handlers/obsidian.py`
  - Add regression tests for each fix

- **Out of scope:**
  - New skills or features
  - UI changes
  - Refactoring unrelated code

## Approach
1. Harden obsidian handler with path containment and proper YAML serialization
2. Align canonical FastAPI route with legacy operation routing contract
3. Move psutil blocking call off the event loop
4. Add minimal regression coverage and re-run E2E

## Tradeoffs
- **Chosen:** Minimal surgical fixes over broader refactor to reduce review surface
- **Deferred:** Full security audit of all skill handlers to later change

## Rollback
- Revert 4 targeted file changes
- Remove added regression tests

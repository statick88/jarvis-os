# Design — JD Critical Fixes for Skills (jarvis-skills-jd-fixes)

## Technical Approach
Apply 4 targeted correctness/security fixes in existing files, keeping change surface minimal for reviewability.

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Path containment | Resolve path + `is_relative_to(vault_path)` before I/O | Deterministic; no runtime allowlist drift |
| Operation routing | Pass `request.operation` into canonical executor path | Restores parity with legacy plugin path |
| Nonblocking metrics | `asyncio.to_thread(psutil.cpu_percent, interval=0)` | Avoids 1s blocking sleep in event loop |
| YAML serialization | Use `yaml.dump` or manual list syntax for tags | Valid YAML frontmatter Obsidian can parse |

## Data Flow

    Client → FastAPI /api/v1/skills/{skill}/execute
      → execute_skill(skill_name, request)
        → canonical path:
            metadata = loader.load_all()[skill_name]
            result = executor.execute(
                skill=metadata,
                operation=request.operation,
                input_data=request.parameters,
                execution_type=metadata.frontmatter.execution_type,
            )
        → legacy fallback unchanged

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `jarvis_os/skills/handlers/obsidian.py` | Modify | Add path containment + YAML tag serialization |
| `jarvis_os/api/routes/skills.py` | Modify | Forward `request.operation` to executor |
| `jarvis_os/skills/os_control/plugin.py` | Modify | Run `psutil.cpu_percent` via `asyncio.to_thread` |
| `scripts/test_jarvis_pipeline.sh` | Modify | Add regression checks for fixes |

## Interfaces / Contracts

```python
# Canonical execution contract
result = await _executor.execute(
    skill=metadata,
    operation=request.operation,
    input_data=request.parameters,
    execution_type=metadata.frontmatter.execution_type,
)
```

```python
# Path containment
resolved = (vault_path / input_data["path"]).resolve()
if not str(resolved).startswith(str(vault_path.resolve())):
    raise ValueError("Path escapes vault root")
```

```python
# Nonblocking CPU metrics
cpu_percent = await asyncio.to_thread(psutil.cpu_percent, interval=0)
```

```python
# Valid YAML tags
tags_yaml = yaml.dump({"tags": tags}, default_flow_style=False)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Obsidian path traversal rejection | `..` and absolute paths return error |
| Unit | Canonical route forwards operation | mock executor assert receives operation |
| Unit | OSControl metrics nonblocking | mock `asyncio.to_thread` call |
| Integration | E2E skills API still passes | existing pipeline script |

## Threat Matrix

| Threat | Fix | Residual Risk |
|---|---|---|
| Arbitrary file read/write via obsidian | Path containment | Low |
| API contract violation | Forward operation field | None |
| DoS via event-loop stall | Threadpool offload | Low |

## Migration / Rollout

No migration needed. Fixes are backward-compatible at API level; invalid paths now return errors instead of escaping.

## Open Questions

None.

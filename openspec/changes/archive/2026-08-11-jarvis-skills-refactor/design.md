# Design — Refactor y Cierre de Skills (jarvis-skills-refactor)

## Technical Approach
Unify the dual skills system by making the existing `.skills/*.md` + `handlers/*.py` path canonical, and rewrite the FastAPI skill routes to use `SkillExecutor` instead of `PluginRegistry`. Then close verification gaps: add `psutil`, implement `summarize_note`, wire real LocalStack/Docker clients with mock fallback, extend E2E, and centralize port config.

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Canonical execution path | Existing `.skills/*.md` + `SkillExecutor` | Already loaded, validated, and wired into the orchestrator; avoids reimplementing loader/schema/retry logic |
| Plugin classes | Deprecated thin wrappers | Preserve investment in `obsidian/os_control/devsecops` modules without duplicating execution |
| Metrics backend | `psutil` with fallback | `psutil` is lightweight and cross-platform; fallback keeps local dev working |
| LocalStack client | `boto3` with `endpoint_url` override | Standard AWS SDK; works against real AWS and LocalStack with env switch |
| Docker client | `docker-py` read-only by default | Official SDK; destructive ops require explicit confirmation flag |
| Port configuration | Env vars with defaults | Single source of truth; compose, orchestrator, and client read same values |

## Data Flow

    Client → FastAPI `/api/v1/skills/{skill}/execute`
      → SkillExecutor.execute(skill, input)
        → handler.run(input)   # canonical path
        → plugin.execute(...)  # deprecated fallback
      → JSON response

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `jarvis_os/api/routes/skills.py` | Modify | Use `SkillExecutor` + `SkillLoader` instead of `PluginRegistry` |
| `docker/Dockerfile.gentle` | Modify | Add `psutil`, `boto3`, `docker-py` to python-deps |
| `jarvis_os/skills/handlers/plan.py` | Modify | Add `summarize` helper if needed by cross-skill workflows |
| `jarvis_os/skills/os_control/plugin.py` | Modify | Add `psutil` metrics path + fallback |
| `jarvis_os/skills/devsecops/plugin.py` | Modify | Replace placeholders with real `boto3`/`docker-py` clients |
| `scripts/test_jarvis_pipeline.sh` | Modify | Add skills API coverage |
| `openspec/changes/jarvis-skills-refactor/tasks.md` | Modify | Keep as implementation backlog |

## Interfaces / Contracts

```python
# Canonical skill execution
from jarvis_os.skills.executor import SkillExecutor
from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.registry import SkillRegistry

loader = SkillLoader(skills_dir=Path(".skills"))
registry = SkillRegistry()
executor = SkillExecutor(default_timeout=30)

# FastAPI route
result = await executor.execute(skill=registry.get(skill_name), input_data=request.parameters)
```

```python
# OS Control metrics
try:
    import psutil
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
except ImportError:
    # fallback to subprocess shell commands
    ...
```

```python
# DevSecOps LocalStack client
import boto3
session = boto3.Session()
s3 = session.client("s3", endpoint_url=os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566"))
```

```python
# DevSecOps Docker client
import docker
client = docker.from_env()
containers = client.containers.list(all=True)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `SkillExecutor.execute()` routing to handlers | Existing pattern; no new harness needed |
| Unit | `os_control` metrics with/without `psutil` | Mock `psutil` import + fallback path |
| Unit | `devsecops` client initialization | Mock `boto3`/`docker-py` when endpoint unreachable |
| Integration | `/api/v1/skills/*` endpoints | Add curl assertions to `test_jarvis_pipeline.sh` |
| E2E | Full skills API coverage | 4 new checks: list, obsidian create, os metrics, devsecops scan |

## Threat Matrix

N/A — no routing/shell/VCS/process-integration boundary changes beyond existing `CommandSandbox`, which already covers subprocess execution.

## Migration / Rollout

No migration required. Existing `.skills/*.md` files remain valid. `PluginRegistry` remains importable during transition. Deprecation warning added in code; removal in future change.

## Open Questions

- [ ] Should `summarize_note` be a handler-only addition or also exposed via `plugin.py` wrapper?
- [ ] Do we add `boto3`/`docker-py` to `requirements.txt` in addition to Dockerfile?
- [ ] Should port env vars be `.env`-backed in addition to compose env?

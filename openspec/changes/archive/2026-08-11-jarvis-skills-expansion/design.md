# Design — Expansión de Skills (jarvis-skills-expansion)

## 1. Plugin Engine Architecture

### 1.1 Base Skill Interface
```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from enum import Enum

class SkillPermission(Enum):
    READ_VAULT = "read_vault"
    WRITE_VAULT = "write_vault"
    READ_METRICS = "read_metrics"
    EXECUTE_COMMANDS = "execute_commands"
    MANAGE_LOCALSTACK = "manage_localstack"
    MANAGE_DOCKER = "manage_docker"

class BaseSkill(ABC):
    def __init__(self, name: str, version: str, permissions: List[SkillPermission]):
        self.name = name
        self.version = version
        self.permissions = permissions
        self._loaded = False

    async def load(self) -> None:
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    @abstractmethod
    async def execute(self, operation: str, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        pass

    def validate_permission(self, permission: SkillPermission) -> bool:
        return permission in self.permissions

    @property
    def is_loaded(self) -> bool:
        return self._loaded
```

### 1.2 Skill Registry and Autodiscovery
```python
class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}
        self._load_order: List[str] = []

    async def register(self, skill: BaseSkill) -> None:
        await skill.load()
        self._skills[skill.name] = skill
        self._load_order.append(skill.name)

    async def unregister(self, skill_name: str) -> None:
        if skill_name in self._skills:
            await self._skills[skill_name].unload()
            del self._skills[skill_name]
            self._load_order.remove(skill_name)

    def get(self, skill_name: str) -> Optional[BaseSkill]:
        return self._skills.get(skill_name)

    def list_skills(self) -> List[Dict[str, str]]:
        return [
            {"name": s.name, "version": s.version, "permissions": [p.value for p in s.permissions]}
            for s in self._skills.values()
        ]

    async def discover_and_load(self, skills_dir: str) -> None:
        for module_path in Path(skills_dir).rglob("plugin.py"):
            module = importlib.import_module(f"jarvis_os.skills.{module_path.stem}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if inspect.isclass(attr) and issubclass(attr, BaseSkill) and attr != BaseSkill:
                    skill = attr()
                    await self.register(skill)
```

### 1.3 Security and Sandbox Model
```python
class CommandSandbox:
    def __init__(self, whitelist: List[str]):
        self.whitelist = set(whitelist)

    def validate(self, command: str) -> bool:
        return command in self.whitelist

    async def execute(self, command: str, args: List[str], timeout: int = 30) -> Dict[str, Any]:
        if not self.validate(command):
            raise PermissionError(f"Command '{command}' not in whitelist")
        proc = await asyncio.create_subprocess_exec(
            command, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {"returncode": proc.returncode, "stdout": stdout.decode(), "stderr": stderr.decode()}
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command '{command}' timed out after {timeout}s")
```

### 1.4 Error Isolation
- Each skill execution runs in its own `asyncio` task with a per-skill timeout.
- Exceptions are caught at the registry level and returned as structured error responses.
- A failing skill does not crash the orchestrator; it returns `{"status": "error", "skill": name, "message": str(e)}`.

## 2. JSON Tool Calling Schemas (OpenAI-compatible)

### 2.1 Obsidian Skill Tools

#### `create_note`
```json
{
  "type": "function",
  "function": {
    "name": "obsidian_create_note",
    "description": "Create a new Markdown note in the Obsidian vault with optional tags and links",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {"type": "string", "description": "Relative path from vault root, e.g. 'notes/meeting.md'"},
        "title": {"type": "string", "description": "Note title (frontmatter or H1)"},
        "content": {"type": "string", "description": "Markdown body content"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
        "links": {"type": "array", "items": {"type": "string"}, "description": "Optional [[wikilinks]]"}
      },
      "required": ["path", "title", "content"]
    }
  }
}
```

#### `search_vault`
```json
{
  "type": "function",
  "function": {
    "name": "obsidian_search_vault",
    "description": "Full-text search across all vault notes",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Search query string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
      },
      "required": ["query"]
    }
  }
}
```

#### `append_to_note`
```json
{
  "type": "function",
  "function": {
    "name": "obsidian_append_to_note",
    "description": "Append content to an existing note",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {"type": "string", "description": "Relative path from vault root"},
        "content": {"type": "string", "description": "Markdown content to append"},
        "separator": {"type": "string", "description": "Optional separator before appended content", "default": "\n\n---\n\n"}
      },
      "required": ["path", "content"]
    }
  }
}
```

### 2.2 OS Control Skill Tools

#### `get_system_metrics`
```json
{
  "type": "function",
  "function": {
    "name": "os_control_get_system_metrics",
    "description": "Get real-time CPU, RAM, and disk usage metrics from the host macOS system",
    "parameters": {
      "type": "object",
      "properties": {
        "metrics": {
          "type": "array",
          "items": {"type": "string", "enum": ["cpu", "ram", "disk", "all"]},
          "description": "Specific metrics to retrieve"
        }
      },
      "required": ["metrics"]
    }
  }
}
```

#### `execute_system_command`
```json
{
  "type": "function",
  "function": {
    "name": "os_control_execute_system_command",
    "description": "Execute a whitelisted macOS command with audit logging",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {"type": "string", "description": "Whitelisted command name"},
        "args": {"type": "array", "items": {"type": "string"}, "description": "Command arguments"},
        "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 30}
      },
      "required": ["command", "args"]
    }
  }
}
```

### 2.3 DevSecOps Skill Tools

#### `scan_repository`
```json
{
  "type": "function",
  "function": {
    "name": "devsecops_scan_repository",
    "description": "Scan the current repository for security issues and configuration drift",
    "parameters": {
      "type": "object",
      "properties": {
        "scan_type": {"type": "string", "enum": ["secrets", "dependencies", "config", "all"], "default": "all"},
        "output_format": {"type": "string", "enum": ["json", "markdown"], "default": "json"}
      },
      "required": ["scan_type"]
    }
  }
}
```

#### `check_vulnerabilities`
```json
{
  "type": "function",
  "function": {
    "name": "devsecops_check_vulnerabilities",
    "description": "Check Docker images and LocalStack resources for known vulnerabilities",
    "parameters": {
      "type": "object",
      "properties": {
        "target": {"type": "string", "enum": ["docker_images", "localstack", "all"], "default": "all"}
      },
      "required": ["target"]
    }
  }
}
```

#### `trigger_pipeline`
```json
{
  "type": "function",
  "function": {
    "name": "devsecops_trigger_pipeline",
    "description": "Trigger an infrastructure verification pipeline",
    "parameters": {
      "type": "object",
      "properties": {
        "pipeline": {"type": "string", "enum": ["e2e", "lint", "build", "all"], "default": "e2e"}
      },
      "required": ["pipeline"]
    }
  }
}
```

## 3. REST API Contracts

### 3.1 Endpoints

#### `GET /api/v1/skills`
List active skills and their capabilities.

**Response 200:**
```json
{
  "skills": [
    {
      "name": "skill-obsidian",
      "version": "1.0.0",
      "permissions": ["read_vault", "write_vault"],
      "tools": [
        {"name": "obsidian_create_note", "description": "Create a new Markdown note"},
        {"name": "obsidian_search_vault", "description": "Full-text search across vault notes"},
        {"name": "obsidian_append_to_note", "description": "Append content to an existing note"}
      ]
    }
  ]
}
```

#### `POST /api/v1/skills/{skill_name}/execute`
Unified skill execution endpoint.

**Request:**
```json
{
  "operation": "obsidian_create_note",
  "parameters": {
    "path": "notes/meeting.md",
    "title": "Daily Standup",
    "content": "# Meeting notes..."
  },
  "context": {
    "user_id": "default",
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

**Response 200:**
```json
{
  "status": "success",
  "skill": "skill-obsidian",
  "operation": "obsidian_create_note",
  "result": {
    "path": "notes/meeting.md",
    "created": true,
    "timestamp": "2026-08-11T10:45:00Z"
  }
}
```

**Response 500:**
```json
{
  "status": "error",
  "skill": "skill-obsidian",
  "operation": "obsidian_create_note",
  "message": "Permission denied: write_vault required"
}
```

#### `GET /api/v1/skills/{skill_name}/health`
Health check for a specific skill plugin and its external dependencies.

**Response 200:**
```json
{
  "skill": "skill-obsidian",
  "status": "healthy",
  "dependencies": {
    "vault_path": {"status": "ok", "path": "/Users/statick/dev/jarvis-os/vault"},
    "disk_space": {"status": "ok", "free_gb": 120.5}
  }
}
```

### 3.2 Sequence Diagrams

#### Skill Execution Flow
```
Client → Orchestrator: POST /api/v1/skills/{skill}/execute
Orchestrator → Registry: get(skill_name)
Registry → Skill: validate_permission(operation)
Skill → Orchestrator: permission granted
Orchestrator → Skill: execute(operation, parameters, context)
Skill → Orchestrator: {status, result}
Orchestrator → Client: 200 OK / 500 Error
```

#### Skill Autodiscovery Flow
```
Orchestrator → Registry: discover_and_load(skills_dir)
Registry → FS: scan plugin.py files
FS → Registry: module paths
Registry → Module: import + instantiate skill classes
Module → Registry: skill instances
Registry → Orchestrator: registered skills list
```

## 4. Permission Matrix

| Skill | Permission | Description |
|-------|------------|-------------|
| `skill-obsidian` | `read_vault` | Read any note in `vault/` |
| `skill-obsidian` | `write_vault` | Create/update/delete notes in `vault/` |
| `skill-os-control` | `read_metrics` | Read CPU, RAM, disk metrics |
| `skill-os-control` | `execute_commands` | Run whitelisted system commands |
| `skill-devsecops` | `manage_localstack` | S3/DynamoDB/SQS operations |
| `skill-devsecops` | `manage_docker` | Container/image/volume queries and management |

## 5. Error Handling and Timeouts

- Global skill execution timeout: 30s default, max 300s per request
- Skill-level timeout override via `context["timeout"]`
- On timeout: return `{"status": "error", "code": "TIMEOUT", "message": "..."}`
- On permission denied: return `{"status": "error", "code": "PERMISSION_DENIED", "message": "..."}`
- On invalid parameters: return `{"status": "error", "code": "INVALID_PARAMETERS", "message": "..."}`
- All errors include a correlation ID for audit logging

## 6. Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Plugin loading | `importlib` + directory scan | No external plugin framework dependency |
| Schema validation | Pydantic v2 | Already used in project |
| Async execution | `asyncio` + `asyncio.create_task` | Matches FastAPI async patterns |
| Command sandbox | `asyncio.create_subprocess_exec` | Secure, non-shell execution |
| Metrics collection | `psutil` | Cross-platform, lightweight |
| LocalStack client | `boto3` with endpoint override | Standard AWS SDK |
| Docker client | `docker-py` | Official Python SDK |

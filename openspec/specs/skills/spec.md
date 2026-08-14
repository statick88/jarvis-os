# Delta Spec — Expansión de Skills (jarvis-skills-expansion)

## ADDED Requirements

### RF-SKILL-01: Obsidian Vault CRUD
The system MUST support creating, reading, updating, and deleting Markdown notes in the local Obsidian vault via structured API calls.

### RF-SKILL-02: Obsidian Search and Summarization
The system MUST support full-text search across vault notes and automatic summarization of note contents through the voice/text interface.

### RF-SKILL-03: macOS Resource Monitoring
The system MUST expose real-time CPU, RAM, and disk usage metrics from the host macOS system through the orchestrator API.

### RF-SKILL-04: Controlled Command Execution
The system MUST allow execution of whitelisted macOS commands and scripts through a sandboxed interface with audit logging.

### RF-SKILL-05: LocalStack Automation
The system MUST provide programmatic access to LocalStack S3, DynamoDB, and SQS operations through dedicated skill endpoints.

### RF-SKILL-06: Docker Infrastructure Management
The system MUST support querying and managing Docker containers, images, and volumes through the DevSecOps skill with safety guards.

## MODIFIED Requirements

None.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

### RF-SKILL-07: Unified Skills Execution
The system MUST use a single canonical execution path for skills, eliminating duplicated plugin architectures.

### RF-SKILL-08: Real System Metrics
The system MUST expose real CPU, RAM, and disk metrics from the host macOS system via `psutil`, without runtime dependency failures.

### RF-SKILL-09: Note Summarization
The system MUST support automatic summarization of Obsidian vault note contents through the Obsidian skill.

### RF-SKILL-10: Real LocalStack Client
The system MUST provide programmatic access to LocalStack S3, DynamoDB, and SQS using real AWS SDK clients with endpoint override.

### RF-SKILL-11: Real Docker Client
The system MUST provide Docker container/image/volume management using the official Docker SDK.

### RF-SKILL-12: E2E Coverage for Skills API
The system MUST include end-to-end test coverage for all `/api/v1/skills/*` endpoints in the pipeline test suite.

### RF-SKILL-13: Path Containment
The system MUST prevent path traversal in obsidian skill handlers by validating that resolved note paths remain inside the configured vault root.

### RF-SKILL-14: Canonical Operation Routing
The system MUST forward the requested operation through the canonical `SkillExecutor` path so `/api/v1/skills/{skill}/execute` honors the `operation` field.

### RF-SKILL-15: Nonblocking Metrics
The system MUST avoid blocking the FastAPI event loop inside async skill handlers; `psutil.cpu_percent` must run in a threadpool executor or use a nonblocking interval.

### RF-SKILL-16: Valid YAML Frontmatter
The system MUST serialize obsidian frontmatter tags as valid YAML so Obsidian parses them correctly.

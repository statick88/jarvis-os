# Delta Spec — Refactor y Cierre de Skills (jarvis-skills-refactor)

## ADDED Requirements

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

## MODIFIED Requirements

None.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

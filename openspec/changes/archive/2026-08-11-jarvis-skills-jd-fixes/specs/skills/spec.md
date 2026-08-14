# Delta Spec — JD Critical Fixes for Skills (jarvis-skills-jd-fixes)

## ADDED Requirements

### RF-SKILL-13: Path Containment
The system MUST prevent path traversal in obsidian skill handlers by validating that resolved note paths remain inside the configured vault root.

### RF-SKILL-14: Canonical Operation Routing
The system MUST forward the requested operation through the canonical `SkillExecutor` path so `/api/v1/skills/{skill}/execute` honors the `operation` field.

### RF-SKILL-15: Nonblocking Metrics
The system MUST avoid blocking the FastAPI event loop inside async skill handlers; `psutil.cpu_percent` must run in a threadpool executor or use a nonblocking interval.

### RF-SKILL-16: Valid YAML Frontmatter
The system MUST serialize obsidian frontmatter tags as valid YAML so Obsidian parses them correctly.

## MODIFIED Requirements

None.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

# Spec — Orchestrator Pipeline

## ADDED Requirements

### RF-ORCH-01: Intent Analysis
The system MUST classify user intent using rule-based keyword matching and pattern rules, without LLM dependency.

**Scenarios:**
- Given "create a note", the analyzer returns intent `obsidian.create` with confidence >= 0.8
- Given unrecognized input, the analyzer returns intent `unknown` with confidence 0.0

### RF-ORCH-02: Skill Resolution
The system MUST resolve the best matching skill by querying SkillRegistry capabilities, falling back to full-text search across skill names and descriptions.

**Scenarios:**
- Given intent `obsidian.create` and skill.obsidian exposing that capability, the resolver returns skill.obsidian with confidence 1.0
- Given no capability match, the resolver returns the highest-relevance skill by keyword overlap, or empty list

### RF-ORCH-03: Skill Composition
The system MUST support sequential execution of skills in a defined order, where each skill's output is merged into the next skill's input, stopping on first failure.

**Scenarios:**
- Given chain [skill.plan, skill.obsidian], skill.obsidian receives input merged with skill.plan output
- Given a chain where the first skill returns FAILED, the chain halts immediately

### RF-ORCH-04: Response Formatting
The system MUST format results into a consistent envelope: `{id, timestamp, type, payload}` where payload includes `success` and either `result` or `error`.

**Scenarios:**
- Given a successful execution, the envelope contains `payload.success=true` and `payload.result`
- Given a failed execution, the envelope contains `payload.success=false` and `payload.error`

### RF-ORCH-05: SkillExecutor Integration
The orchestrator MUST delegate execution to the existing SkillExecutor, preserving its timeout, retry, and sandbox configuration.

**Scenarios:**
- Given a skill with timeout=10s and retries=2, SkillExecutor enforces these values unchanged

### RF-ORCH-06: Backward Compatibility
The system MUST keep all existing `/api/v1/skills/*` endpoints fully functional and unchanged.

**Scenarios:**
- Given a client calling `POST /api/v1/skills/{name}/execute`, the endpoint returns the same response format independent of the new pipeline

## MODIFIED Requirements

None.

## REMOVED Requirements

None.

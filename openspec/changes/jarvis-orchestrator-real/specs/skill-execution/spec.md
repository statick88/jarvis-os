# Delta Spec — Skill Execution Enhancement (jarvis-orchestrator-real)

## ADDED Requirements

### RF-SKILL-17: Skill Composition
The system MUST support sequential execution of skills in a defined order, merging each output into the next input, and halting on first failure.

(Previously: No composition support existed.)

**Scenarios:**
- Given chain [A, B] with A output `{"topic": "meeting"}`, B receives merged input
- Given A returns FAILED, the chain halts immediately

### RF-SKILL-18: Execution Metrics
The system MUST record duration_ms, status, and skill_id per execution, exposing aggregated metrics (total_executions, success_rate, avg_duration_ms).

**Scenarios:**
- Given 5 executions (3 success, 2 failure), metrics show total=5, rate=0.6, avg=<mean>

## MODIFIED Requirements

### RF-SKILL-07: Unified Skills Execution
The system MUST use a single canonical execution path for skills, eliminating duplicated plugin architectures. The canonical path MUST return structured errors with HTTP status codes: 400 for validation failures, 404 for missing skills, 422 for execution failures, and 500 for unexpected errors.

(Previously: The system MUST use a single canonical execution path for skills, eliminating duplicated plugin architectures.)

**Scenarios:**
- Invalid input returns HTTP 400. Missing skill returns HTTP 404. Handler exception returns HTTP 422.

## REMOVED Requirements

None.

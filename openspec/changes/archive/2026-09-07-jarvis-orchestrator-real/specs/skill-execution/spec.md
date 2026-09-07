# Delta Spec — Skill Execution Enhancement (jarvis-orchestrator-real)

## Requirements

### REQ-17: Skill Composition
The system MUST support sequential execution of skills in a defined order, merging each output into the next input, and halting on first failure.

#### Scenario: Chain passes output forward
Given chain [A, B] with A output `{"topic": "meeting"}`, B receives merged input

#### Scenario: Chain halts on failure
Given A returns FAILED, the chain halts immediately

### REQ-18: Execution Metrics
The system MUST record duration_ms, status, and skill_id per execution, exposing aggregated metrics (total_executions, success_rate, avg_duration_ms).

#### Scenario: Metrics aggregation
Given 5 executions (3 success, 2 failure), metrics show total=5, rate=0.6, avg=<mean>

### REQ-07: Unified Skills Execution
The system MUST use a single canonical execution path for skills, eliminating duplicated plugin architectures. The canonical path MUST return structured errors with HTTP status codes: 400 for validation failures, 404 for missing skills, 422 for execution failures, and 500 for unexpected errors.

#### Scenario: Error status codes
Invalid input returns HTTP 400. Missing skill returns HTTP 404. Handler exception returns HTTP 422.

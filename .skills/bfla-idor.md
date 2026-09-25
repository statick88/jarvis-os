---
id: "skill-bfla_idor"
name: "BFLA IDOR Testing"
version: "1.0.0"
description: "Enumerate API endpoints and test BFLA/IDOR authorization boundaries with local finding persistence"
author: "jarvis-os team"
license: "MIT"
capabilities:
  - "security.enumerate_endpoints"
  - "security.test_bfla"
  - "security.test_idor"
  - "security.list_findings"
  - "security.get_confirmed"
  - "security.mark_confirmed"
input_schema:
  type: "object"
  properties:
    action:
      type: "string"
      enum: ["enumerate_endpoints", "test_bfla", "test_idor", "list_findings", "get_confirmed", "mark_confirmed"]
      description: "Action to execute"
    operation:
      type: "string"
      description: "Alias for action"
    endpoint:
      type: "string"
      description: "Target endpoint path for BFLA/IDOR probes"
    method:
      type: "string"
      enum: ["GET", "POST", "PUT", "DELETE", "PATCH"]
      default: "GET"
      description: "HTTP method under test"
    lower_privilege_role:
      type: "string"
      enum: ["SuperAdmin", "BusinessAdmin", "Staff", "Medical", "Fundraiser", "User"]
      description: "Role used for the lower-privilege probe"
    target_object:
      type: "string"
      description: "Object reference name for IDOR testing"
    reference_locations:
      type: "array"
      items:
        type: "string"
      description: "IDOR reference locations to probe"
    include_internal:
      type: "boolean"
      default: false
      description: "Include internal/admin endpoints during enumeration"
    method_switching:
      type: "boolean"
      default: true
      description: "Probe alternate HTTP methods during BFLA testing"
    path_confusion:
      type: "boolean"
      default: true
      description: "Probe trailing-slash path variants during BFLA testing"
    finding_id:
      type: "string"
      description: "Finding id to mark as confirmed"
    context:
      type: "object"
      description: "Runtime context (findings_path, vault_path, session ids)"
  required:
    - action
output_schema:
  type: "object"
  properties:
    success:
      type: "boolean"
    data:
      type: "object"
    error:
      type: "string"
execution:
  timeout_seconds: 60
  memory_limit_mb: 256
  cpu_limit_percent: 50
  sandbox: true
  retries: 0
  retry_backoff_ms: 1000
execution_type: "python"
entrypoint: "bffla_idor"
---

# BFLA IDOR Testing

Tests API Business Logic Field Level Authorization (BFLA) and Insecure Direct
Object Reference (IDOR) against role-gated endpoints, then persists findings in
a local JSON store for cross-session recovery.

## Actions

- `enumerate_endpoints`: list FastAPI routes grouped by role
- `test_bfla`: probe an endpoint with a lower-privilege role (method switching, path confusion)
- `test_idor`: probe object references across URL, query, body, header, and cookie locations
- `list_findings`: list findings persisted in the local store
- `get_confirmed`: return confirmed finding ids (seeded F01–F22 plus local store)
- `mark_confirmed`: mark a finding confirmed so it is not re-tested

## Usage

```bash
PYTHONPATH=. python3 -c "from jarvis_os.skills.handlers.bffla_idor import run; print(run({'action': 'list_findings', 'context': {'findings_path': '.state/bfla_idor_findings.json'}}))"
```

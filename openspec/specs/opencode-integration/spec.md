# Spec — OpenCode Integration

## ADDED Requirements

### RF-OPEN-01: OpenCodeClient Integration
The system MUST route code execution requests to OpenCodeClient as backend.

**Scenarios:**
- Given `code.execute` intent with no local skill match, invokes `execute_skill()`
- Given OpenCode unavailable, returns structured backend-unavailable error

### RF-OPEN-02: Transport Priority
The system MUST attempt WebSocket first, falling back to HTTP on failure using OpenCodeClient's built-in mechanism.

**Scenarios:**
- Active WebSocket carries requests. Dropped WebSocket triggers HTTP fallback automatically.

### RF-OPEN-03: Correlation
The system MUST correlate responses to requests via envelope ID.

**Scenarios:**
- Given concurrent requests A and B arriving out of order, each response matches the correct pending request by ID.

### RF-OPEN-04: Timeout and Retry
The system MUST apply configurable timeouts and retry failed requests up to the configured maximum.

**Scenarios:**
- Given timeout=30s, no response within 30s fails. Given 1 retry allowed on transient error, request retries once.

### RF-OPEN-05: Graceful Degradation
The system MUST return structured errors when OpenCode is unavailable, without crashing or blocking the pipeline.

**Scenarios:**
- Given OpenCode unreachable after all attempts, returns error and continues processing other requests.

## MODIFIED Requirements

None.

## REMOVED Requirements

None.

# ADR 001: Repository Structure — Polyrepo with Shared Contracts

## Status
Accepted

## Context
JARVIS-OS needs clear separation between:
- **Server** (backend API, frontend dashboard, databases)
- **Mobile Client** (Flutter app consuming via Tailscale)
- **Shared Contracts** (OpenAPI types, DTOs, error codes)

## Decision
Use **polyrepo** with three repositories:
1. `jarvis-server` — Backend + Frontend + Infrastructure
2. `jarvis-mobile` — Flutter mobile client
3. `jarvis-contracts` — Shared OpenAPI spec, TypeScript/Dart types, error codes

## Rationale
- **Independent deployments**: Server and mobile have different release cycles
- **Team autonomy**: Backend, frontend, mobile teams can work independently
- **Security**: Mobile repo never contains server secrets or database logic
- **CI/CD isolation**: Separate pipelines, no cross-contamination
- **Contract-first**: `jarvis-contracts` is the source of truth for API types

## Consequences
- Need contract publishing workflow (npm/pub packages)
- Version synchronization via semantic versioning
- Slight overhead in managing three repos

## Related
- ADR 002: Server Architecture
- ADR 003: Mobile Client Architecture
- ADR 004: Tailscale Network Design
# ADR 002: Server Architecture — Clean Architecture with FastAPI + React

## Status
Accepted

## Context
Server must provide:
- **Backend API**: Orchestrator, Skills, Vault, HUD, Voice, Nightly
- **Frontend Dashboard**: Real-time HUD, Skills management, Vault browser, Voice sessions, Nightly reports
- **Databases**: PostgreSQL (primary), Redis (cache/sessions), Vector DB (future)

## Decision
**Backend**: FastAPI with Clean Architecture
```
jarvis-server/
├── backend/
│   ├── src/
│   │   ├── domain/           # Entities, value objects, domain events
│   │   ├── application/      # Use cases, DTOs, ports (interfaces)
│   │   ├── infrastructure/   # Adapters: DB, HTTP, WebSocket, external APIs
│   │   │   ├── database/     # SQLAlchemy models, repositories, migrations
│   │   │   ├── cache/        # Redis client, session store
│   │   │   ├── http/         # FastAPI routes, middleware, dependencies
│   │   │   ├── websocket/    # HUD WebSocket server
│   │   │   ├── voice/        # Voice bridge client
│   │   │   └── external/     # OpenCode, Tailscale, etc.
│   │   └── presentation/     # FastAPI app, dependency injection
│   ├── tests/
│   │   ├── unit/             # Domain + application logic
│   │   ├── integration/      # DB, external APIs, full stack
│   │   └── contract/         # Pact consumer tests
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── docker-compose.yml
```

**Frontend**: React + TypeScript + Vite
```
jarvis-server/
├── frontend/
│   ├── src/
│   │   ├── features/         # Feature-based modules
│   │   │   ├── skills/       # Skills CRUD, execution
│   │   │   ├── vault/        # Vault browser, outputs
│   │   │   ├── hud/          # Real-time HUD WebSocket
│   │   │   ├── voice/        # Voice session management
│   │   │   ├── nightly/      # Nightly reports, scheduler
│   │   │   └── settings/     # Configuration, Tailscale status
│   │   ├── shared/           # UI components, hooks, utilities
│   │   │   ├── components/   # Design system (shadcn/ui + Tailwind)
│   │   │   ├── hooks/        # React Query, WebSocket, auth
│   │   │   └── types/        # Generated from jarvis-contracts
│   │   ├── app/              # Routing, providers, layout
│   │   └── main.tsx
│   ├── tests/
│   │   ├── unit/             # Component tests (Vitest + RTL)
│   │   ├── integration/      # Feature flows
│   │   └── e2e/              # Playwright
│   ├── package.json
│   ├── Dockerfile
│   └── docker-compose.yml
```

**Databases**:
- **PostgreSQL** (primary): SQLAlchemy 2.0 + Alembic migrations
  - Tables: skills, executions, vault_outputs, nightly_reports, users, sessions
- **Redis**: Session store, rate limiting, cache, Celery broker
- **Vector DB** (future): pgvector or Qdrant for embeddings

**Authentication & Authorization**:
- **JWT** (RS256) for API access
- **mTLS via Tailscale** for mobile client (certificate-based identity)
- **Role-based access**: Admin, Operator, Viewer
- **Tailscale ACL** integration for network-level authorization

**Real-time**:
- **WebSocket** (FastAPI native): HUD events, skill execution updates
- **Server-Sent Events**: Voice session streaming, nightly progress
- **WebRTC** (future): Direct voice streaming

## Rationale
- **Clean Architecture**: Testable, maintainable, framework-agnostic domain
- **FastAPI**: High performance, OpenAPI native, async support
- **React + TypeScript**: Type safety, ecosystem, developer experience
- **PostgreSQL + Redis**: Proven, scalable, ACID + caching
- **Contract-first**: OpenAPI spec drives both backend and frontend types

## Consequences
- Requires OpenAPI generation and type sharing via `jarvis-contracts`
- Frontend-backend contract testing via Pact
- Database migrations must be backward-compatible

## Related
- ADR 001: Repository Structure
- ADR 003: Mobile Client Architecture
- ADR 004: Tailscale Network Design
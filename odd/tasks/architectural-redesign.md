# Feature: Architectural Redesign - Server + Mobile Client

## Objective
Redefine JARVIS-OS architecture with clear separation of concerns:
- **Server**: Backend API, Frontend Dashboard, Databases
- **Mobile Client**: Secure consumer via Tailscale mesh
- **Quality**: Comprehensive testing (unit, integration, e2e, functional) + SonarQube in CI

## Problem / Why
Current jarvis-os is a monolithic orchestrator with mixed concerns. Need:
1. **Clear boundaries**: Server vs Client, Back vs Front, Data vs Logic
2. **Security**: Mobile client consumes API via Tailscale (no public exposure)
3. **Quality gates**: SonarQube in GitHub Actions, high test coverage
4. **Scalability**: Independent deployments, separate repositories

## Authorized Scope
- New repository structure (monorepo or polyrepo)
- Server architecture definition
- Mobile client architecture definition
- Tailscale integration design
- Testing strategy and CI/CD pipeline
- SonarQube GitHub Actions integration

## Constraints
- **Security**: Zero-trust, mobile only via Tailscale, no public endpoints for client APIs
- **Quality**: ≥80% unit coverage, ≥60% integration, SonarQube Quality Gate passing
- **Standards**: Conventional Commits, work-unit commits, RDD review per slice
- **Tech**: Python/FastAPI backend, React/TypeScript frontend, PostgreSQL + Redis, Flutter/Dart mobile
- **Testing**: Unit, integration, e2e, functional, contract tests

## Actionable Checklist

### Phase 1: Architecture Definition
- [ ] T1.1 — Define repository structure (monorepo vs polyrepo decision)
- [ ] T1.2 — Server architecture: Backend (FastAPI), Frontend (React), Databases (PostgreSQL, Redis)
- [ ] T1.3 — Mobile client architecture: Flutter, Tailscale integration, API client
- [ ] T1.4 — API contracts (OpenAPI), authentication (JWT + mTLS via Tailscale)
- [ ] T1.5 — Infrastructure: Docker Compose (dev), Kubernetes (prod), Tailscale subnet router

### Phase 2: Repository Setup
- [ ] T2.1 — Create server repository structure
- [ ] T2.2 — Create mobile client repository structure
- [ ] T2.3 — Shared contracts/packages (OpenAPI types, DTOs)
- [ ] T2.4 — Configure GitHub Actions workflows for each repo

### Phase 3: Backend Implementation
- [ ] T3.1 — FastAPI project with clean architecture (domain, application, infrastructure)
- [ ] T3.2 — PostgreSQL models (SQLAlchemy), Redis cache, migrations (Alembic)
- [ ] T3.3 — Authentication: JWT + mTLS, Tailscale ACL integration
- [ ] T3.4 — API endpoints: orchestrator, skills, vault, HUD, voice
- [ ] T3.5 — Unit tests (≥80%), integration tests (≥60%)

### Phase 4: Frontend Implementation
- [ ] T4.1 — React + TypeScript + Vite project
- [ ] T4.2 — Dashboard: skills, vault, HUD, nightly reports, voice sessions
- [ ] T4.3 — Real-time: WebSocket for HUD, Server-Sent Events for voice
- [ ] T4.4 — Component library, design system, accessibility (WCAG 2.1 AA)

### Phase 5: Mobile Client Implementation
- [ ] T5.1 — Flutter project with clean architecture
- [ ] T5.2 — Tailscale integration (tsnet, tailscale-client)
- [ ] T5.3 — API client with auto-retry, offline queue, certificate pinning
- [ ] T5.4 — Voice integration (STT/TTS), HUD WebSocket consumer
- [ ] T5.5 — Unit/widget/integration tests, golden tests

### Phase 6: Testing & Quality
- [ ] T6.1 — Contract tests (Pact) between mobile/client and server
- [ ] T6.2 — E2E tests: Playwright (web), Patrol (mobile)
- [ ] T6.3 — Functional tests: critical user journeys
- [ ] T6.4 — Performance/load tests (k6)
- [ ] T6.5 — SonarQube Quality Gates in GitHub Actions

### Phase 7: CI/CD & Deployment
- [ ] T7.1 — GitHub Actions: lint, test, build, SonarQube, docker build
- [ ] T7.2 — Staging deployment (dev Tailscale network)
- [ ] T7.3 — Production deployment (K8s, Tailscale subnet router)
- [ ] T7.4 — Observability: logs, metrics, traces (OpenTelemetry)

## Acceptance Criteria
- Server and mobile client in separate repositories (or clear monorepo boundaries)
- Mobile client ONLY communicates via Tailscale (verified by network tests)
- All CI pipelines pass: lint, type-check, unit, integration, e2e, SonarQube
- SonarQube Quality Gate: 0 bugs, 0 vulnerabilities, coverage ≥80%, duplication <3%
- Mobile app builds for iOS/Android, Tailscale connection verified in CI
- Documentation: architecture diagrams, API docs, deployment guides

## Verification Commands
```bash
# Server
cd server && make test && make lint && make sonarqube

# Mobile
cd mobile && flutter test && flutter analyze && make sonarqube

# Integration
cd server && docker compose up -d && cd ../mobile && make integration-test
```

## Route Declaration
| Task | Route | Trigger evidence |
|------|-------|------------------|
| T1.1–T1.5 | delegated direct | Architecture decision, requires research |
| T2.1–T2.4 | delegated direct | Repo scaffolding, mechanical |
| T3.1–T3.5 | sdd (optional) | Substantial backend, may use SDD |
| T4.1–T4.4 | sdd (optional) | Substantial frontend |
| T5.1–T5.5 | sdd (optional) | Substantial mobile |
| T6.1–T6.5 | delegated direct | Test setup, configuration |
| T7.1–T7.4 | delegated direct | CI/CD configuration |

## Progress / Evidence
- [ ] Architecture decision documented (ADR)
- [ ] Repositories created and configured
- [ ] CI pipelines green
- [ ] SonarQube Quality Gates passing

## Rationale
Follows ODD protocol: explore → resolve uncertainty → track before write → implement task by task. Each phase creates work-unit commits with tests and docs. RDD review per slice via GitHub Actions + SonarQube.
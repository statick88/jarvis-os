# Development Workflows & Responsibilities — JARVIS-OS

## Repository Structure (Polyrepo)

```
statick88/
├── jarvis-contracts/          # Shared OpenAPI spec + generated types
│   ├── openapi.yaml           # Single source of truth
│   ├── package.json           # npm package: @jarvis/contracts
│   ├── pubspec.yaml           # Dart package: jarvis_contracts
│   └── .github/workflows/     # Contract publishing
│
├── jarvis-server/             # Backend + Frontend + Infra
│   ├── backend/               # FastAPI (Python)
│   ├── frontend/              # React + TypeScript
│   ├── infra/                 # Docker, K8s, Terraform
│   └── .github/workflows/     # CI/CD + SonarQube
│
└── jarvis-mobile/             # Flutter Mobile Client
    ├── lib/                   # Dart source
    ├── integration_test/      # Patrol e2e
    └── .github/workflows/     # CI/CD + SonarQube + Tailscale
```

---

## Branching Strategy (GitFlow Light)

```
main ────────────────────────────────────────────►
  │                    ▲
  │                    │ hotfix/*
  │                    │
develop ────────────────────────────────────────►
  │           │           │           │
  │        feature/*  feature/*   feature/*
  │           │           │           │
  └───────────┴───────────┴───────────┘
              │
           release/vX.Y.Z
              │
              ▼
            main (tag)
```

### Branch Rules
| Branch | Protection | Deploy |
|--------|------------|--------|
| `main` | Required reviews (2), CI pass, linear history | Production (tagged) |
| `develop` | Required reviews (1), CI pass | Staging |
| `feature/*` | CI pass | Preview (optional) |
| `release/*` | CI pass, no new features | Staging → Production |
| `hotfix/*` | CI pass, 1 review | Production (urgent) |

---

## Work-Unit Commits (Conventional Commits)

**Every commit must be a reviewable work unit:**

```bash
# Good: Single logical change with tests
feat(backend): add skill execution endpoint with vault logging

- Add POST /api/v1/execute endpoint
- Integrate VaultOutputLogger for persistence
- Emit SkillExecutionComplete + VaultWriteEvent
- Unit tests: 95% coverage
- Integration test: full flow

# Good: Refactor with tests
refactor(mobile): extract TailscaleClient for testability

- Create TailscaleClient interface
- Implement TsNetClient and MockTailscaleClient
- Update ApiClient to use dependency injection
- Widget tests updated

# Bad: Mixed changes, no tests
fix stuff and add feature
```

### Commit Message Format
```
<type>(<scope>): <subject>

<body>

<footer>
```

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code restructuring |
| `style` | Formatting only |
| `docs` | Documentation |
| `test` | Test changes |
| `chore` | Build/deps/maintenance |
| `perf` | Performance |
| `security` | Security fix |

### Scopes
| Scope | Repository |
|-------|------------|
| `backend` | jarvis-server/backend |
| `frontend` | jarvis-server/frontend |
| `mobile` | jarvis-mobile |
| `infra` | jarvis-server/infra |
| `contracts` | jarvis-contracts |
| `ci` | Any (GitHub Actions) |

---

## Pull Request Template

```markdown
## Description
<!-- What and why -->

## Type
- [ ] feat  - New feature
- [ ] fix   - Bug fix
- [ ] refactor - Code restructuring
- [ ] docs  - Documentation
- [ ] test  - Tests only
- [ ] chore - Maintenance

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Widget/Component tests added/updated
- [ ] E2E tests added/updated
- [ ] Contract tests updated (Pact)
- [ ] Manual testing performed

## Quality Gates
- [ ] All CI checks pass
- [ ] SonarQube Quality Gate passes
- [ ] Coverage thresholds met
- [ ] No new security vulnerabilities

## Breaking Changes
<!-- Any API/contract changes? -->

## Checklist
- [ ] Conventional commits used
- [ ] Work-unit commits (1 logical change per commit)
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] CHANGELOG updated (if user-facing)
```

---

## Code Review Guidelines

### Reviewer Responsibilities
1. **Architecture**: Does it follow Clean Architecture / Clean Architecture?
2. **Tests**: Are tests meaningful? Do they test behavior, not implementation?
3. **Security**: No secrets, proper auth, input validation, certificate pinning
4. **Performance**: No N+1 queries, efficient algorithms, proper caching
5. **Maintainability**: Clear naming, small functions, SOLID principles
6. **Contracts**: OpenAPI spec updated? Pact tests pass?

### Review Checklist
```markdown
## Code Review
- [ ] Logic correct and complete
- [ ] Error handling comprehensive
- [ ] No hardcoded secrets/credentials
- [ ] Input validation on all endpoints
- [ ] Proper logging (structured, no PII)
- [ ] Database migrations backward-compatible
- [ ] API changes reflected in OpenAPI spec
- [ ] Pact consumer/provider tests updated
- [ ] Mobile certificate pinning considered
```

### Approval Requirements
| Repo | Minimum Approvals | Required Reviewers |
|------|-------------------|-------------------|
| `jarvis-contracts` | 2 | 1 backend + 1 frontend/mobile |
| `jarvis-server/backend` | 2 | 1 backend lead |
| `jarvis-server/frontend` | 2 | 1 frontend lead |
| `jarvis-mobile` | 2 | 1 mobile lead + 1 security review |

---

## Development Workflow (Per Feature)

### 1. Start Feature
```bash
# From develop
git checkout develop
git pull origin develop
git checkout -b feature/JARVIS-123-add-voice-session-replay
```

### 2. Develop with Work-Unit Commits
```bash
# Each logical change = 1 commit
git add -p
git commit -m "feat(backend): add voice session replay endpoint

- Add GET /api/v1/voice/sessions/{id}/replay
- Return WebSocket URL for replay stream
- Unit tests: 92% coverage"
```

### 3. Push + CI
```bash
git push origin feature/JARVIS-123-add-voice-session-replay
# GitHub Actions runs: lint, unit, integration, contract, sonarqube
```

### 4. Create PR
```bash
gh pr create --base develop --title "feat(backend): voice session replay"
# Fill PR template
```

### 5. Review + Iterate
```bash
# Address review comments as new commits
git add -p
git commit -m "fix(backend): handle missing session in replay

- Return 404 with proper error envelope
- Add integration test for missing session"
git push
```

### 6. Merge
```bash
# After approvals + CI pass
gh pr merge --squash --delete-branch
# Or: gh pr merge --rebase --delete-branch
```

### 7. Sync
```bash
git checkout develop
git pull origin develop
git branch -d feature/JARVIS-123-add-voice-session-replay
```

---

## Release Workflow

### 1. Release Branch
```bash
git checkout develop
git pull origin develop
git checkout -b release/v1.2.0
# Version bump in pyproject.toml, package.json, pubspec.yaml
git commit -m "chore(release): v1.2.0"
git push origin release/v1.2.0
```

### 2. Release PR
```bash
gh pr create --base main --title "release: v1.2.0"
# Full CI runs on main
```

### 3. Tag + Release
```bash
# After merge to main
git checkout main
git pull origin main
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0
# GitHub Actions: build artifacts, create release, deploy production
```

### 4. Hotfix
```bash
git checkout main
git checkout -b hotfix/v1.2.1-fix-voice-crash
# Fix + test
git commit -m "fix(mobile): prevent crash on voice session timeout

- Add null check for session_id
- Widget test for timeout scenario"
gh pr create --base main --title "hotfix: voice session timeout crash"
# Merge to main + backport to develop
```

---

## Responsibility Matrix (RACI)

| Activity | Backend Lead | Frontend Lead | Mobile Lead | DevOps | Security |
|-----------|--------------|---------------|-------------|--------|----------|
| **Architecture Decisions** | R/A | C | C | I | C |
| **API Design (OpenAPI)** | R/A | C | C | I | C |
| **Backend Implementation** | R/A | I | I | C | C |
| **Frontend Implementation** | C | R/A | I | I | C |
| **Mobile Implementation** | C | C | R/A | I | C |
| **Tailscale Integration** | C | I | R/A | R | A |
| **Database Migrations** | R/A | I | I | C | C |
| **CI/CD Pipelines** | C | C | C | R/A | C |
| **SonarQube Config** | C | C | C | R | A |
| **Security Review** | C | C | C | C | R/A |
| **Release Management** | R | R | R | A | I |
| **Incident Response** | R | R | R | A | C |

**Legend**: R=Responsible, A=Accountable, C=Consulted, I=Informed

---

## Definition of Done (Per Work Unit)

A work unit (commit/PR) is **Done** when:

- [ ] Code compiles + passes static analysis
- [ ] Unit tests pass + coverage threshold met
- [ ] Integration tests pass (if applicable)
- [ ] Widget/Component tests pass (if applicable)
- [ ] Contract tests pass (if API changed)
- [ ] E2E tests pass (if user-facing)
- [ ] SonarQube Quality Gate passes
- [ ] No new security vulnerabilities
- [ ] Documentation updated (README, OpenAPI, CHANGELOG)
- [ ] Peer review approved (minimum required)
- [ ] Merged to target branch

---

## Incident Response (Production)

### Severity Levels
| Level | Response Time | Escalation |
|-------|---------------|------------|
| **SEV-1** (Outage) | 15 min | DevOps + Leads + Security |
| **SEV-2** (Degraded) | 30 min | DevOps + Relevant Lead |
| **SEV-3** (Minor) | 2 hours | Relevant Lead |
| **SEV-4** (Cosmetic) | Next sprint | Assignee |

### Runbook Location
```
jarvis-server/infra/runbooks/
├── sev1-database-down.md
├── sev1-api-unavailable.md
├── sev2-high-latency.md
├── sev2-tailscale-disconnect.md
└── sev3-*.md
```

---

## Tooling Standards

| Category | Tool | Version |
|----------|------|---------|
| **Language (Backend)** | Python | 3.12 |
| **Language (Frontend)** | TypeScript | 5.4+ |
| **Language (Mobile)** | Dart | 3.4+ / Flutter 3.24+ |
| **Package Manager (Backend)** | pip + uv | latest |
| **Package Manager (Frontend)** | npm | 10+ |
| **Package Manager (Mobile)** | pub | Flutter 3.24+ |
| **Lint (Backend)** | ruff | 0.4+ |
| **Type Check (Backend)** | mypy | 1.10+ |
| **Lint (Frontend)** | ESLint | 8.56+ |
| **Type Check (Frontend)** | tsc | 5.4+ |
| **Analyze (Mobile)** | flutter analyze | 3.24+ |
| **Test (Backend)** | pytest | 8.2+ |
| **Test (Frontend)** | Vitest + Playwright | latest |
| **Test (Mobile)** | flutter_test + patrol | latest |
| **Contract** | Pact | latest |
| **SAST** | bandit / npm audit / flutter pub deps | latest |
| **Container Scan** | docker scan / Trivy | latest |
| **SonarQube** | SonarCloud / Self-hosted | 9.9+ |

---

## Onboarding Checklist (New Team Member)

- [ ] Access to all 3 repos + GitHub org
- [ ] Tailscale installed + authenticated
- [ ] Local dev environment: Python 3.12, Node 20, Flutter 3.24
- [ ] IDE configured: VS Code + extensions (Python, Dart, ESLint, etc.)
- [ ] Run `make dev` in each repo (starts local stack)
- [ ] Execute full test suite locally
- [ ] Create first PR (docs fix) → merge
- [ ] Pair program on first feature
- [ ] Complete security training (certificate pinning, Tailscale ACLs)
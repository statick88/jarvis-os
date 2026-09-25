# Testing Strategy — JARVIS-OS Server + Mobile

## Overview
Comprehensive testing pyramid with quality gates at each level.

```
                    ┌─────────────┐
                    │  E2E /      │  ← Few, high confidence
                    │  Functional │
                   ┌┴─────────────┴┐
                   │  Integration  │  ← Medium, API + DB
                  ┌┴────────────────┴┐
                  │  Contract        │  ← Pact consumer/provider
                 ┌┴──────────────────┴┐
                 │  Widget /          │  ← Component behavior
                 │  Component         │
                ┌┴────────────────────┴┐
                │  Unit                │  ← Many, fast, isolated
               ┌┴──────────────────────┴┐
               │  Static Analysis       │  ← Lint, type-check, SAST
              ┌┴────────────────────────┴┐
```

## Quality Gates (Non-Negotiable)

| Layer | Server (Backend) | Server (Frontend) | Mobile | Gate |
|-------|------------------|-------------------|--------|------|
| **Static** | ruff + mypy | ESLint + tsc | flutter analyze | ✅ All pass |
| **Unit** | ≥80% line coverage | ≥80% line coverage | ≥80% line coverage | ✅ Fail if < |
| **Widget** | N/A | ≥70% | ≥70% | ✅ |
| **Integration** | ≥60% | N/A | ≥60% | ✅ |
| **Contract** | Pact provider | Pact provider | Pact consumer | ✅ All pass |
| **E2E** | N/A | Playwright critical paths | Patrol critical flows | ✅ All pass |
| **SonarQube** | Quality Gate | Quality Gate | Quality Gate | ✅ Pass |

---

## 1. Static Analysis

### Backend (Python)
```bash
ruff check src tests          # Lint (fast, replaces flake8+isort+black)
mypy src                      # Type checking (strict mode)
bandit -r src                 # Security SAST
```

### Frontend (TypeScript)
```bash
npm run lint                  # ESLint (Airbnb + Prettier)
npm run type-check            # tsc --noEmit
```

### Mobile (Dart)
```bash
flutter analyze --fatal-infos --fatal-warnings
```

**CI Gate**: All must pass → PR blocked if any fail.

---

## 2. Unit Tests

### Backend
```bash
pytest tests/unit \
  --cov=src \
  --cov-report=xml \
  --cov-fail-under=80 \
  -x -v
```
- **Scope**: Domain entities, value objects, use cases, pure functions
- **No external dependencies**: Mock all ports (DB, HTTP, WebSocket, etc.)
- **Target**: ≥80% line coverage, ≥70% branch coverage

### Frontend
```bash
npm run test:unit -- --coverage --coverageThreshold='{"global":{"lines":80}}'
```
- **Scope**: Components (React Testing Library), hooks, utilities, state logic
- **Target**: ≥80% lines, ≥70% branches, ≥80% functions

### Mobile
```bash
flutter test --coverage --coverage-path=coverage/lcov.info
```
- **Scope**: Domain models, repositories, use cases, BLoC/Cubit logic
- **Target**: ≥80% lines, ≥70% branches

**CI Gate**: Coverage threshold enforced → PR blocked if below.

---

## 3. Widget / Component Tests

### Frontend
```bash
npm run test:component
```
- **Scope**: Individual components, props, events, accessibility
- **Tools**: Vitest + React Testing Library + @testing-library/jest-dom
- **Target**: ≥70% component coverage

### Mobile
```bash
flutter test test/widget --coverage
```
- **Scope**: Widget trees, user interactions, state transitions
- **Tools**: `flutter_test` + `flutter_widget_testing`
- **Target**: ≥70% widget coverage

---

## 4. Integration Tests

### Backend
```bash
pytest tests/integration \
  --cov=src \
  --cov-report=xml \
  --cov-fail-under=60 \
  -v
```
- **Scope**: Database (PostgreSQL testcontainers), Redis, external APIs, full stack
- **Infrastructure**: PostgreSQL + Redis via GitHub Actions services
- **Target**: ≥60% line coverage of integration paths

### Mobile
```bash
# With Tailscale for real server connection
flutter test integration_test/ -v
```
- **Scope**: Full app flows via Tailscale to real/staging backend
- **Infrastructure**: Tailscale GitHub Action → MagicDNS to staging server
- **Patrol** for native-like interaction
- **Target**: ≥60% critical user journeys

---

## 5. Contract Tests (Pact)

### Consumer (Mobile + Frontend)
```bash
# Mobile
flutter test test/contract

# Frontend
npm run test:contract
```
- **Generates**: Pact files (`pacts/*.json`)
- **Published**: To Pact Broker (or GitHub Artifacts) on each PR
- **Versioned**: By consumer version (semver)

### Provider (Backend)
```bash
# Backend verifies all consumer contracts
pytest tests/contract/provider -v
```
- **Runs**: Against Pact Broker (or local pacts)
- **Fails**: If breaking changes detected
- **CI Gate**: Must pass for both consumer and provider

---

## 6. E2E / Functional Tests

### Frontend (Playwright)
```bash
npx playwright test --project=chromium
```
- **Critical paths**:
  1. Login → Dashboard → Skills → Execute skill → View HUD
  2. Vault browser → View output → Follow links
  3. Voice session → Open → Send audio/text → Close
  4. Nightly scheduler → Toggle → View reports
  5. Settings → Tailscale status → Server config

### Mobile (Patrol)
```bash
flutter test integration_test/ -v
# Or
patrol test --target integration_test/main_test.dart
```
- **Critical flows**:
  1. Tailscale connect → Auth → Dashboard
  2. Skill execution → Vault sync → HUD update
  3. Voice session → STT → Skill → TTS response
  4. Offline queue → Reconnect → Sync
  5. Biometric unlock → Session restore

---

## 7. Performance / Load Tests

### Backend (k6)
```javascript
// k6 script: backend-load.js
export const options = {
  stages: [
    { duration: '2m', target: 50 },   // Ramp up
    { duration: '5m', target: 100 },  // Steady state
    { duration: '2m', target: 200 },  // Stress
    { duration: '2m', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],  // 95th percentile < 500ms
    http_req_failed: ['rate<0.01'],    // Error rate < 1%
  },
};
```
```bash
k6 run backend-load.js
```

### Mobile (Flutter Driver + patrol)
```bash
patrol test --target integration_test/perf_test.dart
```

---

## 8. Security Tests

### SAST (Static Application Security Testing)
```bash
# Backend
bandit -r src -f json -o bandit-report.json

# Frontend
npm audit --audit-level=high

# Mobile
flutter pub deps --dev --style=compact | grep -E "(vulnerability|advisory)"
```

### Dependency Scanning
```bash
# All repos
pip-audit (backend) / npm audit (frontend) / flutter pub outdated (mobile)
```

### Container Scanning
```bash
docker scan jarvis-backend:latest
docker scan jarvis-frontend:latest
docker scan jarvis-mobile:latest
```

### DAST (Dynamic) — Staging Only
```bash
# OWASP ZAP baseline scan
docker run -t owasp/zap2docker-stable zap-baseline.py \
  -t https://jarvis-backend.tailnet \
  -r zap-report.html
```

---

## 9. Quality Gate Enforcement

### GitHub Branch Protection Rules
```yaml
# Required for main/develop branches
required_status_checks:
  - backend-lint
  - backend-unit-tests
  - backend-integration-tests
  - frontend-lint
  - frontend-unit-tests
  - frontend-e2e-tests
  - sonarqube (quality-gate)
  # Mobile
  - analyze
  - unit-tests
  - integration-tests
  - sonarqube (quality-gate)
```

### SonarQube Quality Profiles

#### Python (Backend)
```json
{
  "qualityGate": {
    "conditions": [
      {"metric": "bugs", "op": "GREATER_THAN", "value": "0", "status": "ERROR"},
      {"metric": "vulnerabilities", "op": "GREATER_THAN", "value": "0", "status": "ERROR"},
      {"metric": "code_smells", "op": "GREATER_THAN", "value": "10", "status": "WARN"},
      {"metric": "coverage", "op": "LESS_THAN", "value": "80", "status": "ERROR"},
      {"metric": "duplicated_lines_density", "op": "GREATER_THAN", "value": "3", "status": "ERROR"},
      {"metric": "new_bugs", "op": "GREATER_THAN", "value": "0", "status": "ERROR"},
      {"metric": "new_vulnerabilities", "op": "GREATER_THAN", "value": "0", "status": "ERROR"}
    ]
  }
}
```

#### TypeScript (Frontend)
```json
{
  "qualityGate": {
    "conditions": [
      {"metric": "bugs", "op": "GREATER_THAN", "value": "0", "status": "ERROR"},
      {"metric": "vulnerabilities", "op": "GREATER_THAN", "value": "0", "status": "ERROR"},
      {"metric": "coverage", "op": "LESS_THAN", "value": "80", "status": "ERROR"},
      {"metric": "duplicated_lines_density", "op": "GREATER_THAN", "value": "3", "status": "ERROR"}
    ]
  }
}
```

#### Dart (Mobile)
```json
{
  "qualityGate": {
    "conditions": [
      {"metric": "bugs", "op": "GREATER_THAN", "value": "0", "status": "ERROR"},
      {"metric": "vulnerabilities", "op": "GREATER_THAN", "value": "0", "status": "ERROR"},
      {"metric": "coverage", "op": "LESS_THAN", "value": "80", "status": "ERROR"},
      {"metric": "duplicated_lines_density", "op": "GREATER_THAN", "value": "3", "status": "ERROR"}
    ]
  }
}
```

---

## 10. Test Data Management

### Test Fixtures
```
tests/
├── fixtures/
│   ├── skills/           # Skill definitions for testing
│   ├── vault/            # Sample vault outputs
│   ├── hud/              # HUD event samples
│   ├── voice/            # Audio/text samples
│   └── nightly/          # Report templates
├── factories/            # Factory Boy (backend) / Freezed (mobile)
└── builders/             # Test data builders
```

### Database Seeding
```python
# pytest fixture
@pytest.fixture(scope="session")
def seeded_db(db_session):
    seed_skills(db_session)
    seed_vault_outputs(db_session)
    yield db_session
```

---

## 11. CI/CD Integration Matrix

| Event | Backend | Frontend | Mobile |
|-------|---------|----------|--------|
| **PR opened** | lint, unit, integration, contract, sonarqube | lint, unit, e2e, sonarqube | analyze, unit, widget, integration (Tailscale), sonarqube |
| **PR updated** | Same | Same | Same |
| **PR merged to develop** | + docker build, deploy staging | + docker build, deploy staging | + build artifacts, sonarqube |
| **Tag pushed (v*)** | + deploy production | + deploy production | + build Android/iOS, create release |

---

## 12. Reporting & Dashboards

### GitHub Actions
- **Annotations**: Lint/type errors inline on PR
- **Coverage**: Codecov/Codecov comments on PR
- **SonarQube**: Quality Gate status badge + link

### SonarQube Dashboard
- **Projects**: jarvis-server-backend, jarvis-server-frontend, jarvis-mobile
- **Views**: New Code, Overall Code, Security Hotspots

### Custom Dashboard (Grafana)
- **Test trends**: Coverage over time
- **Flakiness**: Test failure rates
- **Performance**: API latency percentiles
- **Mobile**: Crash-free sessions, ANR rate

---

## 13. Flaky Test Management

### Quarantine Process
1. **Detect**: Test fails >2 times in 10 runs
2. **Quarantine**: Add `@pytest.mark.flaky` / `skip` with issue link
3. **Fix**: Root cause analysis within 1 sprint
4. **Restore**: Remove quarantine when stable

### Metrics
- **Flaky rate**: <1% of test suite
- **MTTR**: <2 days for quarantine resolution

---

## 14. Test Execution Times (Targets)

| Layer | Backend | Frontend | Mobile |
|-------|---------|----------|--------|
| Static | <30s | <30s | <30s |
| Unit | <2min | <2min | <3min |
| Widget/Component | N/A | <3min | <5min |
| Integration | <5min | N/A | <10min |
| Contract | <2min | <2min | <2min |
| E2E/Functional | N/A | <10min | <15min |
| **Total CI** | **<10min** | **<15min** | **<25min** |

---

## 15. Responsibility Matrix

| Role | Static | Unit | Widget | Integration | Contract | E2E | SonarQube |
|------|--------|------|--------|-------------|----------|-----|-----------|
| **Backend Dev** | ✅ | ✅ | - | ✅ | Provider | - | ✅ |
| **Frontend Dev** | ✅ | ✅ | ✅ | - | Consumer | ✅ | ✅ |
| **Mobile Dev** | ✅ | ✅ | ✅ | ✅ | Consumer | ✅ | ✅ |
| **QA/Automation** | - | - | - | ✅ | - | ✅ | - |
| **DevOps** | - | - | - | Infra | - | Infra | Config |

---

## 16. Continuous Improvement

### Monthly Review
- Coverage trends
- Flaky test report
- Performance benchmarks
- Security scan results

### Quarterly
- Quality Gate thresholds review
- Tool evaluation (new linters, test frameworks)
- Test pyramid balance check

---

## Appendix: Quick Reference Commands

```bash
# Backend (from backend/)
make test-unit        # Unit tests + coverage
make test-integration # Integration tests + coverage
make test-contract    # Pact provider verification
make lint             # ruff + mypy
make sonarqube        # SonarQube scan

# Frontend (from frontend/)
npm run test:unit
npm run test:e2e
npm run lint
npm run type-check
npm run sonarqube

# Mobile (from mobile root)
flutter analyze
flutter test --coverage
flutter test test/widget
flutter test integration_test/  # With Tailscale
flutter build apk --release
flutter build ios --release
make sonarqube
```
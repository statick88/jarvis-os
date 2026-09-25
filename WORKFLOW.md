# JARVIS-OS Development Workflow

## Branch Strategy

### Protected Branches
| Branch | Purpose | Protection |
|--------|---------|------------|
| `main` | Production-ready code | Required PR + CI pass + SonarQube QG + 2 approvals |
| `dev` | Integration branch | Required PR + CI pass |

### Working Branches (Worktrees)
| Prefix | Purpose | Naming |
|--------|---------|--------|
| `dev/` | Development tasks | `dev/<issue-id>-<short-desc>` |
| `fix/` | Bug fixes | `fix/<issue-id>-<short-desc>` |
| `feature/` | New features | `feature/<issue-id>-<short-desc>` |

### Branch Lifecycle
```
main (protected)
  ↑
dev (integration) ← PR from worktrees
  ↑
dev/xxx / fix/xxx / feature/xxx (worktrees) ← work here
```

## Worktree Workflow

### Creating a Worktree
```bash
# For a new feature
git worktree add ../jarvis-os-feature-XXX feature/JIRA-123-new-feature

# For a bug fix
git worktree add ../jarvis-os-fix-XXX fix/JIRA-456-bug-description

# For dev task
git worktree add ../jarvis-os-dev-XXX dev/JIRA-789-task-name
```

### Workflow in Worktree
```bash
cd ../jarvis-os-feature-XXX

# 1. Implement feature
# 2. Run local tests
# 3. Run SonarQube analysis
# 4. Commit with conventional commits
# 5. Push to origin
git push origin feature/JIRA-123-new-feature

# 6. Create PR to dev branch
# 7. Wait for CI + SonarQube Quality Gate
# 8. Get approvals
# 9. Merge to dev

# 10. Clean up
cd /Users/statick/dev/jarvis-os
git worktree remove ../jarvis-os-feature-XXX
git branch -d feature/JIRA-123-new-feature
git push origin --delete feature/JIRA-123-new-feature
```

## Branch Protection Rules

### main
- Require PR before merge
- Require status checks: CI, SonarQube Quality Gate
- Require 2 approvals
- No force push
- Require linear history

### dev
- Require PR before merge
- Require status checks: CI, SonarQube QG
- 1 approval required
- No force push

### dev/, fix/, feature/ branches
- No direct protection
- Auto-deleted after merge

## CI/CD Pipeline

### On Push to dev/feature/*/fix/*
```yaml
- lint (ruff + mypy)
- unit tests (pytest ≥80% coverage)
- integration tests
- SonarQube scan
- Build Docker images
- Deploy to staging (dev branch only)
```

### On Merge to dev
- Run full test suite
- SonarQube Quality Gate
- Deploy to staging environment

### On Merge to main
- All above +
- Build release artifacts
- Create GitHub release
- Deploy to production (manual approval)

## SonarQube Quality Gate

### Quality Gate Requirements
- **Bugs**: 0
- **Vulnerabilities**: 0
- **Security Hotspots**: 0 reviewed
- **Code Smells**: ≤ 10
- **Duplication**: < 3%
- **Coverage**: ≥ 80% (new code)
- **Maintainability Rating**: A
- **Reliability Rating**: A
- **Security Rating**: A

### Quality Gate Enforcement
- Blocked on PR if QG fails
- Manual override requires 2 approvals + security review

## Release Process

### Versioning
- Semantic Versioning (MAJOR.MINOR.PATCH)
- `main` tags trigger release

### Release Flow
1. `dev` → `main` via PR
2. CI creates release candidate
2. Manual approval in GitHub
3. Tag created: `vX.Y.Z`
3. Docker images pushed to GHCR
4. Deploy to production (manual)
5. GitHub Release created with changelog

## Worktree Cleanup Policy

### After Merge to dev
```bash
# 1. Remove worktree
git worktree remove ../jarvis-os-feature-XXX

# 2. Delete local branch
git branch -d feature/JIRA-123-new-feature

# 3. Delete remote branch
git push origin --delete feature/JIRA-123-new-feature
```

### Automated Cleanup (GitHub Actions)
```yaml
on:
  pull_request:
    types: [closed]
jobs:
  cleanup:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    steps:
      - name: Delete branch
        run: |
          git push origin --delete ${{ github.head_ref }}
      - name: Cleanup worktree
        run: |
          # Not applicable on runner, local cleanup only
```

## Branch Naming Convention

| Type | Pattern | Example |
|------|---------|---------|
| Feature | `feature/JIRA-XXX-short-desc` | `feature/JIRA-123-add-oauth` |
| Bug Fix | `fix/JIRA-XXX-short-desc` | `fix/JIRA-456-fix-login-crash` |
| Dev Task | `dev/JIRA-XXX-short-desc` | `dev/JIRA-789-refactor-auth` |
| Hotfix | `hotfix/JIRA-XXX-short-desc` | `hotfix/JIRA-999-security-patch` |

## Commit Message Convention

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `security`, `ci`, `build`

Example:
```
feat(auth): add Tailscale ACL integration

- Add Tailscale client integration
- Implement device authorization flow
- Add device trust validation

Closes: JIRA-123
```

## SonarQube Integration

### Project Setup
1. Create project in SonarQube: `jarvis-os`
2. Configure Quality Gate (see above)
3. Add project token to GitHub secrets: `SONAR_TOKEN`

### Scanner Configuration
```properties
# sonar-project.properties
sonar.projectKey=jarvis-os
sonar.organization=statick88
sonar.sources=jarvis_os
sonar.tests=tests
sonar.python.coverage.reportPaths=coverage.xml
sonar.python.coverage.reportPaths=coverage.xml
sonar.exclusions=**/tests/**,**/migrations/**,**/alembic/**,**/alembic/**
sonar.python.version=3.12
```

## CI/CD Pipeline Files

### GitHub Actions Workflows
- `.github/workflows/ci.yml` - Main CI pipeline
- `.github/workflows/sonarqube.yml` - SonarQube scan
- `.github/workflows/release.yml` - Release automation
- `.github/workflows/cleanup.yml` - Branch cleanup

## Emergency Hotfix Process

```bash
# 1. Create hotfix branch from main
git worktree add ../jarvis-os-hotfix-XXX hotfix/JIRA-XXX-critical-fix

# 2. Fix issue
cd ../jarvis-os-hotfix-XXX

# 2. Test thoroughly
# 3. Create PR to main (bypass dev)
# 4. Emergency approval (1 security reviewer)
# 5. Merge to main
# 5. Cherry-pick to dev
# 6. Cleanup worktree
```

## Monitoring & Alerts

### SonarQube Alerts
- Quality Gate failure → Slack/Email alert
- New vulnerabilities → Immediate alert
- Coverage drop > 5% → Alert

### CI/CD Alerts
- Build failure → Immediate
- Test failure → Immediate
- Deployment failure → Immediate

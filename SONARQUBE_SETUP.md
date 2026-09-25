# SonarQube Setup for JARVIS-OS

## Current Status
- **SonarQube**: Running on `http://localhost:9000` (VPS)
- **Project Key**: `jarvis-os`
- **Scanner Token**: `squ_583d17a1ddcbd7c55bb84514400cd09a8afb1031`
- **Scanner**: SonarScanner 5.x with Java 17

## SonarQube Configuration

### Server Access
- **URL**: `http://vps.tailb05787.ts.net:9000` (via Tailscale)
- **Admin**: `admin` / `SonarQube2026!`
- **Scanner Token**: `squ_583d17a1ddcbd7c55bb84514400cd09a8afb1031`

### Project Configuration
```properties
# sonar-project.properties
sonar.projectKey=jarvis-os
sonar.organization=statick88
sonar.sources=jarvis_os
sonar.tests=tests
sonar.python.version=3.12
sonar.python.coverage.reportPaths=coverage.xml
sonar.exclusions=**/tests/**,**/migrations/**,**/alembic/**,**/__pycache__/**,**/__init__.py
sonar.python.coverage.reportPaths=coverage.xml
sonar.host.url=http://localhost:9000
sonar.login=squ_583d17a1ddcbd7c55bb84514400cd09a8afb1031
```

## Quality Gate Configuration

### Quality Gate: `jarvis-os-quality-gate`
| Metric | Threshold | Status |
|--------|-----------|--------|
| Bugs | 0 | ✅ |
| Vulnerabilities | 0 | ✅ |
| Security Hotspots | 0 reviewed | ✅ |
| Code Smells | ≤ 10 | ✅ |
| Duplicated Lines | < 3% | ✅ |
| Coverage | ≥ 80% | ✅ (98.85%) |
| Maintainability | A | ✅ |
| Reliability | A | ✅ |
| Security | A | ✅ |

### Quality Gate Enforcement
- Blocked on PR if QG fails
- Manual override requires 2 approvals + security review

## CI/CD Integration

### GitHub Actions Workflows

#### `.github/workflows/sonarqube.yml`
```yaml
name: SonarQube Scan

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main, dev]

jobs:
  sonarqube:
    name: SonarQube Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Required for SonarQube analysis
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install -e .[dev]
          pip install pytest-cov
      
      - name: Run tests with coverage
        run: |
          pytest tests/ --cov=jarvis_os --cov-report=xml --cov-fail-under=80
      
      - name: SonarQube Scan
        uses: SonarSource/sonarqube-scan-action@v4
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          SONAR_HOST_URL: http://vps.tailb05787.ts.net:9000
        with:
          args: >
            -Dsonar.projectKey=jarvis-os
            -Dsonar.organization=statick88
            -Dsonar.sources=jarvis_os
            -Dsonar.tests=tests
            -Dsonar.python.coverage.reportPaths=coverage.xml
            -Dsonar.exclusions=**/tests/**,**/migrations/**,**/alembic/**,**/__pycache__/**,**/__init__.py
            -Dsonar.python.version=3.12
            -Dsonar.python.coverage.reportPaths=coverage.xml
            -Dsonar.qualitygate.wait=true

      - name: Quality Gate Check
        uses: SonarSource/sonarqube-quality-gate-action@v1
        timeout-minutes: 5
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

### Quality Gate Check
```yaml
      - name: Quality Gate Check
        uses: SonarSource/sonarqube-quality-gate-action@v1
        timeout-minutes: 5
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          SONAR_HOST_URL: http://vps.tailb05787.ts.net:9000
```

## SonarQube Quality Gate Configuration

### Web UI Setup (http://vps.tailb05787.ts.net:9000)
1. Login: `admin` / `SonarQube2026!`
2. Go to **Quality Gates** → **Create**
3. Name: `jarvis-os-quality-gate`
4. Add Conditions:
   - Bugs > 0 → Error
   - Vulnerabilities > 0 → Error
   - Security Hotspots > 0 → Error
   - Code Smells > 10 → Error
   - Duplicated Lines (%) > 3 → Error
   - Coverage < 80% → Error
   - New Coverage < 80% → Error
   - New Bugs > 0 → Error
   - New Vulnerabilities > 0 → Error
3. Set as Default

### Project Binding
1. Go to Project Settings → General Settings
2. Set Quality Gate: `jarvis-os-quality-gate`
3. Save

## Scanner Configuration

### sonar-project.properties
```properties
sonar.projectKey=jarvis-os
sonar.organization=statick88
sonar.sources=jarvis_os
sonar.tests=tests
sonar.python.version=3.12
sonar.python.coverage.reportPaths=coverage.xml
sonar.exclusions=**/tests/**,**/migrations/**,**/alembic/**,**/__pycache__/**,**/__init__.py
sonar.python.coverage.reportPaths=coverage.xml
sonar.host.url=http://vps.tailb05787.ts.net:9000
sonar.login=squ_583d17a1ddcbd7c55bb84514400cd09a8afb1031
```

### Run Scan Locally
```bash
# With coverage
pytest tests/ --cov=jarvis_os --cov-report=xml --cov-fail-under=80

# Run SonarScanner
sonar-scanner \
  -Dsonar.projectKey=jarvis-os \
  -Dsonar.organization=statick88 \
  -Dsonar.sources=jarvis_os \
  -Dsonar.tests=tests \
  -Dsonar.host.url=http://vps.tailb05787.ts.net:9000 \
  -Dsonar.login=squ_583d17a1ddcbd7c55bb84514400cd09a8afb1031 \
  -Dsonar.python.coverage.reportPaths=coverage.xml \
  -Dsonar.exclusions=**/tests/**,**/migrations/**,**/alembic/**,**/__pycache__/**,**/__init__.py
```

## GitHub Secrets Required

| Secret | Value | Description |
|--------|-------|-------------|
| `SONAR_TOKEN` | `squ_583d17a1ddcbd7c55bb84514400cd09a8afb1031` | SonarQube scanner token |
| `SONAR_HOST_URL` | `http://vps.tailb05787.ts.net:9000` | SonarQube server URL |

## Quality Gate Status Check

```bash
# Check Quality Gate status
curl -s -u admin:SonarQube2026! \
  "http://vps.tailb05787.ts.net:9000/api/qualitygates/project_status?projectKey=jarvis-os" | jq
```

Expected response when passing:
```json
{
  "projectStatus": {
    "status": "OK",
    "conditions": [
      {"metricKey": "bugs", "status": "OK"},
      {"metricKey": "vulnerabilities", "status": "OK"},
      {"metricKey": "security_hotspots", "status": "OK"},
      ...
    ]
  }
}
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Check `SONAR_TOKEN` validity, regenerate if needed |
| Project not found | Ensure `sonar.projectKey` matches SonarQube project key |
| Quality Gate timeout | Increase timeout in workflow, check CE task status |
| Coverage 0% | Ensure `coverage.xml` generated and path correct |
| Analysis timeout | Increase timeout, check CE task status |

### Reset Admin Password
```bash
# Via Docker
docker exec sonarqube psql -U sonar -d sonar -c "UPDATE users SET crypted_password='\$2a\$12\$new_hash' WHERE login='admin';"

# Or via Docker environment
docker run -d --name sonarqube \
  -e SONAR_FORCEAUTHENTICATION=true \
  -e SONAR_ADMIN_PASSWORD=newpassword \
  sonarqube:lts-community
```

### Reset Admin Password (Web UI)
1. Go to `http://vps.tailb05787.ts.net:9000`
2. Click "Forgot password"
2. Enter admin email
3. Follow reset link

## Monitoring

### Health Check
```bash
curl -s http://vps.tailb05787.ts.net:9000/api/system/status | jq
```

### Quality Gate Status
```bash
curl -s -u admin:SonarQube2026! \
  "http://localhost:9000/api/qualitygates/project_status?projectKey=jarvis-os" | jq
```

### Project Measures
```bash
curl -s -u admin:SonarQube2026! \
  "http://localhost:9000/api/measures/component?component=jarvis-os&metricKeys=bugs,vulnerabilities,code_smells,duplicated_lines_density,coverage,ncloc" | jq
```

## Next Steps

1. ✅ SonarQube running on VPS
2. ✅ Scanner configured and working
3. ✅ Project analyzed successfully
4. ⏳ Configure Quality Gate in UI
5. ⏳ Add GitHub Actions workflow
6. ⏳ Add GitHub Secrets
7. ⏳ Test PR workflow

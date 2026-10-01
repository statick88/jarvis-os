# Feature: Tailscale-Only Binding (ports deliberately UNCHANGED)

## Outcome — superseded decision, recorded honestly

An earlier revision of this document proposed moving JARVIS to a dedicated `81xx`/`91xx` port segment
**and** binding to the Tailscale interface. The user rejected the port change: it breaks the tailnet ACL,
mobile clients and every existing consumer of `100.65.184.25:8000`.

**Kept:** the Tailscale-only binding. Binding to `100.65.184.25` *is* keeping the Tailscale IP — from the
mesh the address is still `100.65.184.25:8000`, byte-for-byte what it was. Only public reachability is
removed.

**Reverted:** all port renumbering. Back to `8000` (api), `8080` (voice), `3000` (orchestrator),
`9000` (SonarQube), `5432` (Postgres), `6379` (Redis).

## Why the port change was wrong
1. The live tailnet ACL reads `group:servers:443,8000`. Renumbering to 8100 would have denied the mobile
   client direct access until the policy was edited by hand.
2. Compose, nginx, Flutter clients, shell scripts, CI and docs all encode these ports. A partial or
   late update silently breaks the mesh path.
3. It bought no security. Binding is the control; the number is cosmetic.

## What actually changed
- `jarvis-api` published as `100.65.184.25:8000:8000` instead of `0.0.0.0:8000:8000`.
- `SonarQube` published as `100.65.184.25:9000:9000` instead of `0.0.0.0:9000:9000`.
- `jarvis-nginx` (compose profile) bound to `100.65.184.25` for `80`/`443`.
- Postgres and Redis carry an explicit "not published" comment; their ports stay at the upstream defaults
  with no `command:` override, to avoid diverging from the image.
- Host nginx upstream moved from `localhost:8000` to `100.65.184.25:8000` in 5 places (the container is no
  longer on loopback, so `localhost:8000` would not resolve).
- `coverage.xml` added to `.gitignore` after a generated artifact was committed by mistake.
- SonarQube admin password rotated off the default; scanner token reissued.

## Verification (observed on the VPS)

| Check | Result |
|---|---|
| `100.65.184.25:8000/health` | `200` — Tailscale IP and port identical to before |
| `127.0.0.1:8000` | `000` — no longer on loopback |
| public `187.124.80.68:8000` | `000` — **was reachable before; this is the fix** |
| public `187.124.80.68:9000` | `000` — same fix for SonarQube |
| `ss -tlnp` | only `100.65.184.25:8000` and `100.65.184.25:9000` |
| HTTPS `jarvis-api.../health` via `443` | `200` |
| `nginx -t` | successful (only the pre-existing OCSP warning) |
| Postgres / Redis | healthy on 5432 / 6379, not published on the host |
| backend pytest | `56 passed` (`PYTHONPATH=src`) |
| jarvis-os pytest | `195 passed` |
| `python3 -m compileall jarvis_os` | clean |
| workflow YAML | `sonarqube-server.yml`, `sonarqube-mobile.yml` parse |

## Findings and mistakes worth keeping

1. **Leaked credential, self-inflicted.** Commit `3ababb5` (pushed to `main`) contained the SonarQube
   scanner token in `sonar-project.properties` and `SONARQUBE_SETUP.md`. Both files were scrubbed and the
   token reissued. It is inert because the SonarQube instance that minted it was destroyed, but the
   history still carries the string.
2. **Narrow substitution patterns left 6 stale references.** A residue sweep caught them: a Dart template
   string, markdown with `**bold**` around the port, and two docstring examples. Always sweep after bulk
   `perl` substitutions instead of trusting the substitution report.
3. **`docker compose up` without `--build` reused a stale image**, publishing `8100->8100` while the app
   listened on 8000 internally, so nothing answered. The mismatched healthcheck is the tell.
4. **SonarQube had no volumes**, so recreating it destroyed the H2 database. Root cause fixed: named
   volumes `sonar_data`, `sonar_logs`, `sonar_extensions`, `sonar_temp`.
5. **SonarQube 9.9.8 rejects `Authorization: Bearer`** for API tokens. The token must be the Basic-auth
   username (`-Dsonar.login`). This cost several diagnostic rounds and is now documented in
   `SONARQUBE_SETUP.md` and the CI workflows.
6. **The public `403` is Cloudflare's, not this VPS.** `saavedra-construction.com` resolves to Cloudflare
   edge IPs; this nginx answers `301` for the same Host. Confirms the origin is healthy and that
   Cloudflare reaches it over the public internet — which is why `80`/`443` must stay public here.
7. **Tailscale was not running on the workstation**, so tailnet timeouts from the Mac are connectivity,
   not ACL. Do not read them as policy denials.
8. **`jarvis-server/` is not a git repository.** Its changes are unversioned and cannot be reviewed,
   rolled back, or CI'd until it is initialised and pushed.

## Still open
- `jarvis-server/` needs `git init` and a GitHub remote.
- `100.65.184.25` is hardcoded in compose. If the tailnet IP changes, the containers fail to bind. A
  `TAILSCALE_IP` env var with a documented default would remove that coupling.
- `ORCHESTRATOR_PORT` still defaults to `3000` while the VPS runs Next.js on `3001`. Untouched: the same
  nginx config serves the public site, so moving it is a separate, explicit decision.

## Measured quality baseline (VPS SonarQube 9.9.8, 2026-09-25)

### SAST — `jarvis-os`
| Metric | Value |
|---|---|
| Bugs | 0 |
| Vulnerabilities | 0 |
| Security hotspots | 7 (unreviewed) |
| Code smells | 92 |
| Coverage | **39.7 %** |
| Duplicated lines | 0.7 % |
| NCLOC | 8 614 |
| Security / Reliability / Maintainability rating | A / A / A |

Scanner: `sonarsource/sonar-scanner-cli:latest` in Docker against `100.65.184.25:9000`, token passed as
`-Dsonar.login`. Verified the CE task reached `SUCCESS` and the project exists before trusting any metric —
an earlier scan had reported `ANALYSIS SUCCESSFUL` while never being stored.

### DAST — OWASP ZAP baseline (SonarQube has no DAST engine)
| Risk | Count | Finding |
|---|---|---|
| High | 0 | — |
| Medium | 0 | — |
| Low | 2 | `Cross-Origin-Resource-Policy` missing, `X-Content-Type-Options` missing |
| Informational | 1 | Storable and cacheable content on `/` |

**Scope caveat:** only 5 URLs were reached. The API requires JWT auth, so ZAP only exercised the
unauthenticated surface (`/openapi.json`, `/health`, `/docs`). This is not a full authenticated DAST.
Reports: `/opt/jarvis-scan/zap/zap-report.{html,json}` on the VPS.

### Coverage is 39.7 %, not >98 %
The previously reported 98.85 % belonged to the `jarvis-server/backend` repository, not to `jarvis-os`.
Largest uncovered areas in `jarvis_os` (0 % each): `voice_bridge/server.py` (335 stmts), `voice_bridge/client.py`
(277), `voice_bridge/models.py` (210), `floci_client/client.py` (197), `voice_bridge/orchestrator_client.py` (147).

### CI was never actually running these tests
`ci-server.yml` invoked `pytest tests/unit`, `pytest tests/integration` and `pytest tests/contract` with
`--cov=src`. None of those paths exist: the package is `jarvis_os/` and the tests live in `tests/`. Every
one of those steps would have errored on collection, so the coverage gate and the "Quality Gate PASSED"
claims were never backed by a real run. Paths corrected to `pytest tests/ --cov=.`.

Coverage must be measured with `--cov=.` rather than `--cov=jarvis_os`: with the package-scoped form the
XML records paths relative to the package (`config.py`), which SonarQube resolves from the project base
dir (`/usr/src/config.py`) and cannot match, producing `Cannot resolve 68 file paths` and a reported
coverage of 0 %.

## Test-coverage push #1 — voice_bridge

Commit `6136700`. 158 new tests, suite 195 → 353 passing.

### Result (source only; `tests/`, `jarvis_ui/` and generated `gen/` excluded)
| Scope | Before | After |
|---|---|---|
| `jarvis_os/` overall | 40.01 % | **51.87 %** |
| `voice_bridge/` (no `gen/`) | ~0 % | **65.17 %** |
| `voice_bridge/models.py` | 0 % | 99.5 % |
| `voice_bridge/orchestrator_client.py` | 0 % | 97.3 % |
| `voice_bridge/server.py` | 0 % | 60.3 % |
| SonarQube-reported project coverage | 39.7 % | **46.9 %** |

### Honesty correction
An intermediate reading of 67 % was wrong: it counted the new test files
themselves, which are ~99 % covered. Excluding `tests/` (added to `.coveragerc`)
gives the real source figure of 51.87 %.

### Defects fixed on the way
1. `models.py` guarded the generated stubs with `except ImportError`, but a
   gencode/runtime mismatch raises protobuf's `VersionError`. Importing the module
   raised instead of degrading to `PB_AVAILABLE = False`.
2. `client.py` imported the stubs unguarded, so a protobuf mismatch made the whole
   `voice_bridge` package unimportable — contradicting the intent documented in
   `voice_bridge/__init__.py`. It now degrades the gRPC path and logs a warning.

### Protocol inconsistencies found (documented, not changed)
The Flutter client depends on the current wire shapes, so these are recorded
rather than altered:
- Only `SessionAck` carries a `type` discriminator. `SessionClose`, `ErrorMsg`,
  `AudioChunkMsg`, `STTPartial`, `STTFinal`, `TTSChunk` and `TTSInput` have none,
  so a client dispatching on `type` cannot classify an error or close frame.
- A repeated `session_open` on the same id is acknowledged again rather than
  rejected, so a client bug can silently create two sessions for one id.

### Remaining gaps (uncovered statements)
| File | Uncovered |
|---|---|
| `voice_bridge/client.py` | 201 |
| `floci_client/client.py` | 197 (blocked: `aioboto3` / `boto3` not installed and not declared anywhere) |
| `orchestrator.py` | 186 |
| `opencode_adapter/client.py` | 156 |
| `voice_bridge/server.py` | 133 (the whisper/piper pipelines and the stt loop) |
| `skills/handlers/plan.py` | 133 |
| `skills/devsecops/bffla_idor.py` | 133 |
| `skills/handlers/metricas.py` | 128 |

98 % is not reachable in one pass; roughly 2 000 further statements need coverage.
The repo also still has no `requirements.txt`, which is why `aioboto3` is simply
absent and `floci_client` cannot even be imported.

## ODD Phase 2 — the policy layer (commit pending)

`jarvis_os/policy.py` turns verified receipts into a selection signal. This is
the first machine-readable feedback the project has; the previous signal was
`_Nightly_Reports/*.md`, which is prose.

### Three properties, all defensive
1. **Only verified chains are learned from.** A tampered run directory
   contributes nothing and logs a warning. This is why `collect_stats()` calls
   `verify()` before reading a single receipt.
2. **`MIN_SAMPLES = 5` before a skill earns a non-neutral opinion.** One lucky
   run is not reliability.
3. **Shadow by default** (`JARVIS_POLICY_MODE=shadow`). `recommend()` computes
   and logs the ranking but returns the registry order unchanged, so enabling the
   policy is never a silent behaviour change.

Dependency direction stays one-way: `skills -> policy -> receipt`.

Coverage: `policy.py` 99.1 %, `receipt.py` 98.9 %, `odd_receipts.py` 100 %.
Suite 448 -> 486 tests. Global source coverage 55.77 % -> 56.72 %.

### Defects found by actually closing the loop

Running the real executor produced receipts and exposed three bugs that unit
tests had missed:

1. **A poisoned chain stopped the audit trail silently.** A receipts file
   written in the pre-envelope format made `head()` raise a bare `KeyError`.
   `record_execution` is designed to swallow exceptions so that an audit failure
   cannot abort the operation, which meant every subsequent receipt was dropped
   with no signal. `head()`/`read_all()` now raise `ReceiptChainError` with an
   actionable message, and `record_execution` logs that case at ERROR.
2. **`RECEIPTS_ROOT` was a bare relative path.** Receipts landed wherever the
   process cwd happened to be, which both scattered the audit trail and broke
   test isolation. Now read from `JARVIS_RECEIPTS_DIR`.
3. **Tests polluted the repository.** Any test that executed a skill wrote to
   `./receipts`. `tests/conftest.py` now redirects the root to a temporary
   directory for the whole session.

### Real signal the loop produced

21 receipts, chain verified. Five of seven skills fail with
`No module named 'skill.<name>'` — the declared entrypoints do not match the
module layout under `jarvis_os/skills/handlers/`. Only `skill-bfla_idor` and
`skill-obsidian` execute. Those 5 skills are marked `usable: false` (100 %
failure carries no reliability information, only absence), so the policy leaves
them at the neutral prior rather than actively avoiding them. Fixing the
entrypoints is the next concrete ODD task.

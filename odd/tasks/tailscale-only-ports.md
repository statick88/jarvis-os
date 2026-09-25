# Feature: Tailscale-Only Exposure + 81xx Port Scheme

## Objective
Move JARVIS off privileged/colliding default ports into a dedicated `81xx`/`91xx` segment and bind every
published service to the Tailscale interface so the stack is reachable only through the mesh.

## Problem / Why
1. **Public exposure.** On the VPS `jarvis-api` (8000) and `sonarqube` (9000) are published on `0.0.0.0`.
   They are reachable from the internet, not just from the mesh. That contradicts the stated
   architecture ("mobile consumes API via Tailscale, no public exposure").
2. **Port collisions.** The VPS already runs `11434` (ollama), `3001` (Next.js), `2377`/`7946` (swarm),
   `80`/`443` (nginx). Low, well-known defaults invite collisions and make JARVIS indistinguishable
   in `ss -tlnp` output.
3. **Latent mismatch.** `ORCHESTRATOR_PORT` defaults to `3000`, but the deployed Next.js runs on `3001`.
   Already broken; corrected in this change.

### Concept note (binding ≠ port)
Changing a port number adds **zero** security. Only binding does. Binding published services to the
Tailscale IP (`100.65.184.25`) or to `127.0.0.1` is the actual control. The port change is justified by
collision avoidance and legibility, not by security. Postgres/Redis stop being published at all and live
only on the internal Docker network.

## Port Mapping (authoritative)

| Service | Old | New | Exposure after change |
|---------|-----|-----|-----------------------|
| gentle-orchestrator (Next.js) | 3000 | **3100** | `127.0.0.1:3100` |
| voice-pipeline (STT/TTS) | 8080 | **8180** | internal only |
| jarvis-api (FastAPI) | 8000 | **8100** | `100.65.184.25:8100` |
| SonarQube | 9000 | **9100** | `100.65.184.25:9100` |
| PostgreSQL | 5432 | **5433** | **not published** (Docker network only) |
| Redis | 6379 | **6380** | **not published** (Docker network only) |

## Authorized Scope
- `jarvis-os` repo: live config, Dockerfiles, scripts, Flutter client, current-facing docs.
- `jarvis-server/backend` repo: compose, Dockerfile, nginx, config, tests, INFRASTRUCTURE.md.
- VPS `/opt/jarvis-server/backend` redeploy.
- Tailscale ACL: `group:mobile → group:servers:443,8000` must become `443,8100`.

## Out of Scope / Must NOT change
- **False positives** — do not edit: `spec/contracts/voice_api.proto:150` (sample rates `48000`),
  `jarvis_os/voice_bridge/models.py:207` (sample rates), `jarvis_ui/macos/Runner.xcodeproj/project.pbxproj`
  (Xcode UUIDs containing `3000`).
- `docs/adr/00X-*.md` — accepted decision records, kept as written.
- Behaviour, routes, and API contracts are unchanged. This is a configuration/binding change only.

## Tasks

- [x] T1. jarvis-os: config defaults (`config.py`, `orchestrator.py`, `opencode_adapter/models.py`, `bffla_idor.py`, voice_bridge client/server)
- [x] T2. jarvis-os: Docker layer (compose, Dockerfile.gentle, Dockerfile.voice, entrypoint.gentle.sh)
- [x] T3. jarvis-os: Flutter client (`jarvis_api_service.dart`, `audio_voice_service.dart`, `audio_stream_service.dart`)
- [x] T4. jarvis-os: scripts (`test_audio_streaming.sh`, `test_jarvis_pipeline.sh`)
- [x] T5. jarvis-os: docs + properties (`sonar-project.properties`, `SONARQUBE_SETUP.md`, `docs/getting-started.md`, `docs/architecture.md`, `spec/jarvis-os-spec.md`)
- [x] T6. jarvis-server: compose + Dockerfile + nginx, Tailscale binding, unpublish Postgres/Redis
- [x] T7. jarvis-server: `config.py`, `http/__init__.py`, `test_config.py`, `INFRASTRUCTURE.md`
- [ ] T8. Tailscale ACL update `443,8000` → `443,8100` (+ `9100` for the scanner) — **BLOCKED: requires tailnet admin console access**
- [x] T9. VPS redeploy + health verification
- [x] T10. Verification: test suites + residue sweep

## Verification Evidence (observed on the VPS)

| Check | Result |
|---|---|
| `100.65.184.25:8100/health` | `200` `{"status":"ok",...,"version":"0.1.0"}` |
| `127.0.0.1:8100` | `000` (not bound to loopback — intended) |
| public IP `187.124.80.68:8100` | `000` (**was reachable before — this is the fix**) |
| `ss -tlnp` | `100.65.184.25:8100` only; no `8000` listener remains |
| Postgres | `pg_isready -p 5433` → accepting connections |
| Redis | `redis-cli -p 6380 ping` → `PONG` |
| DB/Redis host exposure | none (internal Docker network only) |
| SonarQube | `100.65.184.25:9100`, `status: UP`, H2/ES data preserved via `docker commit` |
| Port 9000 | freed |
| `nginx -t` | successful (only pre-existing OCSP warning) |
| HTTPS `jarvis-api.../health` via `443` | `200` from the VPS |
| `saavedra-construction.com` | still served; 403 originates in the app, not nginx |
| backend pytest | `56 passed` (`PYTHONPATH=src`) |
| jarvis-os pytest | `195 passed`, `coverage.xml` produced |
| `python3 -m compileall jarvis_os` | clean |
| `bash -n` on both scripts | clean |
| residue sweep (both repos) | clean; only false positives and this document remain |

## Blockers / decisions pending
1. **T8 Tailscale ACL.** The live tailnet policy still reads `group:servers:443,8000`. Only this
   repository's documentation was updated; the policy itself lives in the Tailscale admin console and
   was not modified. Until it is changed, direct mesh access to `8100`/`9100` is denied. `443` keeps
   working, so the HTTPS production path is unaffected.
2. **SonarQube token leaked in git history.** Commit `3ababb5` (already pushed to `main`) contains the
   scanner token in `sonar-project.properties` and `SONARQUBE_SETUP.md`. Both files were scrubbed in
   this working tree, but **the token must be rotated** and the history rewritten (or accepted).
3. **Host nginx still public on 80/443.** Deliberately not rebound, because the same config serves the
   public `saavedra-construction.com` site. Rebinding to Tailscale-only would take that site offline.
   Needs an explicit decision.
4. **Next.js still on 3001 on the VPS** while `ORCHESTRATOR_PORT` now defaults to `3100`. The host nginx
   `nextjs` upstream still points at `localhost:3001`. Left untouched: it is the public site.
5. SonarQube scan against `9100` could not be executed from the workstation: Tailscale is not running on
   the workstation, so all tailnet traffic fails. Not an ACL effect.

## Progress
- Port mapping agreed (segment 81xx + Tailscale-only binding).
- All repository edits applied and verified locally.
- Backend and SonarQube redeployed on the VPS; security-relevant reachability confirmed.
- Committed on `fix/tailscale-ports-81xx`; merge and push remain a user decision.

## Acceptance Criteria
- [ ] No hardcoded `8000|8080|3000|9000|5432|6379` remains in live config (false positives excluded).
- [ ] `ss -tlnp` on the VPS shows no `0.0.0.0` bind for 8100/9100.
- [ ] `jarvis-api` health returns 200 via `100.65.184.25:8100` and NOT via the public interface.
- [ ] Backend unit tests pass with updated config expectations.
- [ ] Mobile client can reach the API through the mesh (ACL allows 8100).

## Verification commands
- `cd /Users/statick/dev/jarvis-server/backend && python -m pytest -q`
- `cd /Users/statick/dev/jarvis-os && python -m compileall -q jarvis_os`
- `bash -n scripts/test_audio_streaming.sh scripts/test_jarvis_pipeline.sh`
- `rtk ssh vps "ss -tlnp | grep -E '8100|9100'"`
- `rtk ssh vps "curl -s http://100.65.184.25:8100/health"`

## Route
Delegated writer (T1–T7) — 20+ non-trivial files across 2 repos. Production mutation (T8–T9) and
verification (T10) stay in the orchestrator because they are irreversible and high-consequence.

## Progress
- Feature document created; port mapping agreed with user (segment 81xx + Tailscale-only binding).

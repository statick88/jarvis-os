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

# ADR 004: Tailscale Network Design — Zero-Trust Mesh for Mobile ↔ Server

## Status
Accepted

## Context
Mobile client must communicate with server **without any public internet exposure**.
All traffic must flow through Tailscale WireGuard mesh.

## Decision
**Tailscale Mesh Architecture**:

```
┌─────────────────────────────────────────────────────────────────┐
│                      TAILSCALE NETWORK (tailnet)                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  Mobile      │    │  Subnet      │    │  Server          │  │
│  │  Client      │◄──►│  Router      │◄──►│  (backend +      │  │
│  │  (tag:mobile)│    │  (server)    │    │   frontend)      │  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
│         │                   │                    │              │
│         │         ┌─────────┴─────────┐         │              │
│         └────────►│  Tailscale ACL    │◄────────┘              │
│                   │  tag:mobile →     │                        │
│                   │  10.0.0.0/8:443   │                        │
│                   └───────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

**Components**:

1. **Mobile Client** (`tag:mobile-client`)
   - Tailscale userspace client (tsnet or tailscale-client Dart)
   - Authenticates via OAuth device authorization
   - Gets IP in `100.64.0.0/10` (CGNAT range)

2. **Subnet Router** (on server VM/K8s)
   - `tailscale up --advertise-routes=10.0.0.0/8` (server subnet)
   - `--accept-routes` to accept mobile routes
   - Runs as systemd service or K8s DaemonSet

3. **Tailscale ACL** (tailnet policy)
```json
{
  "groups": {
    "group:mobile": ["tag:mobile-client"],
    "group:servers": ["tag:server"]
  },
  "acls": [
    {"action": "accept", "src": ["group:mobile"], "dst": ["group:servers:443"]},
    {"action": "accept", "src": ["group:servers"], "dst": ["group:mobile:*"]}
  ],
  "autoApprovers": {
    "routes": {"10.0.0.0/8": ["group:servers"]},
    "exitNode": ["group:servers"]
  },
  "tagOwners": {
    "tag:mobile-client": ["autogroup:members"],
    "tag:server": ["autogroup:admin"]
  }
}
```

3. **Server Services** (only accessible via Tailscale)
   - Backend API: `https://jarvis-backend.tailnet:443`
   - Frontend: `https://jarvis-frontend.tailnet:443`
   - WebSocket: `wss://jarvis-backend.tailnet/ws/hud`
   - **No public DNS, no public IPs**

4. **Certificate Management**
   - **Tailscale HTTPS** (Let's Encrypt via Tailscale) for `*.tailnet.ts.net`
   - **OR** Self-signed CA + certificate pinning in mobile
   - Mobile validates server cert via pinned SHA-256

5. **Mobile Client Connection Flow**
```
1. User opens app → checks Tailscale status
2. If not connected → launch Tailscale OAuth (device auth)
3. Tailscale establishes WireGuard tunnel to tailnet
4. Mobile resolves `jarvis-backend.tailnet` via MagicDNS
5. TLS connection with certificate pinning
5. API calls route through WireGuard → subnet router → backend
```

## Network Policies

| Traffic | Source | Destination | Port | Protocol | Allowed |
|---------|--------|-------------|------|----------|---------|
| API | Mobile | Backend | 443 | HTTPS | ✅ |
| WebSocket | Mobile | Backend | 443 | WSS | ✅ |
| Voice | Mobile | Backend | 443 | WSS/ WebRTC | ✅ |
| Frontend | Mobile | Frontend | 443 | HTTPS | ✅ |
| Admin | Admin | Backend | 443 | HTTPS | ✅ (tag:admin) |
| Internet | Mobile | * | * | * | ❌ |
| Internet | Backend | * | * | * | ❌ (except updates) |

## CI/CD Integration

**GitHub Actions** (mobile repo):
```yaml
- name: Start Tailscale
  uses: tailscale/github-action@v2
  with:
    oauth-client-id: ${{ secrets.TAILSCALE_CLIENT_ID }}
    oauth-secret: ${{ secrets.TAILSCALE_CLIENT_SECRET }}
    tags: tag:ci-mobile
- name: Run integration tests
  run: |
    # Tailscale provides MagicDNS resolution
    flutter test integration_test/
```

**GitHub Actions** (server repo):
```yaml
- name: Start Tailscale
  uses: tailscale/github-action@v2
  with:
    oauth-client-id: ${{ secrets.TAILSCALE_CLIENT_ID }}
    oauth-secret: ${{ secrets.TAILSCALE_CLIENT_SECRET }}
    tags: tag:ci-server
- name: Run integration tests
  run: |
    # Backend tests against real Tailscale network
    pytest tests/integration/
```

## Secrets Management
- **Tailscale OAuth credentials**: GitHub secrets (`TAILSCALE_CLIENT_ID`, `TAILSCALE_CLIENT_SECRET`)
- **ACL policy**: Managed in Tailscale admin console (not in repo)
- **Certificate pins**: Generated at build time, stored in mobile app config

## Monitoring & Observability
- **Tailscale metrics**: `tailscale status --json`, Prometheus exporter
- **Network health**: Latency, packet loss, DERP usage
- **Alerting**: Mobile disconnect >5min, subnet router down

## Disaster Recovery
- **Break-glass**: Admin can access via Tailscale SSH (`tailscale ssh user@server`)
- **Subnet router HA**: Multiple routers with `--advertise-routes`
- **Mobile fallback**: Cached offline queue, sync on reconnect

## Rationale
- **Zero public attack surface**: No open ports, no public DNS
- **Device identity**: Tailscale provides cryptographic device identity
- **ACL enforcement**: Network-level authorization, not just application
- **Audit trail**: Tailscale logs all connections
- **Simplicity**: MagicDNS, automatic key rotation, NAT traversal

## Consequences
- Requires Tailscale account (free tier supports 100 devices)
- Mobile CI needs Tailscale GitHub Action
- Subnet router must be highly available
- DERP relay latency for mobile on cellular

## Related
- ADR 001: Repository Structure
- ADR 002: Server Architecture
- ADR 003: Mobile Client Architecture
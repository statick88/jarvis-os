# ADR 003: Mobile Client Architecture — Flutter with Tailscale Mesh

## Status
Accepted

## Context
Mobile client must:
- Consume server API securely
- **Never expose server to public internet**
- Connect via **Tailscale mesh network** only
- Provide high-quality UX: Voice, HUD, Skills, Vault, Nightly
- Work offline with sync queue

## Decision
**Flutter** with Clean Architecture + Tailscale integration

```
jarvis-mobile/
├── lib/
│   ├── core/
│   │   ├── config/           # Environment, flavors (dev/staging/prod)
│   │   ├── network/          # Dio client, interceptors, Tailscale
│   │   │   ├── api_client.dart
│   │   │   ├── tailscale_client.dart
│   │   │   ├── certificate_pinning.dart
│   │   │   └── offline_queue.dart
│   │   ├── security/         # Secure storage, biometric auth
│   │   ├── di/               # GetIt/service_locator
│   │   └── utils/
│   ├── features/
│   │   ├── auth/             # Tailscale auth, JWT refresh
│   │   ├── skills/           # Skills list, execution, composition
│   │   ├── vault/            # Vault browser, offline sync
│   │   ├── hud/              # Real-time HUD WebSocket
│   │   ├── voice/            # STT/TTS, session management
│   │   ├── nightly/          # Reports, scheduler control
│   │   └── settings/         # Tailscale status, server config
│   ├── shared/
│   │   ├── widgets/          # Design system components
│   │   ├── theme/            # Material 3, dark/light
│   │   └── extensions/
│   └── main.dart
├── test/
│   ├── unit/                 # Domain + application logic
│   ├── widget/               # Component tests
│   ├── integration/          # Feature flows (patrol)
│   └── golden/               # Visual regression
├── integration_test/         # Patrol e2e
├── pubspec.yaml
├── melos.yaml (if monorepo)
├── Dockerfile
└── docker-compose.yml
```

**Tailscale Integration**:
- **tsnet** (Go library) embedded in Flutter via FFI **OR**
- **tailscale-client** (Dart package) for userspace WireGuard
- **Subnet router** on server side for mobile → backend access
- **ACL tags**: `tag:mobile-client` with restricted server access

**API Client**:
- **Dio** with interceptors: auth, logging, retry, offline queue
- **Certificate pinning** (SHA-256 of server cert)
- **Auto-retry** with exponential backoff
- **Offline queue**: Persist mutations, sync on reconnect
- **Generated types** from `jarvis-contracts` (OpenAPI → Dart)

**Authentication**:
- **Tailscale OAuth** (device authorization flow)
- **JWT** from server (short-lived, refresh via Tailscale identity)
- **Biometric** (FaceID/TouchID, Android BiometricPrompt) for local unlock
- **No passwords** stored on device

**Offline-First**:
- **SQLite** (drift) for local cache
- **Outbox pattern**: Mutations queued, synced when online
- **Conflict resolution**: Server-wins with user notification
- **Background sync**: WorkManager (Android) / BGTaskScheduler (iOS)

**Voice Integration**:
- **STT**: Platform speech recognition (iOS Speech, Android SpeechRecognizer)
- **TTS**: Platform TTS (AVSpeechSynthesizer, Android TextToSpeech)
- **WebRTC** (future): Low-latency streaming via Tailscale

**Testing Strategy**:
- **Unit**: `flutter test` — domain, repository, use cases (≥80%)
- **Widget**: `flutter test` — component behavior (≥70%)
- **Integration**: `patrol` — full app flows (≥60%)
- **Golden**: Visual regression for critical screens
- **Contract**: Pact consumer tests against server

## Rationale
- **Flutter**: Single codebase iOS/Android, high performance, Material 3
- **Tailscale**: Zero-trust network, no public endpoints, device identity
- **Clean Architecture**: Testable, maintainable, platform-agnostic domain
- **Certificate pinning**: Prevents MITM even on compromised networks
- **Offline-first**: Reliable UX on flaky mobile networks

## Security Requirements (Non-Negotiable)
1. **Zero public exposure**: Server API only accessible via Tailscale
2. **Certificate pinning**: Enforced on all API connections
3. **mTLS**: Tailscale provides WireGuard encryption + device identity
4. **ACL enforcement**: Mobile tag can only access `/api/v1/*` on server
5. **No secrets in repo**: All config via environment/flavors
6. **Biometric gate**: App unlock requires biometric/passcode

## Consequences
- Requires Tailscale infrastructure (coordination server, subnet routers)
- Flutter FFI for tsnet adds build complexity
- Mobile CI needs Tailscale for integration tests
- Apple/Google Play review: document Tailscale usage

## Related
- ADR 001: Repository Structure
- ADR 002: Server Architecture
- ADR 004: Tailscale Network Design
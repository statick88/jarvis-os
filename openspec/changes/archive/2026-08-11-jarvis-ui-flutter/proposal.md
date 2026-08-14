# Proposal: Cliente Nativo Flutter para Jarvis-OS

## Intent
Build a native Flutter client (`jarvis_ui`) for macOS and Android that serves as the primary human interface to `jarvis-os`, enabling text chat, voice input/output, and real-time status monitoring of backend services.

## Scope
- **In scope:**
  - Flutter app for macOS and Android
  - Text chat with `gentle-orchestrator` via REST (`/v1/execute`, `/health`)
  - Voice recording → STT via `voice-pipeline:8080` (`/stt`)
  - TTS playback from `voice-pipeline:8080` (`/tts`)
  - Service health status header (orchestrator, voice, floci)
  - Markdown rendering for assistant responses
  - State management with Riverpod

- **Out of scope:**
  - iOS support in this change
  - Web support
  - Direct S3/SQS access from mobile client
  - Authentication beyond `X-Jarvis-Token` header

## Approach
1. Initialize Flutter project with `macos` and `android` platforms.
2. Configure platform entitlements/permissions (network, microphone).
3. Implement `JarvisApiService` (Dio) with dynamic host resolution (`127.0.0.1` for macOS, `10.0.2.2` for Android emulator).
4. Implement `AudioVoiceService` using `record` and `audioplayers` packages.
5. Build `HomeScreen` with health pills, chat history, and multimodal input bar.
6. Validate with `flutter run -d macos` and E2E pipeline.

## Tradeoffs
- **Chosen:** Dio over http for richer interceptors/timeout control.
- **Chosen:** Riverpod for state management (lightweight, testable).
- **Deferred:** gRPC for voice pipeline; REST is sufficient and simpler for mobile.
- **Deferred:** WebSocket for real-time updates; polling health endpoint is acceptable for v1.

## Rollback
- Revert `jarvis_ui/` to initial Flutter scaffold.
- Remove added dependencies from `pubspec.yaml`.
- Restore original `pubspec.yaml` and platform configs.

# Tasks — Cliente Nativo Flutter (jarvis-ui-flutter)

## Phase 1: Foundation
- [x] 1.1 Initialize Flutter project with `macos,android` platforms (`flutter create --platforms=macos,android jarvis_ui`)
- [x] 1.2 Add dependencies: `dio`, `record`, `audioplayers`, `flutter_riverpod`, `flutter_markdown_plus`
- [x] 1.3 Configure macOS entitlements (`network.client`, `audio-input`) and `Info.plist` microphone usage description
- [x] 1.4 Configure Android `AndroidManifest.xml` with `INTERNET` and `RECORD_AUDIO` permissions
- [x] 1.5 Clean linter warnings (`avoid_print`) replacing with `debugPrint`

## Phase 2: Services Layer
- [x] 2.1 Implement `JarvisApiService` with dynamic host resolution and `X-Jarvis-Token` header
- [x] 2.2 Implement `getHealth()` polling for orchestrator, voice, and floci
- [x] 2.3 Implement `postCommand(String prompt)` → `POST /v1/execute`
- [x] 2.4 Implement `AudioVoiceService` with `startRecording()`, `stopRecording()`, `transcribe()`, and `speak()`
- [x] 2.5 Add retry policy for transient network errors in `JarvisApiService`

## Phase 3: UI Layer
- [x] 3.1 Create `HomeScreen` with health status pills header
- [x] 3.2 Implement chat message list with user/assistant bubbles and Markdown rendering
- [x] 3.3 Implement text input bar with send button
- [x] 3.4 Implement mic button with recording animation and state toggle

## Phase 4: Integration & Verification
- [x] 4.1 Wire providers to `HomeScreen` and verify state updates
- [x] 4.2 Run `flutter analyze` and fix warnings
- [x] 4.3 Run `flutter test` and ensure smoke test passes
- [x] 4.4 Run `flutter run -d macos` and verify health check + text command end-to-end
- [ ] 4.5 Run `scripts/test_jarvis_pipeline.sh` to confirm backend compatibility

# Design — Cliente Nativo Flutter (jarvis-ui-flutter)

## Architecture
```
jarvis_ui/
├── lib/
│   ├── main.dart                 # App entry, ProviderScope
│   ├── services/
│   │   ├── jarvis_api_service.dart   # Dio client for orchestrator
│   │   └── audio_voice_service.dart  # Record + AudioPlayers for voice
│   ├── providers/
│   │   └── jarvis_providers.dart     # Riverpod providers
│   └── screens/
│       └── home_screen.dart          # Main UI: health pills, chat, input bar
├── macos/
│   └── Runner/
│       ├── DebugProfile.entitlements # Network client + audio input
│       ├── Release.entitlements      # Network client + audio input
│       └── Info.plist               # NSMicrophoneUsageDescription
└── android/
    └── app/src/main/
        └── AndroidManifest.xml       # INTERNET + RECORD_AUDIO
```

## Sequence: Text Command
1. User types prompt → taps send.
2. `HomeScreen` adds user message to chat state.
3. `JarvisApiService.postCommand()` POSTs to `/v1/execute` with `X-Jarvis-Token`.
4. Response parsed and added as assistant message.
5. UI re-renders with Markdown body.

## Sequence: Voice Input
1. User taps mic button → `AudioVoiceService.startRecording()`.
2. Recording indicator shown.
3. User taps mic again → recording stops.
4. Audio file sent to `voice-pipeline:8080/stt` as multipart.
5. Transcribed text sent to orchestrator via `postCommand()`.

## Sequence: Voice Output
1. Orchestrator or TTS endpoint returns audio bytes.
2. `AudioVoiceService.speak()` plays bytes via `AudioPlayer`.

## Platform Constraints
- **macOS:** Sandbox entitlements require explicit `com.apple.security.network.client` and `com.apple.security.device.audio-input`. `NSMicrophoneUsageDescription` mandatory in `Info.plist`.
- **Android:** `RECORD_AUDIO` permission required at runtime (not just manifest).

## State Management
- `Riverpod` providers for:
  - `JarvisApiService` instance
  - `AudioVoiceService` instance
  - `healthStatusProvider` (`FutureProvider`)
  - `chatMessagesProvider` (`StateProvider<List<Map<String, dynamic>>>`)
  - `isRecordingProvider` (`StateProvider<bool>`)

# Delta Spec — Cliente Nativo Flutter (jarvis-ui-flutter)

## ADDED Requirements

### RF-UI-01: Project Initialization
The client MUST be a Flutter project targeting macOS and Android platforms, located at `jarvis_ui/`.

### RF-UI-02: Health Status Display
The app MUST display real-time health status of three backend services: `gentle-orchestrator` (port 3000), `voice-pipeline` (port 8080), and `floci-localstack` (port 4566).

### RF-UI-03: Text Chat
The app MUST provide a text input field that sends user prompts to `POST /v1/execute` on the orchestrator and displays parsed responses with Markdown support.

### RF-UI-04: Voice Input (STT)
The app MUST support audio recording from the device microphone and send recorded audio to `POST /stt` on `voice-pipeline:8080` for transcription.

### RF-UI-05: Voice Output (TTS)
The app MUST support playback of synthesized speech returned from `POST /tts` on `voice-pipeline:8080`.

### RF-UI-06: Cross-Platform Host Resolution
The app MUST resolve the backend host as `127.0.0.1` on macOS and `10.0.2.2` on Android emulator, with support for configurable IP on physical devices.

### RF-UI-07: Authentication
All API requests to the orchestrator MUST include the `X-Jarvis-Token` header sourced from app configuration.

## MODIFIED Requirements

None.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

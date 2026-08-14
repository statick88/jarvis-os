# Delta Spec — Streaming de Audio Bidireccional y Baja Latencia (jarvis-audio-streaming)

## ADDED Requirements

### RF-AUDIO-01: WebSocket Audio Ingestion
The system MUST expose a WebSocket endpoint on `voice-pipeline` that accepts PCM/WAV audio chunks from Flutter clients in real time.

### RF-AUDIO-02: Incremental STT Transcription
The system MUST return partial transcription results from Whisper before the client finishes speaking, enabling low-latency UI feedback.

### RF-AUDIO-03: Streaming TTS Chunked Playback
The system MUST stream synthesized audio chunks to Flutter as they are produced by the TTS engine, rather than waiting for the full utterance.

### RF-AUDIO-04: Continuous Audio Buffer in Flutter
The Flutter client MUST maintain a circular audio buffer that plays chunks with sub-second TTFB and smooth continuity.

### RF-AUDIO-05: HTTP Fallback
The system MUST preserve REST HTTP `/stt` and `/tts` endpoints as functional fallback when WebSocket is unavailable.

## MODIFIED Requirements

None.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

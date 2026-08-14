# Tasks: Streaming de Audio Bidireccional y Baja Latencia (jarvis-audio-streaming)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~700 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: Foundation Sockets → PR 2: Flutter Audio Buffer → PR 3: Server Voice Stream + Verification |
| Delivery strategy | ask-on-risk |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | WebSocket transport: proto, deps, server route, framing, client transport | PR 1 | `pytest -k ws` | uvicorn + ws probe | Revert server.py, client.py, Dockerfile.voice, audio_stream.proto |
| 2 | Flutter streaming client: service, ring buffer, playback, reconnection | PR 2 | `flutter test test/services/audio_stream_service_test.dart` | Flutter driver vs mock ws | Revert audio_stream_service.dart |
| 3 | Server streaming logic: incremental STT, chunked TTS, session mgmt, E2E tests | PR 3 | `bash scripts/test_audio_streaming.sh` | Docker compose voice-pipeline | Revert server.py additions + test script |

## Phase 1: Foundation Sockets

- [x] 1.1 Add `websockets==12.0` and `soundfile==0.12.1` to api-build stage in `docker/Dockerfile.voice`
- [x] 1.2 Create `spec/contracts/audio_stream.proto` with `AudioStreamRequest` / `AudioStreamResponse` messages
- [x] 1.3 Add `@app.websocket("/v1/audio/stream")` route to `jarvis_os/voice_bridge/server.py` with accept and session_open dispatch
- [x] 1.4 Implement bidirectional message framing: JSON control text frames + raw PCM binary frames
- [x] 1.5 Add `JarvisVoiceBridgeWS` class to `jarvis_os/voice_bridge/client.py` with `ws_transcribe()` / `ws_tts()` async generators
- [x] 1.6 Verify WebSocket handshake, session_open/session_ack exchange, and ping/pong keepalive

## Phase 2: Flutter Audio Buffer

- [x] 2.1 Create `jarvis_ui/lib/services/audio_stream_service.dart` with WebSocket connect, sendAudio, sendText, close, stream getters
- [x] 2.2 Implement `CircularAudioBuffer` class: fixed-size `Uint8List`, configurable `bufferMs` (default 500), write/read pointers, overflow/underflow guards
- [x] 2.3 Integrate `audioplayers` package: feed `TTSChunk` bytes via continuous `AudioSource` for sub-second TTFB
- [x] 2.4 Add exponential backoff reconnection (base 1s, max 30s, jitter) and session resumption on disconnect
- [x] 2.5 Expose `Stream<STTPartial>` onPartialTranscript, `Stream<STTFinal>` onFinalTranscript, `Stream<TTSChunk>` onAudioChunk

## Phase 3: Server Voice Stream

- [x] 3.1 Implement incremental STT: spawn `whisper-cli` subprocess, pipe PCM chunks to stdin, parse stdout, emit `stt_partial` / `stt_final`
- [x] 3.2 Implement chunked TTS: receive `tts_input` chunks, synthesize per-chunk via Piper/Kokoro, stream `tts_chunk` binary frames
- [x] 3.3 Wire LLM stream to `ChunkedTTSPipeline`: send `tts_input` frames as LLM partials arrive in WebSocket handler
- [x] 3.4 Preserve REST HTTP `/stt` and `/tts` endpoints as explicit fallback
- [x] 3.5 Add `SessionManager`: active session dict by session_id, track created_at/last_activity, cleanup expired sessions on disconnect

## Phase 4: Verification

- [x] 4.1 Create `scripts/test_audio_streaming.sh`: start voice-pipeline, ws connect, send 5s PCM fixture, assert handshake
- [x] 4.2 Measure STT partial latency: timestamp audio_chunk send vs stt_partial receive, assert < 300ms over 10 iterations
- [x] 4.3 Measure TTS TTFB: timestamp tts_input send vs first tts_chunk receive, assert < 500ms over 10 iterations
- [x] 4.4 Run 30-minute continuous stream: send 100ms chunks every 100ms, sample RSS every 60s, assert memory bounded
- [x] 4.5 Update `.progress` and `state.yaml` with completion percentages and phase transitions

# Design: Streaming de Audio Bidireccional y Baja Latencia (jarvis-audio-streaming)

## Technical Approach

Replace the synchronous REST round-trip STT/TTS flow with a persistent bidirectional WebSocket channel between `jarvis_ui` (Flutter) and `voice-pipeline` (FastAPI). Audio chunks flow upstream to Whisper.cpp for incremental transcription; LLM partial text chunks flow downstream to Piper/Kokoro for chunked synthesis. The existing REST endpoints (`/stt`, `/tts`) remain functional as an explicit fallback path. All WebSocket logic lives in `voice_bridge/server.py` as a new route alongside existing REST handlers; the gRPC client module (`client.py`) is left untouched for backward compatibility.

## Architecture Decisions

### Decision: WebSocket over gRPC bidirectional streaming

**Choice**: FastAPI WebSocket (`/v1/audio/stream`) as the primary streaming transport.

**Alternatives considered**: gRPC bidirectional streaming (`StreamSTT`/`StreamTTS` already defined in `voice_api.proto`), raw TCP, Server-Sent Events.

**Rationale**: Mobile Flutter has native `WebSocket` support with straightforward reconnection semantics. gRPC on Flutter requires `grpc-dart` with platform channel plumbing on Android, adding ~200 lines of platform-specific setup for the same wire efficiency. The existing `client.py` has `stream_transcribe`/`stream_tts` stubs — they remain as a gRPC fallback for server-to-server use. WebSocket JSON framing is acceptable given the audio payload is bytes; control messages are small.

### Decision: PCM 16 kHz 16-bit mono as wire audio format

**Choice**: Raw PCM little-endian, 16 kHz sample rate, mono, 16-bit signed integers.

**Alternatives considered**: WAV (with header per chunk), Opus-encoded frames, MP3 chunks.

**Rationale**: Whisper.cpp CLI accepts raw PCM natively, eliminating per-chunk header parsing and transcoding. The Flutter `recorder` can output raw PCM directly. A single `format` field in the session-open message future-proofs for Opus if bandwidth becomes a constraint. Chunk size: 1600 samples (100 ms at 16 kHz ≈ 3.2 KB), balancing latency vs. framing overhead.

### Decision: whisper-cli subprocess for STT, Piper/Kokoro for TTS

**Choice**: Reuse the compiled `whisper-cli` binary and Piper/Kokoro already built into `Dockerfile.voice`. No new ML runtime dependency.

**Alternatives considered**: Python bindings (faster-whisper), cloud STT APIs, ONNX Runtime Whisper.

**Rationale**: The Docker image already stages whisper-cli, Piper, and Kokoro with Metal/NEON acceleration. Introducing faster-whisper or cloud APIs adds dependency surface and contradicts the offline-first constraint. Subprocess invocation matches the entrypoint pattern established in `entrypoint.voice.sh`.

### Decision: Ring buffer in Flutter (client-side jitter buffer)

**Choice**: Fixed-size circular byte buffer (default 500 ms) in `AudioStreamService`; drain to `AudioPlayer` on a low-priority isolate.

**Alternatives considered**: Zero-buffer (play chunks as they arrive), large 2-second buffer.

**Rationale**: Zero-buffer causes audible glitches on jitter > 50 ms. A 500 ms ring absorbs normal mobile WiFi variation while keeping TTFB below 800 ms for the user. 2-second buffer pushes perceived latency past the 1-second UX threshold. Buffer size is configurable via constructor parameter for tuning.

### Decision: Wake-word deferred to post-streaming phase

**Choice**: No wake-word engine in this phase. The WebSocket endpoint design includes a `vad_mode` field in the session-open message as a placeholder.

**Alternatives considered**: Integrating Porcupine (Picovoice) or ML-based VAD in Flutter now.

**Rationale**: Wake-word adds an always-on microphone permission requirement and a third-party SDK dependency. The proposal explicitly marks it optional for the initial phase. The `vad_mode` field allows zero-protocol-change activation in FASE 10.

### Decision: REST fallback preserved as explicit alternate path

**Choice**: `/stt` (POST) and `/tts` (POST) remain unchanged. Client selects transport based on `websocket_enabled` flag returned by `/health`.

**Rationale**: Zero migration for existing REST consumers. The Flutter client detects capability at startup and switches transparently. WebSocket unavailability (behind proxy, old server) degrades gracefully.

## Data Flow

```
Flutter jarvis_ui                      voice-pipeline (FastAPI)
───────────────────                    ──────────────────────────

AudioRecorder ──PCM chunks──► WS /v1/audio/stream ──► whisper-cli (subprocess)
                                                              │
◄─── STT partial (text) ────── is_final=false ──────────────┤
                                                              ▼
                                                   TranscribeResult (incremental)
                                                              │
◄─── STT final (text) ─────── is_final=true ────────────────┤
         │                                                   │
         ▼                                                   │
   UI: display text ─────────────────────────────────────────┘

User speaks → LLM stream ──partial text chunks──► WS /v1/audio/stream
                                                              │
                                                 TTS chunked pipeline
                                                 (Piper/Kokoro per chunk)
                                                              │
◄─── AudioChunk (binary) ─────────────────────────────────────┘
         │
         ▼
   RingBuffer ──► AudioPlayer (continuous)
```

Session lifecycle:
1. Flutter opens WS, sends `session_open` with `{session_id, format, sample_rate, vad_mode}`.
2. Server responds `session_ack` with `{session_id, websocket_enabled, stt_model, tts_voice}`.
3. Audio flows upstream as `audio_chunk` binary frames; server emits `stt_partial` / `stt_final` text frames.
4. LLM partial text flows downstream as `tts_input` text frames; server emits `tts_chunk` binary frames.
5. Either side sends `session_close`; remaining audio is drained and connection closes cleanly.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `jarvis_os/voice_bridge/server.py` | Modify | Add `/v1/audio/stream` WebSocket route, session manager, whisper-cli subprocess wrapper, TTS chunked pipeline |
| `jarvis_os/voice_bridge/models.py` | Modify | Add `SessionOpen`, `SessionAck`, `AudioChunkMsg`, `STTPartial`, `STTFinal`, `TTSInput`, `TTSChunk`, `SessionClose`, `ErrorMsg` Pydantic models |
| `spec/contracts/audio_stream.proto` | Create | Protobuf messages for WebSocket framing (optional; server uses JSON, proto used for gRPC fallback parity) |
| `jarvis_ui/lib/services/audio_stream_service.dart` | Create | WebSocket client, ring buffer, reconnection logic, Dart interface |
| `docker/Dockerfile.voice` | Modify | Add `websockets` and `soundfile` Python packages to api-build stage |
| `docker/docker-compose.yml` | No change | Port 8080 already exposed; WebSocket shares HTTP port |
| `scripts/test_audio_streaming.sh` | Create | E2E latency and stability test script |

## Interfaces / Contracts

### WebSocket message envelope (JSON, server ↔ Flutter)

All messages share a top-level `type` discriminator. Binary audio frames are raw `bytes` (not base64 in the implementation; sent as WebSocket binary frames).

```python
# Session control
SessionOpen   = {"type": "session_open",   "session_id": str, "format": str, "sample_rate": int, "vad_mode": str}
SessionAck    = {"type": "session_ack",    "session_id": str, "websocket_enabled": bool, "stt_model": str, "tts_voice": str}
SessionClose  = {"type": "session_close",  "session_id": str, "reason": str}
ErrorMsg      = {"type": "error",          "session_id": str, "code": str, "message": str}

# Audio → STT (binary frame = raw PCM bytes; first frame may carry metadata as JSON)
AudioChunkMsg = {"type": "audio_chunk",    "session_id": str, "is_final": bool, "timestamp_ms": int}

# STT → Flutter
STTPartial    = {"type": "stt_partial",    "session_id": str, "text": str, "confidence": float}
STTFinal      = {"type": "stt_final",      "session_id": str, "text": str, "confidence": float, "duration_ms": int, "segments": list}

# LLM → TTS (text streaming from orchestrator)
TTSInput      = {"type": "tts_input",      "session_id": str, "text": str, "voice": str, "speed": float}

# TTS → Flutter (binary frame = synthesized audio bytes)
TTSChunk      = {"type": "tts_chunk",      "session_id": str, "format": str, "sample_rate": int, "is_final": bool, "duration_ms": int}
```

### Dart service interface (`audio_stream_service.dart`)

```dart
abstract class AudioStreamService {
  /// Connect to the voice-pipeline WebSocket endpoint.
  /// Throws [ConnectionException] if the server does not support WebSocket.
  Future<void> connect(Uri endpoint, {String? token});

  /// Send raw PCM audio bytes. Throws if not connected.
  void sendAudio(Uint8List pcmBytes, {bool isFinal = false});

  /// Send a text chunk for TTS synthesis.
  void sendText(String text, {String voice = 'es_ES-pacifico', double speed = 1.0});

  /// Close the session cleanly.
  Future<void> close({String reason = 'client_disconnect'});

  /// Stream of partial STT results.
  Stream<STTPartial> get onPartialTranscript;

  /// Stream of final STT results.
  Stream<STTFinal> get onFinalTranscript;

  /// Stream of synthesized audio chunks.
  Stream<TTSChunk> get onAudioChunk;

  /// Stream of connection state changes.
  Stream<ConnectionState> get onStateChange;

  /// Current ring buffer fill level (0.0 - 1.0).
  double get bufferFillRatio;
}
```

### Health endpoint extension

`/health` gains an optional `websocket_enabled: bool` field in the JSON response so the Flutter client can detect capability at startup without attempting a connection.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (Python) | WebSocket route routing, session lifecycle, message validation, whisper-cli subprocess wrapper, TTS chunked pipeline | FastAPI `TestClient` with `websockets` library; mock subprocess with `unittest.mock.patch`; pytest |
| Unit (Dart) | Ring buffer overflow/underflow, reconnection backoff, PCM send/receive, state machine transitions | `flutter test` with mock `WebSocketChannel`; buffer edge cases: empty, full, network drop mid-fill |
| Integration | whisper-cli incremental transcription against real audio fixtures, Piper/Kokoro chunked synthesis, E2E WS round-trip in Docker | `scripts/test_audio_streaming.sh` using `arecord`/`aplay` fixtures inside the running container |
| E2E | Latency: STT partial < 300 ms, TTS TTFB < 500 ms, 30-minute stability, memory bounded | Shell script with timestamped probes; `curl` health + WS ping/pong; `ps` RSS sampling |

## Threat Matrix

N/A — This design does not change routing logic, shell command execution, subprocess management, VCS/PR automation, executable-file classification, or process-integration boundaries beyond the existing `whisper-cli` subprocess pattern already present in `entrypoint.voice.sh`. WebSocket routing is a standard FastAPI route addition; no new shell execution paths are introduced.

## Migration / Rollout

No database migration required. The change is additive:

1. **Phase A (server)**: Deploy updated `voice-pipeline` container. REST endpoints unchanged; WebSocket endpoint coexists on port 8080.
2. **Phase B (Flutter)**: Release `jarvis_ui` update with `AudioStreamService`. Client detects `websocket_enabled` from `/health`; uses WebSocket when true, REST fallback otherwise.
3. **Rollback**: Revert `server.py` and `AudioStreamService`; REST fallback continues working with zero downtime.

## Open Questions

- [ ] **OQ-01**: Does `gentle-orchestrator` already expose a streaming response hook for LLM chunks, or must `voice-pipeline` pull from a queue (SQS/local)? This determines whether the TTS chunked pipeline is push or pull.
- [ ] **OQ-02**: What is the actual RSS footprint of whisper-cli loaded with `base` model during a 30-minute session? Needed to validate the 4 GB container memory limit.
- [ ] **OQ-03**: Should the existing gRPC `client.py` be kept alive as a secondary transport, deprecated, or removed? Decision affects maintenance burden.
- [ ] **OQ-04**: Audio format negotiation — should the `session_open` message include a codec field (pcm/opus) or is PCM-only sufficient for FASE 9?
- [ ] **OQ-05**: Reconnection strategy: on WebSocket drop, does the client resume the session (with a `resume_token`) or start fresh? Affects state design in `server.py`.

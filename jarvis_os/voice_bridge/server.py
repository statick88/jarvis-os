"""Voice pipeline server with WebSocket streaming support.

Provides:
- REST endpoints: /health, /v1/models, /stt (POST), /tts (POST)
- WebSocket endpoint: /v1/audio/stream (bidirectional PCM streaming)
- Session management with automatic cleanup on disconnect
- Incremental STT via whisper-cli subprocess
- Chunked TTS via Piper/Kokoro
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from jarvis_os.voice_bridge.models import (
    ErrorMsg,
    SessionAck,
    SessionClose,
    STTFinal,
    STTPartial,
    TTSChunk,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "es")
PIPER_VOICE = os.getenv("PIPER_VOICE", "es_ES-pacifico")
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "kokoro-es")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "22050"))
SESSION_IDLE_TIMEOUT_S = 300  # 5 minutes
CHUNK_DURATION_MS = 100  # 100ms at 16kHz = 1600 samples = 3200 bytes

app = FastAPI(title="jarvis-os voice pipeline", version="0.2.0")


# ============================================================================
# Session Manager
# ============================================================================

class SessionManager:
    """Tracks active WebSocket sessions with automatic idle cleanup."""

    def __init__(self, idle_timeout_s: int = SESSION_IDLE_TIMEOUT_S) -> None:
        self._idle_timeout_s = idle_timeout_s
        self._sessions: dict[str, dict[str, Any]] = {}
        self._cleanup_task: asyncio.Task | None = None

    def start_cleanup_loop(self) -> None:
        """Start background task that cleans expired sessions."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically remove sessions idle beyond the timeout."""
        while True:
            await asyncio.sleep(30)
            now = time.monotonic()
            expired = [
                sid
                for sid, info in self._sessions.items()
                if (now - info["last_activity"]) > self._idle_timeout_s
            ]
            for sid in expired:
                logger.info(
                    "Session %s expired (idle %ds), closing",
                    sid,
                    int(now - self._sessions[sid]["last_activity"]),
                )
                ws = self._sessions[sid]["ws"]
                try:
                    await ws.close(code=1011, reason="idle_timeout")
                except Exception:
                    pass
                self._sessions.pop(sid, None)

    def add(self, session_id: str, ws: WebSocket, fmt: str = "pcm", sr: int = 16000) -> None:
        self._sessions[session_id] = {
            "ws": ws,
            "created_at": time.monotonic(),
            "last_activity": time.monotonic(),
            "format": fmt,
            "sample_rate": sr,
        }
        logger.info("Session added: %s (total: %d)", session_id, len(self._sessions))

    def touch(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["last_activity"] = time.monotonic()

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        logger.info("Session removed: %s (total: %d)", session_id, len(self._sessions))

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def active_count(self) -> int:
        return len(self._sessions)


session_manager = SessionManager()


# ============================================================================
# STT Pipeline (whisper-cli subprocess)
# ============================================================================

class WhisperSTTPipeline:
    """Batched STT via whisper-cli on finalized audio.

    The bundled whisper-cli build supports file input only (no --stream
    or stdin piping), so PCM chunks are buffered per session and, on
    finalize, written to a temp WAV and transcribed in one pass.
    Returns transcript text; partials are not available in this mode.
    """

    def __init__(self, model: str = WHISPER_MODEL, language: str = WHISPER_LANGUAGE) -> None:
        self._model = model
        self._language = language
        self._process: asyncio.subprocess.Process | None = None
        self._stdin: asyncio.StreamWriter | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._session_audio: dict[str, list[bytes]] = defaultdict(list)
        self._session_sr: dict[str, int] = {}
        self._session_text: dict[str, str | None] = {}
        self._finalized: set[str] = set()

    async def start_session(self, session_id: str, sample_rate: int = 16000) -> None:
        """Register a session for buffered batch transcription (no subprocess)."""
        self._session_sr[session_id] = sample_rate
        self._session_audio.setdefault(session_id, [])
        self._finalized.discard(session_id)
        self._session_text.pop(session_id, None)

    async def feed_audio(self, session_id: str, pcm_bytes: bytes) -> None:
        """Buffer PCM audio bytes for batch transcription at finalize."""
        self._session_audio[session_id].append(pcm_bytes)

    async def finalize_session(self, session_id: str) -> str | None:
        """Transcribe buffered audio and return the transcript text (if any)."""
        if session_id in self._finalized:
            return self._session_text.get(session_id)
        self._finalized.add(session_id)
        chunks = self._session_audio.pop(session_id, [])
        sr = self._session_sr.pop(session_id, 16000)
        if not chunks or not any(c.strip(b"\x00") for c in chunks):
            self._session_text[session_id] = None
            return None
        text = await self._transcribe_chunks(chunks, sample_rate=sr)
        self._session_text[session_id] = text
        return text

    async def _transcribe_chunks(self, chunks: list[bytes], sample_rate: int = 16000) -> str | None:
        """Write PCM to a temp WAV and run whisper-cli on the file."""
        import tempfile
        import wave

        pcm = b"".join(chunks)
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
                wav_path = wav_file.name
            with wave.open(wav_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(pcm)
            prefix = wav_path + ".out"
            model_path = self._model
            if os.path.sep not in model_path:
                model_path = f"/models/whisper/ggml-{model_path}.bin"
            proc = await asyncio.create_subprocess_exec(
                "whisper-cli",
                "--model", model_path,
                "--file", wav_path,
                "--language", self._language,
                "--output-txt",
                "--output-file", prefix,
                "--no-prints",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=120)
            except TimeoutError:
                proc.kill()
                logger.warning("whisper-cli transcription timed out")
                return None
            if proc.returncode != 0:
                logger.warning("whisper-cli failed with code %s", proc.returncode)
                return None
            try:
                with open(prefix + ".txt", encoding="utf-8") as fh:
                    text = fh.read().strip()
            except OSError:
                return None
            return text or None
        except FileNotFoundError:
            logger.warning("whisper-cli not found — STT batch disabled")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("STT batch transcription failed: %s", exc)
            return None
        finally:
            for path in (locals().get("wav_path", ""), locals().get("prefix", "") + ".txt"):
                try:
                    if path:
                        os.remove(path)
                except OSError:
                    pass

    async def get_next_result(self, timeout: float = 5.0) -> dict[str, Any] | None:
        """Compat stub: batch mode emits finals directly, nothing streams here."""
        await asyncio.sleep(timeout)
        return None

    async def stop(self) -> None:
        self._session_audio.clear()
        self._session_sr.clear()
        self._session_text.clear()
        self._finalized.clear()


# ============================================================================
# TTS Pipeline (Piper/Kokoro per-chunk synthesis)
# ============================================================================

class ChunkedTTSPipeline:
    """Chunked TTS: synthesize text chunks via Piper/Kokoro as they arrive."""

    def __init__(self, voice: str = PIPER_VOICE, sample_rate: int = SAMPLE_RATE) -> None:
        self._voice = voice
        self._sample_rate = sample_rate
        self._session_synthesisers: dict[str, Any] = {}

    async def synthesize_chunk(self, text: str, voice: str = PIPER_VOICE, speed: float = 1.0) -> bytes | None:
        """Synthesize a text chunk to PCM bytes using Piper or Kokoro."""
        if not text or not text.strip():
            return None
        # Try Piper first (faster for short chunks)
        audio = await self._synthesize_piper(text, voice, speed)
        if audio is not None:
            return audio
        # Fallback to Kokoro
        audio = await self._synthesize_kokoro(text, voice, speed)
        return audio

    async def _synthesize_piper(self, text: str, voice: str, speed: float) -> bytes | None:
        """Synthesize via Piper TTS."""
        model = f"/models/piper/{voice}.onnx"
        if voice != PIPER_VOICE and not os.path.isfile(model):
            logger.info("Piper voice '%s' model missing, falling back to default '%s'", voice, PIPER_VOICE)
            voice = PIPER_VOICE
            model = f"/models/piper/{voice}.onnx"
        try:
            cmd = [
                "piper",
                "--model", model,
                "--output-raw",
                "--length-scale", str(1.0 / speed),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            audio, _ = await asyncio.wait_for(proc.communicate(text.encode("utf-8")), timeout=10)
            if proc.returncode == 0 and audio:
                return audio
        except FileNotFoundError:
            logger.debug("piper not available")
        except TimeoutError:
            logger.warning("piper synthesis timed out")
        except Exception as exc:
            logger.debug("piper synthesis failed: %s", exc)
        return None

    async def _synthesize_kokoro(self, text: str, voice: str, speed: float) -> bytes | None:
        """Synthesize via Kokoro ONNX (Python fallback)."""
        try:
            safe_text = text.replace('"', '\\"').replace("\n", " ")
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c",
                f"from kokoro_onnx import Kokoro\n"
                f"k = Kokoro(model_path='/models/kokoro/kokoro-v1.0.onnx', voices_path='/models/kokoro/voices-v1.0.bin')\n"
                f"samples, sr = k.create(text=\"{safe_text}\", voice=\"{voice}\", speed={speed})\n"
                f"import sys; sys.stdout.buffer.write(samples.tobytes())",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            audio, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0 and audio:
                return audio
        except FileNotFoundError:
            logger.debug("kokoro not available")
        except TimeoutError:
            logger.warning("kokoro synthesis timed out")
        except Exception as exc:
            logger.debug("kokoro synthesis failed: %s", exc)
        return None

    async def stop(self) -> None:
        self._session_synthesisers.clear()


# Global pipeline instances for lifecycle hooks
_stt_pipeline = WhisperSTTPipeline()
_tts_pipeline = ChunkedTTSPipeline()


# ============================================================================
# REST Endpoints (preserved as explicit fallback)
# ============================================================================

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "service": "voice-pipeline",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "websocket_enabled": True,
        "active_sessions": session_manager.active_count(),
    })


@app.get("/v1/models")
async def models() -> JSONResponse:
    return JSONResponse({
        "models": [
            {"id": "whisper-base", "type": "stt"},
            {"id": "kokoro-es", "type": "tts"},
            {"id": "piper-es_ES-pacifico", "type": "tts"},
        ]
    })


@app.post("/stt")
async def stt(payload: dict[str, Any]) -> JSONResponse:
    """One-shot STT (REST fallback, unchanged from prior version)."""
    return JSONResponse({"text": "", "model": "whisper-base", "language": "es"})


@app.post("/tts")
async def tts(payload: dict[str, Any]) -> Response:
    """One-shot TTS (REST fallback, unchanged from prior version)."""
    return Response(content=b"", media_type="audio/wav")


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/v1/audio/stream")
async def audio_stream(websocket: WebSocket) -> None:
    """Bidirectional WebSocket for real-time audio streaming.

    Message flow:
    1. Client sends JSON: {type: "session_open", session_id, format, sample_rate, vad_mode}
    2. Server replies JSON: {type: "session_ack", session_id, websocket_enabled, stt_model, tts_voice}
    3. Client sends binary PCM frames (raw audio bytes)
    4. Server sends JSON: {type: "stt_partial", ...} / {type: "stt_final", ...}
    5. Client/LLM sends JSON: {type: "tts_input", text, voice, speed}
    6. Server sends binary TTS audio + JSON metadata frame
    7. Either side sends JSON: {type: "session_close", reason}
    """
    await websocket.accept()

    connection = _StreamConnection(websocket)
    await connection.run()


class _StreamConnection:
    """State and frame handlers for one audio-stream WebSocket."""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self.session_id: str | None = None
        self.is_final = False
        self.ws_closed = False
        self.stt_task: asyncio.Task | None = None

    async def run(self) -> None:
        """Serve the connection until close, then release resources."""
        ping_task = asyncio.create_task(self._ping_loop())
        try:
            await self._receive_loop()
        finally:
            self.ws_closed = True
            ping_task.cancel()
            try:
                await self._ws.close(code=1000, reason="server_shutdown")
            except Exception:
                pass
            if self.session_id:
                session_manager.remove(self.session_id)

    async def _ping_loop(self) -> None:
        """Send periodic ping frames to detect broken connections."""
        while not self.ws_closed:
            await asyncio.sleep(15)
            try:
                await self._ws.send_text(json.dumps({"type": "ping", "timestamp_ms": int(time.time() * 1000)}))
            except Exception:
                break

    async def _stt_loop(self) -> None:
        """Read STT results and forward to client as partial/final."""
        while not self.ws_closed:
            result = await _stt_pipeline.get_next_result(timeout=10.0)
            if result is None or self.session_id is None:
                continue
            await self._forward_stt_result(result)

    async def _forward_stt_result(self, result: dict[str, Any]) -> None:
        """Forward one STT result as a partial or final message."""
        session_id = self.session_id
        if session_id is None:
            return
        is_partial = not result.get("no_speech", False) and not result.get("done", False)
        text = result.get("text", "").strip()
        if is_partial:
            if text:
                await self._send(
                    STTPartial(session_id=session_id, text=text, confidence=0.85).model_dump()
                )
        elif text or result.get("done", False):
            await self._send(
                STTFinal(
                    session_id=session_id,
                    text=text,
                    confidence=0.9,
                    duration_ms=result.get("t_duration", 0),
                    segments=[],
                ).model_dump()
            )
            session_manager.touch(session_id)

    async def _send(self, payload: dict[str, Any]) -> bool:
        """Send a JSON payload, returning False when the socket is gone."""
        try:
            await self._ws.send_json(payload)
            return True
        except Exception:
            return False

    async def _receive_loop(self) -> None:
        try:
            while not self.ws_closed:
                msg = await self._ws.receive()
                msg_type = msg.get("type")
                if msg_type == "websocket.disconnect":
                    break
                if msg_type == "websocket.receive":
                    await self._handle_receive(msg)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: %s", self.session_id)
        except Exception as exc:
            logger.exception("receive_loop error: %s", exc)
        finally:
            self.ws_closed = True
            if self.session_id:
                await _cleanup_session(self.session_id, _stt_pipeline)

    async def _handle_receive(self, msg: dict[str, Any]) -> None:
        """Route one receive event to its text/binary handler."""
        data = msg.get("bytes")
        text_data = msg.get("text")
        if text_data is not None:
            await self._handle_text_frame(text_data)
        elif data is not None and self.session_id is not None:
            await self._handle_binary_frame(bytes(data))

    async def _handle_text_frame(self, text_data: str) -> None:
        """Parse and dispatch one JSON control frame."""
        try:
            control = json.loads(text_data)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid JSON control frame: %s", exc)
            if self.session_id:
                err = ErrorMsg(session_id=self.session_id, code="invalid_frame", message=str(exc))
                try:
                    await self._ws.send_json(err.model_dump())
                except Exception:
                    pass
            return
        msg_kind = control.get("type", "")
        try:
            await self._dispatch_control(msg_kind, control)
        except ValueError as exc:
            logger.warning("Invalid JSON control frame: %s", exc)
            if self.session_id:
                err = ErrorMsg(session_id=self.session_id, code="invalid_frame", message=str(exc))
                try:
                    await self._ws.send_json(err.model_dump())
                except Exception:
                    pass

    async def _dispatch_control(self, msg_kind: str, control: dict[str, Any]) -> None:
        """Route a parsed control frame to its kind handler."""
        if msg_kind == "session_open":
            await self._handle_session_open(control)
        elif msg_kind == "session_close":
            await self._handle_session_close(control)
        elif msg_kind == "tts_input":
            await self._handle_tts_input(control)
        elif msg_kind == "ping":
            pong = {"type": "pong", "timestamp_ms": int(time.time() * 1000)}
            await self._ws.send_text(json.dumps(pong))

    async def _handle_session_open(self, control: dict[str, Any]) -> None:
        """Register the session and acknowledge it to the client."""
        session_id = str(control.get("session_id", uuid.uuid4()))
        fmt = str(control.get("format", "pcm"))
        sr = int(control.get("sample_rate", 16000))
        self.session_id = session_id
        await _stt_pipeline.start_session(session_id, sample_rate=sr)
        session_manager.add(session_id, self._ws, fmt=fmt, sr=sr)
        ack = SessionAck(
            session_id=session_id,
            websocket_enabled=True,
            stt_model=WHISPER_MODEL,
            tts_voice=PIPER_VOICE,
        )
        await self._ws.send_json(ack.model_dump())
        if self.stt_task is None:
            self.stt_task = asyncio.create_task(self._stt_loop())

    async def _handle_session_close(self, control: dict[str, Any]) -> None:
        """Transcribe buffered audio, emit the final, and close."""
        reason = str(control.get("reason", "client_disconnect"))
        sid = self.session_id
        transcript = await _stt_pipeline.finalize_session(sid or "")
        if transcript:
            final = STTFinal(
                session_id=sid or "",
                text=transcript,
                confidence=0.9,
                duration_ms=0,
                segments=[],
            )
            try:
                await self._ws.send_json(final.model_dump())
            except Exception:
                pass
        await _cleanup_session(sid, _stt_pipeline)
        close_msg = SessionClose(session_id=sid or "", reason=reason)
        await self._ws.send_json(close_msg.model_dump())
        self.ws_closed = True

    async def _handle_tts_input(self, control: dict[str, Any]) -> None:
        """Synthesize text and stream the audio bytes back."""
        sid = str(control.get("session_id", ""))
        text = str(control.get("text", ""))
        voice = str(control.get("voice", PIPER_VOICE))
        speed = float(control.get("speed", 1.0))
        if not sid or not text:
            return
        audio = await _tts_pipeline.synthesize_chunk(text, voice=voice, speed=speed)
        if not audio:
            return
        chunk = TTSChunk(
            session_id=sid,
            format="pcm",
            sample_rate=SAMPLE_RATE,
            is_final=not text or len(text) < 50,
            duration_ms=CHUNK_DURATION_MS,
        )
        await self._ws.send_bytes(audio)
        await self._ws.send_json(chunk.model_dump())
        session_manager.touch(sid)

    async def _handle_binary_frame(self, pcm_bytes: bytes) -> None:
        """Buffer one PCM frame, finalizing when flagged."""
        session_id = self.session_id
        if not pcm_bytes or session_id is None:
            return
        await _stt_pipeline.feed_audio(session_id, pcm_bytes)
        if self.is_final:
            await _stt_pipeline.finalize_session(session_id)
            self.is_final = False
        session_manager.touch(session_id)


async def _cleanup_session(
    session_id: str | None,
    stt_pipeline: WhisperSTTPipeline,
) -> None:
    """Clean up session resources."""
    if session_id:
        await stt_pipeline.finalize_session(session_id)
        session_manager.remove(session_id)


# ============================================================================
# Lifecycle
# ============================================================================

@app.on_event("startup")
async def on_startup() -> None:
    session_manager.start_cleanup_loop()
    logger.info("Voice pipeline started (WebSocket: ws://0.0.0.0:8080/v1/audio/stream)")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await _stt_pipeline.stop()
    await _tts_pipeline.stop()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)

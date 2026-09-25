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
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn

from jarvis_os.voice_bridge.models import (
    AudioChunkMsg,
    ErrorMsg,
    HealthResponse,
    SessionAck,
    SessionClose,
    SessionOpen,
    STTFinal,
    STTPartial,
    TTSChunk,
    TTSInput,
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
        self._cleanup_task: Optional[asyncio.Task] = None

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

    def get(self, session_id: str) -> Optional[dict[str, Any]]:
        return self._sessions.get(session_id)

    def active_count(self) -> int:
        return len(self._sessions)


session_manager = SessionManager()


# ============================================================================
# STT Pipeline (whisper-cli subprocess)
# ============================================================================

class WhisperSTTPipeline:
    """Incremental STT via whisper-cli subprocess.

    PCM chunks are piped to whisper-cli stdin; stdout is parsed for
    partial and final results.
    """

    def __init__(self, model: str = WHISPER_MODEL, language: str = WHISPER_LANGUAGE) -> None:
        self._model = model
        self._language = language
        self._process: Optional[asyncio.subprocess.Process] = None
        self._stdin: Optional[asyncio.StreamWriter] = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._session_audio: dict[str, list[bytes]] = defaultdict(list)
        self._finalized: set[str] = set()

    async def start_session(self, session_id: str) -> None:
        """Start a whisper-cli subprocess for the session."""
        if self._process is not None and self._process.returncode is None:
            # Reuse existing subprocess if healthy
            return
        await self._spawn_process()

    async def _spawn_process(self) -> None:
        """Spawn whisper-cli with streaming options."""
        cmd = [
            "whisper-cli",
            "--model", self._model,
            "--language", self._language,
            "--output-txt",
            "--output-csv",
            "--no-prints",
            "--stream", "stdout",
            "--",
        ]
        logger.info("Spawning whisper-cli: %s", " ".join(cmd))
        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._stdin = self._process.stdin
            assert self._process.stdout is not None
            self._reader_task = asyncio.create_task(self._read_stdout(self._process.stdout))
        except FileNotFoundError:
            logger.warning("whisper-cli not found — STT streaming disabled")
            self._process = None
            self._stdin = None

    async def _read_stdout(self, stdout: asyncio.StreamReader) -> None:
        """Parse whisper-cli stdout lines."""
        while True:
            line = await stdout.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                await self._queue.put(data)
            except json.JSONDecodeError:
                logger.debug("whisper stdout (non-JSON): %s", line_str[:200])

    async def feed_audio(self, session_id: str, pcm_bytes: bytes) -> None:
        """Send PCM audio bytes to whisper-cli stdin."""
        if self._stdin is None or self._process is None or self._process.returncode is not None:
            logger.debug("whisper-cli not running, buffering audio for %s", session_id)
            self._session_audio[session_id].append(pcm_bytes)
            return
        self._session_audio[session_id].append(pcm_bytes)
        try:
            self._stdin.write(pcm_bytes)
            await self._stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            logger.warning("whisper-cli pipe broken")

    async def drain_buffered(self, session_id: str) -> None:
        """Flush buffered audio to whisper-cli."""
        if session_id in self._session_audio:
            chunks = self._session_audio.pop(session_id)
            if chunks and self._stdin is not None and self._process is not None and self._process.returncode is None:
                for chunk in chunks:
                    try:
                        self._stdin.write(chunk)
                        await self._stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        break

    async def get_next_result(self, timeout: float = 5.0) -> Optional[dict[str, Any]]:
        """Get next STT result from whisper-cli."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def finalize_session(self, session_id: str) -> None:
        """Signal end of audio for a session."""
        if session_id in self._finalized:
            return
        self._finalized.add(session_id)
        if self._session_audio.get(session_id):
            await self.drain_buffered(session_id)
        # Whisper final result is produced when it receives EOF or silence
        await asyncio.sleep(0.2)

    async def stop(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._process is not None and self._process.returncode is None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                if self._process.returncode is None:
                    self._process.kill()


# ============================================================================
# TTS Pipeline (Piper/Kokoro per-chunk synthesis)
# ============================================================================

class ChunkedTTSPipeline:
    """Chunked TTS: synthesize text chunks via Piper/Kokoro as they arrive."""

    def __init__(self, voice: str = PIPER_VOICE, sample_rate: int = SAMPLE_RATE) -> None:
        self._voice = voice
        self._sample_rate = sample_rate
        self._session_synthesisers: dict[str, Any] = {}

    async def synthesize_chunk(self, session_id: str, text: str, voice: str = PIPER_VOICE, speed: float = 1.0) -> Optional[bytes]:
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

    async def _synthesize_piper(self, text: str, voice: str, speed: float) -> Optional[bytes]:
        """Synthesize via Piper TTS."""
        try:
            cmd = [
                "piper",
                "--model", f"/models/piper/{voice}.onnx",
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
        except asyncio.TimeoutError:
            logger.warning("piper synthesis timed out")
        except Exception as exc:
            logger.debug("piper synthesis failed: %s", exc)
        return None

    async def _synthesize_kokoro(self, text: str, voice: str, speed: float) -> Optional[bytes]:
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
        except asyncio.TimeoutError:
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
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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

    session_id: Optional[str] = None
    is_final = False
    ping_task: Optional[asyncio.Task] = None
    ws_closed = False
    stt_task_ref: list[Optional[asyncio.Task]] = [None]

    async def ping_loop() -> None:
        """Send periodic ping frames to detect broken connections."""
        while not ws_closed:
            await asyncio.sleep(15)
            try:
                await websocket.send_text(json.dumps({"type": "ping", "timestamp_ms": int(time.time() * 1000)}))
            except Exception:
                break

    async def stt_loop() -> None:
        """Read STT results and forward to client as partial/final."""
        while not ws_closed:
            result = await _stt_pipeline.get_next_result(timeout=10.0)
            if result is None:
                continue
            if session_id is None:
                continue
            is_partial = not result.get("no_speech", False) and not result.get("done", False)
            if is_partial:
                text = result.get("text", "").strip()
                if text:
                    msg = STTPartial(session_id=session_id, text=text, confidence=0.85)
                    try:
                        await websocket.send_json(msg.model_dump())
                    except Exception:
                        break
            else:
                text = result.get("text", "").strip()
                if text or result.get("done", False):
                    msg = STTFinal(
                        session_id=session_id,
                        text=text,
                        confidence=0.9,
                        duration_ms=result.get("t_duration", 0),
                        segments=[],
                    )
                    try:
                        await websocket.send_json(msg.model_dump())
                    except Exception:
                        break
                    session_manager.touch(session_id)

    async def receive_loop() -> None:
        nonlocal session_id, is_final, ws_closed
        try:
            while not ws_closed:
                msg = await websocket.receive()
                msg_type = msg.get("type")
                if msg_type == "websocket.disconnect":
                    break

                if msg_type == "websocket.receive":
                    data = msg.get("bytes")
                    text_data = msg.get("text")

                    if text_data is not None:
                        # JSON control frame
                        try:
                            control = json.loads(text_data)
                            msg_kind = control.get("type", "")

                            if msg_kind == "session_open":
                                session_id = str(control.get("session_id", uuid.uuid4()))
                                fmt = str(control.get("format", "pcm"))
                                sr = int(control.get("sample_rate", 16000))
                                await _stt_pipeline.start_session(session_id)
                                session_manager.add(session_id, websocket, fmt=fmt, sr=sr)
                                ack = SessionAck(
                                    session_id=session_id,
                                    websocket_enabled=True,
                                    stt_model=WHISPER_MODEL,
                                    tts_voice=PIPER_VOICE,
                                )
                                await websocket.send_json(ack.model_dump())
                                if stt_task_ref[0] is None:
                                    stt_task_ref[0] = asyncio.create_task(stt_loop())

                            elif msg_kind == "session_close":
                                reason = str(control.get("reason", "client_disconnect"))
                                sid = session_id
                                await _cleanup_session(sid, _stt_pipeline, _tts_pipeline, stt_task_ref[0])
                                close_msg = SessionClose(session_id=sid or "", reason=reason)
                                await websocket.send_json(close_msg.model_dump())
                                break

                            elif msg_kind == "tts_input":
                                sid = str(control.get("session_id", ""))
                                text = str(control.get("text", ""))
                                voice = str(control.get("voice", PIPER_VOICE))
                                speed = float(control.get("speed", 1.0))
                                if sid and text:
                                    audio = await _tts_pipeline.synthesize_chunk(sid, text, voice=voice, speed=speed)
                                    if audio:
                                        chunk = TTSChunk(
                                            session_id=sid,
                                            format="pcm",
                                            sample_rate=SAMPLE_RATE,
                                            is_final=not text or len(text) < 50,
                                            duration_ms=CHUNK_DURATION_MS,
                                        )
                                        await websocket.send_bytes(audio)
                                        await websocket.send_json(chunk.model_dump())
                                        session_manager.touch(sid)

                            elif msg_kind == "ping":
                                pong = {"type": "pong", "timestamp_ms": int(time.time() * 1000)}
                                await websocket.send_text(json.dumps(pong))

                        except (json.JSONDecodeError, ValueError) as exc:
                            logger.warning("Invalid JSON control frame: %s", exc)
                            if session_id:
                                err = ErrorMsg(session_id=session_id, code="invalid_frame", message=str(exc))
                                try:
                                    await websocket.send_json(err.model_dump())
                                except Exception:
                                    pass

                    elif data is not None and session_id is not None:
                        # Binary audio frame
                        pcm_bytes = bytes(data)
                        if pcm_bytes:
                            await _stt_pipeline.feed_audio(session_id, pcm_bytes)
                            if is_final:
                                await _stt_pipeline.finalize_session(session_id)
                                is_final = False
                            session_manager.touch(session_id)

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: %s", session_id)
        except Exception as exc:
            logger.exception("receive_loop error: %s", exc)
        finally:
            ws_closed = True
            if session_id:
                await _cleanup_session(session_id, _stt_pipeline, _tts_pipeline, stt_task_ref[0])

    try:
        ping_task = asyncio.create_task(ping_loop())
        await receive_loop()
    finally:
        ws_closed = True
        if ping_task:
            ping_task.cancel()
        try:
            await websocket.close(code=1000, reason="server_shutdown")
        except Exception:
            pass
        if session_id:
            session_manager.remove(session_id)


async def _cleanup_session(
    session_id: Optional[str],
    stt_pipeline: WhisperSTTPipeline,
    tts_pipeline: ChunkedTTSPipeline,
    stt_task: Optional[asyncio.Task],
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

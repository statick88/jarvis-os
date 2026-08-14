"""Orchestrator WebSocket client pool for Jarvis Voice Bridge.

Wraps ``JarvisVoiceBridgeWS`` with a bounded session pool, idle timeout,
and lifecycle management. Each session in the pool maps to one active
``JarvisVoiceBridgeWS`` connection.

Usage::

    async with OrchestratorVoiceClient(host="localhost", port=8080) as client:
        ack = await client.open_session("session-001")
        await client.send_audio("session-001", pcm_bytes)
        await client.send_text("session-001", "Hola mundo")
        await client.close_session("session-001")
        stats = client.metrics()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional
from uuid import uuid4

from jarvis_os.voice_bridge.client import (
    ConnectionState,
    JarvisVoiceBridgeWS,
    JarvisVoiceError,
    STTPartialEvent,
    STTFinalEvent,
    TTSChunkEvent,
)

logger = logging.getLogger(__name__)

# Pool configuration
_DEFAULT_MAX_SESSIONS = 10
_DEFAULT_IDLE_TIMEOUT_S = 300


class SessionAck:
    """Acknowledged session from voice-pipeline."""

    def __init__(self, session_id: str, websocket_enabled: bool, stt_model: str, tts_voice: str) -> None:
        self.session_id = session_id
        self.websocket_enabled = websocket_enabled
        self.stt_model = stt_model
        self.tts_voice = tts_voice


class OrchestratorVoiceClient:
    """Session-pooled WebSocket client wrapping ``JarvisVoiceBridgeWS``.

    Manages a pool of WebSocket sessions with:
    - Bounded max sessions (default 10)
    - Idle timeout (default 300s)
    - Automatic cleanup of expired sessions
    - Metrics reporting
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        max_sessions: int = _DEFAULT_MAX_SESSIONS,
        idle_timeout_s: int = _DEFAULT_IDLE_TIMEOUT_S,
        token: Optional[str] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._max_sessions = max_sessions
        self._idle_timeout_s = idle_timeout_s
        self._token = token

        # Active sessions: session_id -> JarvisVoiceBridgeWS
        self._sessions: dict[str, JarvisVoiceBridgeWS] = {}
        # Metadata per session
        self._session_meta: dict[str, dict[str, Any]] = {}
        # Event listeners
        self._listeners: dict[str, list[Callable]] = {
            "partial": [],
            "final": [],
            "audio_chunk": [],
            "state_change": [],
        }

        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the cleanup background loop."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._shutdown.clear()
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("OrchestratorVoiceClient started (max_sessions=%d)", self._max_sessions)

    async def stop(self) -> None:
        """Stop all sessions and cleanup loop."""
        self._shutdown.set()
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        # Close all sessions
        for sid in list(self._sessions.keys()):
            try:
                await self.close_session(sid)
            except Exception:
                pass
        logger.info("OrchestratorVoiceClient stopped")

    async def __aenter__(self) -> OrchestratorVoiceClient:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def open_session(self, session_id: Optional[str] = None) -> SessionAck:
        """Open a new voice session.

        Args:
            session_id: Optional session ID. Generated if not provided.

        Returns:
            SessionAck with session metadata from the server.

        Raises:
            JarvisVoiceError: If pool is full or connection fails.
        """
        if session_id is None:
            session_id = str(uuid4())

        if session_id in self._sessions:
            raise JarvisVoiceError(f"Session {session_id} already exists")

        if len(self._sessions) >= self._max_sessions:
            raise JarvisVoiceError(
                f"Session pool full ({len(self._sessions)}/{self._max_sessions})"
            )

        ws = JarvisVoiceBridgeWS(host=self._host, port=self._port)
        await ws.connect(session_id=session_id, token=self._token)

        # Wait for session_ack from server via listener
        ack = await self._wait_for_ack(ws, session_id)

        self._sessions[session_id] = ws
        self._session_meta[session_id] = {
            "created_at": time.monotonic(),
            "last_activity": time.monotonic(),
            "ack": ack,
        }

        # Wire up event listeners
        self._wire_listeners(ws, session_id)

        logger.info("Session opened: %s (active: %d)", session_id, len(self._sessions))
        return ack

    async def _wait_for_ack(self, ws: JarvisVoiceBridgeWS, session_id: str, timeout: float = 5.0) -> SessionAck:
        """Wait for session_ack from server using listener queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def _on_ack(data: dict[str, Any]) -> None:
            queue.put_nowait(data)

        ws.on_session_ack(_on_ack)
        try:
            data = await asyncio.wait_for(queue.get(), timeout=timeout)
            return SessionAck(
                session_id=data.get("session_id", session_id),
                websocket_enabled=data.get("websocket_enabled", True),
                stt_model=data.get("stt_model", "whisper-base"),
                tts_voice=data.get("tts_voice", "es_ES-pacifico"),
            )
        except asyncio.TimeoutError:
            raise JarvisVoiceError(f"No session_ack received for {session_id} within {timeout}s")

    def _wire_listeners(self, ws: JarvisVoiceBridgeWS, session_id: str) -> None:
        """Wire WS event callbacks to update session metadata."""

        def _on_partial(event: STTPartialEvent) -> None:
            if event.session_id == session_id:
                self._touch_session(session_id)

        def _on_final(event: STTFinalEvent) -> None:
            if event.session_id == session_id:
                self._touch_session(session_id)

        def _on_chunk(event: TTSChunkEvent) -> None:
            if event.session_id == session_id:
                self._touch_session(session_id)

        ws.on_partial_transcript(_on_partial)
        ws.on_final_transcript(_on_final)
        ws.on_audio_chunk(_on_chunk)

    def _touch_session(self, session_id: str) -> None:
        if session_id in self._session_meta:
            self._session_meta[session_id]["last_activity"] = time.monotonic()

    async def close_session(self, session_id: str) -> None:
        """Close a voice session gracefully."""
        ws = self._sessions.pop(session_id, None)
        self._session_meta.pop(session_id, None)
        if ws is not None:
            try:
                await ws.close(reason="orchestrator_close")
            except Exception:
                pass
        logger.info("Session closed: %s (active: %d)", session_id, len(self._sessions))

    async def send_audio(self, session_id: str, pcm_bytes: bytes) -> None:
        """Send raw PCM audio bytes to a session."""
        ws = self._sessions.get(session_id)
        if ws is None:
            raise JarvisVoiceError(f"Session {session_id} not found")
        ws.send_audio(pcm_bytes, session_id=session_id)
        self._touch_session(session_id)

    async def send_text(self, session_id: str, text: str) -> None:
        """Send a text chunk for TTS synthesis."""
        ws = self._sessions.get(session_id)
        if ws is None:
            raise JarvisVoiceError(f"Session {session_id} not found")
        ws.send_text(text, session_id=session_id)
        self._touch_session(session_id)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        """Return pool metrics."""
        active = len(self._sessions)
        idle_sessions = 0
        now = time.monotonic()
        for sid, meta in self._session_meta.items():
            if (now - meta["last_activity"]) > self._idle_timeout_s:
                idle_sessions += 1
        return {
            "active_sessions": active,
            "max_sessions": self._max_sessions,
            "idle_sessions": idle_sessions,
            "available_slots": self._max_sessions - active,
            "host": f"{self._host}:{self._port}",
        }

    # ------------------------------------------------------------------
    # Event listeners (proxy to sessions)
    # ------------------------------------------------------------------

    def on_partial_transcript(self, callback: Callable[[STTPartialEvent], None]) -> None:
        self._listeners["partial"].append(callback)

    def on_final_transcript(self, callback: Callable[[STTFinalEvent], None]) -> None:
        self._listeners["final"].append(callback)

    def on_audio_chunk(self, callback: Callable[[TTSChunkEvent], None]) -> None:
        self._listeners["audio_chunk"].append(callback)

    def on_state_change(self, callback: Callable[[str], None]) -> None:
        self._listeners["state_change"].append(callback)

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Periodically remove idle sessions."""
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            if self._shutdown.is_set():
                break
            now = time.monotonic()
            expired = [
                sid
                for sid, meta in self._session_meta.items()
                if (now - meta["last_activity"]) > self._idle_timeout_s
            ]
            for sid in expired:
                logger.info("Cleaning idle session: %s", sid)
                try:
                    await self.close_session(sid)
                except Exception:
                    pass

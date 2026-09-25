"""Async gRPC client for the Jarvis Voice Bridge service."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Callable, Optional
from uuid import uuid4

import grpc
import websockets

from jarvis_os.voice_bridge.models import (
    AudioChunk,
    HealthRequest,
    HealthResponse,
    ListModelsRequest,
    ListModelsResponse,
    SynthesizeResponse,
    TTSRequest,
    TranscribeRequest,
    STTResponse,
)
from jarvis_os.voice_bridge.gen import voice_api_pb2_grpc

logger = logging.getLogger(__name__)

# gRPC status codes eligible for automatic retry.
_RETRYABLE_CODES: frozenset[grpc.StatusCode] = frozenset(
    {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}
)


class JarvisVoiceError(Exception):
    """Raised when a Voice Bridge RPC fails.

    Attributes:
        message: Human-readable error description.
        status_code: The gRPC ``StatusCode`` that caused the failure, or ``None``
            for non-gRPC errors.
    """

    def __init__(self, message: str, *, status_code: Optional[grpc.StatusCode] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __repr__(self) -> str:
        return (
            f"JarvisVoiceError({self.message!r}, "
            f"status_code={self.status_code!r})"
        )


class JarvisVoiceBridge:
    """Async gRPC client for the Jarvis Voice Bridge service.

    Usage::

        async with JarvisVoiceBridge(host="localhost", port=50051) as bridge:
            response = await bridge.transcribe(request)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 50051,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base

        self._channel: Optional[grpc.aio.Channel] = None
        self._stub: Optional[voice_api_pb2_grpc.VoiceServiceStub] = None

    # ------------------------------------------------------------------
    # Channel management
    # ------------------------------------------------------------------

    def _ensure_channel(self) -> voice_api_pb2_grpc.VoiceServiceStub:
        """Lazily create the gRPC channel and stub on first use."""
        if self._stub is None:
            target = f"{self._host}:{self._port}"
            self._channel = grpc.aio.insecure_channel(target)
            self._stub = voice_api_pb2_grpc.VoiceServiceStub(self._channel)
            logger.debug("Created gRPC channel to %s", target)
        return self._stub

    async def close(self) -> None:
        """Close the gRPC channel gracefully."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None
            logger.debug("Closed gRPC channel")

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> JarvisVoiceBridge:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        rpc_fn: Any,
        request: Any,
        *,
        timeout: Optional[float] = None,
    ) -> Any:
        """Execute *rpc_fn(request)* with exponential-backoff retry.

        Only retries on ``UNAVAILABLE`` and ``DEADLINE_EXCEEDED`` status codes.
        All other errors are wrapped in ``JarvisVoiceError`` and re-raised
        immediately.

        Args:
            rpc_fn: A bound async RPC method (e.g. ``stub.Transcribe``).
            request: The protobuf request object.
            timeout: Per-attempt deadline in seconds.  Falls back to
                ``self._timeout`` when *None*.

        Returns:
            The protobuf response.

        Raises:
            JarvisVoiceError: On non-retryable gRPC errors or when the retry
                budget is exhausted.
        """
        effective_timeout = timeout if timeout is not None else self._timeout
        last_exc: Optional[grpc.aio.AioRpcError] = None

        for attempt in range(self._max_retries + 1):
            try:
                return await rpc_fn(request, timeout=effective_timeout)
            except grpc.aio.AioRpcError as exc:
                last_exc = exc
                if exc.code() not in _RETRYABLE_CODES:
                    raise JarvisVoiceError(
                        f"RPC failed: {exc.details()}",
                        status_code=exc.code(),
                    ) from exc

                if attempt < self._max_retries:
                    delay = self._backoff_base * (2 ** attempt)
                    logger.warning(
                        "Retryable gRPC error (%s), attempt %d/%d, "
                        "waiting %.2fs: %s",
                        exc.code().name,
                        attempt + 1,
                        self._max_retries,
                        delay,
                        exc.details(),
                    )
                    await asyncio.sleep(delay)

        # All retries exhausted.
        assert last_exc is not None
        raise JarvisVoiceError(
            f"RPC failed after {self._max_retries + 1} attempts: "
            f"{last_exc.details()}",
            status_code=last_exc.code(),
        ) from last_exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transcribe(self, request: TranscribeRequest) -> STTResponse:
        """Perform one-shot speech-to-text transcription.

        Args:
            request: A ``TranscribeRequest`` containing the audio data.

        Returns:
            A ``TranscribeResponse`` with the transcribed text.
        """
        stub = self._ensure_channel()
        return await self._call_with_retry(stub.Transcribe, request)

    async def stream_transcribe(
        self, audio_stream: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Any]:
        """Perform streaming speech-to-text via a bidirectional stream.

        Args:
            audio_stream: An async iterator yielding ``AudioChunk`` messages.

        Yields:
            ``STTResponse`` messages as they become available.
        """
        stub = self._ensure_channel()
        try:
            async for response in stub.StreamSTT(audio_stream, timeout=self._timeout):
                yield response
        except grpc.aio.AioRpcError as exc:
            raise JarvisVoiceError(
                f"StreamSTT failed: {exc.details()}",
                status_code=exc.code(),
            ) from exc

    async def synthesize(self, request: TTSRequest) -> SynthesizeResponse:
        """Perform one-shot text-to-speech synthesis.

        Args:
            request: A ``TTSRequest`` containing the text to synthesize.

        Returns:
            A ``SynthesizeResponse`` with the generated audio.
        """
        stub = self._ensure_channel()
        return await self._call_with_retry(stub.Synthesize, request)

    async def stream_tts(
        self, text_stream: AsyncIterator[TTSRequest]
    ) -> AsyncIterator[Any]:
        """Perform streaming text-to-speech via a bidirectional stream.

        Args:
            text_stream: An async iterator yielding ``TTSRequest`` messages.

        Yields:
            ``AudioChunk`` messages as they become available.
        """
        stub = self._ensure_channel()
        try:
            async for response in stub.StreamTTS(text_stream, timeout=self._timeout):
                yield response
        except grpc.aio.AioRpcError as exc:
            raise JarvisVoiceError(
                f"StreamTTS failed: {exc.details()}",
                status_code=exc.code(),
            ) from exc

    async def health(self) -> HealthResponse:
        """Check service health.

        Returns:
            A ``HealthResponse`` indicating service status.
        """
        stub = self._ensure_channel()
        return await self._call_with_retry(
            stub.Health, HealthRequest()
        )

    async def list_models(self) -> ListModelsResponse:
        """List available models on the server.

        Returns:
            A ``ListModelsResponse`` containing the supported models.
        """
        stub = self._ensure_channel()
        return await self._call_with_retry(
            stub.ListModels, ListModelsRequest()
        )


# ============================================================================
# WebSocket Transport (FastAPI voice-pipeline streaming)
# ============================================================================

class STTPartialEvent:
    """Partial STT result from WebSocket stream."""

    def __init__(self, text: str, confidence: float, session_id: str) -> None:
        self.text = text
        self.confidence = confidence
        self.session_id = session_id


class STTFinalEvent:
    """Final STT result from WebSocket stream."""

    def __init__(self, text: str, confidence: float, session_id: str, duration_ms: int) -> None:
        self.text = text
        self.confidence = confidence
        self.session_id = session_id
        self.duration_ms = duration_ms


class TTSChunkEvent:
    """Synthesized audio chunk from WebSocket stream."""

    def __init__(self, audio_data: bytes, session_id: str, format: str, sample_rate: int, is_final: bool, duration_ms: int) -> None:
        self.audio_data = audio_data
        self.session_id = session_id
        self.format = format
        self.sample_rate = sample_rate
        self.is_final = is_final
        self.duration_ms = duration_ms


class ConnectionState:
    """WebSocket connection state enum."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class JarvisVoiceBridgeWS:
    """Async WebSocket client for the Jarvis Voice Bridge streaming endpoint.

    Usage::

        ws = JarvisVoiceBridgeWS(host="localhost", port=8080)
        await ws.connect()
        ws.send_audio(pcm_bytes, session_id="...")
        ws.send_text("Hola", session_id="...")
        async for partial in ws.partial_transcripts():
            print(partial.text)
        await ws.close()
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
        jitter: float = 0.5,
    ) -> None:
        self._host = host
        self._port = port
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._jitter = jitter

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._session_id: str = ""
        self._state: str = ConnectionState.DISCONNECTED
        self._pending_audio: asyncio.Queue[bytes] = asyncio.Queue()
        self._listeners: dict[str, list[Callable]] = {
            "partial": [],
            "final": [],
            "audio_chunk": [],
            "state_change": [],
            "session_ack": [],
        }

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self, session_id: Optional[str] = None, token: Optional[str] = None) -> None:
        """Open WebSocket connection with exponential backoff retry."""
        self._session_id = session_id or str(uuid4())
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        uri = f"ws://{self._host}:{self._port}/v1/audio/stream"
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= self._max_retries:
            try:
                self._set_state(ConnectionState.CONNECTING if attempt == 0 else ConnectionState.RECONNECTING)
                self._ws = await websockets.connect(
                    uri,
                    additional_headers=headers,
                    ping_interval=15,
                    ping_timeout=10,
                    close_timeout=5,
                )
                self._set_state(ConnectionState.CONNECTED)
                logger.info("WebSocket connected to %s (session: %s)", uri, self._session_id)

                # Send session_open
                open_msg = {
                    "type": "session_open",
                    "session_id": self._session_id,
                    "format": "pcm",
                    "sample_rate": 16000,
                    "vad_mode": "none",
                }
                await self._ws.send(json.dumps(open_msg))

                # Start background listener
                asyncio.create_task(self._listen_loop())
                return

            except (ConnectionRefusedError, OSError, websockets.InvalidURI) as exc:
                last_error = exc
                attempt += 1
                if attempt > self._max_retries:
                    break
                delay = min(self._backoff_base * (2 ** (attempt - 1)), self._backoff_max)
                jitter_amount = delay * self._jitter * (2 * (asyncio.get_event_loop().time() % 1) - 1)
                wait = max(0.1, delay + jitter_amount)
                logger.warning(
                    "WS connect failed (attempt %d/%d): %s, retrying in %.1fs",
                    attempt, self._max_retries, exc, wait,
                )
                self._set_state(ConnectionState.RECONNECTING)
                await asyncio.sleep(wait)

        self._set_state(ConnectionState.ERROR)
        raise JarvisVoiceError(
            f"WebSocket connection failed after {self._max_retries} retries: {last_error}"
        )

    async def _listen_loop(self) -> None:
        """Listen for incoming messages from the WebSocket."""
        try:
            async for message in self._ws:  # type: ignore[union-attr]
                if isinstance(message, bytes):
                    # Binary audio frame — dispatch as TTSChunkEvent
                    event = TTSChunkEvent(
                        audio_data=message,
                        session_id=self._session_id,
                        format="pcm",
                        sample_rate=22050,
                        is_final=False,
                        duration_ms=100,
                    )
                    self._dispatch("audio_chunk", event)
                else:
                    # JSON control frame
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type", "")
                        if msg_type == "stt_partial":
                            event = STTPartialEvent(
                                text=data.get("text", ""),
                                confidence=data.get("confidence", 0.0),
                                session_id=data.get("session_id", ""),
                            )
                            self._dispatch("partial", event)
                        elif msg_type == "stt_final":
                            event = STTFinalEvent(
                                text=data.get("text", ""),
                                confidence=data.get("confidence", 0.0),
                                session_id=data.get("session_id", ""),
                                duration_ms=data.get("duration_ms", 0),
                            )
                            self._dispatch("final", event)
                        elif msg_type == "tts_chunk":
                            event = TTSChunkEvent(
                                audio_data=b"",
                                session_id=data.get("session_id", ""),
                                format=data.get("format", "pcm"),
                                sample_rate=data.get("sample_rate", 22050),
                                is_final=data.get("is_final", False),
                                duration_ms=data.get("duration_ms", 0),
                            )
                            self._dispatch("audio_chunk", event)
                        elif msg_type == "error":
                            logger.error("WS error frame: %s", data)
                        elif msg_type == "session_ack":
                            # Dispatch session_ack as a special event for orchestrator clients
                            self._dispatch("session_ack", data)
                    except json.JSONDecodeError:
                        logger.debug("Non-JSON message received: %s", message[:100])
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
            self._set_state(ConnectionState.DISCONNECTED)
        except Exception as exc:
            logger.exception("WebSocket listen error: %s", exc)
            self._set_state(ConnectionState.ERROR)

    async def close(self, reason: str = "client_disconnect") -> None:
        """Close the WebSocket session cleanly."""
        if self._ws is not None:
            try:
                close_msg = {"type": "session_close", "session_id": self._session_id, "reason": reason}
                await self._ws.send(json.dumps(close_msg))
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._set_state(ConnectionState.DISCONNECTED)
        logger.info("WebSocket closed (session: %s)", self._session_id)

    # ------------------------------------------------------------------
    # Audio/Text send
    # ------------------------------------------------------------------

    def send_audio(self, pcm_bytes: bytes, is_final: bool = False, session_id: Optional[str] = None) -> None:
        """Send raw PCM audio bytes to the server."""
        sid = session_id or self._session_id
        if self._ws is None:
            raise JarvisVoiceError("WebSocket not connected")
        meta = json.dumps({
            "type": "audio_chunk",
            "session_id": sid,
            "is_final": is_final,
            "timestamp_ms": int(time.time() * 1000),
        })
        # Send as two frames: JSON metadata + binary PCM
        asyncio.create_task(self._send_frames(meta, pcm_bytes))

    async def _send_frames(self, meta: str, audio: bytes) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(meta)
            await self._ws.send(audio)
        except Exception as exc:
            logger.warning("Failed to send audio frames: %s", exc)

    def send_text(self, text: str, session_id: Optional[str] = None, voice: str = "es_ES-pacifico", speed: float = 1.0) -> None:
        """Send a text chunk for TTS synthesis."""
        sid = session_id or self._session_id
        if self._ws is None:
            raise JarvisVoiceError("WebSocket not connected")
        msg = json.dumps({
            "type": "tts_input",
            "session_id": sid,
            "text": text,
            "voice": voice,
            "speed": speed,
        })
        asyncio.create_task(self._ws.send(msg))

    # ------------------------------------------------------------------
    # Stream getters
    # ------------------------------------------------------------------

    def on_partial_transcript(self, callback: Callable[[STTPartialEvent], None]) -> None:
        """Register callback for partial STT results."""
        self._listeners["partial"].append(callback)

    def on_final_transcript(self, callback: Callable[[STTFinalEvent], None]) -> None:
        """Register callback for final STT results."""
        self._listeners["final"].append(callback)

    def on_audio_chunk(self, callback: Callable[[TTSChunkEvent], None]) -> None:
        """Register callback for TTS audio chunks."""
        self._listeners["audio_chunk"].append(callback)

    def on_state_change(self, callback: Callable[[str], None]) -> None:
        """Register callback for connection state changes."""
        self._listeners["state_change"].append(callback)

    def on_session_ack(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register callback for session_ack events."""
        self._listeners["session_ack"].append(callback)

    async def partial_transcripts(self) -> AsyncIterator[STTPartialEvent]:
        """Async iterator yielding partial transcripts."""
        queue: asyncio.Queue = asyncio.Queue()

        def _on_partial(event: STTPartialEvent) -> None:
            queue.put_nowait(event)

        self.on_partial_transcript(_on_partial)
        try:
            while True:
                yield await queue.get()
        except GeneratorExit:
            pass

    async def final_transcripts(self) -> AsyncIterator[STTFinalEvent]:
        """Async iterator yielding final transcripts."""
        queue: asyncio.Queue = asyncio.Queue()

        def _on_final(event: STTFinalEvent) -> None:
            queue.put_nowait(event)

        self.on_final_transcript(_on_final)
        try:
            while True:
                yield await queue.get()
        except GeneratorExit:
            pass

    async def audio_chunks(self) -> AsyncIterator[TTSChunkEvent]:
        """Async iterator yielding TTS audio chunks."""
        queue: asyncio.Queue = asyncio.Queue()

        def _on_chunk(event: TTSChunkEvent) -> None:
            queue.put_nowait(event)

        self.on_audio_chunk(_on_chunk)
        try:
            while True:
                yield await queue.get()
        except GeneratorExit:
            pass

    @property
    def state(self) -> str:
        """Current connection state."""
        return self._state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_state(self, new_state: str) -> None:
        self._state = new_state
        for callback in self._listeners["state_change"]:
            try:
                callback(new_state)
            except Exception:
                pass

    def _dispatch(self, event_type: str, event: Any) -> None:
        for callback in self._listeners.get(event_type, []):
            try:
                callback(event)
            except Exception:
                pass

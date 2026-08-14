"""
OpenCode Adapter — Async WebSocket Client
===========================================
Provides ``OpenCodeClient`` for bidirectional communication with the OpenCode
agent runtime over WebSocket, with automatic HTTP fallback and reconnection.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from uuid import UUID, uuid4

import aiohttp

from jarvis_os.opencode_adapter.models import (
    ConnectionConfig,
    Envelope,
    Heartbeat,
    MessageType,
    SkillExecutionRequest,
    SkillExecutionResponse,
)
from jarvis_os.opencode_adapter.protocol import (
    create_envelope,
    envelope_to_json,
    validate_envelope,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class OpenCodeError(Exception):
    """Base exception for all OpenCode adapter errors."""


class ConnectionError_(OpenCodeError):
    """Raised when the transport layer cannot establish or maintain a connection."""


class TimeoutError_(OpenCodeError):
    """Raised when a correlated response is not received within the deadline."""


class ProtocolError(OpenCodeError):
    """Raised when the server sends a malformed or unexpected message."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OpenCodeClient:
    """Async WebSocket client with HTTP fallback for OpenCode skill execution.

    Usage::

        client = OpenCodeClient()
        await client.connect()
        response = await client.execute_skill(request)
        await client.disconnect()

    Or as a context manager::

        async with OpenCodeClient() as client:
            response = await client.execute_skill(request)
    """

    def __init__(self, config: ConnectionConfig | None = None) -> None:
        self._config = config or ConnectionConfig()
        self._client_id = uuid4().hex[:12]

        # Transport state
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connected = False
        self._closing = False

        # Pending request futures keyed by envelope ID
        self._pending: dict[str, asyncio.Future[Envelope]] = {}

        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._receive_task: Optional[asyncio.Task[None]] = None

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> OpenCodeClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish a WebSocket connection to the OpenCode runtime.

        Raises:
            ConnectionError_: If the connection cannot be established after
                all reconnection attempts are exhausted.
        """
        if self._connected:
            return

        self._session = aiohttp.ClientSession()
        await self._connect_ws()

    async def _connect_ws(self) -> None:
        """Internal: attempt a single WebSocket handshake with reconnect logic."""
        last_error: Exception | None = None

        for attempt in range(self._config.reconnect_attempts + 1):
            try:
                self._ws = await self._session.ws_connect(  # type: ignore[union-attr]
                    self._config.ws_url,
                    heartbeat=None,  # We manage our own heartbeat
                )
                self._connected = True
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                self._receive_task = asyncio.create_task(self._receive_loop())
                logger.info(
                    "Connected to OpenCode at %s (client=%s)",
                    self._config.ws_url,
                    self._client_id,
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt < self._config.reconnect_attempts:
                    delay = self._config.reconnect_delay * (2 ** attempt)
                    logger.warning(
                        "WS connection attempt %d/%d failed, retrying in %.1fs: %s",
                        attempt + 1,
                        self._config.reconnect_attempts + 1,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        raise ConnectionError_(
            f"Failed to connect to {self._config.ws_url} after "
            f"{self._config.reconnect_attempts + 1} attempts"
        ) from last_error

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection and cancel background tasks."""
        if not self._connected and self._ws is None:
            return

        self._closing = True
        self._connected = False

        # Cancel background tasks
        for task in (self._heartbeat_task, self._receive_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close WebSocket
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        # Close HTTP session
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

        # Fail all pending futures
        for future in self._pending.values():
            if not future.done():
                future.set_exception(
                    ConnectionError_("Connection closed")
                )
        self._pending.clear()

        self._closing = False
        logger.info("Disconnected from OpenCode (client=%s)", self._client_id)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, envelope: Envelope) -> Envelope:
        """Send a message and wait for the correlated response.

        Args:
            envelope: The outgoing envelope (typically REQUEST).

        Returns:
            The response envelope whose ``id`` matches the outgoing ``id``.

        Raises:
            TimeoutError_: If no response arrives within the heartbeat timeout.
            ConnectionError_: If the connection is lost and HTTP fallback fails.
        """
        future: asyncio.Future[Envelope] = asyncio.get_event_loop().create_future()
        self._pending[str(envelope.id)] = future

        try:
            await self._send_ws(envelope)
            timeout = self._config.heartbeat_timeout
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(str(envelope.id), None)
            # Attempt HTTP fallback
            logger.warning(
                "WS response timeout for %s, trying HTTP fallback", envelope.id
            )
            return await self._http_fallback(envelope)
        except Exception:
            self._pending.pop(str(envelope.id), None)
            raise

    async def _send_ws(self, envelope: Envelope) -> None:
        """Serialize and send an envelope over WebSocket."""
        if not self._ws or self._ws.closed:
            raise ConnectionError_("WebSocket is not connected")

        raw = envelope_to_json(envelope)
        await self._ws.send_str(raw)
        logger.debug("Sent %s envelope %s", envelope.type, envelope.id)

    async def execute_skill(
        self, request: SkillExecutionRequest
    ) -> SkillExecutionResponse:
        """Execute a skill and return the typed response.

        Wraps :meth:`send` with a REQUEST envelope and extracts the
        ``SkillExecutionResponse`` from the response payload.

        Args:
            request: The skill execution request.

        Returns:
            The parsed skill execution response.
        """
        envelope = create_envelope(MessageType.REQUEST, request.model_dump(mode="json"))
        response = await self.send(envelope)

        if response.type == MessageType.ERROR:
            error_payload = response.payload
            raise ProtocolError(
                error_payload.get("error", "Unknown server error")
            )

        return SkillExecutionResponse.model_validate(response.payload)

    async def send_event(self, payload: dict) -> None:
        """Fire-and-forget an EVENT envelope (no response expected).

        Args:
            payload: The event payload dict.
        """
        envelope = create_envelope(MessageType.EVENT, payload)
        await self._send_ws(envelope)

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Periodically send HEARTBEAT envelopes to keep the connection alive."""
        try:
            while self._connected and not self._closing:
                heartbeat = Heartbeat(client_id=self._client_id)
                envelope = create_envelope(
                    MessageType.HEARTBEAT,
                    heartbeat.model_dump(mode="json"),
                )
                try:
                    await self._send_ws(envelope)
                except ConnectionError_:
                    logger.warning("Heartbeat failed — connection lost")
                    asyncio.create_task(self._reconnect())
                    return
                await asyncio.sleep(self._config.heartbeat_interval)
        except asyncio.CancelledError:
            pass

    async def _receive_loop(self) -> None:
        """Read incoming WebSocket messages and dispatch by correlation ID."""
        try:
            while self._connected and self._ws and not self._ws.closed:
                msg = await self._ws.receive()

                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    logger.info("WebSocket closed by server")
                    asyncio.create_task(self._reconnect())
                    return

                if msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("WebSocket error: %s", self._ws.exception())
                    asyncio.create_task(self._reconnect())
                    return

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Receive loop error: %s", exc)
            asyncio.create_task(self._reconnect())

    async def _handle_message(self, raw: str) -> None:
        """Parse an incoming message and route to the correct pending future."""
        try:
            envelope = validate_envelope(json.loads(raw))
        except Exception as exc:
            logger.error("Invalid message received: %s", exc)
            return

        msg_id = str(envelope.id)

        # Route RESPONSE or ERROR to a pending request future
        if envelope.type in (MessageType.RESPONSE, MessageType.ERROR):
            future = self._pending.pop(msg_id, None)
            if future and not future.done():
                future.set_result(envelope)
                logger.debug(
                    "Dispatched %s envelope %s", envelope.type, envelope.id
                )
            else:
                logger.debug(
                    "Received %s for unknown request %s", envelope.type, envelope.id
                )
        elif envelope.type == MessageType.ACK:
            logger.debug("Received ACK for %s", envelope.id)
        elif envelope.type == MessageType.HEARTBEAT:
            logger.debug("Received server heartbeat %s", envelope.id)
        else:
            logger.debug("Received %s envelope %s", envelope.type, envelope.id)

    # ------------------------------------------------------------------
    # HTTP fallback
    # ------------------------------------------------------------------

    async def _http_fallback(self, envelope: Envelope) -> Envelope:
        """POST the envelope to the HTTP endpoint when WebSocket fails.

        Args:
            envelope: The original envelope to send.

        Returns:
            The response envelope parsed from the HTTP response body.

        Raises:
            ConnectionError_: If the HTTP request also fails.
        """
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()

        url = f"{self._config.http_url}/api/message"
        payload = envelope_to_json(envelope)

        try:
            async with self._session.post(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=self._config.heartbeat_timeout),
            ) as resp:
                if resp.status != 200:
                    raise ConnectionError_(
                        f"HTTP fallback returned status {resp.status}"
                    )
                body = await resp.json()
                return validate_envelope(body)
        except aiohttp.ClientError as exc:
            raise ConnectionError_(
                f"HTTP fallback request failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Reconnection
    # ------------------------------------------------------------------

    async def _reconnect(self) -> None:
        """Attempt to reconnect the WebSocket with exponential backoff."""
        if self._closing:
            return

        logger.info("Attempting reconnection (client=%s)", self._client_id)
        self._connected = False

        # Cancel stale tasks
        for task in (self._heartbeat_task, self._receive_task):
            if task and not task.done():
                task.cancel()

        # Close stale WS
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        try:
            await self._connect_ws()
            logger.info("Reconnected successfully (client=%s)", self._client_id)
        except ConnectionError_:
            logger.error(
                "Reconnection failed after %d attempts",
                self._config.reconnect_attempts + 1,
            )

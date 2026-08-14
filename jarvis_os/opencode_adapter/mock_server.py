"""
OpenCode Adapter — Mock WebSocket Server
==========================================
Lightweight mock server for testing the adapter client without a real OpenCode
runtime. Echoes REQUEST envelopes back as RESPONSEs with a ``{"status": "success"}`` payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

import websockets
from websockets.server import serve, WebSocketServerProtocol

from jarvis_os.opencode_adapter.models import Envelope, MessageType
from jarvis_os.opencode_adapter.protocol import (
    create_response,
    envelope_to_json,
    validate_envelope,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765


class MockOpenCodeServer:
    """Minimal WebSocket server that responds to REQUEST envelopes.

    Usage::

        server = MockOpenCodeServer()
        await server.start()
        # ... run tests ...
        await server.stop()

    Or as a context manager::

        async with MockOpenCodeServer() as server:
            pass  # server runs in background
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._server: Any | None = None
        self._clients: set[WebSocketServerProtocol] = set()
        self._received: list[Envelope] = []

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> MockOpenCodeServer:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the WebSocket server in the background."""
        self._server = await serve(
            self._handler,
            self.host,
            self.port,
            ping_interval=None,  # We handle pings at the protocol level
        )
        logger.info("MockOpenCodeServer listening on ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Shut down the server and close all client connections."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        # Close all connected clients
        close_tasks = [ws.close() for ws in self._clients]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._clients.clear()
        logger.info("MockOpenCodeServer stopped")

    # ------------------------------------------------------------------
    # Handler
    # ------------------------------------------------------------------

    async def _handler(self, ws: WebSocketServerProtocol) -> None:
        """Handle a single client connection."""
        self._clients.add(ws)
        remote = ws.remote_address
        logger.info("Client connected: %s", remote)

        try:
            async for raw in ws:
                await self._process_message(ws, raw)
        except websockets.ConnectionClosed:
            logger.info("Client disconnected: %s", remote)
        finally:
            self._clients.discard(ws)

    async def _process_message(
        self, ws: WebSocketServerProtocol, raw: str | bytes
    ) -> None:
        """Parse an incoming message, record it, and echo REQUESTs as RESPONSEs."""
        try:
            data = json.loads(raw)
            envelope = validate_envelope(data)
        except Exception as exc:
            logger.error("Invalid message from %s: %s", ws.remote_address, exc)
            return

        self._received.append(envelope)
        logger.debug("Received %s envelope %s", envelope.type, envelope.id)

        # Only respond to REQUEST messages
        if envelope.type == MessageType.REQUEST:
            response = create_response(
                request_id=envelope.id,
                status="success",
                result={},
                skill=envelope.payload.get("skill", ""),
            )
            await ws.send(envelope_to_json(response))
            logger.debug("Sent RESPONSE for %s", envelope.id)

        # Respond to HEARTBEAT with ACK
        elif envelope.type == MessageType.HEARTBEAT:
            ack = Envelope(
                id=uuid4(),
                timestamp=envelope.timestamp,
                type=MessageType.ACK,
                payload={"ack": str(envelope.id)},
            )
            await ws.send(envelope_to_json(ack))

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def received(self) -> list[Envelope]:
        """Return all envelopes received by the server (for assertions)."""
        return list(self._received)

    def clear_received(self) -> None:
        """Clear the received envelope log."""
        self._received.clear()

    @property
    def client_count(self) -> int:
        """Return the number of currently connected clients."""
        return len(self._clients)

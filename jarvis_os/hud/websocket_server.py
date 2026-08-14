"""
HUD — WebSocket Server
======================
Async WebSocket endpoint for JARVIS-OS runtime state.

``HudWebSocketServer`` wraps the ``websockets`` asyncio server API to expose
the HUD state (status, events, errors) to connected clients (e.g. a browser
dashboard or a remote client). Messages use the ``WSMessage`` wire format
defined in ``hud.models``.

The server is config-decoupled: it takes a ``HudConfig`` (or its defaults)
and never imports ``jarvis_os.config`` directly, mirroring the rest of the
package.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Awaitable, Callable, Optional, Set

from jarvis_os.hud.models import HudConfig, HudStatus, WSMessage
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

MessageHandler = Callable[[WSMessage], Awaitable[None]]


class HudWebSocketError(Exception):
    """Base class for HUD WebSocket server errors."""


class HudConnectionError(HudWebSocketError):
    """A client connection could not be established or was invalid."""


class HudProtocolError(HudWebSocketError):
    """A client sent a message that violates the WS wire protocol."""


class HudWebSocketServer:
    """Async WebSocket server publishing HUD state to connected clients."""

    def __init__(
        self,
        config: Optional[HudConfig] = None,
        *,
        handler: Optional[MessageHandler] = None,
    ) -> None:
        self._config = config or HudConfig()
        self._handler = handler
        self._connections: Set[ServerConnection] = set()
        self._server: Optional[Server] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._status: HudStatus = HudStatus.OFFLINE
        self._task: Optional[asyncio.Task] = None
        self._signal_handlers: dict = {}

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Bind and serve. Non-blocking: runs in a background task."""
        if self._server is not None:
            return
        self._loop = asyncio.get_running_loop()
        host = self._config.ws_host
        port = self._config.ws_port
        path = self._config.ws_path

        async def _handler_wrapper(conn: ServerConnection) -> None:
            await self._handle_connection(conn, path)

        self._server = await serve(
            _handler_wrapper,
            host,
            port,
            max_size=self._config.ws_max_message_size,
            ping_interval=self._config.ws_ping_interval_seconds,
            ping_timeout=self._config.ws_ping_timeout_seconds,
        )
        self._install_signal_handlers()
        self._task = asyncio.create_task(self._serve_loop(), name="hud-ws-server")
        logger.info(
            "HUD WebSocket server listening on ws://%s:%s%s",
            host,
            port,
            path,
        )

    async def _serve_loop(self) -> None:
        """Keep the server alive until closed. Exceptions surface via task."""
        assert self._server is not None
        try:
            await self._server.wait_closed()
        finally:
            for conn in list(self._connections):
                await self._close_connection(conn)
            self._connections.clear()

    async def stop(self) -> None:
        """Close all connections, stop listening, and wait for shutdown."""
        if self._server is None:
            return
        self._restore_signal_handlers()
        server, self._server = self._server, None
        server.close()
        try:
            await server.wait_closed()
        finally:
            if self._task is not None:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
        logger.info("HUD WebSocket server stopped")

    # -- connection handling ------------------------------------------------

    async def _handle_connection(self, conn: ServerConnection, path: str) -> None:
        request = conn.request
        if request is None or request.path != path:
            logger.warning(
                "Rejecting connection on unexpected path %r", getattr(request, "path", None)
            )
            await conn.close(code=1008, reason="unexpected path")
            return
        self._connections.add(conn)
        logger.debug("HUD client connected: %s", conn.remote_address)
        try:
            # Push the current status immediately on connect.
            await self._send(conn, self._status_message())
            async for raw in conn:
                if self._handler is not None:
                    try:
                        message = WSMessage.model_validate_json(raw)
                    except ValueError as exc:
                        logger.warning("Invalid WSMessage from client: %s", exc)
                        await self._send(
                            conn,
                            self._error_message(f"invalid message: {exc}"),
                        )
                        continue
                    try:
                        await self._handler(message)
                    except Exception:
                        logger.exception("HUD message handler failed")
        except ConnectionClosed:
            logger.debug("HUD client disconnected: %s", conn.remote_address)
        finally:
            self._connections.discard(conn)

    async def _close_connection(self, conn: ServerConnection) -> None:
        try:
            await conn.close(code=1001, reason="server shutting down")
        except Exception:
            pass

    # -- broadcasting -------------------------------------------------------

    async def broadcast(self, message: WSMessage) -> None:
        """Send a wire message to all connected clients."""
        payload = message.model_dump_json()
        for conn in list(self._connections):
            try:
                await conn.send(payload)
            except ConnectionClosed:
                self._connections.discard(conn)
            except Exception:
                logger.exception("Failed to send to %s", conn.remote_address)

    async def publish_status(
        self,
        status: HudStatus,
        summary: str = "",
        *,
        payload: Optional[dict] = None,
    ) -> WSMessage:
        """Convenience: broadcast a status update, remember it locally."""
        self._status = status
        message = WSMessage(
            type="STATUS",
            payload={
                "status": status.value,
                "summary": summary,
                **(payload or {}),
            },
        )
        await self.broadcast(message)
        return message

    async def _send(self, conn: ServerConnection, message: WSMessage) -> None:
        try:
            await conn.send(message.model_dump_json())
        except ConnectionClosed:
            self._connections.discard(conn)

    # -- message factories --------------------------------------------------

    @staticmethod
    def _status_message() -> WSMessage:
        return WSMessage(type="HEARTBEAT", payload={"status": "ready"})

    @staticmethod
    def _error_message(reason: str) -> WSMessage:
        return WSMessage(type="ERROR", payload={"error": reason})

    # -- signal handling ----------------------------------------------------

    def _install_signal_handlers(self) -> None:
        loop = self._loop
        if loop is None or not hasattr(loop, "add_signal_handler"):
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._signal_handlers[sig] = loop.add_signal_handler(
                    sig, lambda s=sig: asyncio.create_task(self._on_signal(s))
                )
            except (NotImplementedError, RuntimeError):
                # Not on the main thread or platform does not support it.
                pass

    def _restore_signal_handlers(self) -> None:
        loop = self._loop
        if loop is None:
            return
        for sig, old in self._signal_handlers.items():
            try:
                loop.remove_signal_handler(sig)
                if old is not None:
                    loop.add_signal_handler(sig, old)
            except (NotImplementedError, RuntimeError):
                pass
        self._signal_handlers.clear()

    async def _on_signal(self, sig: signal.Signals) -> None:
        logger.info("Received %s, shutting down HUD WebSocket server", sig.name)
        await self.stop()

    @property
    def connections(self) -> int:
        return len(self._connections)

    @property
    def status(self) -> HudStatus:
        return self._status

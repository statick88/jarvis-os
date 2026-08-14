"""
jarvis_os.hud — Runtime state dashboard for JARVIS-OS.
=====================================================

Provides the terminal TUI dashboard and the WebSocket server that expose the
runtime state of the voice pipeline (status, events, errors) to operators
and remote clients.

Wire and domain models live in :mod:`jarvis_os.hud.models`. The TUI
(:class:`JarvisTUI`) and the WebSocket server (:class:`HudWebSocketServer`)
are config-decoupled: they accept a :class:`HudConfig` (or its defaults) and
never import ``jarvis_os.config`` directly.
"""

from jarvis_os.hud.models import (
    HudCommand,
    HudConfig,
    HudMessage,
    HudStatus,
    WSMessage,
)
from jarvis_os.hud.tui import JarvisTUI
from jarvis_os.hud.websocket_server import (
    HudConnectionError,
    HudProtocolError,
    HudWebSocketError,
    HudWebSocketServer,
)

__version__ = "0.1.0"

__all__ = [
    "HudCommand",
    "HudConfig",
    "HudConnectionError",
    "HudMessage",
    "HudProtocolError",
    "HudStatus",
    "HudWebSocketError",
    "HudWebSocketServer",
    "JarvisTUI",
    "WSMessage",
    "__version__",
]


def __getattr__(name: str):
    """Lazy import for model symbols so ``from jarvis_os.hud import X`` works
    without eagerly loading every module. Mirrors voice_bridge's pattern.
    """
    if name in ("HudCommand", "HudConfig", "HudMessage", "HudStatus", "WSMessage"):
        from jarvis_os.hud import models

        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

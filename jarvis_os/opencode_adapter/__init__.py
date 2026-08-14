"""
OpenCode Adapter — WebSocket/HTTP transport for OpenCode agent orchestration.
=============================================================================
Provides a typed async client for skill execution over WebSocket with HTTP
fallback, following the JARVIS-OS message envelope protocol.
"""

from __future__ import annotations

from jarvis_os.opencode_adapter.client import OpenCodeClient
from jarvis_os.opencode_adapter.models import (
    ConnectionConfig,
    Envelope,
    MessageType,
)

__all__ = [
    "OpenCodeClient",
    "MessageType",
    "Envelope",
    "ConnectionConfig",
]

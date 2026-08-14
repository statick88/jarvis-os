"""
HUD — Pydantic Models
======================
Status, command, and WebSocket message models for the JARVIS-OS HUD.

Two layers are defined here:

- *Domain models* (``HudStatus``, ``HudCommand``, ``HudMessage``) describe the
  runtime state the HUD surfaces to the operator.
- *Wire model* (``WSMessage``) is the envelope exchanged over the WebSocket
  server (``HudWebSocketServer``), following the same UUID-correlation
  convention used by ``opencode_adapter``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Domain enums
# ---------------------------------------------------------------------------


class HudStatus(StrEnum):
    """Runtime states surfaced by the HUD."""

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


class HudCommand(StrEnum):
    """Commands accepted by the HUD from WebSocket clients."""

    REFRESH = "REFRESH"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CLEAR = "CLEAR"
    THEME = "THEME"
    SHUTDOWN = "SHUTDOWN"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class HudMessage(BaseModel):
    """A status update displayed by the TUI (and optionally broadcast)."""

    id: UUID = Field(default_factory=uuid4, description="Unique message identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO 8601 UTC timestamp",
    )
    status: HudStatus = Field(..., description="Runtime state at message time")
    summary: str = Field("", description="Short human-readable status line")
    severity: Literal["info", "warning", "error"] = Field(
        default="info", description="Display severity level"
    )
    payload: dict = Field(default_factory=dict, description="Optional structured details")


# ---------------------------------------------------------------------------
# HUD configuration
# ---------------------------------------------------------------------------


class HudConfig(BaseModel):
    """Transport, timing, and rendering configuration for the HUD.

    Field names and defaults mirror ``jarvis_os.config.HudSettings`` so a
    settings instance can be copied directly::

        HudConfig(**get_settings().hud.model_dump())
    """

    # TUI
    tui_refresh_interval_seconds: float = Field(
        default=1.0, gt=0, description="TUI render refresh interval in seconds"
    )
    tui_theme: str = Field(default="dark", description="TUI color theme (dark|light)")

    # WebSocket server (voice capture from host)
    ws_host: str = Field(default="0.0.0.0", description="WebSocket bind host")
    ws_port: int = Field(default=8083, ge=1, le=65535, description="WebSocket bind port")
    ws_path: str = Field(default="/voice", description="Accepted WebSocket request path")
    ws_max_message_size: int = Field(
        default=10 * 1024 * 1024, ge=1024, description="Max inbound message size in bytes"
    )
    ws_ping_interval_seconds: int = Field(
        default=20, ge=1, description="Server ping interval in seconds"
    )
    ws_ping_timeout_seconds: int = Field(
        default=10, ge=1, description="Seconds before a missed ping drops the connection"
    )

    # Audio
    audio_sample_rate: int = Field(default=16000, ge=1, description="Expected sample rate")
    audio_channels: int = Field(default=1, ge=1, description="Expected channel count")
    audio_chunk_ms: int = Field(default=100, ge=1, description="Audio chunk size in ms")


# ---------------------------------------------------------------------------
# WebSocket wire model
# ---------------------------------------------------------------------------


class WSMessage(BaseModel):
    """Wire-format envelope for HUD WebSocket traffic.

    Mirrors the ``opencode_adapter.models.Envelope`` convention: a UUID
    correlates requests/responses, and ``type`` discriminates the payload.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique message identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO 8601 UTC timestamp",
    )
    type: Literal["STATUS", "COMMAND", "EVENT", "ERROR", "HEARTBEAT", "ACK"] = Field(
        ..., description="Message type discriminator"
    )
    payload: dict = Field(default_factory=dict, description="Type-specific payload")

"""
OpenCode Adapter — Pydantic Models
====================================
Protocol models for the JARVIS-OS ↔ OpenCode message envelope system.
All messages flow through a typed envelope with correlation by UUID.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class MessageType(StrEnum):
    """Envelope message types for the OpenCode protocol."""

    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    EVENT = "EVENT"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    ACK = "ACK"


class Envelope(BaseModel):
    """Wire-format envelope for all OpenCode protocol messages."""

    id: UUID = Field(default_factory=uuid4, description="Unique message identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO 8601 UTC timestamp",
    )
    type: MessageType = Field(..., description="Message type discriminator")
    payload: dict = Field(default_factory=dict, description="Type-specific payload")


# ---------------------------------------------------------------------------
# Skill execution models
# ---------------------------------------------------------------------------

_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SkillContext(BaseModel):
    """Context passed with every skill execution request."""

    vault_path: str = Field(default="/app/vault", description="Path to the vault root")
    skills_path: str = Field(default="/app/.skills", description="Path to skills directory")
    session_id: UUID = Field(default_factory=uuid4, description="Session identifier")
    user_id: Optional[str] = Field(default=None, description="Optional user identifier")
    trace_id: Optional[UUID] = Field(default=None, description="Optional distributed trace ID")


class SkillExecutionRequest(BaseModel):
    """Payload for a REQUEST envelope that invokes a skill."""

    skill: str = Field(..., description="Skill name (lowercase, underscore-separated)")
    input: dict = Field(default_factory=dict, description="Skill input parameters")
    context: SkillContext = Field(default_factory=SkillContext, description="Execution context")

    @field_validator("skill")
    @classmethod
    def validate_skill_name(cls, v: str) -> str:
        if not _SKILL_NAME_RE.match(v):
            raise ValueError(
                f"Skill name must match /^[a-z][a-z0-9_]*$/ — got {v!r}"
            )
        return v


class SkillExecutionResponse(BaseModel):
    """Payload for a RESPONSE envelope returned after skill execution."""

    status: Literal["success", "error", "timeout"] = Field(
        ..., description="Execution outcome"
    )
    result: Optional[dict] = Field(default=None, description="Skill output (on success)")
    error: Optional[str] = Field(default=None, description="Error message (on failure)")
    duration_ms: float = Field(default=0.0, description="Execution wall-clock time in ms")
    skill: str = Field(..., description="Skill name that was executed")
    request_id: UUID = Field(..., description="Correlated REQUEST envelope id")


# ---------------------------------------------------------------------------
# Connection configuration
# ---------------------------------------------------------------------------


class ConnectionConfig(BaseModel):
    """Transport and timing configuration for OpenCodeClient."""

    ws_url: str = Field(
        default="ws://host.docker.internal:8765",
        description="WebSocket endpoint",
    )
    http_url: str = Field(
        default="http://host.docker.internal:8080",
        description="HTTP fallback endpoint",
    )
    heartbeat_interval: int = Field(
        default=15, ge=1, description="Heartbeat send interval in seconds"
    )
    heartbeat_timeout: int = Field(
        default=45, ge=1, description="Seconds before a missed heartbeat triggers disconnect"
    )
    reconnect_attempts: int = Field(
        default=5, ge=0, description="Max reconnection attempts before giving up"
    )
    reconnect_delay: float = Field(
        default=2.0, gt=0, description="Base delay (seconds) for exponential backoff"
    )


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class Heartbeat(BaseModel):
    """Payload carried inside a HEARTBEAT envelope."""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Heartbeat send time (ISO 8601 UTC)",
    )
    client_id: str = Field(
        default_factory=lambda: uuid4().hex[:12],
        description="Random client identifier for this connection",
    )

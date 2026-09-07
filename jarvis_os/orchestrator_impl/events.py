"""Domain event models for the JARVIS-OS orchestrator pipeline.

Events are emitted during skill execution and vault writes so the HUD
WebSocket server can broadcast real-time state to connected clients.

Event flow::

    SkillExecutionStart -> SkillExecutionComplete -> VaultWriteEvent
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExecutionStatus(StrEnum):
    """Outcome of a skill execution."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Event models
# ---------------------------------------------------------------------------


class SkillExecutionStart(BaseModel):
    """Emitted just before a skill execution begins."""

    skill_id: str = Field(..., description="Identifier of the skill being executed")
    session_id: str = Field(..., description="Voice or text session identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the event",
    )
    input_preview: str = Field(
        default="", description="Truncated input text for debugging"
    )

    def to_json(self) -> str:
        return self.model_dump_json()


class SkillExecutionComplete(BaseModel):
    """Emitted after a skill execution finishes (success or failure)."""

    skill_id: str = Field(..., description="Identifier of the executed skill")
    session_id: str = Field(..., description="Voice or text session identifier")
    status: ExecutionStatus = Field(..., description="Execution outcome")
    duration_ms: float = Field(..., description="Wall-clock duration in milliseconds")
    output_ref: str = Field(
        default="", description="Vault output path, e.g. vault/outputs/.../skill.md"
    )
    tts_text: Optional[str] = Field(
        default=None, description="Text to synthesize via TTS, if any"
    )
    error: Optional[str] = Field(
        default=None, description="Error message when status is FAILED or TIMEOUT"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the event",
    )

    def to_json(self) -> str:
        return self.model_dump_json()


class VaultWriteEvent(BaseModel):
    """Emitted after a vault output file is written and indexed."""

    path: str = Field(..., description="Absolute path of the written vault note")
    note_id: str = Field(..., description="Note identifier derived from filename")
    links_added: list[str] = Field(
        default_factory=list, description="Wikilinks added to related notes"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the write",
    )

    def to_json(self) -> str:
        return self.model_dump_json()


class VoiceEvent(BaseModel):
    """Emitted when voice session state changes."""

    session_id: str = Field(..., description="Voice session identifier")
    event_type: str = Field(..., description="open, close, stt_final, tts_chunk")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the event",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Event-specific data"
    )

    def to_json(self) -> str:
        return self.model_dump_json()

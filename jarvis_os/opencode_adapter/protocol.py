"""
OpenCode Adapter — Protocol Utilities
=======================================
Factory and serialization helpers for the message envelope protocol.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4

from jarvis_os.opencode_adapter.models import (
    Envelope,
    MessageType,
    SkillContext,
    SkillExecutionRequest,
    SkillExecutionResponse,
)


def create_envelope(type: MessageType, payload: dict) -> Envelope:
    """Create an Envelope with auto-generated UUID and UTC timestamp.

    Args:
        type: The message type discriminator.
        payload: The type-specific payload dict.

    Returns:
        A fully populated Envelope.
    """
    return Envelope(
        id=uuid4(),
        timestamp=datetime.now(timezone.utc),
        type=type,
        payload=payload,
    )


def create_request(
    skill: str,
    input: dict,
    context: SkillContext | None = None,
) -> Envelope:
    """Shorthand to build a REQUEST envelope for skill execution.

    Args:
        skill: Skill name (must match ``^[a-z][a-z0-9_]*$``).
        input: Skill input parameters.
        context: Execution context; uses defaults when *None*.

    Returns:
        A REQUEST Envelope wrapping a SkillExecutionRequest payload.
    """
    req = SkillExecutionRequest(
        skill=skill,
        input=input,
        context=context or SkillContext(),
    )
    return create_envelope(MessageType.REQUEST, req.model_dump(mode="json"))


def create_response(
    request_id: UUID,
    status: Literal["success", "error", "timeout"],
    result: dict | None = None,
    error: str | None = None,
    duration_ms: float = 0.0,
    skill: str = "",
) -> Envelope:
    """Build a RESPONSE envelope correlated to a REQUEST.

    Args:
        request_id: The ``id`` of the REQUEST envelope being answered.
        status: Execution outcome literal.
        result: Skill output dict (on success).
        error: Human-readable error message (on failure).
        duration_ms: Wall-clock execution time in milliseconds.
        skill: Skill name that was executed.

    Returns:
        A RESPONSE Envelope wrapping a SkillExecutionResponse payload.
    """
    resp = SkillExecutionResponse(
        status=status,
        result=result,
        error=error,
        duration_ms=duration_ms,
        skill=skill,
        request_id=request_id,
    )
    return create_envelope(MessageType.RESPONSE, resp.model_dump(mode="json"))


def validate_envelope(data: dict) -> Envelope:
    """Parse and validate a raw dict into an Envelope.

    Raises:
        pydantic.ValidationError: If the dict does not match the Envelope schema.
    """
    return Envelope.model_validate(data)


def envelope_to_json(env: Envelope) -> str:
    """Serialize an Envelope to a JSON string (UTF-8, no whitespace)."""
    return env.model_dump_json()


def envelope_from_json(raw: str) -> Envelope:
    """Parse a JSON string into a validated Envelope.

    Raises:
        pydantic.ValidationError: If the JSON does not match the Envelope schema.
        json.JSONDecodeError: If the string is not valid JSON.
    """
    data = json.loads(raw)
    return Envelope.model_validate(data)

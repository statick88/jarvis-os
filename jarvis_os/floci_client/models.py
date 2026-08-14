"""Pydantic models for the Floci S3 + SQS client."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BucketType(str, Enum):
    """S3 buckets managed by the Floci service."""

    INBOX = "jarvis-inbox"
    PROCESSED = "jarvis-processed"
    METRICS = "jarvis-metrics"


class SQSQueue(str, Enum):
    """SQS queues managed by the Floci service."""

    VOICE_COMMANDS = "jarvis-voice-commands"
    EVENTS = "jarvis-events"


class FlociConfig(BaseModel):
    """Configuration for the Floci async AWS client.

    All defaults target the local LocalStack instance.
    """

    endpoint_url: str = "http://localhost:4566"
    region_name: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"

    s3_buckets: dict[BucketType, str] = Field(
        default_factory=lambda: {
            BucketType.INBOX: BucketType.INBOX.value,
            BucketType.PROCESSED: BucketType.PROCESSED.value,
            BucketType.METRICS: BucketType.METRICS.value,
        }
    )
    sqs_queues: dict[SQSQueue, str] = Field(
        default_factory=lambda: {
            SQSQueue.VOICE_COMMANDS: SQSQueue.VOICE_COMMANDS.value,
            SQSQueue.EVENTS: SQSQueue.EVENTS.value,
        }
    )

    s3_init_retries: int = 5
    s3_init_delay: float = 2.0


class S3Object(BaseModel):
    """Metadata for an S3 object."""

    key: str
    bucket: str
    size: int
    last_modified: datetime
    etag: str


class SQSMessage(BaseModel):
    """A received SQS message."""

    message_id: str
    receipt_handle: str
    body: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

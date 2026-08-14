"""Async AWS S3 + SQS client for the Floci media pipeline."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import aioboto3
import botocore.exceptions

from jarvis_os.floci_client.models import (
    BucketType,
    FlociConfig,
    S3Object,
    SQSMessage,
    SQSQueue,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FlociError(Exception):
    """Base exception for all Floci client errors."""


class BucketNotFoundError(FlociError):
    """Raised when an S3 bucket does not exist and cannot be created."""


class QueueNotFoundError(FlociError):
    """Raised when an SQS queue does not exist and cannot be created."""


class UploadError(FlociError):
    """Raised when an S3 upload fails."""


class DownloadError(FlociError):
    """Raised when an S3 download fails."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class FlociClient:
    """Async AWS client for the Floci S3 + SQS service running on LocalStack.

    Usage::

        async with FlociClient() as client:
            await client.upload_audio("recording.wav", audio_bytes)
            messages = await client.receive_sqs(SQSQueue.VOICE_COMMANDS)
    """

    def __init__(self, config: FlociConfig | None = None) -> None:
        self._config = config or FlociConfig()
        self._session: aioboto3.Session | None = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create an aioboto3 session and verify S3 buckets / SQS queues.

        Retries up to ``config.s3_init_retries`` times with
        ``config.s3_init_delay`` seconds between attempts to allow
        LocalStack to start.
        """
        self._session = aioboto3.Session(
            aws_access_key_id=self._config.aws_access_key_id,
            aws_secret_access_key=self._config.aws_secret_access_key,
            region_name=self._config.region_name,
        )

        last_exc: Exception | None = None
        for attempt in range(1, self._config.s3_init_retries + 1):
            try:
                await self._ensure_buckets()
                await self._ensure_queues()
                self._initialized = True
                logger.info("FlociClient initialized (attempt %d)", attempt)
                return
            except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
                last_exc = exc
                logger.warning(
                    "Initialization attempt %d/%d failed: %s",
                    attempt,
                    self._config.s3_init_retries,
                    exc,
                )
                if attempt < self._config.s3_init_retries:
                    import asyncio

                    await asyncio.sleep(self._config.s3_init_delay)

        raise FlociError(
            f"Failed to initialize after {self._config.s3_init_retries} attempts"
        ) from last_exc

    async def close(self) -> None:
        """Close the underlying session."""
        self._session = None
        self._initialized = False
        logger.debug("FlociClient closed")

    async def __aenter__(self) -> FlociClient:
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_session(self) -> aioboto3.Session:
        if self._session is None:
            raise FlociError("Client not initialized — call initialize() first")
        return self._session

    def _s3_client(self) -> Any:
        session = self._ensure_session()
        return session.client(
            "s3",
            endpoint_url=self._config.endpoint_url,
            region_name=self._config.region_name,
        )

    def _sqs_client(self) -> Any:
        session = self._ensure_session()
        return session.client(
            "sqs",
            endpoint_url=self._config.endpoint_url,
            region_name=self._config.region_name,
        )

    async def _ensure_buckets(self) -> None:
        """Create S3 buckets if they do not already exist."""
        async with self._s3_client() as s3:
            for bucket_type, bucket_name in self._config.s3_buckets.items():
                try:
                    await s3.head_bucket(Bucket=bucket_name)
                    logger.debug("Bucket %s exists", bucket_name)
                except botocore.exceptions.ClientError:
                    logger.info("Creating bucket %s", bucket_name)
                    await s3.create_bucket(Bucket=bucket_name)

    async def _ensure_queues(self) -> None:
        """Create SQS queues if they do not already exist."""
        async with self._sqs_client() as sqs:
            for queue_type, queue_name in self._config.sqs_queues.items():
                try:
                    await sqs.get_queue_url(QueueName=queue_name)
                    logger.debug("Queue %s exists", queue_name)
                except botocore.exceptions.ClientError:
                    logger.info("Creating queue %s", queue_name)
                    await sqs.create_queue(QueueName=queue_name)

    # ------------------------------------------------------------------
    # S3 operations
    # ------------------------------------------------------------------

    async def upload_audio(
        self, key: str, data: bytes, content_type: str = "audio/wav"
    ) -> str:
        """Upload raw audio to the INBOX bucket.

        Returns:
            The ETag of the uploaded object.
        """
        bucket_name = self._config.s3_buckets[BucketType.INBOX]
        try:
            async with self._s3_client() as s3:
                response = await s3.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
                etag: str = response["ETag"].strip('"')
                logger.info("Uploaded %s to %s (%d bytes)", key, bucket_name, len(data))
                return etag
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise UploadError(f"Failed to upload {key}: {exc}") from exc

    async def download_audio(self, key: str) -> bytes:
        """Download raw audio from the INBOX bucket."""
        bucket_name = self._config.s3_buckets[BucketType.INBOX]
        try:
            async with self._s3_client() as s3:
                response = await s3.get_object(Bucket=bucket_name, Key=key)
                data: bytes = await response["Body"].read()
                logger.info("Downloaded %s from %s (%d bytes)", key, bucket_name, len(data))
                return data
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise DownloadError(f"Failed to download {key}: {exc}") from exc

    async def upload_transcription(self, key: str, data: dict) -> str:
        """Upload a transcription result as JSON to the PROCESSED bucket.

        Returns:
            The ETag of the uploaded object.
        """
        bucket_name = self._config.s3_buckets[BucketType.PROCESSED]
        try:
            async with self._s3_client() as s3:
                response = await s3.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=json.dumps(data, default=str).encode(),
                    ContentType="application/json",
                )
                etag: str = response["ETag"].strip('"')
                logger.info("Uploaded transcription %s to %s", key, bucket_name)
                return etag
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise UploadError(f"Failed to upload transcription {key}: {exc}") from exc

    async def upload_metrics(self, key: str, data: dict) -> str:
        """Upload daily metrics as JSON to the METRICS bucket.

        Returns:
            The ETag of the uploaded object.
        """
        bucket_name = self._config.s3_buckets[BucketType.METRICS]
        try:
            async with self._s3_client() as s3:
                response = await s3.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=json.dumps(data, default=str).encode(),
                    ContentType="application/json",
                )
                etag: str = response["ETag"].strip('"')
                logger.info("Uploaded metrics %s to %s", key, bucket_name)
                return etag
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise UploadError(f"Failed to upload metrics {key}: {exc}") from exc

    async def list_s3_objects(
        self, bucket: BucketType, prefix: str = ""
    ) -> list[S3Object]:
        """List objects in a bucket, optionally filtered by prefix."""
        bucket_name = self._config.s3_buckets[bucket]
        try:
            async with self._s3_client() as s3:
                response = await s3.list_objects_v2(
                    Bucket=bucket_name, Prefix=prefix
                )
                objects: list[S3Object] = []
                for obj in response.get("Contents", []):
                    objects.append(
                        S3Object(
                            key=obj["Key"],
                            bucket=bucket_name,
                            size=obj["Size"],
                            last_modified=obj["LastModified"],
                            etag=obj["ETag"].strip('"'),
                        )
                    )
                return objects
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise FlociError(f"Failed to list objects in {bucket_name}: {exc}") from exc

    async def delete_s3_object(self, bucket: BucketType, key: str) -> bool:
        """Delete an object from a bucket.

        Returns:
            ``True`` if the deletion succeeded.
        """
        bucket_name = self._config.s3_buckets[bucket]
        try:
            async with self._s3_client() as s3:
                await s3.delete_object(Bucket=bucket_name, Key=key)
                logger.info("Deleted %s from %s", key, bucket_name)
                return True
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise FlociError(f"Failed to delete {key} from {bucket_name}: {exc}") from exc

    # ------------------------------------------------------------------
    # SQS operations
    # ------------------------------------------------------------------

    async def send_sqs(
        self,
        queue: SQSQueue,
        message_body: str,
        delay_seconds: int = 0,
    ) -> str:
        """Send a message to an SQS queue.

        Returns:
            The ``MessageId`` of the sent message.
        """
        queue_name = self._config.sqs_queues[queue]
        try:
            async with self._sqs_client() as sqs:
                response = await sqs.send_message(
                    QueueUrl=await self._get_queue_url(sqs, queue_name),
                    MessageBody=message_body,
                    DelaySeconds=delay_seconds,
                )
                message_id: str = response["MessageId"]
                logger.info("Sent message %s to %s", message_id, queue_name)
                return message_id
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise FlociError(f"Failed to send message to {queue_name}: {exc}") from exc

    async def receive_sqs(
        self,
        queue: SQSQueue,
        max_messages: int = 10,
        wait_seconds: int = 20,
    ) -> list[SQSMessage]:
        """Long-poll receive messages from an SQS queue.

        Returns:
            A list of ``SQSMessage`` objects (empty if no messages available).
        """
        queue_name = self._config.sqs_queues[queue]
        try:
            async with self._sqs_client() as sqs:
                response = await sqs.receive_message(
                    QueueUrl=await self._get_queue_url(sqs, queue_name),
                    MaxNumberOfMessages=max_messages,
                    WaitTimeSeconds=wait_seconds,
                    MessageAttributeNames=["All"],
                    AttributeNames=["All"],
                )
                messages: list[SQSMessage] = []
                for msg in response.get("Messages", []):
                    messages.append(
                        SQSMessage(
                            message_id=msg["MessageId"],
                            receipt_handle=msg["ReceiptHandle"],
                            body=msg["Body"],
                            attributes=msg.get("Attributes", {}),
                        )
                    )
                logger.info(
                    "Received %d message(s) from %s", len(messages), queue_name
                )
                return messages
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise FlociError(
                f"Failed to receive messages from {queue_name}: {exc}"
            ) from exc

    async def delete_sqs_message(self, queue: SQSQueue, receipt_handle: str) -> bool:
        """Delete a processed message from an SQS queue.

        Returns:
            ``True`` if the deletion succeeded.
        """
        queue_name = self._config.sqs_queues[queue]
        try:
            async with self._sqs_client() as sqs:
                await sqs.delete_message(
                    QueueUrl=await self._get_queue_url(sqs, queue_name),
                    ReceiptHandle=receipt_handle,
                )
                logger.debug("Deleted message from %s", queue_name)
                return True
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise FlociError(
                f"Failed to delete message from {queue_name}: {exc}"
            ) from exc

    async def _get_queue_url(self, sqs: Any, queue_name: str) -> str:
        """Resolve a queue name to its URL."""
        response = await sqs.get_queue_url(QueueName=queue_name)
        return response["QueueUrl"]

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """Verify connectivity to S3 and SQS, and check each bucket / queue.

        Returns:
            A dict with ``s3`` (bool), ``sqs`` (bool), ``buckets``
            (dict[str, bool]), and ``queues`` (dict[str, bool]).
        """
        result: dict[str, Any] = {
            "s3": False,
            "sqs": False,
            "buckets": {},
            "queues": {},
        }

        # Check S3
        try:
            async with self._s3_client() as s3:
                await s3.list_buckets()
                result["s3"] = True
        except Exception as exc:
            logger.warning("S3 health check failed: %s", exc)

        # Check each bucket
        if result["s3"]:
            async with self._s3_client() as s3:
                for bucket_type, bucket_name in self._config.s3_buckets.items():
                    try:
                        await s3.head_bucket(Bucket=bucket_name)
                        result["buckets"][bucket_name] = True
                    except Exception:
                        result["buckets"][bucket_name] = False

        # Check SQS
        try:
            async with self._sqs_client() as sqs:
                await sqs.list_queues()
                result["sqs"] = True
        except Exception as exc:
            logger.warning("SQS health check failed: %s", exc)

        # Check each queue
        if result["sqs"]:
            async with self._sqs_client() as sqs:
                for queue_type, queue_name in self._config.sqs_queues.items():
                    try:
                        await sqs.get_queue_url(QueueName=queue_name)
                        result["queues"][queue_name] = True
                    except Exception:
                        result["queues"][queue_name] = False

        return result

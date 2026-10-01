"""Tests for ``jarvis_os.floci_client`` — the async S3/SQS client for LocalStack.

Covers:
  - Lifecycle: initialize, retry on transient failure, close, async context
  - The "not initialized" guard
  - S3: upload (audio / transcription / metrics), download, list, delete
  - SQS: send, receive, delete message
  - Error translation into the domain exceptions
  - The models (enums, config, S3Object, SQSMessage)

No network is touched: a fake aioboto3 Session is injected in place of the real
one, so these run without LocalStack.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import botocore.exceptions
import pytest

from jarvis_os.floci_client import client as fc_client
from jarvis_os.floci_client.client import (
    BucketNotFoundError,
    DownloadError,
    FlociClient,
    FlociError,
    QueueNotFoundError,
    UploadError,
)
from jarvis_os.floci_client.models import (
    BucketType,
    FlociConfig,
    S3Object,
    SQSMessage,
    SQSQueue,
)


# ── test doubles ─────────────────────────────────────────────────────

class FakeBody:
    """Stand-in for the streaming body returned by ``get_object``."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class FakeS3:
    def __init__(self, clock: "FakeClock") -> None:
        self.clock = clock

    async def __aenter__(self) -> "FakeS3":
        self.clock.s3_opened += 1
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.calls.append(("s3", "put_object", kwargs))
        if self.clock.fail_with is not None:
            raise self.clock.fail_with
        self.clock.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": '"abc123"'}

    async def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.calls.append(("s3", "get_object", kwargs))
        if self.clock.fail_with is not None:
            raise self.clock.fail_with
        if kwargs["Key"] not in self.clock.objects:
            raise KeyError(kwargs["Key"])
        return {"Body": FakeBody(self.clock.objects[kwargs["Key"]])}

    async def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.calls.append(("s3", "list_objects_v2", kwargs))
        if self.clock.fail_with is not None:
            raise self.clock.fail_with
        prefix = kwargs.get("Prefix", "")
        return {
            "Contents": [
                {
                    "Key": key,
                    "Size": len(value),
                    "LastModified": datetime(2026, 10, 1, tzinfo=timezone.utc),
                    "ETag": '"e1"',
                }
                for key, value in self.clock.objects.items()
                if key.startswith(prefix)
            ]
        }

    async def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.calls.append(("s3", "delete_object", kwargs))
        if self.clock.fail_with is not None:
            raise self.clock.fail_with
        self.clock.objects.pop(kwargs["Key"], None)
        return {}

    async def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["Bucket"] in self.clock.missing_buckets:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "404"}}, "HeadBucket"
            )
        return {}

    async def create_bucket(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.buckets_created.append(kwargs["Bucket"])
        return {}


class FakeSQS:
    def __init__(self, clock: "FakeClock") -> None:
        self.clock = clock

    async def __aenter__(self) -> "FakeSQS":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get_queue_url(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["QueueName"] in self.clock.missing_queues:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue"}},
                "GetQueueUrl",
            )
        return {"QueueUrl": f"http://local/{kwargs['QueueName']}"}

    async def create_queue(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.queues_created.append(kwargs["QueueName"])
        return {"QueueUrl": f"http://local/{kwargs['QueueName']}"}

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.calls.append(("sqs", "send_message", kwargs))
        if self.clock.fail_with is not None:
            raise self.clock.fail_with
        return {"MessageId": "m-1", "MD5OfMessageBody": "d41d8cd98f00b204e9800998ecf8427e"}

    async def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.calls.append(("sqs", "receive_message", kwargs))
        if self.clock.fail_with is not None:
            raise self.clock.fail_with
        if not self.clock.messages:
            return {"Messages": []}
        return {"Messages": list(self.clock.messages)}

    async def delete_message(self, **kwargs: Any) -> dict[str, Any]:
        self.clock.calls.append(("sqs", "delete_message", kwargs))
        if self.clock.fail_with is not None:
            raise self.clock.fail_with
        return {}


class FakeClock:
    """Shared mutable state the fakes read and write."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.objects: dict[str, bytes] = {}
        self.messages: list[dict[str, Any]] = []
        self.buckets_created: list[str] = []
        self.queues_created: list[str] = []
        self.missing_buckets: set[str] = set()
        self.missing_queues: set[str] = set()
        self.fail_with: Exception | None = None
        self.s3_opened = 0

    def last(self, service: str, op: str) -> dict[str, Any] | None:
        for svc, name, kwargs in reversed(self.calls):
            if svc == service and name == op:
                return kwargs
        return None


class FakeSession:
    def __init__(self, clock: FakeClock, **kwargs: Any) -> None:
        self.clock = clock
        self.init_kwargs = kwargs

    def client(self, service: str, **kwargs: Any) -> Any:
        if service == "s3":
            return FakeS3(self.clock)
        if service == "sqs":
            return FakeSQS(self.clock)
        raise AssertionError(f"unexpected service {service!r}")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> list[FakeSession]:
    """Replace aioboto3.Session and collect the instances the code creates."""
    created: list[FakeSession] = []

    def factory(**kwargs: Any) -> FakeSession:
        session = FakeSession(clock, **kwargs)
        created.append(session)
        return session

    monkeypatch.setattr(fc_client.aioboto3, "Session", factory)
    return created


@pytest.fixture
async def client(fake_session: list[FakeSession]) -> FlociClient:
    c = FlociClient()
    await c.initialize()
    return c


# ── models ───────────────────────────────────────────────────────────

class TestModels:
    def test_bucket_type_values(self) -> None:
        assert {b.value for b in BucketType} == {
            "jarvis-inbox", "jarvis-processed", "jarvis-metrics"
        }

    def test_sqs_queue_values(self) -> None:
        assert {q.value for q in SQSQueue} == {"jarvis-voice-commands", "jarvis-events"}

    def test_config_defaults(self) -> None:
        cfg = FlociConfig()
        assert cfg.endpoint_url == "http://localhost:4566"
        assert cfg.region_name == "us-east-1"
        assert cfg.aws_access_key_id == "test"
        assert set(cfg.s3_buckets) == set(BucketType)
        assert set(cfg.sqs_queues) == set(SQSQueue)

    def test_s3_object(self) -> None:
        obj = S3Object(
            key="k", bucket="b", size=10,
            last_modified=datetime.now(timezone.utc), etag="e",
        )
        assert obj.key == "k" and obj.size == 10

    def test_sqs_message_defaults(self) -> None:
        msg = SQSMessage(message_id="m", receipt_handle="r", body="{}")
        assert msg.attributes == {}
        assert msg.received_at.tzinfo is not None

    def test_config_rejects_unknown_bucket(self) -> None:
        with pytest.raises(Exception):
            FlociConfig(s3_buckets={"nope": "x"})  # type: ignore[dict-item]


# ── lifecycle ────────────────────────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_creates_a_session(self, fake_session: list[FakeSession]) -> None:
        c = FlociClient()
        await c.initialize()
        assert c._initialized is True
        assert len(fake_session) == 1
        assert fake_session[0].init_kwargs["region_name"] == "us-east-1"

    @pytest.mark.asyncio
    async def test_initialize_creates_missing_buckets_and_queues(
        self, clock: FakeClock, fake_session: list[FakeSession]
    ) -> None:
        clock.missing_buckets = {"jarvis-inbox"}
        clock.missing_queues = {"jarvis-events"}
        c = FlociClient()
        await c.initialize()
        assert "jarvis-inbox" in clock.buckets_created
        assert "jarvis-events" in clock.queues_created

    @pytest.mark.asyncio
    async def test_initialize_retries_then_raises(
        self, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
    ) -> None:
        """Transient LocalStack errors are retried, then surfaced as FlociError."""
        attempts = {"n": 0}

        async def always_fail(self: Any) -> None:
            attempts["n"] += 1
            raise botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "HeadBucket")

        monkeypatch.setattr(FlociClient, "_ensure_buckets", always_fail)
        monkeypatch.setattr(
            FlociClient, "_ensure_queues", lambda self: _noop()
        )
        # zero delay so the retry loop is fast
        cfg = FlociConfig(s3_init_retries=3, s3_init_delay=0)
        c = FlociClient(cfg)
        with pytest.raises(FlociError, match="after 3 attempts"):
            await c.initialize()
        assert attempts["n"] == 3

    @pytest.mark.asyncio
    async def test_initialize_succeeds_after_a_transient_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        async def flaky(self: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "HeadBucket")

        monkeypatch.setattr(FlociClient, "_ensure_buckets", flaky)
        monkeypatch.setattr(FlociClient, "_ensure_queues", lambda self: _noop())
        c = FlociClient(FlociConfig(s3_init_retries=3, s3_init_delay=0))
        await c.initialize()
        assert c._initialized is True
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_close_resets_state(self, client: FlociClient) -> None:
        await client.close()
        assert client._initialized is False
        assert client._session is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self, fake_session: list[FakeSession]) -> None:
        async with FlociClient() as c:
            assert c._initialized is True
        assert c._initialized is False

    @pytest.mark.asyncio
    async def test_operations_require_initialization(self) -> None:
        c = FlociClient()
        with pytest.raises(FlociError, match="not initialized"):
            await c.upload_audio("k", b"x")

    @pytest.mark.asyncio
    async def test_client_helpers_also_guard(
        self, client: FlociClient
    ) -> None:
        client._session = None
        with pytest.raises(FlociError, match="not initialized"):
            client._s3_client()
        with pytest.raises(FlociError, match="not initialized"):
            client._sqs_client()


async def _noop() -> None:
    return None


# ── S3 ───────────────────────────────────────────────────────────────

class TestS3Operations:
    @pytest.mark.asyncio
    async def test_upload_audio_returns_unquoted_etag(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        etag = await client.upload_audio("a.wav", b"RIFF123", content_type="audio/wav")
        assert etag == "abc123"
        call = clock.last("s3", "put_object")
        assert call is not None
        assert call["Bucket"] == "jarvis-inbox"
        assert call["ContentType"] == "audio/wav"

    @pytest.mark.asyncio
    async def test_upload_audio_wraps_transport_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Put")
        with pytest.raises(UploadError, match="Failed to upload a.wav"):
            await client.upload_audio("a.wav", b"x")

    @pytest.mark.asyncio
    async def test_download_audio_round_trips(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.objects["a.wav"] = b"RIFFpayload"
        assert await client.download_audio("a.wav") == b"RIFFpayload"

    @pytest.mark.asyncio
    async def test_download_audio_wraps_transport_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Get")
        with pytest.raises(DownloadError, match="Failed to download a.wav"):
            await client.download_audio("a.wav")

    @pytest.mark.asyncio
    async def test_upload_transcription_targets_processed_bucket(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        etag = await client.upload_transcription("t.json", {"text": "hola"})
        assert etag == "abc123"
        call = clock.last("s3", "put_object")
        assert call is not None
        assert call["Bucket"] == "jarvis-processed"
        assert call["ContentType"] == "application/json"
        assert json.loads(call["Body"]) == {"text": "hola"}

    @pytest.mark.asyncio
    async def test_upload_transcription_serializes_non_json_values(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        await client.upload_transcription("t.json", {"at": datetime(2026, 10, 1)})
        call = clock.last("s3", "put_object")
        assert call is not None and b"2026" in call["Body"]

    @pytest.mark.asyncio
    async def test_upload_transcription_wraps_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Put")
        with pytest.raises(UploadError):
            await client.upload_transcription("t.json", {})

    @pytest.mark.asyncio
    async def test_upload_metrics_targets_metrics_bucket(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        await client.upload_metrics("m.json", {"count": 1})
        call = clock.last("s3", "put_object")
        assert call is not None and call["Bucket"] == "jarvis-metrics"

    @pytest.mark.asyncio
    async def test_upload_metrics_wraps_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Put")
        with pytest.raises(UploadError):
            await client.upload_metrics("m.json", {})

    @pytest.mark.asyncio
    async def test_list_objects_maps_the_response(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.objects["a/1.txt"] = b"one"
        clock.objects["a/2.txt"] = b"twotwo"
        clock.objects["b/3.txt"] = b"three"
        objects = await client.list_s3_objects(BucketType.INBOX, prefix="a/")
        assert [o.key for o in objects] == ["a/1.txt", "a/2.txt"]
        assert objects[0].size == 3
        assert objects[0].etag == "e1"
        assert objects[0].bucket == "jarvis-inbox"

    @pytest.mark.asyncio
    async def test_list_objects_empty_bucket(
        self, client: FlociClient
    ) -> None:
        assert await client.list_s3_objects(BucketType.INBOX) == []

    @pytest.mark.asyncio
    async def test_list_objects_wraps_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "List")
        with pytest.raises(FlociError, match="Failed to list objects"):
            await client.list_s3_objects(BucketType.INBOX)

    @pytest.mark.asyncio
    async def test_delete_object_reports_success(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.objects["a/1.txt"] = b"x"
        assert await client.delete_s3_object(BucketType.INBOX, "a/1.txt") is True
        assert "a/1.txt" not in clock.objects

    @pytest.mark.asyncio
    async def test_delete_object_wraps_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Del")
        with pytest.raises(FlociError, match="Failed to delete"):
            await client.delete_s3_object(BucketType.INBOX, "k")


# ── SQS ──────────────────────────────────────────────────────────────

class TestSQSOperations:
    @pytest.mark.asyncio
    async def test_send_sqs_returns_message_id(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        assert await client.send_sqs(SQSQueue.EVENTS, "hello") == "m-1"
        call = clock.last("sqs", "send_message")
        assert call is not None
        assert call["QueueUrl"].endswith("jarvis-events")
        assert call["MessageBody"] == "hello"
        assert call["DelaySeconds"] == 0

    @pytest.mark.asyncio
    async def test_send_sqs_passes_delay(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        await client.send_sqs(SQSQueue.VOICE_COMMANDS, "x", delay_seconds=5)
        call = clock.last("sqs", "send_message")
        assert call is not None and call["DelaySeconds"] == 5

    @pytest.mark.asyncio
    async def test_send_sqs_wraps_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Send")
        with pytest.raises(FlociError, match="Failed to send message"):
            await client.send_sqs(SQSQueue.EVENTS, "x")

    @pytest.mark.asyncio
    async def test_receive_returns_empty_list_when_no_messages(
        self, client: FlociClient
    ) -> None:
        assert await client.receive_sqs(SQSQueue.EVENTS) == []

    @pytest.mark.asyncio
    async def test_receive_maps_messages(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.messages = [
            {
                "MessageId": "m-1",
                "ReceiptHandle": "rh-1",
                "Body": "hola",
                "Attributes": {"SentTimestamp": "1"},
            }
        ]
        messages = await client.receive_sqs(SQSQueue.EVENTS)
        assert len(messages) == 1
        assert isinstance(messages[0], SQSMessage)
        assert messages[0].message_id == "m-1"
        assert messages[0].receipt_handle == "rh-1"
        assert messages[0].body == "hola"
        assert messages[0].attributes == {"SentTimestamp": "1"}

    @pytest.mark.asyncio
    async def test_receive_defaults_attributes(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.messages = [
            {"MessageId": "m", "ReceiptHandle": "r", "Body": "b"}
        ]
        messages = await client.receive_sqs(SQSQueue.EVENTS)
        assert messages[0].attributes == {}

    @pytest.mark.asyncio
    async def test_receive_passes_poll_parameters(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        await client.receive_sqs(SQSQueue.EVENTS, max_messages=5, wait_seconds=3)
        call = clock.last("sqs", "receive_message")
        assert call is not None
        assert call["MaxNumberOfMessages"] == 5
        assert call["WaitTimeSeconds"] == 3

    @pytest.mark.asyncio
    async def test_receive_wraps_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Recv")
        with pytest.raises(FlociError, match="Failed to receive messages"):
            await client.receive_sqs(SQSQueue.EVENTS)

    @pytest.mark.asyncio
    async def test_delete_message(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        assert await client.delete_sqs_message(SQSQueue.EVENTS, "rh-1") is True
        call = clock.last("sqs", "delete_message")
        assert call is not None and call["ReceiptHandle"] == "rh-1"

    @pytest.mark.asyncio
    async def test_delete_message_wraps_errors(
        self, client: FlociClient, clock: FakeClock
    ) -> None:
        clock.fail_with = botocore.exceptions.ClientError({"Error": {"Code": "500"}}, "Del")
        with pytest.raises(FlociError, match="Failed to delete message"):
            await client.delete_sqs_message(SQSQueue.EVENTS, "rh-1")


# ── exception hierarchy ──────────────────────────────────────────────

def test_exception_hierarchy() -> None:
    for exc in (BucketNotFoundError, QueueNotFoundError, UploadError, DownloadError):
        assert issubclass(exc, FlociError)
    assert issubclass(FlociError, Exception)

"""Tests for ``jarvis_os.voice_bridge.orchestrator_client`` — the session pool.

Covers:
  - Pool admission: generated ids, duplicate rejection, capacity limits
  - Ack negotiation, including the timeout path
  - Listener wiring and the activity-timestamp refresh
  - Graceful close, including unknown sessions and close failures
  - ``send_audio`` / ``send_text`` delegation and rejection
  - Metrics, including idle detection
  - Lifecycle: start / stop / async context manager
  - The idle-session cleanup loop
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import pytest

from jarvis_os.voice_bridge import orchestrator_client as oc
from jarvis_os.voice_bridge.client import (
    JarvisVoiceError,
    STTFinalEvent,
    STTPartialEvent,
    TTSChunkEvent,
)


# ── test double ──────────────────────────────────────────────────────

class FakeWS:
    """Stand-in for ``JarvisVoiceBridgeWS``.

    Records every interaction and lets a test drive the inbound callbacks
    (ack, partial, final, audio chunk) that the real WebSocket would deliver.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.connected_with: dict[str, Any] | None = None
        self.close_reasons: list[str] = []
        self.sent_audio: list[tuple[bytes, str | None]] = []
        self.sent_text: list[tuple[str, str | None]] = []
        self.close_should_fail = False
        self.ack_payload: dict[str, Any] | None = {
            "session_id": "ignored",
            "websocket_enabled": True,
            "stt_model": "whisper-base",
            "tts_voice": "es_ES-pacifico",
        }
        self.deliver_ack = True
        self._cbs: dict[str, Callable] = {}

    async def connect(self, session_id: str, token: str | None = None) -> None:
        self.connected_with = {"session_id": session_id, "token": token}

    async def close(self, reason: str = "client_close") -> None:
        if self.close_should_fail:
            raise RuntimeError("socket already gone")
        self.close_reasons.append(reason)

    def send_audio(self, pcm_bytes: bytes, session_id: str | None = None) -> None:
        self.sent_audio.append((pcm_bytes, session_id))

    def send_text(self, text: str, session_id: str | None = None) -> None:
        self.sent_text.append((text, session_id))

    def on_session_ack(self, cb: Callable) -> None:
        self._cbs["ack"] = cb
        if self.deliver_ack and self.ack_payload is not None:
            # The pool registers the listener and then awaits, so delivering
            # on the next loop tick lands after registration completes.
            asyncio.get_event_loop().call_soon(cb, self.ack_payload)

    def on_partial_transcript(self, cb: Callable) -> None:
        self._cbs["partial"] = cb

    def on_final_transcript(self, cb: Callable) -> None:
        self._cbs["final"] = cb

    def on_audio_chunk(self, cb: Callable) -> None:
        self._cbs["chunk"] = cb

    # helpers used by the tests to simulate server-pushed events
    def emit_partial(self, session_id: str) -> None:
        self._cbs["partial"](STTPartialEvent("hola", 0.5, session_id))

    def emit_final(self, session_id: str) -> None:
        self._cbs["final"](STTFinalEvent("hola", 0.9, session_id, 120))

    def emit_chunk(self, session_id: str) -> None:
        self._cbs["chunk"](TTSChunkEvent(b"pcm", session_id, "pcm", 22050, False, 10))


@pytest.fixture
def fake_ws_factory(monkeypatch: pytest.MonkeyPatch) -> list[FakeWS]:
    """Install a FakeWS constructor in the module and collect the instances."""
    created: list[FakeWS] = []

    def factory(host: str, port: int) -> FakeWS:
        ws = FakeWS(host, port)
        created.append(ws)
        return ws

    monkeypatch.setattr(oc, "JarvisVoiceBridgeWS", factory)
    return created


@pytest.fixture
def pool() -> oc.OrchestratorVoiceClient:
    return oc.OrchestratorVoiceClient(host="voice", port=8080)


# ── SessionAck ───────────────────────────────────────────────────────

class TestSessionAck:
    def test_stores_all_fields(self) -> None:
        ack = oc.SessionAck("s-1", True, "whisper-base", "es_ES-pacifico")
        assert ack.session_id == "s-1"
        assert ack.websocket_enabled is True
        assert ack.stt_model == "whisper-base"
        assert ack.tts_voice == "es_ES-pacifico"


# ── admission control ────────────────────────────────────────────────

class TestOpenSession:
    @pytest.mark.asyncio
    async def test_generates_session_id_when_omitted(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        ack = await pool.open_session()
        assert len(fake_ws_factory) == 1
        assert fake_ws_factory[0].connected_with["session_id"]
        assert isinstance(ack, oc.SessionAck)

    @pytest.mark.asyncio
    async def test_uses_provided_session_id(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-42")
        assert fake_ws_factory[0].connected_with["session_id"] == "s-42"
        assert "s-42" in pool._sessions

    @pytest.mark.asyncio
    async def test_duplicate_session_is_rejected(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        with pytest.raises(JarvisVoiceError, match="already exists"):
            await pool.open_session("s-1")
        assert len(fake_ws_factory) == 1

    @pytest.mark.asyncio
    async def test_pool_capacity_is_enforced(self, fake_ws_factory: list[FakeWS]) -> None:
        pool = oc.OrchestratorVoiceClient(host="v", port=8080, max_sessions=2)
        await pool.open_session("a")
        await pool.open_session("b")
        with pytest.raises(JarvisVoiceError, match=r"Session pool full \(2/2\)"):
            await pool.open_session("c")
        assert len(pool._sessions) == 2

    @pytest.mark.asyncio
    async def test_token_is_forwarded_to_connect(
        self, fake_ws_factory: list[FakeWS]
    ) -> None:
        pool = oc.OrchestratorVoiceClient(host="v", port=8080, token="jwt-123")
        await pool.open_session("s-1")
        assert fake_ws_factory[0].connected_with["token"] == "jwt-123"

    @pytest.mark.asyncio
    async def test_meta_records_timestamps(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        meta = pool._session_meta["s-1"]
        assert set(meta) == {"created_at", "last_activity", "ack"}
        assert isinstance(meta["ack"], oc.SessionAck)


# ── ack negotiation ──────────────────────────────────────────────────

class TestWaitForAck:
    @pytest.mark.asyncio
    async def test_ack_payload_is_mapped(self, pool: oc.OrchestratorVoiceClient) -> None:
        ws = FakeWS("v", 8080)
        ws.ack_payload = {
            "session_id": "server-1",
            "websocket_enabled": False,
            "stt_model": "whisper-small",
            "tts_voice": "kokoro-es",
        }
        ack = await pool._wait_for_ack(ws, "s-1", timeout=1.0)  # type: ignore[arg-type]
        assert ack.session_id == "server-1"
        assert ack.websocket_enabled is False
        assert ack.stt_model == "whisper-small"
        assert ack.tts_voice == "kokoro-es"

    @pytest.mark.asyncio
    async def test_missing_fields_fall_back_to_defaults(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        ws = FakeWS("v", 8080)
        ws.ack_payload = {}
        ack = await pool._wait_for_ack(ws, "fallback-id", timeout=1.0)  # type: ignore[arg-type]
        assert ack.session_id == "fallback-id"
        assert ack.websocket_enabled is True
        assert ack.stt_model == "whisper-base"
        assert ack.tts_voice == "es_ES-pacifico"

    @pytest.mark.asyncio
    async def test_timeout_raises(self, pool: oc.OrchestratorVoiceClient) -> None:
        ws = FakeWS("v", 8080)
        ws.deliver_ack = False
        with pytest.raises(JarvisVoiceError, match="No session_ack received"):
            await pool._wait_for_ack(ws, "s-1", timeout=0.05)  # type: ignore[arg-type]


# ── listeners and activity tracking ──────────────────────────────────

class TestListeners:
    @pytest.mark.asyncio
    async def test_events_refresh_last_activity(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        ws = fake_ws_factory[0]
        pool._session_meta["s-1"]["last_activity"] = 0.0

        ws.emit_partial("s-1")
        assert pool._session_meta["s-1"]["last_activity"] > 0.0

        pool._session_meta["s-1"]["last_activity"] = 0.0
        ws.emit_final("s-1")
        assert pool._session_meta["s-1"]["last_activity"] > 0.0

        pool._session_meta["s-1"]["last_activity"] = 0.0
        ws.emit_chunk("s-1")
        assert pool._session_meta["s-1"]["last_activity"] > 0.0

    @pytest.mark.asyncio
    async def test_events_for_another_session_are_ignored(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        pool._session_meta["s-1"]["last_activity"] = 0.0
        fake_ws_factory[0].emit_partial("other-session")
        assert pool._session_meta["s-1"]["last_activity"] == 0.0

    def test_touch_unknown_session_is_a_noop(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        pool._touch_session("nope")  # must not raise

    def test_public_listener_registration(self, pool: oc.OrchestratorVoiceClient) -> None:
        noop = lambda *_: None  # noqa: E731
        pool.on_partial_transcript(noop)
        pool.on_final_transcript(noop)
        pool.on_audio_chunk(noop)
        pool.on_state_change(noop)
        assert pool._listeners["partial"] == [noop]
        assert pool._listeners["final"] == [noop]
        assert pool._listeners["audio_chunk"] == [noop]
        assert pool._listeners["state_change"] == [noop]


# ── closing ──────────────────────────────────────────────────────────

class TestCloseSession:
    @pytest.mark.asyncio
    async def test_close_removes_and_closes(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        await pool.close_session("s-1")
        assert "s-1" not in pool._sessions
        assert "s-1" not in pool._session_meta
        assert fake_ws_factory[0].close_reasons == ["orchestrator_close"]

    @pytest.mark.asyncio
    async def test_closing_unknown_session_is_a_noop(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        await pool.close_session("ghost")  # must not raise

    @pytest.mark.asyncio
    async def test_close_failure_is_swallowed(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        fake_ws_factory[0].close_should_fail = True
        await pool.close_session("s-1")  # must not raise
        assert "s-1" not in pool._sessions


# ── sending ──────────────────────────────────────────────────────────

class TestSend:
    @pytest.mark.asyncio
    async def test_send_audio_delegates(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        await pool.send_audio("s-1", b"\x01\x02")
        assert fake_ws_factory[0].sent_audio == [(b"\x01\x02", "s-1")]

    @pytest.mark.asyncio
    async def test_send_text_delegates(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        await pool.send_text("s-1", "hola")
        assert fake_ws_factory[0].sent_text == [("hola", "s-1")]

    @pytest.mark.asyncio
    async def test_send_audio_requires_session(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        with pytest.raises(JarvisVoiceError, match="not found"):
            await pool.send_audio("ghost", b"x")

    @pytest.mark.asyncio
    async def test_send_text_requires_session(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        with pytest.raises(JarvisVoiceError, match="not found"):
            await pool.send_text("ghost", "x")

    @pytest.mark.asyncio
    async def test_send_refreshes_activity(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.open_session("s-1")
        pool._session_meta["s-1"]["last_activity"] = 0.0
        await pool.send_audio("s-1", b"x")
        assert pool._session_meta["s-1"]["last_activity"] > 0.0
        pool._session_meta["s-1"]["last_activity"] = 0.0
        await pool.send_text("s-1", "x")
        assert pool._session_meta["s-1"]["last_activity"] > 0.0


# ── metrics ──────────────────────────────────────────────────────────

class TestMetrics:
    def test_empty_pool(self, pool: oc.OrchestratorVoiceClient) -> None:
        m = pool.metrics()
        assert m["active_sessions"] == 0
        assert m["max_sessions"] == oc._DEFAULT_MAX_SESSIONS
        assert m["idle_sessions"] == 0
        assert m["available_slots"] == oc._DEFAULT_MAX_SESSIONS
        assert m["host"] == "voice:8080"

    @pytest.mark.asyncio
    async def test_counts_active_and_available(
        self, fake_ws_factory: list[FakeWS]
    ) -> None:
        pool = oc.OrchestratorVoiceClient(host="v", port=8080, max_sessions=3)
        await pool.open_session("a")
        await pool.open_session("b")
        m = pool.metrics()
        assert m["active_sessions"] == 2
        assert m["available_slots"] == 1

    @pytest.mark.asyncio
    async def test_detects_idle_sessions(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        import time

        await pool.open_session("fresh")
        await pool.open_session("stale")
        pool._session_meta["stale"]["last_activity"] = time.monotonic() - 10_000
        assert pool.metrics()["idle_sessions"] == 1

    def test_metrics_with_zero_max(self) -> None:
        pool = oc.OrchestratorVoiceClient(host="v", port=1, max_sessions=0)
        m = pool.metrics()
        assert m["max_sessions"] == 0
        assert m["available_slots"] == 0


# ── lifecycle ────────────────────────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_cleanup_task(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        await pool.start()
        assert pool._cleanup_task is not None
        assert not pool._cleanup_task.done()
        await pool.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        await pool.start()
        first = pool._cleanup_task
        await pool.start()
        assert pool._cleanup_task is first
        await pool.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task_and_closes_sessions(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.start()
        await pool.open_session("s-1")
        await pool.stop()
        assert pool._sessions == {}
        assert fake_ws_factory[0].close_reasons == ["orchestrator_close"]

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        await pool.stop()  # must not raise

    @pytest.mark.asyncio
    async def test_stop_tolerates_close_failure(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        await pool.start()
        await pool.open_session("s-1")
        fake_ws_factory[0].close_should_fail = True
        await pool.stop()  # must not raise

    @pytest.mark.asyncio
    async def test_async_context_manager(
        self, pool: oc.OrchestratorVoiceClient, fake_ws_factory: list[FakeWS]
    ) -> None:
        async with pool as entered:
            assert entered is pool
            assert pool._cleanup_task is not None
        assert pool._shutdown.is_set()

    @pytest.mark.asyncio
    async def test_context_manager_propagates_exceptions(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        with pytest.raises(ValueError, match="boom"):
            async with pool:
                raise ValueError("boom")


# ── idle cleanup loop ────────────────────────────────────────────────

async def _bounded_cleanup_loop(
    pool: oc.OrchestratorVoiceClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive one sweep of ``_cleanup_loop`` without waiting 30 real seconds.

    The sweep is only reachable after the idle wait elapses and shutdown is
    still clear. So: first wait times out (sweep runs), second wait sets the
    shutdown flag (loop breaks). Any further iteration is cancelled as a guard
    against an infinite loop.
    """
    real_wait_for = asyncio.wait_for  # captured before the patch below
    calls = {"n": 0}

    async def fake_wait_for(awaitable: Any, timeout: float | None = None) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError
        if calls["n"] == 2:
            pool._shutdown.set()
            return await awaitable
        raise asyncio.CancelledError  # pragma: no cover - safety net

    monkeypatch.setattr(oc.asyncio, "wait_for", fake_wait_for)
    await real_wait_for(pool._cleanup_loop(), timeout=2.0)


class TestCleanupLoop:
    @pytest.mark.asyncio
    async def test_removes_expired_sessions(
        self,
        pool: oc.OrchestratorVoiceClient,
        fake_ws_factory: list[FakeWS],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import time

        await pool.open_session("stale")
        pool._session_meta["stale"]["last_activity"] = time.monotonic() - 10_000

        await _bounded_cleanup_loop(pool, monkeypatch)

        assert "stale" not in pool._sessions
        assert fake_ws_factory[0].close_reasons == ["orchestrator_close"]

    @pytest.mark.asyncio
    async def test_keeps_fresh_sessions(
        self,
        pool: oc.OrchestratorVoiceClient,
        fake_ws_factory: list[FakeWS],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await pool.open_session("fresh")

        await _bounded_cleanup_loop(pool, monkeypatch)

        assert "fresh" in pool._sessions

    @pytest.mark.asyncio
    async def test_loop_exits_when_shutdown_set(
        self, pool: oc.OrchestratorVoiceClient
    ) -> None:
        pool._shutdown.set()
        await asyncio.wait_for(pool._cleanup_loop(), timeout=1.0)


def test_module_defaults() -> None:
    assert oc._DEFAULT_MAX_SESSIONS == 10
    assert oc._DEFAULT_IDLE_TIMEOUT_S == 300


def test_pool_exposes_private_helpers() -> None:
    for name in (
        "_wait_for_ack",
        "_wire_listeners",
        "_touch_session",
        "_cleanup_loop",
    ):
        assert callable(getattr(oc.OrchestratorVoiceClient, name))

"""Tests for ``jarvis_os.voice_bridge.server`` — the voice-pipeline FastAPI app.

Covers:
  - ``SessionManager`` bookkeeping: add, touch, get, remove, active_count
  - The idle-cleanup loop, including websocket close and error tolerance
  - The REST fallbacks: /health, /v1/models, /stt, /tts
  - The /v1/audio/stream WebSocket handshake: session_open -> session_ack
  - Startup and shutdown hooks

The whisper/piper/kokoro backends are real subprocesses and are not exercised
here; the pipelines are only constructed and stopped, never fed audio.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jarvis_os.voice_bridge import server as srv


# ── test doubles ─────────────────────────────────────────────────────

class FakeWebSocket:
    """Records close() calls and can be made to fail on close."""

    def __init__(self) -> None:
        self.closed: list[tuple[int, str]] = []
        self.close_should_fail = False

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.close_should_fail:
            raise RuntimeError("already closed")
        self.closed.append((code, reason))

    async def accept(self) -> None:  # pragma: no cover - unused by these tests
        return None

    async def send_text(self, message: str) -> None:  # pragma: no cover
        return None

    async def receive_text(self) -> str:  # pragma: no cover
        return "{}"

    async def receive_bytes(self) -> bytes:  # pragma: no cover
        return b""


# ── SessionManager ───────────────────────────────────────────────────

class TestSessionManager:
    def test_add_records_session_metadata(self) -> None:
        sm = srv.SessionManager()
        ws = FakeWebSocket()
        sm.add("s-1", ws)  # type: ignore[arg-type]
        info = sm.get("s-1")
        assert info is not None
        assert info["ws"] is ws
        assert info["format"] == "pcm"
        assert info["sample_rate"] == 16000
        assert info["created_at"] <= info["last_activity"]

    def test_add_accepts_format_and_rate(self) -> None:
        sm = srv.SessionManager()
        sm.add("s-1", FakeWebSocket(), "wav", 22050)  # type: ignore[arg-type]
        info = sm.get("s-1")
        assert info is not None
        assert info["format"] == "wav"
        assert info["sample_rate"] == 22050

    def test_touch_refreshes_last_activity(self) -> None:
        sm = srv.SessionManager()
        sm.add("s-1", FakeWebSocket())  # type: ignore[arg-type]
        sm._sessions["s-1"]["last_activity"] = 0.0
        sm.touch("s-1")
        assert sm._sessions["s-1"]["last_activity"] > 0.0

    def test_touch_unknown_session_is_a_noop(self) -> None:
        srv.SessionManager().touch("ghost")  # must not raise

    def test_remove_drops_the_session(self) -> None:
        sm = srv.SessionManager()
        sm.add("s-1", FakeWebSocket())  # type: ignore[arg-type]
        sm.remove("s-1")
        assert sm.get("s-1") is None
        assert sm.active_count() == 0

    def test_remove_unknown_session_is_a_noop(self) -> None:
        srv.SessionManager().remove("ghost")  # must not raise

    def test_get_unknown_returns_none(self) -> None:
        assert srv.SessionManager().get("nope") is None

    def test_active_count_tracks_sessions(self) -> None:
        sm = srv.SessionManager()
        assert sm.active_count() == 0
        sm.add("a", FakeWebSocket())  # type: ignore[arg-type]
        sm.add("b", FakeWebSocket())  # type: ignore[arg-type]
        assert sm.active_count() == 2

    def test_custom_idle_timeout_is_stored(self) -> None:
        assert srv.SessionManager(idle_timeout_s=42)._idle_timeout_s == 42

    @pytest.mark.asyncio
    async def test_start_cleanup_loop_is_idempotent(self) -> None:
        sm = srv.SessionManager()
        sm.start_cleanup_loop()
        first = sm._cleanup_task
        sm.start_cleanup_loop()
        assert sm._cleanup_task is first
        assert first is not None
        first.cancel()

    @pytest.mark.asyncio
    async def test_start_cleanup_loop_restarts_after_completion(self) -> None:
        sm = srv.SessionManager()

        async def done() -> None:
            return None

        sm._cleanup_task = asyncio.ensure_future(done())
        await asyncio.sleep(0)
        assert sm._cleanup_task is not None and sm._cleanup_task.done()
        sm.start_cleanup_loop()
        assert sm._cleanup_task is not None and not sm._cleanup_task.done()
        sm._cleanup_task.cancel()


class TestSessionManagerCleanupLoop:
    @pytest.mark.asyncio
    async def test_expired_session_is_closed_and_removed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sm = srv.SessionManager(idle_timeout_s=1)
        ws = FakeWebSocket()
        sm.add("stale", ws)  # type: ignore[arg-type]
        sm._sessions["stale"]["last_activity"] = time.monotonic() - 10_000

        real_sleep = asyncio.sleep
        passes = {"n": 0}

        async def fake_sleep(delay: float, *args: Any, **kw: Any) -> Any:
            passes["n"] += 1
            if passes["n"] > 1:
                raise asyncio.CancelledError  # pragma: no cover - safety net
            return await real_sleep(0)

        monkeypatch.setattr(srv.asyncio, "sleep", fake_sleep)
        task = asyncio.ensure_future(sm._cleanup_loop())
        with pytest.raises(asyncio.CancelledError):
            await task

        assert "stale" not in sm._sessions
        assert ws.closed == [(1011, "idle_timeout")]

    @pytest.mark.asyncio
    async def test_fresh_session_survives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sm = srv.SessionManager(idle_timeout_s=300)
        ws = FakeWebSocket()
        sm.add("fresh", ws)  # type: ignore[arg-type]

        real_sleep = asyncio.sleep
        passes = {"n": 0}

        async def fake_sleep(delay: float, *args: Any, **kw: Any) -> Any:
            passes["n"] += 1
            if passes["n"] > 1:
                raise asyncio.CancelledError  # pragma: no cover - safety net
            return await real_sleep(0)

        monkeypatch.setattr(srv.asyncio, "sleep", fake_sleep)
        task = asyncio.ensure_future(sm._cleanup_loop())
        with pytest.raises(asyncio.CancelledError):
            await task

        assert "fresh" in sm._sessions
        assert ws.closed == []

    @pytest.mark.asyncio
    async def test_close_failure_does_not_stop_the_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sm = srv.SessionManager(idle_timeout_s=1)
        ws = FakeWebSocket()
        ws.close_should_fail = True
        sm.add("stale", ws)  # type: ignore[arg-type]
        sm._sessions["stale"]["last_activity"] = time.monotonic() - 10_000

        real_sleep = asyncio.sleep
        passes = {"n": 0}

        async def fake_sleep(delay: float, *args: Any, **kw: Any) -> Any:
            passes["n"] += 1
            if passes["n"] > 1:
                raise asyncio.CancelledError  # pragma: no cover - safety net
            return await real_sleep(0)

        monkeypatch.setattr(srv.asyncio, "sleep", fake_sleep)
        task = asyncio.ensure_future(sm._cleanup_loop())
        with pytest.raises(asyncio.CancelledError):
            await task

        # removed even though close() raised
        assert "stale" not in sm._sessions


# ── module wiring ────────────────────────────────────────────────────

def test_module_constants() -> None:
    assert srv.SESSION_IDLE_TIMEOUT_S == 300
    assert srv.CHUNK_DURATION_MS == 100
    assert srv.WHISPER_MODEL
    assert srv.SAMPLE_RATE > 0


def test_app_metadata() -> None:
    assert srv.app.title == "jarvis-os voice pipeline"
    assert srv.app.version == "0.2.0"


def test_module_level_session_manager_exists() -> None:
    assert isinstance(srv.session_manager, srv.SessionManager)


# ── REST endpoints ───────────────────────────────────────────────────

class TestRestEndpoints:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(srv.app)

    def test_health(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "voice-pipeline"
        assert body["websocket_enabled"] is True
        assert body["active_sessions"] == 0
        # timestamp format: YYYY-MM-DDTHH:MM:SSZ
        assert body["timestamp"].endswith("Z")

    def test_health_reports_active_sessions(self, client: TestClient) -> None:
        srv.session_manager.add("s-1", FakeWebSocket())  # type: ignore[arg-type]
        try:
            assert client.get("/health").json()["active_sessions"] == 1
        finally:
            srv.session_manager.remove("s-1")

    def test_models(self, client: TestClient) -> None:
        r = client.get("/v1/models")
        assert r.status_code == 200
        models = r.json()["models"]
        ids = {m["id"] for m in models}
        assert {"whisper-base", "kokoro-es", "piper-es_ES-pacifico"} == ids
        assert {m["type"] for m in models} == {"stt", "tts"}

    def test_stt_fallback(self, client: TestClient) -> None:
        r = client.post("/stt", json={"audio": "ignored"})
        assert r.status_code == 200
        assert r.json() == {"text": "", "model": "whisper-base", "language": "es"}

    def test_tts_fallback_returns_audio(self, client: TestClient) -> None:
        r = client.post("/tts", json={"text": "hola"})
        assert r.status_code == 200
        assert r.content == b""
        assert r.headers["content-type"].startswith("audio/wav")

    def test_openapi_is_served(self, client: TestClient) -> None:
        assert client.get("/openapi.json").status_code == 200


# ── websocket handshake ──────────────────────────────────────────────

def _recv_type(ws: Any, wanted: str, limit: int = 6) -> dict[str, Any]:
    """Read frames until one of type ``wanted`` arrives.

    The server also emits keepalive ``ping`` frames, so a single
    ``receive_json`` is not enough to assert on a specific message.
    """
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == wanted:
            return msg
    raise AssertionError(f"never received a {wanted!r} frame")


def _recv_with(ws: Any, *keys: str, limit: int = 6) -> dict[str, Any]:
    """Read frames until one carries every key in ``keys``.

    Needed for ``session_close`` and ``error`` frames: unlike ``session_ack``,
    those models carry no ``type`` discriminator, so they can only be told
    apart by the fields they contain.
    """
    for _ in range(limit):
        msg = ws.receive_json()
        if all(k in msg for k in keys):
            return msg
    raise AssertionError(f"never received a frame with keys {keys!r}")


class TestAudioStreamWebSocket:
    def test_session_open_is_acknowledged(self) -> None:
        with TestClient(srv.app).websocket_connect("/v1/audio/stream") as ws:
            ws.send_json(
                {
                    "type": "session_open",
                    "session_id": "s-1",
                    "format": "pcm",
                    "sample_rate": 16000,
                }
            )
            ack = _recv_type(ws, "session_ack")
            assert ack["session_id"] == "s-1"
            assert ack["websocket_enabled"] is True
            assert ack["stt_model"] == srv.WHISPER_MODEL
            assert ack["tts_voice"] == srv.PIPER_VOICE
            assert "s-1" in srv.session_manager._sessions

    def test_session_id_is_generated_when_omitted(self) -> None:
        with TestClient(srv.app).websocket_connect("/v1/audio/stream") as ws:
            ws.send_json({"type": "session_open"})
            ack = _recv_type(ws, "session_ack")
            assert ack["session_id"]

    def test_ping_is_answered_with_pong(self) -> None:
        with TestClient(srv.app).websocket_connect("/v1/audio/stream") as ws:
            ws.send_json({"type": "ping"})
            pong = _recv_type(ws, "pong")
            assert "timestamp_ms" in pong

    def test_unknown_control_frame_is_ignored(self) -> None:
        """An unknown kind produces no error frame; the next ping still works."""
        with TestClient(srv.app).websocket_connect("/v1/audio/stream") as ws:
            ws.send_json({"type": "totally-unknown"})
            ws.send_json({"type": "ping"})
            assert _recv_type(ws, "pong")["type"] == "pong"

    def test_session_close_is_acknowledged(self) -> None:
        with TestClient(srv.app).websocket_connect("/v1/audio/stream") as ws:
            ws.send_json({"type": "session_open", "session_id": "s-2"})
            _recv_type(ws, "session_ack")
            ws.send_json({"type": "session_close", "session_id": "s-2", "reason": "done"})
            # NOTE: SessionClose has no `type` discriminator, so it can only be
            # recognised by the fields it carries.
            closed = _recv_with(ws, "session_id", "reason")
            assert closed["session_id"] == "s-2"
            assert closed["reason"] == "done"

    def test_repeated_session_open_is_acknowledged_again(self) -> None:
        """Current behaviour: the server does not reject a reused session id."""
        with TestClient(srv.app).websocket_connect("/v1/audio/stream") as ws:
            ws.send_json({"type": "session_open", "session_id": "dup"})
            _recv_type(ws, "session_ack")
            ws.send_json({"type": "session_open", "session_id": "dup"})
            assert _recv_type(ws, "session_ack")["session_id"] == "dup"
        srv.session_manager.remove("dup")

    def test_malformed_json_is_reported_as_an_error(self) -> None:
        with TestClient(srv.app).websocket_connect("/v1/audio/stream") as ws:
            ws.send_json({"type": "session_open", "session_id": "s-3"})
            _recv_type(ws, "session_ack")
            ws.send_text("{not valid json")
            # NOTE: ErrorMsg has no `type` discriminator either.
            err = _recv_with(ws, "code", "message")
            assert err["code"] == "invalid_frame"
            assert "message" in err
        srv.session_manager.remove("s-3")


# ── lifecycle hooks ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_startup_starts_the_cleanup_loop() -> None:
    srv.session_manager._cleanup_task = None
    await srv.on_startup()
    assert srv.session_manager._cleanup_task is not None
    srv.session_manager._cleanup_task.cancel()


@pytest.mark.asyncio
async def test_shutdown_stops_the_pipelines() -> None:
    await srv.on_shutdown()  # must not raise even with no models loaded

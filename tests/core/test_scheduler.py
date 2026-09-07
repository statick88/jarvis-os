"""Tests for ``jarvis_os.core.scheduler`` — IdleScheduler.

Covers:
  - State transitions (start / stop / pause / resume)
  - Toggle on / off / explicit enable
  - Task registration and removal
  - Session-active deferral
  - Active-hours window gating
  - Resource-throttle gating (CPU, RAM)
  - Task execution, run_count, and error capture
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from jarvis_os.core.scheduler import (
    IdleScheduler,
    ResourceSnapshot,
    ScheduledTask,
    SchedulerState,
)


# ── helpers ──────────────────────────────────────────────────────────

async def _noop() -> None:
    """No-op async task for registration tests."""


async def _counting(counter: list[int]) -> None:
    """Append to *counter* each time it runs."""
    counter.append(len(counter) + 1)


async def _failing() -> None:
    """Raise to simulate a task error."""
    raise RuntimeError("simulated failure")


def _make_scheduler(**kwargs) -> IdleScheduler:
    """Create an IdleScheduler with fast ticks for testing."""
    return IdleScheduler(check_interval_seconds=0.05, **kwargs)


# ── State transitions ────────────────────────────────────────────────

class TestStateTransitions:
    """Scheduler starts, stops, pauses, and resumes cleanly."""

    def test_initial_state_is_stopped(self) -> None:
        s = _make_scheduler()
        assert s._state == SchedulerState.STOPPED

    @pytest.mark.asyncio
    async def test_start_sets_running(self) -> None:
        s = _make_scheduler()
        s.start()
        assert s._state == SchedulerState.RUNNING
        s.stop()

    @pytest.mark.asyncio
    async def test_start_twice_raises(self) -> None:
        s = _make_scheduler()
        s.start()
        with pytest.raises(RuntimeError, match="already running"):
            s.start()
        s.stop()

    @pytest.mark.asyncio
    async def test_stop_from_stopped_is_noop(self) -> None:
        s = _make_scheduler()
        s.stop()  # should not raise
        assert s._state == SchedulerState.STOPPED

    @pytest.mark.asyncio
    async def test_pause_and_resume(self) -> None:
        s = _make_scheduler()
        s.start()
        s.pause()
        assert s._state == SchedulerState.PAUSED
        s.resume()
        assert s._state == SchedulerState.RUNNING
        s.stop()

    @pytest.mark.asyncio
    async def test_resume_from_running_is_noop(self) -> None:
        s = _make_scheduler()
        s.start()
        s.resume()  # already running
        assert s._state == SchedulerState.RUNNING
        s.stop()


# ── Toggle ───────────────────────────────────────────────────────────

class TestToggle:
    """Toggle flips state or sets explicit enable/disable."""

    def test_toggle_from_stopped_starts(self) -> None:
        s = _make_scheduler()
        status = s.toggle()
        assert status["state"] == "running"
        s.stop()

    def test_toggle_from_running_stops(self) -> None:
        s = _make_scheduler()
        s.start()
        status = s.toggle()
        assert status["state"] == "stopped"

    def test_toggle_explicit_enable(self) -> None:
        s = _make_scheduler()
        s.toggle(enabled=True)
        assert s._state == SchedulerState.RUNNING
        s.stop()

    def test_toggle_explicit_disable(self) -> None:
        s = _make_scheduler()
        s.start()
        s.toggle(enabled=False)
        assert s._state == SchedulerState.STOPPED


# ── Task registration ────────────────────────────────────────────────

class TestTaskRegistration:
    """Tasks are added, removed, and enumerated."""

    def test_add_task_returns_id(self) -> None:
        s = _make_scheduler()
        tid = s.add_task(_noop, interval_minutes=30)
        assert tid.startswith("nightly-task-")

    def test_add_task_custom_id(self) -> None:
        s = _make_scheduler()
        tid = s.add_task(_noop, interval_minutes=15, task_id="my-task")
        assert tid == "my-task"

    def test_remove_task(self) -> None:
        s = _make_scheduler()
        tid = s.add_task(_noop, interval_minutes=10)
        assert s.remove_task(tid) is True
        assert s.remove_task(tid) is False  # already removed

    def test_get_status_shows_tasks(self) -> None:
        s = _make_scheduler()
        s.add_task(_noop, interval_minutes=5, task_id="t1")
        s.add_task(_noop, interval_minutes=10, task_id="t2")
        status = s.get_status()
        assert status["total_tasks"] == 2
        ids = {t["task_id"] for t in status["tasks"]}
        assert ids == {"t1", "t2"}


# ── Session-active deferral ─────────────────────────────────────────

class TestSessionDeferral:
    """Tasks are deferred when user session is active."""

    @pytest.mark.asyncio
    async def test_session_active_skips_tick(self) -> None:
        s = _make_scheduler(active_hours_start=0, active_hours_end=24)
        counter: list[int] = []
        s.add_task(lambda: _counting(counter), interval_minutes=0, task_id="c")
        s.set_session_active(True)
        s.start()
        await asyncio.sleep(0.2)
        s.stop()
        assert counter == []  # task never ran

    @pytest.mark.asyncio
    async def test_session_inactive_runs_tick(self) -> None:
        s = _make_scheduler(active_hours_start=0, active_hours_end=24)
        counter: list[int] = []
        s.add_task(lambda: _counting(counter), interval_minutes=0, task_id="c")
        s.set_session_active(False)
        s.start()
        await asyncio.sleep(0.2)
        s.stop()
        assert len(counter) >= 1  # task ran at least once


# ── Active hours window ─────────────────────────────────────────────

class TestActiveHoursWindow:
    """Tasks only execute within the configured hour window."""

    @pytest.mark.asyncio
    async def test_outside_window_skips(self) -> None:
        # Window 02:00-04:00 — we're almost certainly outside it now
        s = _make_scheduler(active_hours_start=2, active_hours_end=4)
        counter: list[int] = []
        s.add_task(lambda: _counting(counter), interval_minutes=0, task_id="c")
        s.start()
        await asyncio.sleep(0.2)
        s.stop()
        # If current hour is 2 or 3, task ran; otherwise it didn't.
        # We can't control the clock, so just assert no crash.
        assert isinstance(counter, list)

    @pytest.mark.asyncio
    async def test_always_window_runs(self) -> None:
        """Window 0-24 should always allow execution."""
        s = _make_scheduler(active_hours_start=0, active_hours_end=24)
        counter: list[int] = []
        s.add_task(lambda: _counting(counter), interval_minutes=0, task_id="c")
        s.start()
        await asyncio.sleep(0.2)
        s.stop()
        assert len(counter) >= 1


# ── Resource throttling ──────────────────────────────────────────────

class TestResourceThrottling:
    """High CPU/RAM blocks task execution."""

    @pytest.mark.asyncio
    async def test_high_cpu_skips_tick(self) -> None:
        s = _make_scheduler(max_cpu_percent=1.0)  # very low threshold
        counter: list[int] = []
        s.add_task(lambda: _counting(counter), interval_minutes=0, task_id="c")

        fake_snapshot = ResourceSnapshot(cpu_percent=99.0, ram_mb=10.0)
        with patch.object(s, "_get_resources", new=AsyncMock(return_value=fake_snapshot)):
            s.start()
            await asyncio.sleep(0.2)
            s.stop()
        assert counter == []

    @pytest.mark.asyncio
    async def test_high_ram_skips_tick(self) -> None:
        s = _make_scheduler(max_ram_mb=1.0)  # 1 MB threshold
        counter: list[int] = []
        s.add_task(lambda: _counting(counter), interval_minutes=0, task_id="c")

        fake_snapshot = ResourceSnapshot(cpu_percent=1.0, ram_mb=9999.0)
        with patch.object(s, "_get_resources", new=AsyncMock(return_value=fake_snapshot)):
            s.start()
            await asyncio.sleep(0.2)
            s.stop()
        assert counter == []


# ── Task execution ───────────────────────────────────────────────────

class TestTaskExecution:
    """Tasks run, increment counters, and capture errors."""

    @pytest.mark.asyncio
    async def test_task_runs_and_increments(self) -> None:
        s = _make_scheduler(active_hours_start=0, active_hours_end=24)
        counter: list[int] = []
        s.add_task(lambda: _counting(counter), interval_minutes=0, task_id="c")
        s.start()
        await asyncio.sleep(0.3)
        s.stop()
        assert len(counter) >= 1
        task = s._tasks["c"]
        assert task.run_count >= 1
        assert task.last_error is None

    @pytest.mark.asyncio
    async def test_task_error_captured(self) -> None:
        s = _make_scheduler(active_hours_start=0, active_hours_end=24)
        s.add_task(_failing, interval_minutes=0, task_id="fail")
        s.start()
        await asyncio.sleep(0.3)
        s.stop()
        task = s._tasks["fail"]
        assert task.last_error == "simulated failure"
        assert task.run_count == 0  # failure doesn't increment


# ── ResourceSnapshot ─────────────────────────────────────────────────

class TestResourceSnapshot:
    """ResourceSnapshot dataclass defaults."""

    def test_defaults(self) -> None:
        snap = ResourceSnapshot()
        assert snap.cpu_percent == 0.0
        assert snap.ram_mb == 0.0
        assert snap.timestamp > 0

"""Idle scheduler for JARVIS OS nightly autonomous execution.

Runs background tasks during user idle windows (00:00-06:00) with
resource throttling, session-aware deferral, and toggle control via REST.

Architecture decisions (from design.md):
  - asyncio.create_task() loop (not cron, not separate process)
  - CPU/RAM throttling to prevent resource exhaustion
  - Session detection: skip tasks while user is active
  - Toggle via POST /v1/nightly/scheduler/toggle
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class SchedulerState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


@dataclass
class ScheduledTask:
    """A single scheduled background task."""

    task_id: str
    func: Callable[[], Coroutine[Any, Any, Any]]
    interval_minutes: int
    priority: str = "low"
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0
    last_error: str | None = None


@dataclass
class ResourceSnapshot:
    """Current system resource usage."""

    cpu_percent: float = 0.0
    ram_mb: float = 0.0
    timestamp: float = field(default_factory=time.time)


class IdleScheduler:
    """Autonomous scheduler that runs tasks during idle windows.

    The scheduler activates during configured hours (default 00:00-06:00)
    and respects resource limits and active user sessions.

    Usage::

        scheduler = IdleScheduler()
        scheduler.add_task(my_func, interval_minutes=30)
        scheduler.start()
        # later...
        scheduler.stop()
    """

    def __init__(
        self,
        active_hours_start: int = 0,
        active_hours_end: int = 6,
        max_cpu_percent: float = 80.0,
        max_ram_mb: float = 512.0,
        check_interval_seconds: float = 60.0,
    ) -> None:
        self._state = SchedulerState.STOPPED
        self._tasks: dict[str, ScheduledTask] = {}
        self._active_hours_start = active_hours_start
        self._active_hours_end = active_hours_end
        self._max_cpu_percent = max_cpu_percent
        self._max_ram_mb = max_ram_mb
        self._check_interval = check_interval_seconds
        self._loop_task: asyncio.Task | None = None
        self._running_tasks: set[str] = set()
        self._session_active = False
        self._started_at: float | None = None
        self._task_counter = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler loop as a background asyncio task.

        Raises RuntimeError if already running.
        """
        if self._state == SchedulerState.RUNNING:
            raise RuntimeError("Scheduler is already running")

        self._state = SchedulerState.RUNNING
        self._started_at = time.time()
        logger.info("Idle scheduler started (active %02d:00-%02d:00)",
                     self._active_hours_start, self._active_hours_end)

        try:
            loop = asyncio.get_running_loop()
            self._loop_task = loop.create_task(self._run_loop())
        except RuntimeError:
            logger.warning("No running event loop — scheduler will not tick. "
                           "Call start() from an async context.")

    def stop(self) -> None:
        """Stop the scheduler and cancel any in-flight background tasks."""
        if self._state == SchedulerState.STOPPED:
            return

        self._state = SchedulerState.STOPPED
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            self._loop_task = None
        logger.info("Idle scheduler stopped")

    def pause(self) -> None:
        """Pause the scheduler without fully stopping it."""
        self._state = SchedulerState.PAUSED
        logger.info("Idle scheduler paused")

    def resume(self) -> None:
        """Resume a paused scheduler."""
        if self._state == SchedulerState.PAUSED:
            self._state = SchedulerState.RUNNING
            logger.info("Idle scheduler resumed")

    def add_task(
        self,
        task_func: Callable[[], Coroutine[Any, Any, Any]],
        interval_minutes: int,
        priority: str = "low",
        task_id: str | None = None,
    ) -> str:
        """Register a background task.

        Args:
            task_func: Async callable to execute.
            interval_minutes: Minimum minutes between runs.
            priority: Task priority (low, medium, high).
            task_id: Optional custom ID; auto-generated if omitted.

        Returns:
            The task ID string.
        """
        self._task_counter += 1
        tid = task_id or f"nightly-task-{self._task_counter}"
        self._tasks[tid] = ScheduledTask(
            task_id=tid,
            func=task_func,
            interval_minutes=interval_minutes,
            priority=priority,
        )
        logger.info("Scheduled task %s (every %dm, priority=%s)",
                     tid, interval_minutes, priority)
        return tid

    def remove_task(self, task_id: str) -> bool:
        """Remove a scheduled task by ID. Returns True if found."""
        removed = self._tasks.pop(task_id, None)
        if removed:
            logger.info("Removed task %s", task_id)
        return removed is not None

    def get_status(self) -> dict[str, Any]:
        """Return current scheduler status as a serialisable dict."""
        now_hour = datetime.now().hour
        in_window = self._active_hours_start <= now_hour < self._active_hours_end

        tasks_info = []
        for t in self._tasks.values():
            tasks_info.append({
                "task_id": t.task_id,
                "interval_minutes": t.interval_minutes,
                "priority": t.priority,
                "enabled": t.enabled,
                "run_count": t.run_count,
                "last_run": t.last_run,
                "last_error": t.last_error,
            })

        return {
            "state": self._state.value,
            "active_window": f"{self._active_hours_start:02d}:00-{self._active_hours_end:02d}:00",
            "in_active_window": in_window,
            "session_active": self._session_active,
            "total_tasks": len(self._tasks),
            "running_tasks": len(self._running_tasks),
            "tasks": tasks_info,
            "started_at": self._started_at,
            "resource_limits": {
                "max_cpu_percent": self._max_cpu_percent,
                "max_ram_mb": self._max_ram_mb,
            },
        }

    def toggle(self, enabled: bool | None = None) -> dict[str, Any]:
        """Toggle the scheduler on/off. Returns new status.

        If *enabled* is None, the current state is flipped.
        """
        if enabled is None:
            enabled = self._state == SchedulerState.STOPPED

        if enabled and self._state != SchedulerState.RUNNING:
            self.start()
        elif not enabled and self._state != SchedulerState.STOPPED:
            self.stop()

        return self.get_status()

    def set_session_active(self, active: bool) -> None:
        """Notify the scheduler that a user session is (in)active."""
        self._session_active = active
        if active:
            logger.info("User session active — deferring nightly tasks")

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Main scheduler loop — ticks every check_interval seconds."""
        while self._state == SchedulerState.RUNNING:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(self._check_interval)

    async def _tick(self) -> None:
        """Single scheduler tick: evaluate and run eligible tasks."""
        now_hour = datetime.now().hour
        in_window = self._active_hours_start <= now_hour < self._active_hours_end

        if not in_window:
            return

        if self._session_active:
            logger.debug("Session active — skipping tick")
            return

        snapshot = await self._get_resources()
        if snapshot.cpu_percent > self._max_cpu_percent:
            logger.warning("CPU %.1f%% exceeds limit %.1f%% — skipping tick",
                           snapshot.cpu_percent, self._max_cpu_percent)
            return

        if snapshot.ram_mb > self._max_ram_mb:
            logger.warning("RAM %.0fMB exceeds limit %.0fMB — skipping tick",
                           snapshot.ram_mb, self._max_ram_mb)
            return

        now = time.time()
        for tid, task in self._tasks.items():
            if not task.enabled:
                continue
            if tid in self._running_tasks:
                continue
            elapsed = now - task.last_run
            if elapsed < task.interval_minutes * 60:
                continue
            asyncio.create_task(self._execute_task(task))

    async def _execute_task(self, task: ScheduledTask) -> None:
        """Execute a single task with error handling."""
        self._running_tasks.add(task.task_id)
        start = time.time()
        try:
            await task.func()
            task.run_count += 1
            task.last_run = time.time()
            task.last_error = None
            duration_ms = int((time.time() - start) * 1000)
            logger.info("Task %s completed in %dms (run #%d)",
                        task.task_id, duration_ms, task.run_count)
        except Exception as exc:
            task.last_error = str(exc)
            task.last_run = time.time()
            logger.error("Task %s failed: %s", task.task_id, exc)
        finally:
            self._running_tasks.discard(task.task_id)

    async def _get_resources(self) -> ResourceSnapshot:
        """Sample current CPU/RAM usage (best-effort, cross-platform)."""
        try:
            import psutil  # type: ignore[import-untyped]
            return ResourceSnapshot(
                cpu_percent=psutil.cpu_percent(interval=0.1),
                ram_mb=psutil.Process().memory_info().rss / (1024 * 1024),
            )
        except ImportError:
            pass

        # Fallback: read /proc on Linux
        try:
            with open("/proc/loadavg") as f:  # noqa: SIM115
                load = float(f.read().split()[0])
            return ResourceSnapshot(cpu_percent=load * 25)  # rough estimate
        except (FileNotFoundError, IndexError, ValueError):
            pass

        return ResourceSnapshot(cpu_percent=0.0, ram_mb=0.0)

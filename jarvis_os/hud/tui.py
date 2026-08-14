"""
HUD — Terminal TUI
==================
Async, dependency-light terminal dashboard for JARVIS-OS.

``JarvisTUI`` renders a fixed status panel (voice pipeline state, system
metrics, recent message feed) using ANSI escape codes, so it needs no curses
and stays composable with the rest of the async stack. Rendering is a pure
function of the latest published ``HudMessage`` values; the refresh loop
re-renders at ``tui_refresh_interval_seconds``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import psutil

from jarvis_os.hud.models import HudConfig, HudMessage, HudStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Palette:
    """ANSI 256-color palette for one theme."""

    fg: str
    dim: str
    accent: str
    ok: str
    warn: str
    error: str
    header: str

    def paint(self, code: str, text: str) -> str:
        return f"{code}{text}\x1b[0m"


_DARK_PALETTE = _Palette(
    fg="\x1b[38;5;252m",
    dim="\x1b[38;5;242m",
    accent="\x1b[38;5;75m",
    ok="\x1b[38;5;78m",
    warn="\x1b[38;5;215m",
    error="\x1b[38;5;203m",
    header="\x1b[1;38;5;75m",
)

_LIGHT_PALETTE = _Palette(
    fg="\x1b[38;5;237m",
    dim="\x1b[38;5;244m",
    accent="\x1b[38;5;26m",
    ok="\x1b[38;5;28m",
    warn="\x1b[38;5;130m",
    error="\x1b[38;5;160m",
    header="\x1b[1;38;5;26m",
)


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------


class JarvisTUI:
    """Async terminal dashboard for JARVIS-OS runtime state."""

    def __init__(self, config: Optional[HudConfig] = None) -> None:
        self._config = config or HudConfig()
        self._palette = (
            _DARK_PALETTE if self._config.tui_theme == "dark" else _LIGHT_PALETTE
        )
        self._latest: HudMessage = HudMessage(
            status=HudStatus.IDLE, summary="Waiting for activity...", payload={}
        )
        self._feed: Deque[HudMessage] = deque(maxlen=20)
        self._running = False
        self._render_task: Optional[asyncio.Task] = None
        self._last_render = ""

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Begin the periodic render loop in the running event loop."""
        if self._running:
            return
        self._running = True
        self._render_task = asyncio.create_task(
            self._render_loop(), name="hud-tui-render"
        )
        logger.debug("HUD TUI started (theme=%s, interval=%ss)", self._config.tui_theme, self._config.tui_refresh_interval_seconds)

    async def stop(self) -> None:
        """Stop the render loop and restore the terminal line."""
        self._running = False
        if self._render_task is not None:
            self._render_task.cancel()
            try:
                await self._render_task
            except asyncio.CancelledError:
                pass
            self._render_task = None
        print("\x1b[0m", end="", flush=True)

    # -- publish / query ----------------------------------------------------

    def publish(self, message: HudMessage) -> None:
        """Record the latest status and append to the on-screen feed."""
        self._latest = message
        if len(self._feed) >= 20:
            self._feed.popleft()
        self._feed.append(message)

    def update_status(
        self,
        status: HudStatus,
        summary: str = "",
        *,
        severity: str = "info",
        payload: Optional[dict] = None,
    ) -> HudMessage:
        """Convenience builder: publish a status update, return the message."""
        message = HudMessage(
            status=status,
            summary=summary or status.value,
            severity=severity,  # type: ignore[arg-type]
            payload=payload or {},
        )
        self.publish(message)
        return message

    def clear(self) -> None:
        """Empty the message feed (status line is preserved)."""
        self._feed.clear()

    def status(self) -> HudStatus:
        return self._latest.status

    # -- rendering ----------------------------------------------------------

    async def _render_loop(self) -> None:
        try:
            while self._running:
                await self.render()
                await asyncio.sleep(self._config.tui_refresh_interval_seconds)
        except asyncio.CancelledError:
            raise

    async def render(self) -> None:
        """Redraw the dashboard in place (single-line refresh)."""
        lines = self._build_lines()
        width = shutil.get_terminal_size((100, 30)).columns

        # Clear the previous block and rewrite it. Cursor home approach: we
        # render the full panel each tick, overwriting prior lines.
        frame = "\r" + "\n".join(self._fit(line, width) for line in lines) + "\x1b[0m"
        if frame != self._last_render:
            print("\x1b[2K", end="")
            print("\x1b[0m" + frame, end="", flush=True)
            self._last_render = frame

    def _build_lines(self) -> list[str]:
        p = self._palette
        m = self._latest
        metrics = self._system_metrics()

        status_color = self._status_color(m.status)

        header = p.paint(p.header, " JARVIS-OS HUD ".center(78, "="))
        status_line = (
            f"{p.paint(p.dim, 'state:')} {p.paint(status_color, m.status.value):<10}"
            f" {p.paint(p.dim, '| summary:')} {p.paint(p.fg, m.summary)}"
        )
        metric_line = (
            f"{p.paint(p.dim, 'cpu:')} {metrics['cpu']:>4.1f}%"
            f"  {p.paint(p.dim, 'mem:')} {metrics['mem']:>4.1f}%"
            f"  {p.paint(p.dim, 'up:')} {metrics['uptime']}"
        )
        feed_header = p.paint(p.dim, " feed ")

        lines = [header, "", status_line, metric_line, "", feed_header]
        if self._feed:
            for item in self._feed:
                lines.append(self._feed_line(item))
        else:
            lines.append(p.paint(p.dim, "  (empty)"))
        lines.append("")
        return lines

    def _feed_line(self, item: HudMessage) -> str:
        p = self._palette
        sev_color = {
            "info": p.fg,
            "warning": p.warn,
            "error": p.error,
        }.get(item.severity, p.fg)
        ts = item.timestamp.strftime("%H:%M:%S")
        return (
            f"  {p.paint(p.dim, ts)} "
            f"{p.paint(sev_color, item.status.value):<11} "
            f"{p.paint(p.fg, item.summary)}"
        )

    def _status_color(self, status: HudStatus) -> str:
        p = self._palette
        mapping = {
            HudStatus.IDLE: p.dim,
            HudStatus.LISTENING: p.accent,
            HudStatus.PROCESSING: p.warn,
            HudStatus.SPEAKING: p.ok,
            HudStatus.ERROR: p.error,
            HudStatus.OFFLINE: p.error,
        }
        return mapping.get(status, p.fg)

    @staticmethod
    def _fit(line: str, width: int) -> str:
        """Truncate/pad a rendered (ANSI-aware) line to the terminal width.

        ANSI codes are stripped for the length computation so the visible
        width matches the terminal; the codes themselves stay in the payload.
        """
        if not line:
            return ""
        stripped = line
        for code in ("\x1b[0m", "\x1b[2K", "\x1b[2J"):
            stripped = stripped.replace(code, "")
        visible = stripped
        # crude but robust: remove any remaining CSI sequences
        parts = []
        i = 0
        while i < len(visible):
            if visible[i] == "\x1b":
                j = visible.find("m", i)
                if j == -1:
                    break
                i = j + 1
            else:
                parts.append(visible[i])
                i += 1
        length = len("".join(parts))
        if length <= width:
            return line + " " * (width - length)
        return line

    @staticmethod
    def _system_metrics() -> dict:
        try:
            cpu = psutil.cpu_percent(interval=None) or 0.0
            mem = psutil.virtual_memory().percent
            uptime_s = int(psutil.boot_time())
            import time

            uptime = int(time.time() - uptime_s)
            h, rem = divmod(uptime, 3600)
            m, s = divmod(rem, 60)
            return {"cpu": float(cpu), "mem": float(mem), "uptime": f"{h:02d}:{m:02d}:{s:02d}"}
        except Exception:  # pragma: no cover - psutil can be unavailable/racy
            return {"cpu": 0.0, "mem": 0.0, "uptime": "00:00:00"}

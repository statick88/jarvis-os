"""Command sandbox for safe execution of whitelisted system commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CommandSandbox:
    """Validates and executes whitelisted system commands with timeouts."""

    def __init__(self, whitelist: list[str], default_timeout: int = 30) -> None:
        self.whitelist = set(whitelist)
        self.default_timeout = default_timeout

    def validate(self, command: str) -> bool:
        """Check if a command is in the whitelist."""
        binary = command.split(maxsplit=1)[0].split("/")[-1]
        return binary in self.whitelist

    async def execute(
        self,
        command: str,
        args: list[str] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute a whitelisted command with the given arguments.

        Args:
            command: The command to execute (must be whitelisted).
            args: Command arguments.
            timeout: Maximum execution time in seconds.

        Returns:
            Dict with ``returncode``, ``stdout``, and ``stderr``.

        Raises:
            PermissionError: If the command is not whitelisted.
            TimeoutError: If the command exceeds the timeout.
        """
        if not self.validate(command):
            raise PermissionError(f"Command '{command}' is not whitelisted")

        timeout = timeout or self.default_timeout
        args = args or []
        cmd_parts = [command, *args]

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            }
        except asyncio.TimeoutError:
            if proc is not None:
                proc.kill()
            raise TimeoutError(
                f"Command '{command}' timed out after {timeout}s"
            ) from None
        except Exception as exc:
            raise RuntimeError(f"Command '{command}' failed: {exc}") from exc

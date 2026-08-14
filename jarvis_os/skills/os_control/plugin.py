"""macOS system control skill plugin."""

from __future__ import annotations

import asyncio
import logging
import platform
from datetime import datetime, timezone
from typing import Any

from jarvis_os.skills.base import BaseSkill, SkillPermission
from jarvis_os.skills.sandbox import CommandSandbox

logger = logging.getLogger(__name__)

try:
    import psutil  # type: ignore[import-untyped]
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


class OSControlSkill(BaseSkill):
    """Skill for macOS system monitoring and controlled command execution."""

    def __init__(self) -> None:
        super().__init__(name="skill-os-control", version="1.0.0", permissions=[
            SkillPermission.READ_METRICS,
            SkillPermission.EXECUTE_COMMANDS,
        ])
        self.sandbox = CommandSandbox(
            whitelist=["ls", "df", "du", "ps", "top", "uptime", "whoami", "date", "echo", "pwd", "uname"],
            default_timeout=30,
        )

    async def load(self) -> None:
        await super().load()
        logger.debug("OSControlSkill loaded on %s; psutil=%s", platform.system(), _PSUTIL_AVAILABLE)

    async def execute(self, operation: str, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if not self.is_loaded:
            return {"status": "error", "message": "Skill not loaded"}

        try:
            if operation == "get_system_metrics":
                return await self._get_system_metrics(parameters)
            elif operation == "execute_system_command":
                return await self._execute_system_command(parameters, context)
            else:
                return {"status": "error", "message": f"Unknown operation: {operation}"}
        except Exception as exc:
            logger.exception("OSControlSkill operation failed: %s", operation)
            return {"status": "error", "message": str(exc)}

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "skill-os-control",
            "version": self.version,
            "operations": {
                "get_system_metrics": {
                    "description": "Get real-time CPU, RAM, and disk usage metrics",
                    "parameters": {
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["cpu", "ram", "disk", "all"]},
                            "description": "Specific metrics to retrieve",
                        }
                    },
                },
                "execute_system_command": {
                    "description": "Execute a whitelisted macOS command with audit logging",
                    "parameters": {
                        "command": {"type": "string", "required": True, "description": "Whitelisted command name"},
                        "args": {"type": "array", "items": {"type": "string"}, "description": "Command arguments"},
                        "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 30},
                    },
                },
            },
        }

    async def _get_system_metrics(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("metrics", ["all"])
        if "all" in requested:
            requested = ["cpu", "ram", "disk"]

        result: dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat(), "metrics": {}}

        if "cpu" in requested:
            if _PSUTIL_AVAILABLE:
                result["metrics"]["cpu"] = {
                    "percent": await asyncio.to_thread(psutil.cpu_percent, interval=0),  # type: ignore[possibly-unbound]
                    "count": psutil.cpu_count(),  # type: ignore[possibly-unbound]
                    "freq_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,  # type: ignore[possibly-unbound]
                }
            else:
                result["metrics"]["cpu"] = {"error": "psutil not available"}

        if "ram" in requested:
            if _PSUTIL_AVAILABLE:
                mem = psutil.virtual_memory()  # type: ignore[possibly-unbound]
                result["metrics"]["ram"] = {
                    "total_gb": round(mem.total / (1024 ** 3), 2),
                    "used_gb": round(mem.used / (1024 ** 3), 2),
                    "percent": mem.percent,
                }
            else:
                result["metrics"]["ram"] = {"error": "psutil not available"}

        if "disk" in requested:
            if _PSUTIL_AVAILABLE:
                disk = psutil.disk_usage("/")  # type: ignore[possibly-unbound]
                result["metrics"]["disk"] = {
                    "total_gb": round(disk.total / (1024 ** 3), 2),
                    "used_gb": round(disk.used / (1024 ** 3), 2),
                    "percent": disk.percent,
                }
            else:
                result["metrics"]["disk"] = {"error": "psutil not available"}

        return {"status": "success", "result": result}

    async def _execute_system_command(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        command = params.get("command", "")
        args = params.get("args", [])
        timeout = params.get("timeout", 30)
        exec_result = await self.sandbox.execute(command, args, timeout=timeout)
        return {
            "status": "success",
            "result": {
                "command": command,
                "args": args,
                "returncode": exec_result["returncode"],
                "stdout": exec_result["stdout"],
                "stderr": exec_result["stderr"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

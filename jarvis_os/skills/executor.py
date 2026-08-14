"""Skill execution engine.

Runs a loaded skill through one of the supported execution types — Python
(import a handler module), bash (subprocess), or hybrid (bash then Python
post-processing) — enforcing the skill's timeout, retry policy and sandbox
settings.  Failures are returned as :class:`SkillExecutionResult` records, not
raised, so callers can always inspect the outcome.

Usage::

    from jarvis_os.skills.executor import SkillExecutor
    from jarvis_os.skills.models import ExecutionType

    executor = SkillExecutor(default_timeout=30)
    result = await executor.execute(
        skill, {"date": "today"}, execution_type=ExecutionType.BASH
    )
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis_os.skills.models import (
    ExecutionStatus,
    ExecutionType,
    SkillDependencyError,
    SkillDependency,
    SkillExecutionError,
    SkillExecutionResult,
    SkillMetadata,
    SkillNotFoundError,
    SkillTimeoutError,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SkillExecutor:
    """Executes skills with timeout, retry, sandbox and dependency checks.

    Args:
        default_timeout: Timeout (seconds) used when a skill declares none.
        allowed_commands: Bash commands permitted in ``bash``/``hybrid`` runs;
            an empty list disables the allowlist.
        use_cgroups: Reserved for cgroup memory/CPU enforcement; currently only
            honored as a flag for the sandbox policy.
    """

    def __init__(
        self,
        default_timeout: int = 30,
        allowed_commands: list[str] | None = None,
        use_cgroups: bool = False,
    ) -> None:
        self.default_timeout = default_timeout
        self.allowed_commands = allowed_commands or [
            "python",
            "bash",
            "sh",
            "node",
            "npm",
            "curl",
            "wget",
            "jq",
            "awk",
            "sed",
            "grep",
            "cat",
            "ls",
            "find",
        ]
        self.use_cgroups = use_cgroups

    # --- Public API ----------------------------------------------------------

    async def execute(
        self,
        skill: SkillMetadata,
        input_data: dict[str, Any],
        timeout: int | None = None,
        execution_type: ExecutionType = ExecutionType.PYTHON,
        entrypoint: str | None = None,
        script: str | None = None,
    ) -> SkillExecutionResult:
        """Execute a skill and return its result.

        Args:
            skill: Loaded skill metadata.
            input_data: The skill's input payload (validated against its
                ``input_schema`` by the caller when applicable).
            timeout: Override the declared execution timeout.
            execution_type: One of ``python``, ``bash`` or ``hybrid``.
            entrypoint: Handler module (python) or command name (bash).  Falls
                back to the skill's declared entrypoint, then to its id.
            script: Optional bash script body for ``bash``/``hybrid`` runs.

        Returns:
            The execution result; timeouts and failures are captured in the
            result rather than raised.
        """
        effective_timeout = (
            timeout
            or skill.frontmatter.execution.timeout_seconds
            or self.default_timeout
        )
        started = _utcnow()
        try:
            if execution_type == ExecutionType.PYTHON:
                result = await self._run_python(skill, input_data, entrypoint, effective_timeout)
            elif execution_type == ExecutionType.BASH:
                result = await self._run_bash(skill, input_data, entrypoint, script, effective_timeout)
            elif execution_type == ExecutionType.HYBRID:
                result = await self._run_hybrid(skill, input_data, entrypoint, script, effective_timeout)
            else:  # pragma: no cover — ExecutionType is closed
                result = self._failed(skill, f"unsupported execution type {execution_type!r}", started)
            # Apply the declared retry policy for transient failures.
            result = await self._apply_retries(skill, result, input_data, execution_type, entrypoint, script)
        except SkillTimeoutError as exc:
            result = self._failed(skill, str(exc), started, status=ExecutionStatus.TIMEOUT)
        except SkillExecutionError as exc:
            result = self._failed(skill, str(exc), started)
        return result

    async def execute_with_timeout(
        self,
        skill: SkillMetadata,
        input_data: dict[str, Any],
        timeout: int,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Execute a skill with an explicit timeout override."""
        return await self.execute(skill, input_data, timeout=timeout, **kwargs)

    async def check_dependencies(
        self,
        skill: SkillMetadata,
        loaded_skills: dict[str, SkillMetadata],
    ) -> list[SkillDependency]:
        """Verify every declared dependency is present in ``loaded_skills``.

        Args:
            skill: The skill to check.
            loaded_skills: Mapping of available skill id → metadata.

        Returns:
            The satisfied dependency records.

        Raises:
            SkillDependencyError: If a declared dependency is missing.
        """
        satisfied: list[SkillDependency] = []
        for dep_id in skill.frontmatter.depends_on:
            if dep_id not in loaded_skills:
                raise SkillDependencyError(
                    f"skill {skill.id!r} depends on {dep_id!r}, which is not loaded"
                )
            satisfied.append(SkillDependency(skill_id=dep_id, required_by=skill.id))
        return satisfied

    # --- Execution strategies --------------------------------------------------

    async def _run_python(
        self,
        skill: SkillMetadata,
        input_data: dict[str, Any],
        entrypoint: str | None,
        timeout: int,
    ) -> SkillExecutionResult:
        target = entrypoint or skill.frontmatter.entrypoint or skill.frontmatter.default_entrypoint
        started = _utcnow()
        try:
            module = await asyncio.to_thread(self._import_handler, skill, target)
            output = await asyncio.wait_for(
                asyncio.to_thread(module.run, input_data),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise SkillTimeoutError(
                f"skill {skill.id!r} exceeded {timeout}s timeout"
            ) from None
        except Exception as exc:
            raise SkillExecutionError(f"skill {skill.id!r} failed: {exc}") from exc
        if not isinstance(output, dict):
            output = {"result": output}
        return SkillExecutionResult(
            skill_id=skill.id,
            status=ExecutionStatus.SUCCESS,
            output=output,
            duration_ms=(_utcnow() - started).total_seconds() * 1000,
            started_at=started,
            completed_at=_utcnow(),
        )

    def _import_handler(self, skill: SkillMetadata, target: str) -> Any:
        """Import the Python handler module for a skill.

        ``target`` may be an explicit module path (``pkg.module``) or a bare
        skill name; the latter resolves to ``jarvis_os.skills.handlers.<name>``.
        """
        module_name = target if "." in target else f"jarvis_os.skills.handlers.{target}"
        module = importlib.import_module(module_name)
        handler = getattr(module, "run", None)
        if handler is None:
            raise SkillExecutionError(
                f"skill {skill.id!r}: handler module {module_name!r} has no 'run(input)'"
            )
        return module

    async def _run_bash(
        self,
        skill: SkillMetadata,
        input_data: dict[str, Any],
        entrypoint: str | None,
        script: str | None,
        timeout: int,
    ) -> SkillExecutionResult:
        command = entrypoint or skill.frontmatter.entrypoint or skill.frontmatter.default_entrypoint
        self._check_command_allowed(command)
        started = _utcnow()
        try:
            if script is None:
                script = f"{command} $@"
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=timeout,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise SkillTimeoutError(
                f"skill {skill.id!r} exceeded {timeout}s timeout"
            ) from None
        except Exception as exc:
            raise SkillExecutionError(f"skill {skill.id!r} bash run failed: {exc}") from exc
        if proc.returncode != 0:
            raise SkillExecutionError(
                f"skill {skill.id!r} exited with {proc.returncode}: {stderr.decode(errors='replace')}"
            )
        return SkillExecutionResult(
            skill_id=skill.id,
            status=ExecutionStatus.SUCCESS,
            output={
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            },
            duration_ms=(_utcnow() - started).total_seconds() * 1000,
            started_at=started,
            completed_at=_utcnow(),
        )

    async def _run_hybrid(
        self,
        skill: SkillMetadata,
        input_data: dict[str, Any],
        entrypoint: str | None,
        script: str | None,
        timeout: int,
    ) -> SkillExecutionResult:
        bash_result = await self._run_bash(skill, input_data, entrypoint, script, timeout)
        if bash_result.status != ExecutionStatus.SUCCESS:
            return bash_result
        target = entrypoint or skill.frontmatter.entrypoint or skill.frontmatter.default_entrypoint
        started = _utcnow()
        try:
            module = await asyncio.to_thread(self._import_handler, skill, target)
            merged = {**input_data, "bash": bash_result.output}
            output = await asyncio.wait_for(
                asyncio.to_thread(module.run, merged),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise SkillTimeoutError(
                f"skill {skill.id!r} exceeded {timeout}s timeout (hybrid post-processing)"
            ) from None
        except Exception as exc:
            raise SkillExecutionError(f"skill {skill.id!r} hybrid post-processing failed: {exc}") from exc
        if not isinstance(output, dict):
            output = {"result": output}
        return SkillExecutionResult(
            skill_id=skill.id,
            status=ExecutionStatus.SUCCESS,
            output=output,
            duration_ms=bash_result.duration_ms + (_utcnow() - started).total_seconds() * 1000,
            started_at=bash_result.started_at,
            completed_at=_utcnow(),
        )

    # --- Helpers ---------------------------------------------------------------

    def _check_command_allowed(self, command: str) -> None:
        if not self.allowed_commands:
            return
        binary = command.split(maxsplit=1)[0].split("/")[-1]
        if binary not in self.allowed_commands:
            raise SkillExecutionError(
                f"command {binary!r} is not in the allowed_commands allowlist"
            )

    async def _apply_retries(
        self,
        skill: SkillMetadata,
        result: SkillExecutionResult,
        input_data: dict[str, Any],
        execution_type: ExecutionType,
        entrypoint: str | None,
        script: str | None,
    ) -> SkillExecutionResult:
        retries = skill.frontmatter.execution.retries
        backoff_ms = skill.frontmatter.execution.retry_backoff_ms
        attempt = 0
        while result.status == ExecutionStatus.FAILED and attempt < retries:
            attempt += 1
            logger.debug(
                "Retrying skill %s (attempt %d/%d)", skill.id, attempt, retries
            )
            await asyncio.sleep(backoff_ms / 1000 * (2 ** (attempt - 1)))
            result = await self.execute(
                skill,
                input_data,
                execution_type=execution_type,
                entrypoint=entrypoint,
                script=script,
            )
        return result

    def _failed(
        self,
        skill: SkillMetadata,
        error: str,
        started: datetime,
        status: ExecutionStatus = ExecutionStatus.FAILED,
    ) -> SkillExecutionResult:
        return SkillExecutionResult(
            skill_id=skill.id,
            status=status,
            error=error,
            duration_ms=(_utcnow() - started).total_seconds() * 1000,
            started_at=started,
            completed_at=_utcnow(),
        )

"""RED tests for threat matrix adversarial cases."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis_os.orchestrator_impl.errors import SkillExecutionPipelineError
from jarvis_os.orchestrator_impl.pipeline import OrchestratorPipeline
from jarvis_os.orchestrator_impl.resolver import ResolvedSkill
from jarvis_os.skills.executor import SkillExecutor
from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.models import (
    ExecutionConfig,
    ExecutionStatus,
    ExecutionType,
    SkillFrontmatter,
    SkillMetadata,
)
from jarvis_os.skills.registry import SkillRegistry
from pathlib import Path


def _make_skill(
    skill_id: str,
    name: str,
    description: str,
    capabilities: list[str],
    execution_type: ExecutionType = ExecutionType.PYTHON,
) -> SkillMetadata:
    frontmatter = SkillFrontmatter(
        id=skill_id,
        name=name,
        version="1.0.0",
        description=description,
        capabilities=capabilities,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        execution=ExecutionConfig(),
        execution_type=execution_type,
    )
    return SkillMetadata(
        id=frontmatter.id,
        name=frontmatter.name,
        version=frontmatter.version,
        description=frontmatter.description,
        path=Path("/tmp/fake.md"),
        frontmatter=frontmatter,
    )


def _make_registry(skills: list[SkillMetadata]) -> SkillRegistry:
    registry = SkillRegistry()
    for skill in skills:
        registry.register(skill)
    return registry


def _make_loader() -> MagicMock:
    return MagicMock(spec=SkillLoader)


def _make_executor(success: bool = True) -> MagicMock:
    executor = MagicMock(spec=SkillExecutor)
    result = MagicMock()
    result.ok = success
    result.output = {"result": "done"} if success else None
    result.error = None if success else "something failed"
    result.status = ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILED
    executor.execute = AsyncMock(return_value=result)
    return executor


class TestRoutingAdversarial:
    """RED: adversarial input must not reach executor."""

    @pytest.fixture
    def pipeline(self):
        registry = SkillRegistry()
        loader = _make_loader()
        executor = _make_executor()
        return OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )

    @pytest.mark.asyncio
    async def test_adversarial_delete_everything_returns_unknown(self, pipeline):
        payload = {"text": "delete everything"}
        response = await pipeline.execute(payload)
        assert response.status_code == 404
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"
        assert "No skill found" in body["payload"]["error"]

    @pytest.mark.asyncio
    async def test_adversarial_sudo_rm_rf_returns_unknown(self, pipeline):
        payload = {"text": "sudo rm -rf /"}
        response = await pipeline.execute(payload)
        assert response.status_code == 404
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"

    @pytest.mark.asyncio
    async def test_adversarial_spoofed_skill_id_does_not_execute(self, pipeline):
        skill = _make_skill(
            "skill.safe",
            "Safe",
            "A safe skill",
            ["safe.action"],
        )
        registry = _make_registry([skill])
        loader = _make_loader()
        executor = _make_executor()
        pipeline = OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )
        payload = {"text": "unknown action xyz", "skill_id": "malicious"}
        response = await pipeline.execute(payload)
        assert response.status_code == 404
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"


class TestShellCommandAllowlist:
    """RED: command not in allowlist must be rejected."""

    @pytest.mark.asyncio
    async def test_disallowed_command_rejected(self):
        from jarvis_os.skills.executor import SkillExecutor
        executor = SkillExecutor(allowed_commands=["python"])
        skill = _make_skill(
            "skill.bad",
            "Bad",
            "Tries to run rm",
            ["bad.action"],
            execution_type=ExecutionType.BASH,
        )
        skill.frontmatter.entrypoint = "rm -rf /"
        result = await executor.execute(
            skill=skill,
            input_data={},
            execution_type=ExecutionType.BASH,
        )
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None
        assert "not in the allowed_commands" in result.error


class TestTimeoutEnforcement:
    """RED: skill exceeding timeout returns TIMEOUT status."""

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self):
        from jarvis_os.skills.executor import SkillExecutor
        from jarvis_os.skills.models import ExecutionStatus
        from jarvis_os.orchestrator_impl.pipeline import OrchestratorPipeline

        skill = _make_skill(
            "skill.slow",
            "Slow",
            "Sleeps forever",
            ["slow.action"],
            execution_type=ExecutionType.PYTHON,
        )
        registry = _make_registry([skill])
        loader = _make_loader()
        
        # Mock executor that returns TIMEOUT status
        executor = MagicMock(spec=SkillExecutor)
        result = MagicMock()
        result.ok = False
        result.status = ExecutionStatus.TIMEOUT
        result.error = "exceeded 1s timeout"
        result.output = None
        executor.execute = AsyncMock(return_value=result)
        
        pipeline = OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )
        payload = {"text": "slow action"}
        response = await pipeline.execute(payload)
        
        assert response.status_code == 422
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"
        assert "timeout" in body["payload"]["error"].lower()


class TestOpenCodeUnavailable:
    """RED: OpenCode unreachable returns structured error within deadline."""

    @pytest.fixture
    def pipeline(self):
        registry = SkillRegistry()
        loader = _make_loader()
        executor = _make_executor()
        return OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor, opencode_client=None
        )

    @pytest.mark.asyncio
    async def test_opencode_unavailable_returns_error(self, pipeline):
        payload = {"text": "ejecuta código", "skill_id": "opencode"}
        response = await pipeline.execute(payload)
        assert response.status_code == 404
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"
        assert "OpenCode" in body["payload"]["error"]

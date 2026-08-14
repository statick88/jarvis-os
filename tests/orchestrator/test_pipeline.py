"""Tests for ``jarvis_os.orchestrator.pipeline``."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis_os.orchestrator_impl.errors import (
    IntentAnalysisError,
    SkillExecutionPipelineError,
    SkillResolutionError,
)
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


class TestOrchestratorPipelineHappyPath:
    """Happy path: intent matches skill, executor returns success."""

    @pytest.fixture
    def pipeline(self):
        skill = _make_skill(
            "skill.obsidian",
            "Obsidian",
            "Notes in Obsidian vault",
            ["obsidian.create_note"],
        )
        registry = _make_registry([skill])
        loader = _make_loader()
        executor = _make_executor(success=True)
        return OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )

    @pytest.mark.asyncio
    async def test_happy_path_returns_success(self, pipeline):
        payload = {"text": "crear nota"}
        response = await pipeline.execute(payload)

        assert response.status_code == 200
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "RESPONSE"
        assert body["payload"]["success"] is True
        assert "result" in body["payload"]

    @pytest.mark.asyncio
    async def test_executor_called_with_skill(self, pipeline):
        payload = {"text": "crear nota"}
        await pipeline.execute(payload)
        pipeline._executor.execute.assert_called_once()
        call_kwargs = pipeline._executor.execute.call_args.kwargs
        assert call_kwargs["skill"].id == "skill.obsidian"


class TestOrchestratorPipelineSkillNotFound:
    """Skill not found: returns 404 envelope."""

    @pytest.fixture
    def pipeline(self):
        registry = SkillRegistry()  # empty
        loader = _make_loader()
        executor = _make_executor()
        return OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )

    @pytest.mark.asyncio
    async def test_skill_not_found_returns_404(self, pipeline):
        payload = {"text": "accion desconocida total"}
        response = await pipeline.execute(payload)

        assert response.status_code == 404
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"
        assert body["payload"]["success"] is False
        assert "No skill found" in body["payload"]["error"]


class TestOrchestratorPipelineExecutorFailure:
    """Executor failure: returns 422 envelope with error."""

    @pytest.fixture
    def pipeline(self):
        skill = _make_skill(
            "skill.plan",
            "Plan Diario",
            "Manage daily priorities",
            ["plan.create"],
        )
        registry = _make_registry([skill])
        loader = _make_loader()
        executor = _make_executor(success=False)
        return OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )

    @pytest.mark.asyncio
    async def test_executor_failure_returns_422(self, pipeline):
        payload = {"text": "crear plan"}
        response = await pipeline.execute(payload)

        assert response.status_code == 422
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"
        assert body["payload"]["success"] is False
        assert "failed" in body["payload"]["error"]


class TestOrchestratorPipelineOpenCodeUnavailable:
    """OpenCode unavailable: returns structured error."""

    @pytest.fixture
    def pipeline(self):
        registry = SkillRegistry()
        loader = _make_loader()
        executor = _make_executor()
        return OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor, opencode_client=None
        )

    @pytest.mark.asyncio
    async def test_code_execute_without_client_returns_error(self, pipeline):
        payload = {"text": "accion desconocida total"}
        response = await pipeline.execute(payload)

        assert response.status_code == 404
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["type"] == "ERROR"
        assert "No skill found" in body["payload"]["error"]


class TestOrchestratorPipelineTTS:
    """TTS trigger: asserts voice_client.send_text called."""

    @pytest.fixture
    def pipeline(self):
        skill = _make_skill(
            "skill.obsidian",
            "Obsidian",
            "Notes in Obsidian vault",
            ["obsidian.create_note"],
        )
        registry = _make_registry([skill])
        loader = _make_loader()
        executor = _make_executor(success=True)
        voice_client = MagicMock()
        voice_client.send_text = AsyncMock()
        return OrchestratorPipeline(
            registry=registry,
            loader=loader,
            executor=executor,
            voice_client=voice_client,
        )

    @pytest.mark.asyncio
    async def test_tts_triggered_when_text_and_session_present(self, pipeline):
        payload = {
            "text": "crear nota",
            "tts_text": "Nota creada",
            "session_id": "session-001",
        }
        response = await pipeline.execute(payload)

        assert response.status_code == 200
        pipeline._voice_client.send_text.assert_called_once_with(
            "session-001", "Nota creada"
        )

    @pytest.mark.asyncio
    async def test_tts_not_triggered_without_voice_client(self):
        skill = _make_skill(
            "skill.obsidian",
            "Obsidian",
            "Notes in Obsidian vault",
            ["obsidian.create_note"],
        )
        registry = _make_registry([skill])
        loader = _make_loader()
        executor = _make_executor(success=True)
        pipeline = OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor, voice_client=None
        )
        payload = {
            "text": "crear nota",
            "tts_text": "Nota creada",
            "session_id": "session-001",
        }
        response = await pipeline.execute(payload)
        assert response.status_code == 200


class TestOrchestratorPipelineComposition:
    """Composition: chain of skills executes sequentially."""

    @pytest.fixture
    def pipeline(self):
        skill_a = _make_skill(
            "skill.metricas",
            "Metricas",
            "System metrics",
            ["metricas.collect"],
        )
        skill_b = _make_skill(
            "skill.plan",
            "Plan",
            "Daily plan",
            ["plan.create"],
        )
        registry = _make_registry([skill_a, skill_b])
        loader = _make_loader()
        executor = MagicMock(spec=SkillExecutor)

        async def fake_execute(skill, input_data, **kwargs):
            result = MagicMock()
            result.ok = True
            result.output = {skill.id: f"output_from_{skill.id}"}
            result.status = ExecutionStatus.SUCCESS
            result.error = None
            return result

        executor.execute = AsyncMock(side_effect=fake_execute)
        return OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )

    @pytest.mark.asyncio
    async def test_composition_chains_skills(self, pipeline):
        payload = {
            "text": "crear plan",
            "composition": ["skill.metricas", "skill.plan"],
        }
        response = await pipeline.execute(payload)

        assert response.status_code == 200
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["payload"]["success"] is True
        # Both skills should have been executed
        assert pipeline._executor.execute.call_count == 2


class TestOrchestratorPipelineOpenCodeAvailable:
    """OpenCode available: delegates to client."""

    @pytest.fixture
    def pipeline(self):
        registry = SkillRegistry()
        loader = _make_loader()
        executor = _make_executor()
        opencode_client = MagicMock()
        opencode_response = MagicMock()
        opencode_response.status = "success"
        opencode_response.result = {"code_output": "42"}
        opencode_client.execute_skill = AsyncMock(return_value=opencode_response)
        return OrchestratorPipeline(
            registry=registry,
            loader=loader,
            executor=executor,
            opencode_client=opencode_client,
        )

    @pytest.mark.asyncio
    async def test_code_execute_delegates_to_opencode(self, pipeline):
        payload = {"text": "haz algo", "skill_id": "opencode"}
        response = await pipeline.execute(payload)

        assert response.status_code == 200
        body = response.body
        if isinstance(body, bytes):
            import json
            body = json.loads(body)
        assert body["payload"]["success"] is True
        pipeline._opencode_client.execute_skill.assert_called_once()

"""Integration tests for the orchestrator pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from jarvis_os.orchestrator import app
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


@pytest.fixture
def client():
    import jarvis_os.orchestrator as orch_mod
    from jarvis_os.skills.registry import SkillRegistry
    from jarvis_os.skills.loader import SkillLoader
    from pathlib import Path
    import asyncio

    original_get_voice = orch_mod._get_voice_client
    orch_mod._get_voice_client = lambda: None

    registry = SkillRegistry(skills_dir=Path(".skills"))
    try:
        asyncio.get_event_loop().run_until_complete(
            registry.load_from_directory(skills_dir=Path(".skills"))
        )
    except Exception:
        pass
    app.state.skill_registry = registry

    try:
        yield TestClient(app)
    finally:
        orch_mod._get_voice_client = original_get_voice


class TestV1ExecuteIntegration:
    """Integration: /v1/execute end-to-end with real SkillRegistry."""

    def test_happy_path_returns_envelope(self, client):
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
            registry=registry, loader=loader, executor=executor
        )
        app.state.pipeline = pipeline

        payload = {"text": "crear nota"}
        response = client.post("/v1/execute", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "RESPONSE"
        assert body["payload"]["success"] is True

    def test_skill_not_found_returns_404(self, client):
        registry = SkillRegistry()
        loader = _make_loader()
        executor = _make_executor()

        pipeline = OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )
        app.state.pipeline = pipeline

        payload = {"text": "accion desconocida total"}
        response = client.post("/v1/execute", json=payload)
        assert response.status_code == 404
        body = response.json()
        assert body["type"] == "ERROR"
        assert "No skill found" in body["payload"]["error"]

    def test_executor_failure_returns_422(self, client):
        skill = _make_skill(
            "skill.plan",
            "Plan Diario",
            "Manage daily priorities",
            ["plan.create"],
        )
        registry = _make_registry([skill])
        loader = _make_loader()
        executor = _make_executor(success=False)

        pipeline = OrchestratorPipeline(
            registry=registry, loader=loader, executor=executor
        )
        app.state.pipeline = pipeline

        payload = {"text": "crear plan"}
        response = client.post("/v1/execute", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert body["type"] == "ERROR"
        assert "failed" in body["payload"]["error"]


class TestBackwardCompatibility:
    """Backward compatibility: /api/v1/skills/* endpoints remain functional."""

    def test_skills_list_endpoint(self, client):
        response = client.get("/api/v1/skills")
        assert response.status_code == 200
        body = response.json()
        assert "skills" in body

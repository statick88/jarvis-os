"""T-4: pipeline latency instrumentation (FASE 11)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis_os.orchestrator_impl.pipeline import OrchestratorPipeline
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


def _make_skill() -> SkillMetadata:
    frontmatter = SkillFrontmatter(
        id="skill.obsidian",
        name="Obsidian",
        version="1.0.0",
        description="Notes in Obsidian vault",
        capabilities=["obsidian.create_note"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        execution=ExecutionConfig(),
        execution_type=ExecutionType.PYTHON,
    )
    return SkillMetadata(
        id=frontmatter.id,
        name=frontmatter.name,
        version=frontmatter.version,
        description=frontmatter.description,
        path=Path("/tmp/fake.md"),
        frontmatter=frontmatter,
    )


def _make_pipeline(tmp_path: Path, tts_text: str | None) -> OrchestratorPipeline:
    registry = SkillRegistry()
    registry.register(_make_skill())
    executor = MagicMock(spec=SkillExecutor)
    result = MagicMock()
    result.ok = True
    result.output = {"result": "done"}
    result.error = None
    result.status = ExecutionStatus.SUCCESS
    executor.execute = AsyncMock(return_value=result)
    tts_calls: list[str] = []

    async def _tts(text: str) -> None:
        tts_calls.append(text)

    pipeline = OrchestratorPipeline(
        registry=registry,
        loader=MagicMock(spec=SkillLoader),
        executor=executor,
        vault_root=tmp_path / "vault",
        tts_callback=_tts,
    )
    pipeline._test_tts_calls = tts_calls  # type: ignore[attr-defined]
    return pipeline


@pytest.mark.asyncio
async def test_pipeline_latency_instrumented(tmp_path: Path) -> None:
    pipeline = _make_pipeline(tmp_path, tts_text="hola")
    events: list = []
    pipeline.add_event_listener(events.append)
    response = await pipeline.execute({"text": "crear nota", "tts_text": "hola"})
    assert response.status_code == 200
    complete = next(e for e in events if type(e).__name__ == "SkillExecutionComplete")
    assert complete.pipeline_latency_ms is not None
    assert complete.pipeline_latency_ms >= complete.duration_ms >= 0
    assert complete.pipeline_latency_ms < 5000
    assert complete.tts_dispatch_ms is not None
    assert complete.tts_dispatch_ms >= 0


@pytest.mark.asyncio
async def test_no_tts_no_dispatch_latency(tmp_path: Path) -> None:
    pipeline = _make_pipeline(tmp_path, tts_text=None)
    events: list = []
    pipeline.add_event_listener(events.append)
    response = await pipeline.execute({"text": "crear nota"})
    assert response.status_code == 200
    complete = next(e for e in events if type(e).__name__ == "SkillExecutionComplete")
    assert complete.pipeline_latency_ms is not None
    assert complete.tts_dispatch_ms is None

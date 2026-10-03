"""Regression tests: pipeline vault write + VaultIndexer wiring (FASE 11 T-2).

Covers:
1. Vault write success triggers an incremental index pass whose backlink
   connects the new output file to the related wiki note.
2. Vault write failure never breaks the pipeline response (fallback contract).
3. Indexer failure never breaks the pipeline response (fallback contract).
"""

from __future__ import annotations

import json
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
from jarvis_os.vault.indexer import VaultIndexer
from jarvis_os.vault.models import VaultIndex, VaultWriteError


# ---------------------------------------------------------------------------
# Helpers (mirrors tests/orchestrator/test_pipeline.py conventions)
# ---------------------------------------------------------------------------


def _make_skill(
    skill_id: str = "skill.obsidian",
    name: str = "Obsidian",
    description: str = "Notes in Obsidian vault",
    capabilities: list[str] | None = None,
    execution_type: ExecutionType = ExecutionType.PYTHON,
) -> SkillMetadata:
    frontmatter = SkillFrontmatter(
        id=skill_id,
        name=name,
        version="1.0.0",
        description=description,
        capabilities=capabilities or ["obsidian.create_note"],
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


def _make_pipeline(vault_root: Path, vault_indexer) -> OrchestratorPipeline:
    """Build a pipeline with a working executor and the vault wiring under test."""
    registry = _make_registry([_make_skill()])
    return OrchestratorPipeline(
        registry=registry,
        loader=_make_loader(),
        executor=_make_executor(success=True),
        vault_root=vault_root,
        vault_indexer=vault_indexer,
    )


def _write_wiki_note(path: Path, note_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f'id: "{note_id}"\n'
        f'title: "{note_id}"\n'
        'tags: ["skill"]\n'
        'created: "2026-10-02T10:00:00+00:00"\n'
        'modified: "2026-10-02T10:00:00+00:00"\n'
        "---\n\n"
        "Skill note for backlink regression tests.\n",
        encoding="utf-8",
    )


def _load_index(vault_root: Path) -> VaultIndex:
    raw = (vault_root / "wiki" / ".boveda_index.json").read_text(encoding="utf-8")
    return VaultIndex.model_validate(json.loads(raw))


def _body_json(response) -> dict:
    body = response.body
    if isinstance(body, bytes):
        body = json.loads(body)
    return body


# ---------------------------------------------------------------------------
# 1. Vault write success -> incremental index creates the backlink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vault_write_success_creates_backlink(tmp_path: Path) -> None:
    """Successful write_execution must trigger indexing that backlinks output -> wiki."""
    vault = tmp_path / "vault"
    _write_wiki_note(vault / "wiki" / "skill-obsidian.md", "skill-obsidian")
    indexer = VaultIndexer(vault_root=vault)

    pipeline = _make_pipeline(vault, indexer)
    response = await pipeline.execute({"text": "crear nota"})

    assert response.status_code == 200
    assert _body_json(response)["payload"]["success"] is True

    # Output file was written under outputs/<date>/
    outputs = list((vault / "outputs").rglob("skill-obsidian-*.md"))
    assert outputs, "vault output markdown was not written"

    # Index file exists and the wiki note links to the new output
    index = _load_index(vault)
    wiki_entry = next(
        e for e in index.files.values() if e.rel_path == "wiki/skill-obsidian.md"
    )
    output_links = [link for link in wiki_entry.links if link.startswith("outputs/")]
    assert output_links, (
        f"wiki note should backlink to the output, got links={wiki_entry.links}"
    )


# ---------------------------------------------------------------------------
# 2. Vault write failure never breaks the pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vault_write_failure_does_not_break_pipeline(tmp_path: Path) -> None:
    """write_execution raising must fall back to the warning path, HTTP 200."""
    vault = tmp_path / "vault"
    _write_wiki_note(vault / "wiki" / "skill-obsidian.md", "skill-obsidian")

    failing_indexer = MagicMock()
    failing_indexer.index = AsyncMock()

    pipeline = _make_pipeline(vault, failing_indexer)
    pipeline._vault_logger.write_execution = AsyncMock(
        side_effect=VaultWriteError("disk full")
    )

    response = await pipeline.execute({"text": "crear nota"})

    assert response.status_code == 200
    assert _body_json(response)["payload"]["success"] is True
    # Indexing must not run when the vault write failed
    failing_indexer.index.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. Indexer failure never breaks the pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_indexer_failure_does_not_break_pipeline(tmp_path: Path) -> None:
    """index() raising must be caught by the vault fallback, HTTP 200."""
    vault = tmp_path / "vault"
    _write_wiki_note(vault / "wiki" / "skill-obsidian.md", "skill-obsidian")

    exploding_indexer = MagicMock()
    exploding_indexer.index = AsyncMock(side_effect=RuntimeError("index exploded"))

    pipeline = _make_pipeline(vault, exploding_indexer)
    response = await pipeline.execute({"text": "crear nota"})

    assert response.status_code == 200
    assert _body_json(response)["payload"]["success"] is True
    exploding_indexer.index.assert_awaited_once()

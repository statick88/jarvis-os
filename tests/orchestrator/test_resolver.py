"""Tests for ``jarvis_os.orchestrator.resolver``."""

from __future__ import annotations

from pathlib import Path

from unittest.mock import MagicMock

import pytest

from jarvis_os.orchestrator_impl.resolver import ResolvedSkill, SkillResolver
from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.models import (
    ExecutionConfig,
    SkillFrontmatter,
    SkillMetadata,
)
from jarvis_os.skills.registry import SkillRegistry


def _make_skill(
    skill_id: str,
    name: str,
    description: str,
    capabilities: list[str],
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
    )
    return SkillMetadata(
        id=frontmatter.id,
        name=frontmatter.name,
        version=frontmatter.version,
        description=frontmatter.description,
        path=Path("/tmp/fake.md"),
        frontmatter=frontmatter,
    )


class TestSkillResolver:
    def test_capability_hit(self) -> None:
        skill = _make_skill(
            "skill.obsidian",
            "Obsidian",
            "Notes in Obsidian vault",
            ["obsidian.create", "obsidian.read"],
        )
        registry = SkillRegistry()
        registry.register(skill)
        loader = MagicMock(spec=SkillLoader)

        resolver = SkillResolver(registry=registry, loader=loader)
        result = resolver.resolve("obsidian.create", "crear nota")

        assert result.skill is not None
        assert result.skill.id == "skill.obsidian"
        assert result.confidence == 1.0
        assert result.source == "capability"

    def test_skill_not_found_returns_empty(self) -> None:
        registry = SkillRegistry()
        loader = MagicMock(spec=SkillLoader)

        resolver = SkillResolver(registry=registry, loader=loader)
        result = resolver.resolve("unknown.capability", "foo bar")

        assert result.skill is None
        assert result.confidence == 0.0
        assert result.source == ""

    def test_keyword_fallback(self) -> None:
        skill = _make_skill(
            "skill.plan",
            "Plan Diario",
            "Manage daily priorities and tasks",
            ["plan.create"],
        )
        registry = SkillRegistry()
        registry.register(skill)
        loader = MagicMock(spec=SkillLoader)

        resolver = SkillResolver(registry=registry, loader=loader)
        result = resolver.resolve("unknown.intent", "crear plan diario")

        assert result.skill is not None
        assert result.skill.id == "skill.plan"
        assert result.source == "keyword"
        assert result.confidence > 0.0

    def test_empty_registry(self) -> None:
        registry = SkillRegistry()
        loader = MagicMock(spec=SkillLoader)

        resolver = SkillResolver(registry=registry, loader=loader)
        result = resolver.resolve("obsidian.create", "crear nota")

        assert result.skill is None
        assert result.confidence == 0.0

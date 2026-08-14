"""Skills subsystem: models, loader, executor, registry.

Exposes the public API for working with JARVIS-OS skills::

    from jarvis_os.skills import SkillRegistry

    registry = SkillRegistry(skills_dir=Path(".skills"))
    await registry.load_from_directory()
    skills = registry.list_all()

The subsystem is pure logic with no IO on import; callers wire the loader,
executor and registry together (typically via the skills service layer).
"""

from __future__ import annotations

from jarvis_os.skills.executor import SkillExecutor
from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.models import (
    ExecutionConfig,
    ExecutionStatus,
    ExecutionType,
    SkillDependency,
    SkillDependencyError,
    SkillError,
    SkillExecutionError,
    SkillExecutionResult,
    SkillFrontmatter,
    SkillMetadata,
    SkillNotFoundError,
    SkillRegistryError,
    SkillTimeoutError,
    SkillValidationError,
)
from jarvis_os.skills.registry import SkillRegistry

__all__ = [
    "ExecutionConfig",
    "ExecutionStatus",
    "ExecutionType",
    "SkillDependency",
    "SkillDependencyError",
    "SkillError",
    "SkillExecutionError",
    "SkillExecutionResult",
    "SkillExecutor",
    "SkillFrontmatter",
    "SkillLoader",
    "SkillMetadata",
    "SkillNotFoundError",
    "SkillRegistry",
    "SkillRegistryError",
    "SkillTimeoutError",
    "SkillValidationError",
]

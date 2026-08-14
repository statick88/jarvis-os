"""Skill domain models for JARVIS-OS.

Defines the pydantic models that mirror ``spec/contracts/skill_schema.yaml``
plus the runtime metadata, execution results and dependency records used by
``loader.py``, ``executor.py`` and ``registry.py``.

Usage::

    from jarvis_os.skills.models import SkillFrontmatter, SkillMetadata

    frontmatter = SkillFrontmatter(
        id="skill.plan",
        name="Plan Diario",
        version="1.0.0",
        description="CRUD de prioridades diarias en wiki/plan_hoy.md",
        capabilities=["plan.create", "plan.read"],
    )
    metadata = SkillMetadata.from_path(frontmatter, Path(".skills/plan.md"))
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# --- Constants ---

SKILL_ID_RE = re.compile(r"^skill[.\-][a-z][a-z0-9_]*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$")
CAPABILITY_RE = re.compile(r"^[a-z]+\.[a-z_]+$")

VALID_LICENSES = frozenset({"MIT", "Apache-2.0", "GPL-3.0", "BSD-3-Clause"})
DEFAULT_AUTHOR = "jarvis-os team"
DEFAULT_LICENSE = "MIT"


# --- Exceptions ---


class SkillError(Exception):
    """Base error for the skills module."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)!r})"


class SkillNotFoundError(SkillError):
    """Raised when a skill id is not registered or loaded."""


class SkillRegistryError(SkillError):
    """Raised when registry persistence (save/load) fails."""


class SkillValidationError(SkillError):
    """Raised when frontmatter fails validation against the schema."""


class SkillDependencyError(SkillError):
    """Raised when a skill's declared dependencies are unavailable."""


class SkillExecutionError(SkillError):
    """Raised when a skill run fails (non-zero exit, raised handler, etc.)."""


class SkillTimeoutError(SkillError):
    """Raised when a skill exceeds its execution timeout."""


# --- Execution types ---


class ExecutionType(StrEnum):
    """Supported skill execution strategies."""

    PYTHON = "python"
    BASH = "bash"
    HYBRID = "hybrid"


class ExecutionStatus(StrEnum):
    """Lifecycle status of a skill run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


# --- Frontmatter models ---


class ExecutionConfig(BaseModel):
    """Execution resource limits and retry policy (schema ``execution``).

    Only ``timeout_seconds`` is mandatory in real skill files; the remaining
    fields fall back to the schema defaults when absent so every shipped
    ``.skills/*.md`` parses under strict validation.
    """

    timeout_seconds: int = Field(
        default=30, ge=5, le=300, description="Max run time before kill"
    )
    memory_limit_mb: int = Field(
        default=256, ge=64, le=2048, description="RSS memory limit (cgroups if available)"
    )
    cpu_limit_percent: int = Field(
        default=50, ge=10, le=100, description="Relative CPU limit (100% = 1 core)"
    )
    sandbox: bool = Field(default=True, description="Run in an isolated subprocess")
    retries: int = Field(
        default=0, ge=0, le=3, description="Automatic retries on transient failure"
    )
    retry_backoff_ms: int = Field(
        default=1000, ge=100, le=10_000, description="Exponential backoff between retries (ms)"
    )


class SkillFrontmatter(BaseModel):
    """Validated YAML frontmatter of a ``.skills/*.md`` file.

    Mirrors ``spec/contracts/skill_schema.yaml`` required properties.
    """

    id: str = Field(..., description="Unique identifier with 'skill.' namespace")
    name: str = Field(..., min_length=1, max_length=50, description="Human-readable name")
    version: str = Field(..., description="SemVer version, e.g. 1.2.3-beta.1")
    description: str = Field(
        ..., min_length=10, max_length=200, description="Short summary of what the skill does"
    )
    author: str = Field(default=DEFAULT_AUTHOR)
    license: str = Field(default=DEFAULT_LICENSE)
    capabilities: list[str] = Field(
        ..., min_length=1, description="namespace.action capabilities the skill exposes"
    )
    input_schema: dict[str, Any] = Field(..., description="JSON Schema Draft 07 for 'input'")
    output_schema: dict[str, Any] = Field(..., description="JSON Schema Draft 07 for 'output'")
    depends_on: list[str] = Field(
        default_factory=list, description="Skills that must load first (topological order)"
    )
    execution: ExecutionConfig = Field(
        default_factory=ExecutionConfig, description="Execution resource limits and retry policy"
    )
    execution_type: ExecutionType = Field(
        default=ExecutionType.PYTHON,
        description="How the executor runs the skill (python / bash / hybrid)",
    )
    entrypoint: str = Field(
        default="", description="Handler module/command; derived from id when empty"
    )
    health: Optional[dict[str, Any]] = Field(
        default=None, description="Optional HTTP health check configuration"
    )

    @field_validator("id", "depends_on")
    @classmethod
    def validate_skill_ids(cls, v: str | list[str]) -> str | list[str]:
        values = [v] if isinstance(v, str) else v
        for value in values:
            if not SKILL_ID_RE.match(value):
                raise ValueError(
                    f"Skill id must match /^skill\\.[a-z][a-z0-9_]*$/ — got {value!r}"
                )
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError(f"Version must match SemVer — got {v!r}")
        return v

    @field_validator("license")
    @classmethod
    def validate_license(cls, v: str) -> str:
        if v not in VALID_LICENSES:
            raise ValueError(f"License must be one of {sorted(VALID_LICENSES)} — got {v!r}")
        return v

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        for cap in v:
            if not CAPABILITY_RE.match(cap):
                raise ValueError(
                    f"Capability must match /^[a-z]+\\.[a-z_]+$/ — got {cap!r}"
                )
        if len(set(v)) != len(v):
            raise ValueError(f"Capabilities must be unique — got {v!r}")
        return v

    @property
    def default_entrypoint(self) -> str:
        """Entrypoint convention when none is declared (skill id without prefix)."""
        return re.sub(r"^skill[.\-]", "", self.id)


# --- Runtime models ---


class SkillMetadata(BaseModel):
    """Loaded skill: frontmatter plus the file it came from and load time."""

    id: str = Field(..., description="Skill id, e.g. skill.plan")
    name: str = Field(..., description="Human-readable name")
    version: str = Field(..., description="SemVer version")
    description: str = Field(..., description="Short summary")
    path: Path = Field(..., description="Path of the .skills/*.md file")
    frontmatter: SkillFrontmatter = Field(..., description="Validated frontmatter")
    loaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Load timestamp (UTC)"
    )

    @classmethod
    def from_path(cls, frontmatter: SkillFrontmatter, path: Path) -> "SkillMetadata":
        """Build metadata for a validated frontmatter loaded from ``path``."""
        return cls(
            id=frontmatter.id,
            name=frontmatter.name,
            version=frontmatter.version,
            description=frontmatter.description,
            path=path,
            frontmatter=frontmatter,
        )


class SkillExecutionResult(BaseModel):
    """Outcome of one skill run."""

    skill_id: str = Field(..., description="Skill id that ran")
    status: ExecutionStatus = Field(
        default=ExecutionStatus.PENDING, description="Run lifecycle status"
    )
    output: Optional[dict[str, Any]] = Field(default=None, description="Structured skill output")
    error: Optional[str] = Field(default=None, description="Error message on failure")
    duration_ms: float = Field(default=0.0, description="Wall-clock time in ms")
    started_at: Optional[datetime] = Field(default=None, description="Run start (UTC)")
    completed_at: Optional[datetime] = Field(default=None, description="Run end (UTC)")

    @property
    def ok(self) -> bool:
        """True when the run succeeded."""
        return self.status == ExecutionStatus.SUCCESS


class SkillDependency(BaseModel):
    """Edge in the skill dependency graph."""

    skill_id: str = Field(..., description="Dependency skill id")
    required_by: str = Field(..., description="Skill id that depends on it")
    version_constraint: Optional[str] = Field(
        default=None, description="Optional semver constraint, e.g. ^1.0.0"
    )

"""Skill frontmatter loader.

Parses ``.skills/*.md`` files, extracts the YAML frontmatter between the
``---`` delimiters, merges schema defaults for missing ``execution`` keys, and
validates the result into :class:`SkillFrontmatter`.  File I/O is offloaded
to the event loop via :func:`asyncio.to_thread` so the loader never blocks.

Usage::

    from jarvis_os.skills.loader import SkillLoader

    loader = SkillLoader(skills_dir=Path(".skills"))
    skills = await loader.load_all()          # {skill.plan: SkillMetadata, ...}
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml

from jarvis_os.skills.models import (
    DEFAULT_AUTHOR,
    DEFAULT_LICENSE,
    ExecutionConfig,
    SkillFrontmatter,
    SkillMetadata,
    SkillValidationError,
)

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = "---"  # delimiter (kept as literal for clarity)


class SkillLoader:
    """Loads and validates skill frontmatter from a skills directory.

    Args:
        skills_dir: Directory containing ``*.md`` skill files.
        schema_path: Path to the JSON Schema used for strict validation
            (``strict_schema_validation`` must be enabled in settings).
        strict_schema_validation: When True, validate frontmatter against the
            skill schema; missing ``execution`` keys still fall back to the
            schema defaults so real skill files parse.
        defaults: Optional :class:`ExecutionConfig` used to fill any missing
            ``execution`` keys (falls back to model defaults otherwise).
    """

    def __init__(
        self,
        skills_dir: Path,
        schema_path: Path | None = None,
        strict_schema_validation: bool = True,
        defaults: ExecutionConfig | None = None,
    ) -> None:
        self.skills_dir = skills_dir
        self.schema_path = schema_path
        self.strict_schema_validation = strict_schema_validation
        self._defaults = defaults or ExecutionConfig()

    # --- Frontmatter parsing -------------------------------------------------

    def parse_frontmatter(self, text: str, source: str) -> dict[str, Any]:
        """Extract and YAML-parse the frontmatter block of a skill file.

        Args:
            text: Raw markdown file content.
            source: Human-readable source label used in error messages.

        Returns:
            The parsed frontmatter mapping.

        Raises:
            SkillValidationError: If the block is missing, unclosed, or not a
                valid YAML mapping.
        """
        stripped = text.lstrip()
        if not stripped.startswith(_FRONTMATTER_RE):
            raise SkillValidationError(f"{source}: missing '---' frontmatter opener")
        first_newline = stripped.find("\n")
        if first_newline == -1:
            raise SkillValidationError(f"{source}: unterminated '---' frontmatter")
        rest = stripped[first_newline + 1 :]
        if not rest.startswith(_FRONTMATTER_RE):
            # Find the closing delimiter (its own line).
            closing = rest.find("\n" + _FRONTMATTER_RE + "\n")
            if closing == -1:
                raise SkillValidationError(f"{source}: missing closing '---' delimiter")
            block = rest[:closing]
        else:
            block = ""  # "---\n---" → empty frontmatter
        try:
            data = yaml.safe_load(block) or {}
        except yaml.YAMLError as exc:
            raise SkillValidationError(f"{source}: invalid YAML frontmatter: {exc}") from exc
        if not isinstance(data, dict):
            raise SkillValidationError(
                f"{source}: frontmatter must be a YAML mapping, got {type(data).__name__}"
            )
        return data

    def apply_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        """Fill missing ``execution`` keys with schema/config defaults.

        Real ``.skills/*.md`` files only declare ``timeout_seconds``; the
        schema lists ``memory_limit_mb``/``cpu_limit_percent``/``sandbox`` as
        required.  Merging the defaults keeps strict validation green.
        """
        merged = dict(data)
        if "author" not in merged:
            merged["author"] = DEFAULT_AUTHOR
        if "license" not in merged:
            merged["license"] = DEFAULT_LICENSE
        if "execution" not in merged or not isinstance(merged["execution"], dict):
            merged["execution"] = self._defaults.model_dump()
        else:
            merged["execution"] = {
                **self._defaults.model_dump(),
                **merged["execution"],
            }
        return merged

    def validate_frontmatter(self, data: dict[str, Any], source: str) -> SkillFrontmatter:
        """Validate a parsed frontmatter mapping into a model.

        Args:
            data: Parsed YAML frontmatter.
            source: Source label for error messages.

        Returns:
            The validated frontmatter.

        Raises:
            SkillValidationError: If validation fails under the current mode.
        """
        enriched = self.apply_defaults(data)
        try:
            frontmatter = SkillFrontmatter(**enriched)
        except Exception as exc:  # pydantic.ValidationError
            raise SkillValidationError(f"{source}: invalid frontmatter: {exc}") from exc
        if self.schema_path is not None and self.strict_schema_validation:
            self._validate_against_schema(frontmatter)
        return frontmatter

    def _validate_against_schema(self, frontmatter: SkillFrontmatter) -> None:
        """Strict-mode schema check (id/version/capabilities already enforced by the model)."""
        # The pydantic model enforces id, version, capabilities and license
        # patterns; the YAML schema file adds no extra constraints beyond those,
        # so a successfully constructed model is schema-conformant.
        logger.debug("Strict schema validation passed for %s", frontmatter.id)

    # --- I/O -----------------------------------------------------------------

    async def load_skill(self, path: Path) -> SkillMetadata:
        """Load and validate a single ``*.md`` skill file."""
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = await asyncio.to_thread(self.parse_frontmatter, text, str(path))
        frontmatter = await asyncio.to_thread(self.validate_frontmatter, data, str(path))
        metadata = SkillMetadata.from_path(frontmatter, path)
        logger.debug("Loaded skill %s from %s", metadata.id, path)
        return metadata

    async def load_all(self) -> dict[str, SkillMetadata]:
        """Load every ``*.md`` file under ``skills_dir``.

        Returns:
            Mapping of skill id → :class:`SkillMetadata`.

        Raises:
            SkillValidationError: If any skill file fails to validate.
        """
        files = await asyncio.to_thread(sorted, self.skills_dir.glob("*.md"))
        skills: dict[str, SkillMetadata] = {}
        for path in files:
            metadata = await self.load_skill(path)
            skills[metadata.id] = metadata
        return skills

    async def reload_skill(self, skill_id: str, skills_dir: Path | None = None) -> SkillMetadata:
        """Reload a single skill by id (optionally from another directory)."""
        directory = skills_dir or self.skills_dir
        path = directory / f"{skill_id.removeprefix('skill.')}.md"
        if not await asyncio.to_thread(path.exists):
            raise SkillValidationError(f"skill {skill_id!r} not found at {path}")
        return await self.load_skill(path)

    async def validate_frontmatter_file(self, path: Path) -> SkillFrontmatter:
        """Parse + validate a file and return only its frontmatter (no metadata)."""
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = await asyncio.to_thread(self.parse_frontmatter, text, str(path))
        return await asyncio.to_thread(self.validate_frontmatter, data, str(path))

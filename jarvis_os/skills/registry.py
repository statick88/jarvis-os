"""Skill registry.

Holds the in-memory mapping of skill id → :class:`SkillMetadata` and
persists it as a JSON file so the registry survives restarts.  The registry
can be populated by scanning a skills directory (via :class:`SkillLoader`) or
by explicit ``register`` calls, and supports capability lookup.

Usage::

    from jarvis_os.skills.registry import SkillRegistry

    registry = SkillRegistry()
    registry.load_from_directory(Path(".skills"))
    plan = registry.get("skill.plan")
    crud_skills = registry.find_by_capability("plan.create")
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.models import (
    SkillFrontmatter,
    SkillMetadata,
    SkillNotFoundError,
    SkillRegistryError,
)

logger = logging.getLogger(__name__)


class SkillRegistry:
    """In-memory skill registry with optional JSON persistence.

    Args:
        skills_dir: Optional default directory scanned by
            :meth:`load_from_directory` and :meth:`reload`.
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir
        self._skills: dict[str, SkillMetadata] = {}

    # --- Query API -------------------------------------------------------------

    def register(self, metadata: SkillMetadata) -> None:
        """Register a loaded skill (replaces any existing entry)."""
        self._skills[metadata.id] = metadata
        logger.debug("Registered skill %s", metadata.id)

    def unregister(self, skill_id: str) -> None:
        """Remove a skill from the registry.

        Raises:
            SkillNotFoundError: If the skill id is not registered.
        """
        if skill_id not in self._skills:
            raise SkillNotFoundError(f"skill {skill_id!r} is not registered")
        del self._skills[skill_id]

    def get(self, skill_id: str) -> SkillMetadata:
        """Return a registered skill by id.

        Raises:
            SkillNotFoundError: If the skill id is not registered.
        """
        try:
            return self._skills[skill_id]
        except KeyError:
            raise SkillNotFoundError(f"skill {skill_id!r} is not registered") from None

    def list_all(self) -> list[SkillMetadata]:
        """Return all registered skills (sorted by id)."""
        return [self._skills[key] for key in sorted(self._skills)]

    def find_by_capability(self, capability: str) -> list[SkillMetadata]:
        """Return skills exposing the given ``namespace.action`` capability."""
        return [
            meta
            for meta in self.list_all()
            if capability in meta.frontmatter.capabilities
        ]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, skill_id: str) -> bool:
        return skill_id in self._skills

    # --- Loading -----------------------------------------------------------------

    async def load_from_directory(
        self, skills_dir: Path | None = None, loader: SkillLoader | None = None
    ) -> int:
        """Scan a directory and register every valid skill file.

        Args:
            skills_dir: Directory to scan (defaults to the registry's).
            loader: Optional preconfigured :class:`SkillLoader`; a default one
                is created for ``skills_dir`` when omitted.

        Returns:
            Number of skills registered.

        Raises:
            SkillRegistryError: If the directory does not exist or is empty.
        """
        directory = skills_dir or self.skills_dir
        if directory is None:
            raise SkillRegistryError("no skills_dir configured for registry")
        if not await asyncio.to_thread(directory.is_dir):
            raise SkillRegistryError(f"skills directory {directory} does not exist")
        loader = loader or SkillLoader(skills_dir=directory)
        loaded = await loader.load_all()
        for metadata in loaded.values():
            self.register(metadata)
        if not loaded:
            logger.warning("No skill files found in %s", directory)
        return len(loaded)

    async def reload(self, skill_id: str) -> SkillMetadata:
        """Reload a single skill from disk and update the registry.

        Raises:
            SkillNotFoundError: If the skill id is not registered.
        """
        if skill_id not in self._skills:
            raise SkillNotFoundError(f"skill {skill_id!r} is not registered")
        directory = self.skills_dir or self._skills[skill_id].path.parent
        loader = SkillLoader(skills_dir=directory)
        metadata = await loader.reload_skill(skill_id, skills_dir=directory)
        self.register(metadata)
        return metadata

    # --- Persistence -------------------------------------------------------------

    async def save(self, registry_file: Path | None = None) -> Path:
        """Persist the registry to a JSON file.

        Args:
            registry_file: Destination path (defaults to ``skills_dir /
                registry.json``).

        Returns:
            The path the registry was written to.
        """
        target = registry_file or (
            (self.skills_dir / "registry.json") if self.skills_dir else Path("registry.json")
        )
        payload = {
            "version": 1,
            "skills": {
                skill_id: self._metadata_to_dict(meta)
                for skill_id, meta in self._skills.items()
            },
        }
        await asyncio.to_thread(target.write_text, json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Saved %d skills to %s", len(self._skills), target)
        return target

    async def load(self, registry_file: Path) -> int:
        """Load the registry from a JSON file produced by :meth:`save`.

        Returns:
            Number of skills loaded.

        Raises:
            SkillRegistryError: If the file is missing or malformed.
        """
        if not await asyncio.to_thread(registry_file.exists):
            raise SkillRegistryError(f"registry file {registry_file} does not exist")
        try:
            text = await asyncio.to_thread(registry_file.read_text, encoding="utf-8")
            payload = json.loads(text)
            skills = payload["skills"]
            metadata = [self._metadata_from_dict(skills[key]) for key in sorted(skills)]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SkillRegistryError(f"malformed registry file {registry_file}: {exc}") from exc
        for item in metadata:
            self.register(item)
        logger.info("Loaded %d skills from %s", len(metadata), registry_file)
        return len(metadata)

    # --- Serialization helpers ---------------------------------------------------

    @staticmethod
    def _metadata_to_dict(meta: SkillMetadata) -> dict[str, Any]:
        return {
            "id": meta.id,
            "name": meta.name,
            "version": meta.version,
            "description": meta.description,
            "path": str(meta.path),
            "frontmatter": meta.frontmatter.model_dump(mode="json"),
            "loaded_at": meta.loaded_at.isoformat(),
        }

    @staticmethod
    def _metadata_from_dict(data: dict[str, Any]) -> SkillMetadata:
        return SkillMetadata(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data["description"],
            path=Path(data["path"]),
            frontmatter=SkillFrontmatter(**data["frontmatter"]),
            loaded_at=datetime.fromisoformat(data["loaded_at"]),
        )

"""Plugin registry with autodiscovery for JARVIS-OS skills.

Scans ``jarvis_os/skills`` for ``plugin.py`` files and registers
``BaseSkill`` subclasses automatically.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import BaseSkill, SkillPermission

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry for skill plugins with filesystem autodiscovery."""

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    async def register(self, skill: BaseSkill) -> None:
        """Register a skill instance."""
        await skill.load()
        self._skills[skill.name] = skill
        logger.debug("Registered skill plugin %s", skill.name)

    async def unregister(self, name: str) -> None:
        """Unregister a skill by name."""
        skill = self._skills.pop(name, None)
        if skill is not None:
            await skill.unload()
            logger.debug("Unregistered skill plugin %s", name)

    def get(self, name: str) -> BaseSkill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[dict[str, Any]]:
        """List all registered skills with metadata."""
        return [
            {
                "name": skill.name,
                "version": skill.version,
                "permissions": [p.value for p in skill.permissions],
                "schema": skill.get_schema(),
            }
            for skill in self._skills.values()
        ]

    async def discover_and_load(self, skills_dir: str | Path) -> None:
        """Scan a directory for ``plugin.py`` files and register found skills."""
        skills_path = Path(skills_dir)
        if not skills_path.is_dir():
            logger.warning("Skills directory %s does not exist", skills_path)
            return

        for plugin_file in sorted(skills_path.rglob("plugin.py")):
            await self._load_plugin_from_file(plugin_file)

    async def _load_plugin_from_file(self, path: Path) -> None:
        """Import a plugin module and register any ``BaseSkill`` subclasses."""
        try:
            module_name = f"jarvis_os.skills.{path.parent.name}.plugin"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseSkill)
                    and attr is not BaseSkill
                ):
                    try:
                        skill = attr()  # type: ignore[call-arg]
                    except TypeError:
                        continue
                    await self.register(skill)
        except Exception as exc:  # pragma: no cover - safety net
            logger.warning("Failed to load plugin from %s: %s", path, exc)

"""Base skill plugin interface for JARVIS-OS.

Defines the contract that all skill plugins must implement.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SkillPermission(Enum):
    """Permission types for skill operations."""

    READ_VAULT = "read_vault"
    WRITE_VAULT = "write_vault"
    READ_METRICS = "read_metrics"
    EXECUTE_COMMANDS = "execute_commands"
    MANAGE_LOCALSTACK = "manage_localstack"
    MANAGE_DOCKER = "manage_docker"


class BaseSkill(ABC):
    """Abstract base class for all JARVIS-OS skill plugins.

    Provides a standard lifecycle and interface for skill discovery,
    validation, execution, and health checking.
    """

    def __init__(
        self,
        name: str = "",
        version: str = "0.0.0",
        permissions: list[SkillPermission] | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.permissions = permissions or []
        self._loaded = False

    async def load(self) -> None:
        """Initialize the skill (load configs, connect to services, etc.)."""
        self._loaded = True
        logger.debug("Skill %s loaded", self.name)

    async def unload(self) -> None:
        """Clean up resources when the skill is unloaded."""
        self._loaded = False
        logger.debug("Skill %s unloaded", self.name)

    @abstractmethod
    async def execute(self, operation: str, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Execute a skill operation.

        Args:
            operation: The operation name (e.g., 'create_note', 'get_metrics').
            parameters: Operation-specific parameters.
            context: Runtime context (user_id, session_id, timeouts, etc.).

        Returns:
            A dict with at least ``status`` and ``result`` or ``message``.
        """
        ...

    @abstractmethod
    def get_schema(self) -> dict[str, Any]:
        """Return the JSON Schema describing available operations and parameters."""
        ...

    def validate_permission(self, permission: SkillPermission) -> bool:
        """Check if this skill has the requested permission."""
        return permission in self.permissions

    @property
    def is_loaded(self) -> bool:
        """Whether the skill has been loaded."""
        return self._loaded

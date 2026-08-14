"""Skill resolution for the orchestrator pipeline.

Implements ``RF-ORCH-02``: resolve the best matching skill by querying the
``SkillRegistry`` capabilities first, then falling back to a keyword search
across skill names and descriptions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.models import SkillMetadata
from jarvis_os.skills.registry import SkillRegistry

from jarvis_os.orchestrator_impl.errors import SkillResolutionError

logger = logging.getLogger(__name__)


@dataclass
class ResolvedSkill:
    """Outcome of skill resolution.

    Attributes:
        skill: The matched skill metadata, or ``None`` when unresolved.
        confidence: Match score in ``[0.0, 1.0]``.
        source: How the skill was found: ``capability``, ``keyword``, or
            ``opencode``.
    """

    skill: SkillMetadata | None = None
    confidence: float = 0.0
    source: str = ""


class SkillResolver:
    """Resolve an intent to the best available skill.

    Resolution order:
    1. Registry capability lookup (exact match on ``namespace.action``).
    2. Keyword fallback: score all registered skills by name/description
       overlap with the original text.
    3. OpenCode fallback: return ``None`` so the caller can delegate to
       ``OpenCodeClient``.

    Args:
        registry: Populated ``SkillRegistry`` instance.
        loader: ``SkillLoader`` for on-demand disk fallback when the
            registry is empty.
    """

    def __init__(
        self, registry: SkillRegistry, loader: SkillLoader
    ) -> None:
        self._registry = registry
        self._loader = loader

    def resolve(self, intent: str, text: str) -> ResolvedSkill:
        """Return the best skill for ``intent``.

        Args:
            intent: Capability string, e.g. ``obsidian.create``.
            text: Original user text for keyword fallback.

        Returns:
            ``ResolvedSkill`` with the matched skill or ``None``.
        """
        # 1. Capability-first lookup in registry
        capabilities = self._registry.find_by_capability(intent)
        if capabilities:
            skill = capabilities[0]
            logger.debug("Resolved %s via capability → %s", intent, skill.id)
            return ResolvedSkill(
                skill=skill, confidence=1.0, source="capability"
            )

        # 2. Keyword fallback across registered skill names and descriptions
        text_terms = set(text.lower().split())
        best: ResolvedSkill = ResolvedSkill()
        for skill in self._registry.list_all():
            haystack = f"{skill.name} {skill.description} {skill.id}".lower()
            matches = text_terms & set(haystack.split())
            if not matches:
                continue
            score = len(matches) / max(len(text_terms), 1)
            if score > best.confidence:
                best = ResolvedSkill(
                    skill=skill, confidence=score, source="keyword"
                )

        if best.skill is not None:
            logger.debug(
                "Resolved %s via keyword → %s (score=%.2f)",
                intent,
                best.skill.id,
                best.confidence,
            )
            return best

        # 3. No match — caller should route to OpenCode or return 404
        logger.debug("No skill resolved for intent %s", intent)
        return ResolvedSkill()

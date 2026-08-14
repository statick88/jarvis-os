"""Rule-based intent analysis for JARVIS-OS.

Implements ``RF-ORCH-01``: classify user intent using deterministic keyword
and capability-pattern matching without any LLM dependency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """Outcome of intent classification.

    Attributes:
        intent: Detected capability, e.g. ``obsidian.create`` or ``unknown``.
        confidence: Score in ``[0.0, 1.0]`` indicating classification certainty.
        entities: Optional extracted entities (e.g. skill name, action).
    """

    intent: str = "unknown"
    confidence: float = 0.0
    entities: dict[str, Any] = field(default_factory=dict)


class IntentAnalyzer:
    """Rule-based intent classifier.

    Maps free-form text to a capability string (``namespace.action``) by
    scanning for known keywords and capability patterns.  Returns ``unknown``
    with ``confidence=0.0`` when no match is found.

    Args:
        capability_map: Optional mapping of capability → list of trigger
            keywords.  When omitted, a conservative default map is used.
    """

    _DEFAULT_MAP: dict[str, list[str]] = {
        "obsidian.create_note": ["crear nota", "create note", "nueva nota", "new note"],
        "obsidian.read_note": ["leer nota", "read note", "buscar nota", "search note"],
        "obsidian.search_vault": ["buscar vault", "search vault"],
        "metricas.collect": ["métricas del sistema", "system metrics", "cpu", "ram"],
        "metricas.report": ["reporte métricas", "metrics report"],
        "metricas.docker_stats": ["docker stats", "contenedores"],
        "metricas.host_stats": ["host stats", "máquina"],
        "plan.create": ["crear plan", "create plan", "plan diario", "daily plan"],
        "plan.read": ["leer plan", "read plan", "ver plan"],
        "tendencias.fetch": ["tendencias", "trends", "fetch trends"],
        "tendencias.analyze": ["analizar tendencias", "analyze trends"],
        "bandeja.capture": ["capturar", "capture", "guardar en bandeja"],
        "boveda.search": ["buscar en vault", "search vault", "buscar bóveda"],
    }

    def __init__(
        self, capability_map: dict[str, list[str]] | None = None
    ) -> None:
        self._map = capability_map if capability_map is not None else dict(
            self._DEFAULT_MAP
        )
        self._keywords: dict[str, str] = {}
        for capability, keywords in self._map.items():
            for kw in keywords:
                self._keywords[kw.lower()] = capability

    def classify(self, text: str) -> IntentResult:
        """Classify ``text`` into a capability intent.

        Args:
            text: Raw user input to classify.

        Returns:
            ``IntentResult`` with the best-matching intent and confidence.
        """
        if not text or not text.strip():
            return IntentResult(intent="unknown", confidence=0.0)

        normalized = text.lower().strip()
        best_intent = "unknown"
        best_confidence = 0.0
        entities: dict[str, Any] = {}

        text_words = set(normalized.split())

        # Exact keyword hit (highest confidence)
        if normalized in self._keywords:
            best_intent = self._keywords[normalized]
            best_confidence = 1.0
        else:
            # Word-overlap match: all words of the keyword must appear in text
            for keyword, capability in self._keywords.items():
                keyword_words = set(keyword.split())
                if keyword_words.issubset(text_words):
                    score = len(keyword_words) / max(len(text_words), 1)
                    if score > best_confidence:
                        best_confidence = score
                        best_intent = capability
                        entities["matched_keyword"] = keyword

        # Capability pattern (e.g. "skill.xxx" already in text)
        cap_match = re.search(r"\b([a-z]+\.[a-z_]+)\b", normalized)
        if cap_match:
            candidate = cap_match.group(1)
            if candidate in self._map:
                best_intent = candidate
                best_confidence = max(best_confidence, 0.9)
                entities["capability_pattern"] = candidate

        # Clamp confidence to [0, 1]
        best_confidence = max(0.0, min(1.0, best_confidence))

        # Threshold: only return known intents above 0.2 confidence
        if best_confidence < 0.2:
            best_intent = "unknown"
            best_confidence = 0.0

        logger.debug(
            "Classified %r → %s (confidence=%.2f)",
            text,
            best_intent,
            best_confidence,
        )
        return IntentResult(
            intent=best_intent, confidence=best_confidence, entities=entities
        )

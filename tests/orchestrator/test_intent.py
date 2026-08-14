"""Tests for ``jarvis_os.orchestrator.intent``."""

from __future__ import annotations

import pytest

from jarvis_os.orchestrator_impl.intent import IntentAnalyzer, IntentResult


class TestIntentResult:
    def test_defaults(self) -> None:
        result = IntentResult()
        assert result.intent == "unknown"
        assert result.confidence == 0.0
        assert result.entities == {}


class TestIntentAnalyzer:
    def test_exact_keyword_match(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("crear nota")
        assert result.intent == "obsidian.create_note"
        assert result.confidence == 1.0

    def test_unknown_input(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("xyzzy nonsense")
        assert result.intent == "unknown"
        assert result.confidence == 0.0

    def test_substring_match(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("por favor crear una nota nueva")
        assert result.intent == "obsidian.create_note"
        assert result.confidence > 0.0
        assert result.confidence < 1.0

    def test_capability_pattern(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("ejecutar obsidian.create_note ahora")
        assert result.intent == "obsidian.create_note"
        assert result.confidence >= 0.9
        assert result.entities.get("capability_pattern") == "obsidian.create_note"

    def test_empty_string(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("")
        assert result.intent == "unknown"
        assert result.confidence == 0.0

    def test_whitespace_only(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("   ")
        assert result.intent == "unknown"
        assert result.confidence == 0.0

    def test_custom_capability_map(self) -> None:
        custom_map = {"custom.do": ["haz algo", "do something"]}
        analyzer = IntentAnalyzer(capability_map=custom_map)
        result = analyzer.classify("haz algo")
        assert result.intent == "custom.do"
        assert result.confidence == 1.0

    def test_os_metrics(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("muestra las métricas del sistema")
        assert result.intent == "metricas.collect"
        assert result.confidence >= 0.5

    def test_devsecops_containers(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("lista los contenedores docker")
        assert result.intent == "metricas.docker_stats"
        assert result.confidence > 0.0

    def test_tendencias_fetch(self) -> None:
        analyzer = IntentAnalyzer()
        result = analyzer.classify("obtener tendencias")
        assert result.intent == "tendencias.fetch"
        assert result.confidence >= 0.5

    def test_low_confidence_returns_unknown(self) -> None:
        """Short or ambiguous text with weak keyword overlap must return unknown."""
        analyzer = IntentAnalyzer()
        result = analyzer.classify("la")
        assert result.intent == "unknown"
        assert result.confidence == 0.0

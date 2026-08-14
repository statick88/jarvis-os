"""Tests for ``jarvis_os.orchestrator_impl`` package imports."""

from __future__ import annotations

import jarvis_os.orchestrator_impl as orch


def test_package_exports() -> None:
    assert hasattr(orch, "IntentAnalyzer")
    assert hasattr(orch, "IntentResult")
    assert hasattr(orch, "SkillResolver")
    assert hasattr(orch, "ResolvedSkill")
    assert hasattr(orch, "OrchestratorError")
    assert hasattr(orch, "IntentAnalysisError")
    assert hasattr(orch, "SkillResolutionError")
    assert hasattr(orch, "SkillExecutionPipelineError")

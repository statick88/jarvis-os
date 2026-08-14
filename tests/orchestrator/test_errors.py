"""Tests for ``jarvis_os.orchestrator.errors``."""

from __future__ import annotations

import pytest

from jarvis_os.orchestrator_impl.errors import (
    IntentAnalysisError,
    OrchestratorError,
    SkillExecutionPipelineError,
    SkillResolutionError,
)


class TestOrchestratorError:
    def test_base_defaults(self) -> None:
        err = OrchestratorError()
        assert err.status_code == 500
        assert err.detail == ""
        assert str(err) == ""

    def test_base_with_detail(self) -> None:
        err = OrchestratorError("something went wrong")
        assert err.status_code == 500
        assert err.detail == "something went wrong"
        assert str(err) == "something went wrong"

    def test_repr(self) -> None:
        err = OrchestratorError("boom")
        assert repr(err) == "OrchestratorError('boom')"


class TestIntentAnalysisError:
    def test_status_code(self) -> None:
        err = IntentAnalysisError("bad input")
        assert err.status_code == 400
        assert err.detail == "bad input"

    def test_is_orchestrator_error(self) -> None:
        err = IntentAnalysisError("x")
        assert isinstance(err, OrchestratorError)


class TestSkillResolutionError:
    def test_status_code(self) -> None:
        err = SkillResolutionError("not found")
        assert err.status_code == 404

    def test_is_orchestrator_error(self) -> None:
        err = SkillResolutionError("x")
        assert isinstance(err, OrchestratorError)


class TestSkillExecutionPipelineError:
    def test_status_code(self) -> None:
        err = SkillExecutionPipelineError("exec failed")
        assert err.status_code == 422

    def test_is_orchestrator_error(self) -> None:
        err = SkillExecutionPipelineError("x")
        assert isinstance(err, OrchestratorError)

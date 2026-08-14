"""Structured exceptions for the orchestrator pipeline.

All errors map to HTTP status codes so FastAPI can return consistent
responses without ad-hoc exception handling in route handlers.
"""

from __future__ import annotations

from typing import Any


class OrchestratorError(Exception):
    """Base error for all orchestrator failures.

    Attributes:
        status_code: HTTP status code to return (default 500).
        detail: Human-readable explanation of the failure.
    """

    status_code: int = 500
    detail: str = ""

    def __init__(self, detail: str = "", **kwargs: Any) -> None:
        super().__init__(detail)
        if detail:
            self.detail = detail

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.detail!r})"


class IntentAnalysisError(OrchestratorError):
    """Raised when intent classification fails or input is invalid."""

    status_code: int = 400


class SkillResolutionError(OrchestratorError):
    """Raised when no skill can resolve the given intent."""

    status_code: int = 404


class SkillExecutionPipelineError(OrchestratorError):
    """Raised when a skill execution step fails (422)."""

    status_code: int = 422

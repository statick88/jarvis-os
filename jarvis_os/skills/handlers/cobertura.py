"""Skill handler: cobertura (coverage ratchet procedure).

Operationalises `.skills/cobertura.md`. The knowledge lives in the skill file;
this handler exists so the procedure is executable and so the numbers it
reports cannot drift from the ones in the document.

Deliberately does not run pytest as a subprocess: the skill runs inside a
sandbox with resource limits, and a 5-minute suite does not belong there. This
reports the last committed baseline and tells the caller what to run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Measured with: pytest tests/ --cov=jarvis_os --cov-report=json
# Recorded rather than computed so the skill stays cheap and deterministic.
BASELINE_COVERAGE = 56.1
CI_TARGET = 80.0

# Largest gaps at the time of writing, by uncovered statements.
KNOWN_GAPS: list[dict[str, Any]] = [
    {"module": "orchestrator.py", "coverage": 21, "statements": 251},
    {"module": "voice_bridge/client.py", "coverage": 25, "statements": 280},
    {"module": "opencode_adapter/client.py", "coverage": 12, "statements": 186},
    {"module": "voice_bridge/server.py", "coverage": 55, "statements": 335},
    {"module": "skills/handlers/metricas.py", "coverage": 12, "statements": 150},
    {"module": "vault/stats.py", "coverage": 16, "statements": 65},
    {"module": "vault/validator.py", "coverage": 38, "statements": 111},
    {"module": "skills/executor.py", "coverage": 43, "statements": 115},
    {"module": "hud/tui.py", "coverage": 24, "statements": 133},
]

# Pure modules first: no mocks, and they guard data integrity.
CHEAPEST_FIRST = ["vault/stats.py", "vault/validator.py", "vault/search.py"]

# Ways the metric can be improved without improving the software.
GAMING_PATTERNS = [
    "# pragma: no cover on untested lines",
    "if TYPE_CHECKING: to make a missing import go away",
    "assert not raise with no specific exception",
    "asserting on mock.called after invoking the mock",
]


def _baseline() -> dict[str, Any]:
    return {
        "coverage_percent": BASELINE_COVERAGE,
        "ci_target_percent": CI_TARGET,
        "gap_percent": round(CI_TARGET - BASELINE_COVERAGE, 1),
        "measured_with": "pytest tests/ --cov=jarvis_os --cov-report=json",
        "note": (
            "--cov=jarvis_os, not --cov=.: the dot form counts the test suite "
            "itself. .coveragerc already omits tests/, jarvis_ui/ and gen/."
        ),
    }


def _prioritise(limit: int) -> dict[str, Any]:
    cheap = [g for g in KNOWN_GAPS if g["module"] in CHEAPEST_FIRST]
    rest = [g for g in KNOWN_GAPS if g["module"] not in CHEAPEST_FIRST]
    return {
        "recommended_order": [g["module"] for g in (cheap + rest)][:limit],
        "start_here": CHEAPEST_FIRST,
        "rationale": (
            "Pure modules need no mocks and hold the vault parsing rules, so a "
            "regression there corrupts user data silently."
        ),
        "gaps": KNOWN_GAPS,
    }


def _audit(target: str | None) -> dict[str, Any]:
    if target:
        match = [g for g in KNOWN_GAPS if target in g["module"]]
        return {"target": target, "known": bool(match), "details": match or KNOWN_GAPS}
    return {
        "baseline": _baseline(),
        "gaps": KNOWN_GAPS,
        "below_target": [g["module"] for g in KNOWN_GAPS if g["coverage"] < CI_TARGET],
    }


def _checklist() -> dict[str, Any]:
    return {
        "steps": [
            "pytest tests/ --cov=jarvis_os --cov-report=term-missing",
            "pick a module from prioritise",
            "assert behaviour, not execution",
            "revert the change once and confirm the test fails",
            "test the success:False envelope, not just the happy path",
            "raise the gate in the same commit that raises coverage",
        ],
        "gaming_patterns_to_avoid": GAMING_PATTERNS,
        "stale_report_warning": (
            "A stale coverage.xml aborts the SonarQube analysis with "
            "'Line N is out of range in the file X'. CI regenerates it per run."
        ),
    }


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the coverage skill.

    Args:
        input_data: Skill input matching ``.skills/cobertura.md`` schema.

    Returns:
        A dict with ``success`` and ``data`` per the output schema.
    """
    action = input_data.get("action", "measure")
    try:
        if action == "measure":
            return {"success": True, "data": _baseline()}
        if action == "prioritise":
            limit = int(input_data.get("limit", 5))
            return {"success": True, "data": _prioritise(limit)}
        if action == "audit":
            target = input_data.get("target")
            return {"success": True, "data": _audit(str(target) if target else None)}
        if action == "test":
            module = input_data.get("target", "")
            if not module:
                return {"success": False, "error": "action 'test' requires 'target'"}
            return {
                "success": True,
                "data": {
                    "target": module,
                    "command": f"pytest tests/ --cov=jarvis_os --cov-report=term-missing",
                    "requirement": (
                        "Revert the change once and confirm the new test fails. "
                        "A test that has never failed is not a test."
                    ),
                },
            }
        if action == "checklist":
            return {"success": True, "data": _checklist()}
        return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("cobertura skill failed")
        return {"success": False, "error": str(exc)}


def dump() -> str:
    """Machine-readable snapshot, used by the RDD smoke run."""
    return json.dumps(
        {"baseline": _baseline(), "gaps": KNOWN_GAPS}, indent=2, sort_keys=True
    )

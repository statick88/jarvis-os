"""Skill handler: verificar_rdd (RDD verification procedure).

Operationalises `.skills/verificar-rdd.md`. Unlike the other procedure skills
this one actually touches the receipt chain, because verifying the chain is the
whole point and reading recorded numbers would be circular.

It never runs pytest as a subprocess: a five-minute suite does not belong in a
sandboxed skill. It verifies what the receipts already record.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from jarvis_os.receipt import ReceiptChain, ReceiptChainError

logger = logging.getLogger(__name__)

MIN_SAMPLES = 5  # mirrors jarvis_os.policy.MIN_SAMPLES

# The limit that gets misread. A verified receipt proves the executor
# completed; it does not prove the handler returned success.
SIGNAL_LIMITS = [
    "A green receipt means the executor completed, not that the handler "
    "succeeded. plan.py recorded usable:true while action='read', the default, "
    "was raising NameError and the handler returned success:False.",
    "Always assert the handler envelope: result['success'] is True.",
    "Latency spread across skills is a fact about the skills, not a defect in "
    "the chain: 0.3 ms (skill-bfla_idor) to 34.5 s (skill.tendencias).",
    "If the chain verifies but behaviour is wrong, the harness is wrong, not "
    "the chain. A receipt faithfully records whatever was measured.",
]


def _root(input_data: dict[str, Any]) -> Path:
    configured = input_data.get("receipts_dir") or os.getenv("JARVIS_RECEIPTS_DIR")
    return Path(configured or "receipts")


def _verify(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {
            "root": str(root),
            "verified": False,
            "reason": f"no receipt root at {root}",
            "hint": "run a skill first, or set JARVIS_RECEIPTS_DIR",
        }
    chain = ReceiptChain(root)
    try:
        result = chain.verify()
    except ReceiptChainError as exc:
        return {"root": str(root), "verified": False, "error": str(exc)}
    return {"root": str(root), "verified": True, "detail": _jsonable(result)}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _policy(root: Path) -> dict[str, Any]:
    """Read the policy signal without activating it.

    Shadow mode is the default, so this reports the ranking without letting it
    steer anything.
    """
    from jarvis_os.policy import MIN_SAMPLES as POLICY_MIN_SAMPLES
    from jarvis_os.policy import collect_stats, dump_stats, policy_mode, score_for

    mode = policy_mode()
    stats = collect_stats(root)
    # ToolStats already computes usable, which folds in the MIN_SAMPLES floor,
    # so use it rather than re-deriving the threshold here.
    scored = {
        skill_id: {
            "score": score_for(stats, skill_id),
            "runs": s.runs,
            "usable": s.usable,
            "p95_ms": round(s.p95_ms, 2),
            "failure_rate": round(s.failure_rate, 4),
        }
        for skill_id, s in sorted(stats.items())
    }
    return {
        "mode": mode,
        "steering": mode == "active",
        "min_samples": POLICY_MIN_SAMPLES,
        "sample_note": (
            f"A skill needs {POLICY_MIN_SAMPLES} runs before its score counts; "
            "below that it stays neutral regardless of latency."
        ),
        "scored": scored,
        "dump": dump_stats(root),
    }


def _interpret() -> dict[str, Any]:
    return {
        "limits": SIGNAL_LIMITS,
        "completion_checklist": [
            "skill exercised with a real input, not a stub",
            "result['success'] is True asserted on the handler envelope",
            "ReceiptChain.verify() passes",
            "error and skipped_* fields inspected, not just the happy path",
            "policy stats read and sample count at or above 5",
            "for a behavioural change, the test was reverted once to fail",
        ],
    }


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the RDD verification skill.

    Args:
        input_data: Skill input matching ``.skills/verificar-rdd.md`` schema.

    Returns:
        A dict with ``success`` and ``data`` per the output schema.
    """
    action = input_data.get("action", "verify")
    root = _root(input_data)
    try:
        if action == "verify":
            data = _verify(root)
            # verified=False is a legitimate finding, not a handler failure.
            return {"success": True, "data": data}
        if action == "policy":
            return {"success": True, "data": _policy(root)}
        if action == "interpret":
            return {"success": True, "data": _interpret()}
        if action == "run":
            return {
                "success": True,
                "data": {
                    "note": "receipts are written by SkillExecutor.execute, not here",
                    "harness": (
                        "SkillExecutor(SkillRegistry()).execute(<skill_id>, "
                        "{'action': ..., 'context': {'vault_path': ...}})"
                    ),
                    "warning": (
                        "Pass context.vault_path explicitly. Without it the "
                        "handler falls back to /app/vault, which does not exist "
                        "on a workstation and surfaces as a confusing "
                        "FileNotFoundError."
                    ),
                },
            }
        if action == "checklist":
            return {"success": True, "data": _interpret()}
        return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("verificar_rdd skill failed")
        return {"success": False, "error": str(exc)}


def dump() -> str:
    """Machine-readable snapshot of the verification contract."""
    return json.dumps(
        {"root": str(_root({})), "min_samples": MIN_SAMPLES, "limits": SIGNAL_LIMITS},
        indent=2,
        sort_keys=True,
    )

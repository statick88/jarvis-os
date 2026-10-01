"""ODD adapter: turn a ``SkillExecutor`` run into a Receipt.

This is the only module that bridges the skills package and the receipt store.
It is intentionally defensive: an audit failure must never abort the operation
being audited, so :func:`record_execution` swallows its own errors and reports
``None``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from jarvis_os.receipt import (
    Receipt,
    ReceiptChain,
    allowlisted_inputs,
    run_directory,
    summarize_output,
    utcnow_iso,
)

logger = logging.getLogger(__name__)

#: Where receipts land. Overridable so tests never touch the real directory.
RECEIPTS_ROOT = Path("receipts")

# Map the executor's own status onto the receipt's closed vocabulary.
#
# Keyed by the *string* value rather than by ExecutionStatus, and deliberately
# without importing jarvis_os.skills: the skills package imports this module, so
# importing back would be a cycle, and the receipt layer is meant to be the
# lower-level primitive that skills depends on. ExecutionStatus is a StrEnum, so
# enum members compare equal to their value.
_STATUS_MAP: dict[str, str] = {
    "success": "success",
    "failed": "failed",
    "timeout": "timeout",
}


def receipts_root(base: Path | str | None = None) -> Path:
    return Path(base) if base is not None else RECEIPTS_ROOT


def record_execution(
    *,
    skill_id: str,
    input_data: dict[str, Any],
    result: Any,
    started: float,
    tool_version: str | None = None,
    base: Path | str | None = None,
    trace_id: str | None = None,
) -> Receipt | None:
    """Persist one receipt for a finished execution.

    Args:
        skill_id: Identifier of the skill that ran.
        input_data: Raw input payload. Only allowlisted keys are persisted.
        result: A ``SkillExecutionResult`` (duck-typed: any object with
            ``status``/``output``/``error``/``duration_ms`` works).
        started: ``time.monotonic()`` reading taken before the run.
        tool_version: Optional version string from the skill frontmatter.
        base: Receipts root override, for tests.
        trace_id: Attach the receipt to an existing trace.

    Returns:
        The sealed :class:`Receipt`, or ``None`` if the audit could not be
        written. Never raises: the caller is a runtime path, not a critical
        transaction.
    """
    try:
        duration = getattr(result, "duration_ms", None)
        if not duration:
            duration = (time.monotonic() - started) * 1000.0

        raw_status = getattr(result, "status", None)
        # StrEnum members compare equal to their string value; a duck-typed
        # result may already carry a plain string. Anything unrecognized is an
        # error rather than a silent success.
        status = _STATUS_MAP.get(str(raw_status), "error")
        output = getattr(result, "output", None)
        error = getattr(result, "error", None)

        receipt = Receipt(
            tool_name=skill_id,
            tool_version=tool_version,
            input_sanitized=allowlisted_inputs(input_data or {}),
            output_summary=summarize_output(output),
            error=error if error is None else str(error)[:1024],
            execution_time_ms=round(float(duration), 3),
            status=status,  # type: ignore[arg-type]
            started_at=utcnow_iso(),
            completed_at=utcnow_iso(),
        )
        if trace_id:
            receipt.trace_id = trace_id

        chain = ReceiptChain(run_directory(receipts_root(base)))
        return chain.append(receipt)
    except Exception:
        logger.warning("receipt emission failed for %s; execution continues", skill_id,
                       exc_info=True)
        return None

"""Shared test configuration.

Two things every test run needs and that individual test modules should not
have to remember:

1. **Receipt isolation.** ``SkillExecutor.execute()`` emits a receipt on every
   run, and the default receipts root is repository-relative. Without this
   redirect, running the suite litters ``./receipts`` and the audit trail
   becomes a mix of test and real runs.
2. **The plugin version is not the environment version.** Tests assert against
   the local checkout, not against whatever happens to be importable.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True, scope="session")
def _isolate_receipts():
    """Point the receipts root at a throwaway directory for the whole session."""
    from jarvis_os import odd_receipts

    with tempfile.TemporaryDirectory(prefix="jarvis-test-receipts-") as tmp:
        original = odd_receipts.RECEIPTS_ROOT
        odd_receipts.RECEIPTS_ROOT = Path(tmp)
        os.environ.setdefault("JARVIS_RECEIPTS_DIR", tmp)
        try:
            yield Path(tmp)
        finally:
            odd_receipts.RECEIPTS_ROOT = original


@pytest.fixture(autouse=True)
def _no_sleep_patching_leak():
    """Guard against a monkeypatched asyncio.sleep escaping its test.

    Several tests in this suite patch ``asyncio.sleep`` to drive infinite
    loops. A leaked patch would make unrelated timing-sensitive tests hang or
    flake, so the module attribute is snapshotted and restored.
    """
    import asyncio

    original = asyncio.sleep
    yield
    asyncio.sleep = original

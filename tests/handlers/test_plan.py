"""Regression tests for the `plan` handler.

The ``read`` and ``list`` branches called ``_read(...)``, which does not exist.
The function is named ``_read_plan``. Because ``action`` defaults to ``"read"``,
the most common call into this skill -- ``plan.run({"context": ...})`` with no
action at all -- raised ``NameError`` and returned
``{"success": False, "error": "name '_read' is not defined"}``.

The handler swallows exceptions into a ``success: False`` envelope, so the bug
was silent: nothing crashed, and the skill just always reported failure. The
receipt chain recorded the run as usable because the executor itself completed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis_os.skills.handlers import plan


def _ctx(vault: Path) -> dict[str, Any]:
    return {"context": {"vault_path": str(vault)}}


class TestReadAction:
    def test_default_action_is_read_and_must_work(self, tmp_path: Path) -> None:
        """No 'action' key at all: the default branch must not raise."""
        result = plan.run(_ctx(tmp_path))

        assert result["success"] is True, result.get("error")
        assert "error" not in result

    def test_explicit_read_action(self, tmp_path: Path) -> None:
        result = plan.run({"action": "read", **_ctx(tmp_path)})

        assert result["success"] is True, result.get("error")

    def test_list_action(self, tmp_path: Path) -> None:
        """On a fresh vault, read/list return the *creation* envelope, because
        _read_plan delegates to _create when the file is absent. See
        test_read_returns_two_different_shapes for the contract problem this
        exposes."""
        result = plan.run({"action": "list", **_ctx(tmp_path)})

        assert result["success"] is True, result.get("error")
        assert "is not defined" not in str(result.get("error", ""))

    def test_read_returns_two_different_shapes(self, tmp_path: Path) -> None:
        """Documented defect, pinned so it cannot change silently.

        ``_read_plan`` returns ``_create(...)`` (a success envelope) when the
        plan file is missing, and ``_parse_plan(...)`` (a bare dict with
        focus/tasks/blockers, no ``success`` key) when it exists. The same
        action therefore returns two incompatible shapes, so a caller that
        unwraps ``result["success"]`` works on the first call and raises
        KeyError on the second.

        Fixing this means choosing one envelope, which is an API decision, so
        this test records the current behaviour instead of asserting a fix.
        """
        first = plan.run({"action": "read", **_ctx(tmp_path)})
        second = plan.run({"action": "read", **_ctx(tmp_path)})

        assert "success" in first
        assert "success" not in second, (
            "if this now fails, _read_plan was unified -- update the callers "
            "and delete this note"
        )
        assert set(second) >= {"focus", "tasks", "blockers"}

    @pytest.mark.parametrize("action", ["read", "list"])
    def test_never_reports_a_nameerror(self, tmp_path: Path, action: str) -> None:
        """Guards the exact regression: an undefined helper leaking to the envelope."""
        result = plan.run({"action": action, **_ctx(tmp_path)})

        assert "is not defined" not in str(result.get("error", ""))


class TestKnownGoodActions:
    """The branches that already worked; these guard against collateral damage."""

    def test_update_rejects_the_generic_verb(self, tmp_path: Path) -> None:
        result = plan.run({"action": "update", **_ctx(tmp_path)})

        assert result["success"] is True
        assert "specific actions" in result["data"]["message"]

    def test_delete(self, tmp_path: Path) -> None:
        result = plan.run({"action": "delete", **_ctx(tmp_path)})

        assert result["success"] is True
        assert result["data"]["deleted"] is True

    def test_unknown_action_is_reported(self, tmp_path: Path) -> None:
        result = plan.run({"action": "nope", **_ctx(tmp_path)})

        assert result["success"] is False
        assert "Unknown action" in result["error"]

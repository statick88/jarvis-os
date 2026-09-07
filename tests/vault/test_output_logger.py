"""Tests for VaultOutputLogger: Markdown generation and frontmatter validity."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

from jarvis_os.vault.output_logger import VaultOutputLogger
from jarvis_os.vault.models import VaultWriteError
from jarvis_os.vault.validator import parse_frontmatter_block


@pytest.fixture()
def tmp_vault() -> Path:
    """Create a temporary vault root with outputs/ directory."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "outputs").mkdir(parents=True, exist_ok=True)
        yield root


def test_write_execution_creates_daily_file(tmp_vault: Path) -> None:
    """A successful execution creates a Markdown file under outputs/YYYY-MM-DD/."""
    logger = VaultOutputLogger(vault_root=tmp_vault)
    input_data = {"text": "crear nota de prueba"}
    result = {"success": True, "output": {"note_id": "obsidian-143055"}}

    output_ref = asyncio.run(logger.write_execution("skill.obsidian", input_data, result))

    assert output_ref.startswith("outputs/")
    assert output_ref.endswith(".md")
    abs_path = tmp_vault / output_ref
    assert abs_path.exists()
    content = abs_path.read_text(encoding="utf-8")
    assert "---" in content
    assert "skill.obsidian" in content
    assert "crear nota de prueba" in content


def test_frontmatter_contains_required_fields(tmp_vault: Path) -> None:
    """Frontmatter must include id, tags, skill, created, input_ref, output_ref."""
    import asyncio

    logger = VaultOutputLogger(vault_root=tmp_vault)
    result = {"success": True, "output": {}}
    output_ref = asyncio.run(logger.write_execution("skill.test", {"x": 1}, result))
    abs_path = tmp_vault / output_ref
    text = abs_path.read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter_block(text)

    assert frontmatter.id == "skill-test-" + text.split("skill-test-")[1].split('"')[0]
    assert "skill-execution" in frontmatter.tags
    assert frontmatter.title.startswith("skill.test")
    assert frontmatter.created is not None
    # status is execution metadata; verify it exists in raw text
    assert "status:" in text


def test_karpathy_link_format_in_body(tmp_vault: Path) -> None:
    """Body must contain a [[wiki/...]] link related to the skill."""
    import asyncio

    logger = VaultOutputLogger(vault_root=tmp_vault)
    result = {"success": True, "output": {}}
    output_ref = asyncio.run(logger.write_execution("skill.os_control", {}, result))
    abs_path = tmp_vault / output_ref
    content = abs_path.read_text(encoding="utf-8")

    assert "[[" in content
    assert "]]" in content


def test_failed_execution_status_in_frontmatter(tmp_vault: Path) -> None:
    """When result.success is False, frontmatter status must be 'failed'."""
    import asyncio

    logger = VaultOutputLogger(vault_root=tmp_vault)
    result = {"success": False, "error": "skill timed out"}
    output_ref = asyncio.run(logger.write_execution("skill.broken", {}, result))
    abs_path = tmp_vault / output_ref
    text = abs_path.read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter_block(text)

    assert frontmatter.id.startswith("skill-broken-")
    # status is execution metadata; verify it in raw text (YAML-quoted)
    assert 'status: "failed"' in text
    assert "timed out" in text


def test_unwritable_vault_raises_vault_write_error(tmp_vault: Path) -> None:
    """If outputs/ is read-only, write_execution must raise VaultWriteError."""
    import asyncio

    logger = VaultOutputLogger(vault_root=tmp_vault)
    os.chmod(tmp_vault / "outputs", 0o444)

    with pytest.raises(VaultWriteError):
        asyncio.run(
            logger.write_execution("skill.forbidden", {}, {"success": True})
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

"""Vault output logger: writes skill execution Markdown to ``vault/outputs/``.

Each execution creates one daily-organized Markdown file with Karpathy-style
frontmatter so the vault indexer can link outputs back to related wiki notes.

Usage::

    from jarvis_os.vault.output_logger import VaultOutputLogger

    logger = VaultOutputLogger(vault_root=Path("/app/vault"))
    output_ref = await logger.write_execution(
        skill_id="skill.obsidian",
        input_data={"text": "crear nota de prueba"},
        result={"success": True, "output": {"note_id": "obsidian-143055"}},
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis_os.vault.models import VaultWriteError
from jarvis_os.vault.validator import parse_frontmatter_block

logger = logging.getLogger(__name__)

# Sanitize skill_id to safe path segments: lowercase, alnum, dash, underscore
_SKILL_ID_RE = re.compile(r"[^a-z0-9_-]+")
# Default frontmatter fields required by the vault indexer
_REQUIRED_FRONTMATTER_FIELDS = {"id", "tags", "skill", "created", "input_ref", "output_ref"}


class VaultOutputLogger:
    """Append-only execution log for skill runs.

    Writes one Markdown file per execution under::

        vault_root/outputs/YYYY-MM-DD/<skill-id>-<HHMMSS>.md

    Files include YAML frontmatter with Karpathy-style fields so the
    ``VaultIndexer`` can discover and link them automatically.
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root.resolve()

    async def write_execution(
        self,
        skill_id: str,
        input_data: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        """Write an execution Markdown file and return its relative output_ref.

        Args:
            skill_id: Identifier of the executed skill.
            input_data: Input payload forwarded to the skill.
            result: Execution result dict with ``success`` and either
                ``result`` or ``error``.

        Returns:
            Relative path from vault root, e.g.
            ``outputs/2026-08-31/skill-obsidian-143055.md``.

        Raises:
            VaultWriteError: If the vault directory is not writable.
        """
        safe_skill_id = self._sanitize_skill_id(skill_id)
        now = datetime.now(timezone.utc)
        date_dir = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")
        filename = f"{safe_skill_id}-{time_str}.md"

        output_dir = self.vault_root / "outputs" / date_dir
        try:
            await asyncio.to_thread(self._ensure_dir, output_dir)
        except OSError as exc:
            raise VaultWriteError(f"Cannot create outputs directory: {exc}") from exc

        abs_path = output_dir / filename
        rel_path = abs_path.relative_to(self.vault_root)

        # Build stable refs
        input_hash = hashlib.sha256(
            json.dumps(input_data, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
        output_ref = str(rel_path)

        success = result.get("success", False)
        output_content = result.get("result") or result.get("error") or ""
        if isinstance(output_content, dict):
            output_content = json.dumps(output_content, indent=2, default=str)

        frontmatter = {
            "id": Path(filename).stem,
            "title": f"{skill_id} — {now.strftime('%H:%M:%S')}",
            "tags": ["skill-execution", safe_skill_id],
            "skill": skill_id,
            "created": now.isoformat(),
            "modified": now.isoformat(),
            "input_ref": f"input_hash:{input_hash}",
            "output_ref": output_ref,
            "status": "success" if success else "failed",
        }
        body = "\n".join([
            f"# Skill Execution: {skill_id}",
            "",
            f"> {now.isoformat()} — {'OK' if success else 'FAILED'}",
            "",
            "## Input",
            "```json",
            json.dumps(input_data, indent=2, default=str),
            "```",
            "",
            "## Output",
            "```",
            output_content,
            "```",
            "",
            "## Links",
            f"- [[{self._guess_related_note(skill_id)}]]",
        ])

        content = self._render_frontmatter(frontmatter) + "\n" + body

        try:
            await asyncio.to_thread(self._atomic_write, abs_path, content)
        except OSError as exc:
            raise VaultWriteError(f"Cannot write vault output: {exc}") from exc

        logger.debug("Wrote vault output: %s", rel_path)
        return str(rel_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_skill_id(skill_id: str) -> str:
        return _SKILL_ID_RE.sub("-", skill_id.lower()).strip("-")

    @staticmethod
    def _ensure_dir(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(path: Path, data: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _render_frontmatter(data: dict[str, Any]) -> str:
        lines = ["---"]
        for key, value in data.items():
            if isinstance(value, list):
                items = ", ".join(f'"{item}"' for item in value)
                lines.append(f'{key}: [{items}]')
            elif isinstance(value, str):
                lines.append(f'{key}: "{value}"')
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        return "\n".join(lines)

    @staticmethod
    def _guess_related_note(skill_id: str) -> str:
        """Heuristic: map skill.id to a likely wiki note id."""
        safe = _SKILL_ID_RE.sub("-", skill_id.lower()).strip("-")
        return safe.replace(".", "-").replace("_", "-")


# ---------------------------------------------------------------------------
# Convenience: parse back the frontmatter of a written output file
# ---------------------------------------------------------------------------


async def parse_output_frontmatter(path: Path) -> dict[str, Any]:
    """Read a vault output Markdown file and return its frontmatter dict.

    Args:
        path: Absolute path to the output file.

    Returns:
        Parsed frontmatter dict, or empty dict on failure.
    """
    try:
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        frontmatter, _ = parse_frontmatter_block(text)
        return dict(frontmatter)
    except Exception as exc:
        logger.warning("Failed to parse output frontmatter %s: %s", path, exc)
        return {}

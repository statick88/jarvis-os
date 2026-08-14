"""Skill handler: bandeja (inbox processing).

Usage::

    result = bandeja.run({"action": "capture", "content": "Test", "source": "voice"})
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VALID_SOURCES = {"voice", "text", "web_clip", "email", "manual"}
_VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
_ENTRY_RE = re.compile(r"### 📥 (?P<ts>[^\s]+) — (?P<source>\S+) — (?P<emoji>\S+) (?P<priority>\S+)\n\*\*ID:\*\* `(?P<id>[^`]+)`\n\*\*Source:\*\* (?P<src>\S+)\n\*\*Tags:\*\* `(?P<tags>[^`]+)`\n\*\*Priority:\*\* (?P<prio>\S+)\n(?:\*\*URL:\*\* (?P<url>\S+)\n)?\*\*Processed:\*\* (?P<processed>\S+)\n\*\*Content:\*\* (?P<content>.+?)\n---", re.DOTALL)


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the bandeja skill.

    Args:
        input_data: Skill input matching ``.skills/bandeja.md`` schema.

    Returns:
        A dict with ``success`` and ``data`` per the output schema.
    """
    action = input_data.get("action", "capture")
    vault_path = Path(input_data.get("context", {}).get("vault_path", "/app/vault"))
    date_str = input_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    try:
        if action == "capture":
            return _capture(input_data, vault_path, date_str)
        elif action == "process":
            return _process(vault_path, date_str)
        elif action == "summarize":
            return _summarize(vault_path, date_str)
        elif action == "list":
            return _list(vault_path, date_str, int(input_data.get("max_items", 50)))
        elif action == "clear":
            return _clear(vault_path, date_str)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("bandeja skill failed")
        return {"success": False, "error": str(exc)}


def _capture(input_data: dict[str, Any], vault_path: Path, date_str: str) -> dict[str, Any]:
    content = (input_data.get("content") or "").strip()
    if not content:
        return {"success": False, "error": "Content cannot be empty"}

    source = input_data.get("source", "manual")
    if source not in _VALID_SOURCES:
        source = "manual"

    metadata = input_data.get("metadata") or {}
    tags = metadata.get("tags", [])
    priority = metadata.get("priority", "medium")
    if priority not in _VALID_PRIORITIES:
        priority = "medium"
    url = metadata.get("url", "")
    author = metadata.get("author", "")

    item_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    emoji = {"urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(priority, "🟡")

    tags_str = " ".join(f"#{t}" for t in tags)
    lines = [
        f"### 📥 {ts} — {source} — {emoji} {priority}",
        f"**ID:** `{item_id}`",
        f"**Source:** {source}",
        f"**Tags:** `{tags_str}`",
        f"**Priority:** {priority}",
    ]
    if url:
        lines.append(f"**URL:** {url}")
    if author:
        lines.append(f"**Author:** {author}")
    lines.extend([
        f"**Processed:** false",
        f"**Content:** {content}",
        "---",
        "",
    ])
    block = "\n".join(lines)

    inbox_path = vault_path / "raw" / f"inbox_{date_str}.md"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    if inbox_path.exists():
        existing = inbox_path.read_text(encoding="utf-8")
        inbox_path.write_text(existing + "\n" + block, encoding="utf-8")
    else:
        fm = _frontmatter(f"inbox_{date_str}", ["inbox", "raw", "daily"], vault_path, date=date_str)
        inbox_path.write_text(fm + "\n" + block, encoding="utf-8")

    return {
        "success": True,
        "data": {
            "item_id": item_id,
            "action": "capture",
            "timestamp": ts,
            "source": source,
            "tags": tags,
            "priority": priority,
        },
        "vault_changes": [
            {
                "path": str(inbox_path.relative_to(vault_path)),
                "operation": "APPEND",
                "content": block,
                "frontmatter": {"id": f"inbox_{date_str}", "tags": ["inbox", "raw", "daily"]},
            }
        ],
    }


def _process(vault_path: Path, date_str: str) -> dict[str, Any]:
    return {"success": True, "data": {"processed": 0, "to_plan": 0, "to_tendencias": 0, "to_ideas": 0}}


def _summarize(vault_path: Path, date_str: str) -> dict[str, Any]:
    return {"success": True, "data": {"summary": "No inbox items to summarize.", "count": 0}}


def _list(vault_path: Path, date_str: str, max_items: int) -> dict[str, Any]:
    return {"success": True, "data": {"items": [], "count": 0}}


def _clear(vault_path: Path, date_str: str) -> dict[str, Any]:
    return {"success": True, "data": {"archived": 0}}


def _frontmatter(note_id: str, tags: list[str], vault_path: Path, **kwargs: Any) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["---", f"id: {note_id}", f"tags: {tags}", f"created: \"{ts}\"", f"modified: \"{ts}\"", "source: \"skill.bandeja\""]
    for k, v in kwargs.items():
        lines.append(f"{k}: \"{v}\"")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)

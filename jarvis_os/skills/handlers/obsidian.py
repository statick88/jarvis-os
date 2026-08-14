"""Skill handler: obsidian (Obsidian vault CRUD, search, summarize).

Usage::

    result = obsidian.run({"action": "create_note", "path": "notes/example.md", "title": "Example", "content": "Hello"})
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _resolve_safe_path(input_data: dict[str, Any], vault_path: Path) -> Path:
    """Resolve ``input_data['path']`` against the vault and verify containment.

    Raises :class:`ValueError` if the resolved path escapes the vault root,
    preventing path-traversal attacks (e.g. ``../../etc/passwd``).
    """
    vault_root = vault_path.resolve()
    resolved_path = (vault_root / input_data["path"]).resolve()
    if not resolved_path.is_relative_to(vault_root):
        raise ValueError(f"Path escapes vault root: {input_data['path']}")
    return resolved_path


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    action = input_data.get("action") or input_data.get("operation", "search_vault")
    vault_path = Path(input_data.get("context", {}).get("vault_path", "/app/vault"))
    vault_path = vault_path.resolve()

    try:
        if action == "create_note":
            return _create_note(input_data, vault_path)
        elif action == "read_note":
            return _read_note(input_data, vault_path)
        elif action == "update_note":
            return _update_note(input_data, vault_path)
        elif action == "delete_note":
            return _delete_note(input_data, vault_path)
        elif action == "search_vault":
            return _search_vault(input_data, vault_path)
        elif action == "append_to_note":
            return _append_to_note(input_data, vault_path)
        elif action == "summarize_note":
            return _summarize_note(input_data, vault_path)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("obsidian skill failed")
        return {"success": False, "error": str(exc)}


def _create_note(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    path = _resolve_safe_path(input_data, vault_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    title = input_data.get("title", "")
    content = input_data.get("content", "")
    tags = input_data.get("tags", [])
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tags_yaml = yaml.dump({"tags": tags}, default_flow_style=False).strip()
    frontmatter = f"---\ntitle: {title}\n{tags_yaml}\ncreated: {ts}\nmodified: {ts}\n---\n\n"
    body = f"# {title}\n\n{content}\n"
    path.write_text(frontmatter + body, encoding="utf-8")
    return {
        "success": True,
        "data": {"path": str(path.relative_to(vault_path)), "created": True, "timestamp": ts},
        "vault_changes": [{"path": str(path.relative_to(vault_path)), "operation": "CREATE", "content": frontmatter + body}],
    }


def _read_note(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    path = _resolve_safe_path(input_data, vault_path)
    if not path.exists():
        return {"success": False, "error": f"Note not found: {input_data['path']}"}
    text = path.read_text(encoding="utf-8")
    return {"success": True, "data": {"path": str(path.relative_to(vault_path)), "content": text}}


def _update_note(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    path = _resolve_safe_path(input_data, vault_path)
    if not path.exists():
        return {"success": False, "error": f"Note not found: {input_data['path']}"}
    content = input_data.get("content", "")
    path.write_text(content, encoding="utf-8")
    return {
        "success": True,
        "data": {"path": str(path.relative_to(vault_path)), "updated": True},
        "vault_changes": [{"path": str(path.relative_to(vault_path)), "operation": "UPDATE", "content": content}],
    }


def _delete_note(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    path = _resolve_safe_path(input_data, vault_path)
    if not path.exists():
        return {"success": False, "error": f"Note not found: {input_data['path']}"}
    path.unlink()
    return {"success": True, "data": {"path": str(path.relative_to(vault_path)), "deleted": True}}


def _search_vault(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    query = input_data.get("query", "").lower()
    limit = int(input_data.get("limit", 10))
    results = []
    for md_file in vault_path.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore").lower()
            if query in text:
                results.append(str(md_file.relative_to(vault_path)))
        except OSError:
            continue
        if len(results) >= limit:
            break
    return {"success": True, "data": {"matches": results, "count": len(results)}}


def _append_to_note(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    path = _resolve_safe_path(input_data, vault_path)
    if not path.exists():
        return {"success": False, "error": f"Note not found: {input_data['path']}"}
    content = input_data.get("content", "")
    separator = input_data.get("separator", "\n\n---\n\n")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{separator}{content}\n")
    return {"success": True, "data": {"appended": True, "path": str(path.relative_to(vault_path))}}


def _summarize_note(input_data: dict[str, Any], vault_path: Path) -> dict[str, Any]:
    path = _resolve_safe_path(input_data, vault_path)
    if not path.exists():
        return {"success": False, "error": f"Note not found: {input_data['path']}"}
    text = path.read_text(encoding="utf-8")
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    summary = " ".join(sentences[:3])
    return {
        "success": True,
        "data": {
            "path": str(path.relative_to(vault_path)),
            "summary": summary,
            "sentence_count": len(sentences),
        },
    }

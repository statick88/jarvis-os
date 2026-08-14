"""Obsidian vault management skill plugin."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import BaseSkill, SkillPermission

logger = logging.getLogger(__name__)


class ObsidianSkill(BaseSkill):
    """Skill for managing Obsidian vault notes."""

    def __init__(self, vault_path: str | Path = "/app/vault") -> None:
        super().__init__(name="skill-obsidian", version="1.0.0", permissions=[
            SkillPermission.READ_VAULT,
            SkillPermission.WRITE_VAULT,
        ])
        self.vault_path = Path(vault_path)

    async def load(self) -> None:
        await super().load()
        self.vault_path.mkdir(parents=True, exist_ok=True)

    async def execute(self, operation: str, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if not self.is_loaded:
            return {"status": "error", "message": "Skill not loaded"}

        try:
            if operation == "create_note":
                return await self._create_note(parameters)
            elif operation == "search_vault":
                return await self._search_vault(parameters)
            elif operation == "append_to_note":
                return await self._append_to_note(parameters)
            else:
                return {"status": "error", "message": f"Unknown operation: {operation}"}
        except Exception as exc:
            logger.exception("Obsidian skill operation failed: %s", operation)
            return {"status": "error", "message": str(exc)}

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "skill-obsidian",
            "version": self.version,
            "operations": {
                "create_note": {
                    "description": "Create a new Markdown note in the Obsidian vault",
                    "parameters": {
                        "path": {"type": "string", "required": True, "description": "Relative path from vault root"},
                        "title": {"type": "string", "required": True, "description": "Note title"},
                        "content": {"type": "string", "required": True, "description": "Markdown body content"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
                        "links": {"type": "array", "items": {"type": "string"}, "description": "Optional [[wikilinks]]"},
                    },
                },
                "search_vault": {
                    "description": "Full-text search across vault notes",
                    "parameters": {
                        "query": {"type": "string", "required": True, "description": "Search query"},
                        "limit": {"type": "integer", "default": 10, "description": "Max results"},
                    },
                },
                "append_to_note": {
                    "description": "Append content to an existing note",
                    "parameters": {
                        "path": {"type": "string", "required": True, "description": "Relative path from vault root"},
                        "content": {"type": "string", "required": True, "description": "Markdown content to append"},
                        "separator": {"type": "string", "default": "\n\n---\n\n", "description": "Optional separator"},
                    },
                },
            },
        }

    async def _create_note(self, params: dict[str, Any]) -> dict[str, Any]:
        path = self.vault_path / params["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        title = params.get("title", "")
        content = params.get("content", "")
        tags = params.get("tags", [])
        links = params.get("links", [])
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        frontmatter = f"---\ntitle: {title}\ntags: {tags}\ncreated: {ts}\nmodified: {ts}\n---\n\n"
        body = f"# {title}\n\n{content}\n"
        if links:
            body += "\n## Links\n\n" + "\n".join(f"- [[{link}]]" for link in links) + "\n"
        path.write_text(frontmatter + body, encoding="utf-8")
        return {
            "status": "success",
            "result": {"path": str(path.relative_to(self.vault_path)), "created": True, "timestamp": ts},
        }

    async def _search_vault(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "").lower()
        limit = int(params.get("limit", 10))
        results = []
        for md_file in self.vault_path.rglob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8", errors="ignore").lower()
                if query in text:
                    results.append(str(md_file.relative_to(self.vault_path)))
            except OSError:
                continue
            if len(results) >= limit:
                break
        return {"status": "success", "result": {"matches": results, "count": len(results)}}

    async def _append_to_note(self, params: dict[str, Any]) -> dict[str, Any]:
        path = self.vault_path / params["path"]
        if not path.exists():
            return {"status": "error", "message": f"Note not found: {params['path']}"}
        content = params.get("content", "")
        separator = params.get("separator", "\n\n---\n\n")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{separator}{content}\n")
        return {"status": "success", "result": {"appended": True, "path": str(path.relative_to(self.vault_path))}}

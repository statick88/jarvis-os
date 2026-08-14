"""Skill handler: boveda (Zettelkasten vault operations).

Usage::

    result = boveda.run({"action": "index"})
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from jarvis_os.vault.indexer import VaultIndexer
from jarvis_os.vault.search import VaultSearch
from jarvis_os.vault.graph import KnowledgeGraphBuilder
from jarvis_os.vault.stats import VaultStatsComputer
from jarvis_os.vault.validator import VaultValidator
from jarvis_os.vault.models import GraphFormat

logger = logging.getLogger(__name__)


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the boveda skill.

    Args:
        input_data: Skill input matching ``.skills/boveda.md`` schema.

    Returns:
        A dict with ``success`` and ``data`` per the output schema.
    """
    action = input_data.get("action", "index")
    vault_root = Path(input_data.get("context", {}).get("vault_path", "/app/vault"))

    try:
        if action == "index":
            result = asyncio.run(VaultIndexer(vault_root=vault_root).index())
            return {"success": result.success, "data": result.data, "vault_changes": [c.model_dump(mode="json") for c in result.changes]}
        elif action == "rebuild":
            result = asyncio.run(VaultIndexer(vault_root=vault_root).rebuild())
            return {"success": result.success, "data": result.data, "vault_changes": [c.model_dump(mode="json") for c in result.changes]}
        elif action == "graph":
            fmt = input_data.get("output_format", "markdown")
            builder = KnowledgeGraphBuilder(vault_root=vault_root)
            graph = asyncio.run(builder.build(max_depth=int(input_data.get("max_depth", 2))))
            export_result = asyncio.run(builder.export(graph, fmt=GraphFormat(fmt)))
            return {"success": True, "data": {"graph": graph.model_dump(mode="json"), **export_result.data}}
        elif action == "links":
            return _links(input_data, vault_root)
        elif action == "search":
            query = input_data.get("query", "")
            search = VaultSearch(vault_root=vault_root)
            result = asyncio.run(search.search(
                query,
                tags=input_data.get("tags"),
                date_from=input_data.get("date_from"),
                date_to=input_data.get("date_to"),
            ))
            return {"success": True, "data": result.data}
        elif action == "stats":
            computer = VaultStatsComputer(vault_root=vault_root)
            result = asyncio.run(computer.compute())
            return {"success": True, "data": result.data}
        elif action == "validate":
            validator = VaultValidator(vault_root=vault_root)
            result = asyncio.run(validator.validate())
            return {"success": True, "data": result.data}
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("boveda skill failed")
        return {"success": False, "error": str(exc)}


def _links(input_data: dict[str, Any], vault_root: Path) -> dict[str, Any]:
    from jarvis_os.vault.links import backlinks_for

    note_id = input_data.get("note_id", "")
    backlinks = asyncio.run(backlinks_for(note_id, vault_root))
    return {
        "success": True,
        "data": {
            "note_id": note_id,
            "incoming": [{"target": l.target, "kind": l.kind.value} for l in backlinks],
        },
    }

"""Vault statistics aggregation.

Computes per-tag, per-directory, per-date, link and orphan statistics from
the vault index.

Usage::

    from jarvis_os.vault.stats import VaultStatsComputer

    computer = VaultStatsComputer(vault_root=Path("/app/vault"))
    stats = await computer.compute()
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis_os.vault.models import (
    GraphStats,
    VaultIndex,
    VaultNote,
    VaultOperationResult,
    VaultStats,
)
from jarvis_os.vault.validator import parse_frontmatter_block

logger = logging.getLogger(__name__)


class VaultStatsComputer:
    """Aggregates vault statistics from the index.

    Args:
        vault_root: Root directory of the vault.
        index_path: Path to ``.boveda_index.json``.
    """

    def __init__(
        self,
        vault_root: Path,
        index_path: Path | None = None,
    ) -> None:
        self.vault_root = vault_root.resolve()
        self.index_path = (index_path or self.vault_root / "wiki" / ".boveda_index.json").resolve()

    async def compute(self) -> VaultOperationResult:
        """Compute full vault statistics.

        Returns:
            A :class:`VaultOperationResult` with ``vault_stats`` and
            ``graph_stats`` in ``data``.
        """
        index = await self._load_index()
        active_entries = [e for e in index.files.values() if not e.deleted]

        notes: list[VaultNote] = []
        for entry in active_entries:
            note = await self._load_note(entry.rel_path)
            if note is not None:
                notes.append(note)

        total_notes = len(notes)
        total_words = sum(n.word_count for n in notes)
        total_links = sum(len(n.explicit_links) for n in notes)

        tag_counter: Counter[str] = Counter()
        dir_counter: Counter[str] = Counter()
        year_counter: Counter[int] = Counter()
        broken_links = 0

        all_target_ids = {n.id for n in notes}
        for note in notes:
            for tag in note.tags:
                tag_counter[tag] += 1
            directory = str(Path(note.rel_path).parent)
            dir_counter[directory] += 1
            if note.frontmatter.created.year not in year_counter:
                year_counter[note.frontmatter.created.year] = 0
            year_counter[note.frontmatter.created.year] += 1
            for link in note.explicit_links:
                if link.target not in all_target_ids:
                    broken_links += 1

        orphan_notes = sum(
            1 for n in notes if not n.explicit_links and not n.implicit_links
        )

        vault_stats = VaultStats(
            total_notes=total_notes,
            total_words=total_words,
            total_links=total_links,
            broken_links=broken_links,
            orphan_notes=orphan_notes,
            notes_by_tag=dict(tag_counter.most_common(50)),
            notes_by_dir=dict(dir_counter.most_common(50)),
            notes_by_year={str(k): v for k, v in sorted(year_counter.items())},
            index_updated_at=index.updated_at,
        )

        node_count = total_notes
        edge_count = total_links
        graph_stats = GraphStats(
            node_count=node_count,
            edge_count=edge_count,
            orphan_count=orphan_notes,
            broken_link_count=broken_links,
            average_degree=(edge_count * 2 / node_count) if node_count else 0.0,
        )

        return VaultOperationResult.ok(
            {
                "vault_stats": vault_stats.model_dump(mode="json"),
                "graph_stats": graph_stats.model_dump(mode="json"),
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_index(self) -> VaultIndex:
        import json

        if not self.index_path.exists():
            return VaultIndex()
        raw = await asyncio_import().to_thread(self.index_path.read_text, encoding="utf-8")
        data = json.loads(raw)
        return VaultIndex.model_validate(data)

    async def _load_note(self, rel_path: str) -> VaultNote | None:
        abs_path = self.vault_root / rel_path
        if not abs_path.exists():
            return None
        try:
            text = await asyncio_import().to_thread(abs_path.read_text, encoding="utf-8")
            frontmatter, body = parse_frontmatter_block(text)
            return VaultNote(
                frontmatter=frontmatter,
                content=body,
                path=abs_path,
                rel_path=rel_path,
                word_count=len(body.split()),
            )
        except Exception as exc:
            logger.warning("Failed to load note %s: %s", rel_path, exc)
            return None


def asyncio_import():
    import asyncio
    return asyncio

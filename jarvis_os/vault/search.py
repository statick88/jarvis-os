"""Vault search: full-text and filtered search over indexed notes.

Usage::

    from jarvis_os.vault.search import VaultSearch

    search = VaultSearch(vault_root=Path("/app/vault"))
    results = await search.search("Kubernetes", tags=["tech"])
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from jarvis_os.vault.models import (
    MAX_SEARCH_RESULTS,
    SearchResult,
    VaultIndex,
    VaultNote,
    VaultOperationResult,
)
from jarvis_os.vault.validator import parse_frontmatter_block

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\w+", re.IGNORECASE)


class VaultSearch:
    """Search engine for the vault subsystem.

    Args:
        vault_root: Root directory of the vault.
        index_path: Path to ``.boveda_index.json`` (defaults to
            ``<vault_root>/wiki/.boveda_index.json``).
    """

    def __init__(
        self,
        vault_root: Path,
        index_path: Path | None = None,
    ) -> None:
        self.vault_root = vault_root.resolve()
        self.index_path = (index_path or self.vault_root / "wiki" / ".boveda_index.json").resolve()

    async def search(
        self,
        query: str,
        *,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = MAX_SEARCH_RESULTS,
    ) -> VaultOperationResult:
        """Search notes by query string with optional filters.

        Args:
            query: Free-text search term.
            tags: Only return notes that have at least one of these tags.
            date_from: ISO date ``YYYY-MM-DD`` inclusive lower bound on
                ``frontmatter.created``.
            date_to: ISO date ``YYYY-MM-DD`` inclusive upper bound on
                ``frontmatter.created``.
            max_results: Maximum number of results to return.

        Returns:
            A :class:`VaultOperationResult` with ``search_results`` in
            ``data``.
        """
        index = await self._load_index()
        active_entries = [e for e in index.files.values() if not e.deleted]

        terms = _TOKEN_RE.findall(query.lower())
        if not terms:
            return VaultOperationResult.ok({"search_results": []})

        results: list[SearchResult] = []
        for entry in active_entries:
            if tags and not set(tags) & set(entry.tags):
                continue
            if date_from and entry.rel_path:
                created = self._extract_date_from_path(entry.rel_path)
                if created and created < date_from:
                    continue
            if date_to and entry.rel_path:
                created = self._extract_date_from_path(entry.rel_path)
                if created and created > date_to:
                    continue

            note = await self._load_note(entry.rel_path)
            if note is None:
                continue

            score = self._score(note, terms)
            if score <= 0:
                continue

            snippet = self._snippet(note.content, terms)
            results.append(
                SearchResult(
                    id=note.id,
                    title=note.title,
                    rel_path=entry.rel_path,
                    snippet=snippet,
                    score=score,
                    tags=note.tags,
                    matched_terms=terms,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:max_results]

        return VaultOperationResult.ok(
            {"search_results": [r.model_dump(mode="json") for r in results]}
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

    @staticmethod
    def _score(note: VaultNote, terms: list[str]) -> float:
        title_lower = note.title.lower()
        content_lower = note.content.lower()
        id_lower = note.id.lower()
        tags_lower = [t.lower() for t in note.tags]

        score = 0.0
        for term in terms:
            if term in title_lower:
                score += 10.0
            if term in tags_lower:
                score += 5.0
            if term in id_lower:
                score += 3.0
            score += content_lower.count(term)
        return score

    @staticmethod
    def _snippet(content: str, terms: list[str], window: int = 100) -> str:
        lower = content.lower()
        best_pos = 0
        best_count = -1
        for term in terms:
            pos = 0
            while True:
                idx = lower.find(term, pos)
                if idx == -1:
                    break
                if idx > best_pos:
                    best_pos = idx
                pos = idx + 1

        start = max(0, best_pos - window)
        end = min(len(content), best_pos + window)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    @staticmethod
    def _extract_date_from_path(rel_path: str) -> str | None:
        import re
        match = re.search(r"(\d{4}-\d{2}-\d{2})", rel_path)
        return match.group(1) if match else None


def asyncio_import():
    import asyncio
    return asyncio

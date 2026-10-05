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
            if not self._passes_filters(entry, tags, date_from, date_to):
                continue

            note = await self._load_note(entry.rel_path)
            if note is None:
                continue

            score = self._score(note, terms)
            if score <= 0:
                continue

            results.append(
                SearchResult(
                    id=note.id,
                    title=note.title,
                    rel_path=entry.rel_path,
                    snippet=self._snippet(note.content, terms),
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

    def _passes_filters(
        self,
        entry: Any,
        tags: list[str] | None,
        date_from: str | None,
        date_to: str | None,
    ) -> bool:
        """Check tag and date filters for an index entry."""
        if tags and not set(tags) & set(entry.tags):
            return False
        if date_from and entry.rel_path:
            created = self._extract_date_from_path(entry.rel_path)
            if created and created < date_from:
                return False
        if date_to and entry.rel_path:
            created = self._extract_date_from_path(entry.rel_path)
            if created and created > date_to:
                return False
        return True

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
        """Return a window of ``content`` centred on its densest cluster of hits.

        The previous implementation computed ``max(best_pos, idx)`` over every
        occurrence, so the snippet was anchored to the *last* match in the
        document rather than the most relevant region, and a local variable
        intended to track the hit count was initialised and never updated.

        A sliding window over the sorted hit positions gives the region with the
        most matches in O(n) after the sort, and ties resolve to the earliest
        position so the output is deterministic.
        """
        lower = content.lower()
        hits = VaultSearch._find_term_hits(lower, terms)

        if not hits:
            return content[:window]

        hits.sort()
        best_start = hits[0]
        best_count = 0
        left = 0
        for right, position in enumerate(hits):
            # Shrink from the left until every hit in [position - window,
            # position] is inside the window anchored at `position`.
            while hits[left] < position - window:
                left += 1
            count = right - left + 1
            if count > best_count:
                best_count = count
                best_start = position

        start = max(0, best_start - window // 2)
        end = min(len(content), start + window)
        start = max(0, end - window)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    @staticmethod
    def _find_term_hits(lower: str, terms: list[str]) -> list[int]:
        """Return every start position of every term in the lowered content."""
        hits: list[int] = []
        for term in terms:
            needle = term.lower()
            if not needle:
                continue
            pos = 0
            while True:
                idx = lower.find(needle, pos)
                if idx == -1:
                    break
                hits.append(idx)
                pos = idx + 1
        return hits

    @staticmethod
    def _extract_date_from_path(rel_path: str) -> str | None:
        import re
        match = re.search(r"(\d{4}-\d{2}-\d{2})", rel_path)
        return match.group(1) if match else None


def asyncio_import():
    import asyncio
    return asyncio

"""Vault link extraction and resolution for Zettelkasten notes.

Extracts ``[[wikilink]]`` references from note bodies, resolves them to
target note IDs, and identifies broken links.

Usage::

    from jarvis_os.vault.links import extract_wikilinks, resolve_links

    links = extract_wikilinks("See [[plan_hoy]] and [[metricas_2026-08-08|metrics]]")
    resolved = await resolve_links(links, vault_root=Path("/app/vault"))
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from jarvis_os.vault.models import LinkKind, NoteLink

logger = logging.getLogger(__name__)

# Matches [[target]] or [[target|alias]]
_WIKILINK_RE = r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]"


def extract_wikilinks(text: str) -> list[NoteLink]:
    """Return all wikilinks found in *text*.

    Args:
        text: Raw note body.

    Returns:
        A list of :class:`NoteLink` with ``kind=WIKI_LINK``.
    """
    import re

    links: list[NoteLink] = []
    for match in re.finditer(_WIKILINK_RE, text):
        target = match.group(1).strip()
        alias = match.group(2).strip() if match.group(2) else None
        links.append(
            NoteLink(
                target=target,
                kind=LinkKind.WIKI_LINK,
                alias=alias,
                resolved=True,
            )
        )
    return links


def extract_frontmatter_links(links_raw: list[str]) -> list[NoteLink]:
    """Convert frontmatter ``links`` array entries to :class:`NoteLink`.

    Args:
        links_raw: List of target IDs or paths from frontmatter.

    Returns:
        A list of :class:`NoteLink` with ``kind=REFERENCE``.
    """
    return [
        NoteLink(target=target.strip(), kind=LinkKind.REFERENCE, resolved=True)
        for target in links_raw
        if target.strip()
    ]


async def resolve_links(
    links: list[NoteLink],
    vault_root: Path,
) -> list[NoteLink]:
    """Mark links as resolved/broken based on whether the target exists.

    Walks ``vault_root`` for note files whose stem matches ``link.target``.

    Args:
        links: Candidate links to resolve.
        vault_root: Root directory of the vault.

    Returns:
        The same list, with ``resolved`` set to ``True`` when the target
        file exists and ``False`` otherwise.
    """
    existing_ids = _collect_note_ids(vault_root)
    for link in links:
        link.resolved = link.target in existing_ids
        if not link.resolved:
            logger.debug("Broken link: %r not found in vault", link.target)
    return links


async def backlinks_for(
    note_id: str,
    vault_root: Path,
) -> list[NoteLink]:
    """Find all links that point to *note_id*.

    Args:
        note_id: Target note id.
        vault_root: Root directory of the vault.

    Returns:
        A list of :class:`NoteLink` where ``target == note_id``.
    """
    backlinks: list[NoteLink] = []
    for path in _walk_note_files(vault_root):
        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            from jarvis_os.vault.validator import parse_frontmatter_block

            _, body = parse_frontmatter_block(text)
            for link in extract_wikilinks(body):
                if link.target == note_id:
                    backlinks.append(
                        NoteLink(
                            target=path.stem,
                            kind=LinkKind.WIKI_LINK,
                            alias=None,
                            resolved=True,
                        )
                    )
        except Exception:
            continue
    return backlinks


def _collect_note_ids(vault_root: Path) -> set[str]:
    ids: set[str] = set()
    for path in _walk_note_files(vault_root):
        try:
            text = path.read_text(encoding="utf-8")
            from jarvis_os.vault.validator import parse_frontmatter_block

            frontmatter, _ = parse_frontmatter_block(text)
            ids.add(frontmatter.id)
        except Exception:
            continue
    return ids


def _walk_note_files(vault_root: Path):
    for subdir in ("raw", "wiki", "outputs"):
        base = vault_root / subdir
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".md", ".json", ".txt"}:
                yield path

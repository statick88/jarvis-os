"""Vault indexer: incremental and full indexation of Zettelkasten notes.

Walks configured vault paths, parses frontmatter and wikilinks, computes
SHA-256 + mtime for change detection, and persists ``.boveda_index.json``.
Also regenerates ``wiki/index.md`` after each run.

Usage::

    from jarvis_os.vault.indexer import VaultIndexer

    indexer = VaultIndexer(vault_root=Path("/app/vault"))
    result = await indexer.index()
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis_os.vault.links import extract_wikilinks
from jarvis_os.vault.models import (
    INDEX_VERSION,
    IndexEntry,
    VaultIndex,
    VaultNote,
    VaultOperationResult,
    VaultParseError,
    VaultWriteError,
)
from jarvis_os.vault.validator import parse_frontmatter_block

logger = logging.getLogger(__name__)


class VaultIndexer:
    """Incremental indexer for the vault subsystem.

    Args:
        vault_root: Root directory of the vault (contains raw/, wiki/, outputs/).
        paths: Subdirectories to index (relative to ``vault_root``).
    """

    def __init__(
        self,
        vault_root: Path,
        paths: list[str] | None = None,
    ) -> None:
        self.vault_root = vault_root.resolve()
        self.paths = paths or ["raw", "wiki", "outputs"]
        self.index_path = self.vault_root / "wiki" / ".boveda_index.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def index(self, force_full: bool = False) -> VaultOperationResult:
        """Run an incremental index pass.

        Args:
            force_full: When True, ignore the existing index and scan every
                file regardless of mtime/hash.

        Returns:
            A :class:`VaultOperationResult` with ``indexed_count``,
            ``updated_count`` and optional ``errors``.
        """
        try:
            index = await self._load_index()
        except Exception as exc:
            logger.warning("Could not load existing index, rebuilding: %s", exc)
            index = VaultIndex()
            force_full = True

        files_on_disk = self._discover_files()
        previous_files = {e.rel_path: e for e in index.files.values() if not e.deleted}

        to_process: list[Path] = []
        indexed_count = 0
        updated_count = 0
        errors: list[dict[str, Any]] = []

        for rel_path in sorted(files_on_disk):
            abs_path = self.vault_root / rel_path
            try:
                stat = abs_path.stat()
            except OSError:
                continue

            mtime_ns = stat.st_mtime_ns
            size_bytes = stat.st_size
            sha256 = self._sha256(abs_path)

            entry = previous_files.get(rel_path)
            if not force_full and entry is not None:
                if entry.sha256 == sha256 and entry.mtime_ns == mtime_ns:
                    continue
                updated_count += 1
            else:
                indexed_count += 1

            to_process.append(abs_path)

        for abs_path in to_process:
            rel_path = str(abs_path.relative_to(self.vault_root))
            try:
                note = await self._parse_note(abs_path)
                entry = IndexEntry(
                    id=note.id,
                    title=note.title,
                    rel_path=rel_path,
                    tags=note.tags,
                    links=[link.target for link in note.explicit_links],
                    sha256=self._sha256(abs_path),
                    mtime_ns=abs_path.stat().st_mtime_ns,
                    size_bytes=abs_path.stat().st_size,
                )
                index.files[note.id] = entry
            except (VaultParseError, Exception) as exc:
                errors.append({"path": rel_path, "error": str(exc)})
                logger.warning("Failed to index %s: %s", rel_path, exc)

        for rel_path, entry in list(previous_files.items()):
            if rel_path not in files_on_disk:
                index.files[entry.id].deleted = True

        index.updated_at = _now_utc()
        await self._write_index(index)
        await self._write_master_index(index)

        return VaultOperationResult.ok(
            {
                "indexed_count": indexed_count,
                "updated_count": updated_count,
                "errors": errors,
                "total_active": sum(1 for e in index.files.values() if not e.deleted),
            }
        )

    async def rebuild(self) -> VaultOperationResult:
        """Force a full re-index, discarding the existing index file."""
        return await self.index(force_full=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_index(self) -> VaultIndex:
        if not self.index_path.exists():
            return VaultIndex()
        raw = await asyncio.to_thread(self.index_path.read_text, encoding="utf-8")
        data = json.loads(raw)
        return VaultIndex.model_validate(data)

    async def _write_index(self, index: VaultIndex) -> None:
        raw = index.model_dump_json(indent=2)
        await asyncio.to_thread(self._atomic_write, self.index_path, raw)

    async def _write_master_index(self, index: VaultIndex) -> None:
        active = [e for e in index.files.values() if not e.deleted]
        lines = [
            "---",
            "id: vault_index",
            "tags: [index, vault, master]",
            f"created: \"{_format_iso(index.updated_at)}\"",
            f"modified: \"{_format_iso(index.updated_at)}\"",
            "source: \"skill.boveda\"",
            f"total_notes: {len(active)}",
            f"last_indexed: \"{_format_iso(index.updated_at)}\"",
            "---",
            "",
            f"# Índice Maestro de la Bóveda — {index.updated_at.strftime('%Y-%m-%d')}",
            "",
            "> Generado automáticamente por `skill.boveda`",
            "",
            "## 📁 Por Directorio",
        ]

        by_dir: dict[str, list[str]] = {}
        for entry in active:
            directory = str(Path(entry.rel_path).parent)
            by_dir.setdefault(directory, []).append(entry.rel_path)

        for directory in sorted(by_dir):
            entries = by_dir[directory]
            lines.append(f"### `{directory}/` ({len(entries)} notas)")
            for rel in entries:
                note_id = Path(rel).stem
                lines.append(
                    f"- [{note_id}]({rel}) — *indexado {index.updated_at.strftime('%Y-%m-%d')}*"
                )
            lines.append("")

        master_path = self.vault_root / "wiki" / "index.md"
        content = "\n".join(lines)
        await asyncio.to_thread(self._atomic_write, master_path, content)

    def _discover_files(self) -> set[str]:
        files: set[str] = set()
        for subdir in self.paths:
            base = self.vault_root / subdir
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".md", ".json", ".txt"}:
                    files.add(str(path.relative_to(self.vault_root)))
        return files

    async def _parse_note(self, path: Path) -> VaultNote:
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        frontmatter, body = parse_frontmatter_block(text)
        wikilinks = extract_wikilinks(body)
        return VaultNote(
            frontmatter=frontmatter,
            content=body,
            path=path,
            rel_path=str(path.relative_to(self.vault_root)),
            word_count=len(body.split()),
            explicit_links=wikilinks,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _atomic_write(path: Path, data: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

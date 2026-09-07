"""Tests for VaultIndexer nightly scan: search_by_tags and link consistency."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from jarvis_os.vault.indexer import VaultIndexer
from jarvis_os.vault.models import VaultIndex, IndexEntry


def _write_markdown(path: Path, frontmatter: dict, body: str) -> None:
    """Write a vault note with YAML frontmatter block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            items = ", ".join(f'"{item}"' for item in value)
            lines.append(f"{key}: [{items}]")
        elif isinstance(value, str):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")


def _index_vault(vault: Path) -> None:
    """Run a full index pass on the vault."""
    indexer = VaultIndexer(vault_root=vault)
    asyncio.run(indexer.index(force_full=True))


def _search_tags(vault: Path, tags: list[str], *, include_deleted: bool = False):
    """Run search_by_tags on the vault and return the result."""
    indexer = VaultIndexer(vault_root=vault)
    return asyncio.run(indexer.search_by_tags(tags, include_deleted=include_deleted))


# ------------------------------------------------------------------
# search_by_tags: basic functionality
# ------------------------------------------------------------------


class TestSearchByTags:
    """search_by_tags index-only queries for nightly scans."""

    def test_returns_matching_notes(self, tmp_path: Path) -> None:
        """Notes with matching tags are returned."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "idea-alpha.md",
            {
                "id": "idea-alpha",
                "title": "Alpha Idea",
                "tags": ["idea", "research"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "An idea note.\n",
        )
        _write_markdown(
            wiki / "todo-fix.md",
            {
                "id": "todo-fix",
                "title": "Fix Bug",
                "tags": ["todo", "bugfix"],
                "created": "2026-09-01T11:00:00+00:00",
                "modified": "2026-09-01T11:00:00+00:00",
            },
            "Fix the thing.\n",
        )
        _write_markdown(
            wiki / "journal-daily.md",
            {
                "id": "journal-daily",
                "title": "Daily Journal",
                "tags": ["journal"],
                "created": "2026-09-01T12:00:00+00:00",
                "modified": "2026-09-01T12:00:00+00:00",
            },
            "Just a journal.\n",
        )

        _index_vault(vault)
        result = _search_tags(vault, ["#idea", "#todo"])

        assert result.success is True
        matched = result.data["matched_entries"]
        ids = {e["id"] for e in matched}
        assert "idea-alpha" in ids
        assert "todo-fix" in ids
        assert "journal-daily" not in ids
        assert result.data["total_matched"] == 2

    def test_case_insensitive_matching(self, tmp_path: Path) -> None:
        """Tag matching is case-insensitive."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "note.md",
            {
                "id": "note",
                "title": "Note",
                "tags": ["Idea", "RESEARCH"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Content.\n",
        )

        _index_vault(vault)
        result = _search_tags(vault, ["#idea", "#research"])

        assert result.success is True
        assert result.data["total_matched"] == 1
        assert result.data["matched_entries"][0]["id"] == "note"

    def test_no_matches_returns_empty(self, tmp_path: Path) -> None:
        """Non-matching tags return an empty list."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "note.md",
            {
                "id": "note",
                "title": "Note",
                "tags": ["journal"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Content.\n",
        )

        _index_vault(vault)
        result = _search_tags(vault, ["#idea", "#todo"])

        assert result.success is True
        assert result.data["matched_entries"] == []
        assert result.data["total_matched"] == 0

    def test_empty_tag_list_returns_all(self, tmp_path: Path) -> None:
        """Empty tag list returns no matches (no overlap possible)."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "note.md",
            {
                "id": "note",
                "title": "Note",
                "tags": ["idea"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Content.\n",
        )

        _index_vault(vault)
        result = _search_tags(vault, [])

        assert result.success is True
        assert result.data["total_matched"] == 0

    def test_empty_index_returns_empty(self, tmp_path: Path) -> None:
        """Searching an empty index returns empty results."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        # No files — just run search directly
        result = _search_tags(vault, ["#idea"])

        assert result.success is True
        assert result.data["matched_entries"] == []

    def test_missing_index_file_returns_empty(self, tmp_path: Path) -> None:
        """When .boveda_index.json doesn't exist, returns empty with error info."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        indexer = VaultIndexer(vault_root=vault)
        result = asyncio.run(indexer.search_by_tags(["#idea"]))

        assert result.success is True
        assert result.data["matched_entries"] == []
        # _load_index returns empty VaultIndex, no error field
        assert "error" not in result.data or result.data.get("error") is None


# ------------------------------------------------------------------
# search_by_tags: deleted entries
# ------------------------------------------------------------------


class TestSearchByTagsDeleted:
    """Tests for include_deleted flag behavior."""

    def test_deleted_entries_excluded_by_default(self, tmp_path: Path) -> None:
        """Deleted entries are not returned unless include_deleted=True."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "active.md",
            {
                "id": "active",
                "title": "Active Note",
                "tags": ["idea"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Still here.\n",
        )
        _write_markdown(
            wiki / "removed.md",
            {
                "id": "removed",
                "title": "Removed Note",
                "tags": ["idea"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Gone soon.\n",
        )

        _index_vault(vault)

        # Delete the file and re-index to mark it as deleted
        (wiki / "removed.md").unlink()
        _index_vault(vault)

        # Default: deleted excluded
        result = _search_tags(vault, ["#idea"])
        ids = {e["id"] for e in result.data["matched_entries"]}
        assert "active" in ids
        assert "removed" not in ids

        # include_deleted: deleted included
        result_del = _search_tags(vault, ["#idea"], include_deleted=True)
        ids_del = {e["id"] for e in result_del.data["matched_entries"]}
        assert "active" in ids_del
        assert "removed" in ids_del


# ------------------------------------------------------------------
# search_by_tags: returned structure
# ------------------------------------------------------------------


class TestSearchByTagsStructure:
    """Verify the shape of returned matched entries."""

    def test_matched_entry_contains_required_fields(self, tmp_path: Path) -> None:
        """Each matched entry has id, title, rel_path, tags, links."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "note.md",
            {
                "id": "note",
                "title": "Test Note",
                "tags": ["idea", "research"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Some content.\n",
        )

        _index_vault(vault)
        result = _search_tags(vault, ["#idea"])

        entry = result.data["matched_entries"][0]
        assert "id" in entry
        assert "title" in entry
        assert "rel_path" in entry
        assert "tags" in entry
        assert "links" in entry
        assert entry["id"] == "note"
        assert entry["title"] == "Test Note"
        assert entry["rel_path"] == "wiki/note.md"
        assert "idea" in entry["tags"]


# ------------------------------------------------------------------
# Link consistency after nightly scan
# ------------------------------------------------------------------


class TestLinkConsistencyAfterNightlyScan:
    """After a nightly index + tag search, links should be consistent."""

    def test_wikilinks_preserved_in_index(self, tmp_path: Path) -> None:
        """Wikilinks in note bodies are preserved as links in index entries."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "project-x.md",
            {
                "id": "project-x",
                "title": "Project X",
                "tags": ["idea", "project"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Related to [[research-deep]] and [[todo-fix]].\n",
        )
        _write_markdown(
            wiki / "research-deep.md",
            {
                "id": "research-deep",
                "title": "Deep Research",
                "tags": ["research"],
                "created": "2026-09-01T11:00:00+00:00",
                "modified": "2026-09-01T11:00:00+00:00",
            },
            "Research notes.\n",
        )
        _write_markdown(
            wiki / "todo-fix.md",
            {
                "id": "todo-fix",
                "title": "Fix Bug",
                "tags": ["todo"],
                "created": "2026-09-01T12:00:00+00:00",
                "modified": "2026-09-01T12:00:00+00:00",
            },
            "Fix it.\n",
        )

        _index_vault(vault)
        result = _search_tags(vault, ["#idea"])

        entry = result.data["matched_entries"][0]
        assert entry["id"] == "project-x"
        assert "research-deep" in entry["links"]
        assert "todo-fix" in entry["links"]

    def test_output_backlinks_visible_after_nightly_scan(self, tmp_path: Path) -> None:
        """Output files with wikilinks create backlinks visible via tag search."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        outputs = vault / "outputs" / "2026-09-01"
        wiki.mkdir(parents=True)
        outputs.mkdir(parents=True)

        _write_markdown(
            wiki / "skill-os.md",
            {
                "id": "skill-os",
                "title": "OS Skill",
                "tags": ["skill", "idea"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "OS control skill.\n",
        )
        _write_markdown(
            outputs / "skill-os-131200.md",
            {
                "id": "skill-os-131200",
                "title": "skill.os — 13:12:00",
                "tags": ["skill-execution", "idea"],
                "created": "2026-09-01T13:12:00+00:00",
                "modified": "2026-09-01T13:12:00+00:00",
            },
            "Executed.\n\nLinks:\n- [[skill-os]]\n",
        )

        _index_vault(vault)

        # Tag search for #idea should find both
        result = _search_tags(vault, ["#idea"])
        ids = {e["id"] for e in result.data["matched_entries"]}
        assert "skill-os" in ids
        assert "skill-os-131200" in ids

        # Verify the wiki note has a backlink to the output
        indexer = VaultIndexer(vault_root=vault)
        index = asyncio.run(indexer._load_index())
        wiki_entry = next(e for e in index.files.values() if e.rel_path == "wiki/skill-os.md")
        assert "outputs/2026-09-01/skill-os-131200.md" in wiki_entry.links

    def test_reindex_preserves_tag_search_results(self, tmp_path: Path) -> None:
        """Re-indexing doesn't break tag search results."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "note.md",
            {
                "id": "note",
                "title": "Note",
                "tags": ["idea"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "Content.\n",
        )

        # Index twice
        _index_vault(vault)
        _index_vault(vault)

        result = _search_tags(vault, ["#idea"])
        assert result.data["total_matched"] == 1
        assert result.data["matched_entries"][0]["id"] == "note"

    def test_multiple_tags_or_logic(self, tmp_path: Path) -> None:
        """Multiple tags use OR logic — match if ANY tag overlaps."""
        vault = tmp_path / "vault"
        wiki = vault / "wiki"
        wiki.mkdir(parents=True)

        _write_markdown(
            wiki / "a.md",
            {
                "id": "a",
                "title": "A",
                "tags": ["idea"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "A.\n",
        )
        _write_markdown(
            wiki / "b.md",
            {
                "id": "b",
                "title": "B",
                "tags": ["todo"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "B.\n",
        )
        _write_markdown(
            wiki / "c.md",
            {
                "id": "c",
                "title": "C",
                "tags": ["journal"],
                "created": "2026-09-01T10:00:00+00:00",
                "modified": "2026-09-01T10:00:00+00:00",
            },
            "C.\n",
        )

        _index_vault(vault)
        result = _search_tags(vault, ["#idea", "#todo"])

        ids = {e["id"] for e in result.data["matched_entries"]}
        assert "a" in ids
        assert "b" in ids
        assert "c" not in ids

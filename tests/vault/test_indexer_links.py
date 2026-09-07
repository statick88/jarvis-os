"""Tests for VaultIndexer backlink behavior between outputs/ and wiki/."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from jarvis_os.vault.indexer import VaultIndexer
from jarvis_os.vault.models import VaultIndex, IndexEntry, VaultNote, NoteFrontmatter
from jarvis_os.vault.validator import parse_frontmatter_block


def _write_markdown(path: Path, frontmatter: dict, body: str) -> None:
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


def test_backlinks_created_between_outputs_and_wiki(tmp_path: Path) -> None:
    """After indexing, wiki notes should backlink to related outputs."""
    vault = tmp_path / "vault"
    wiki_dir = vault / "wiki"
    outputs_dir = vault / "outputs" / "2026-08-31"
    wiki_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)

    # Create a wiki note
    _write_markdown(
        wiki_dir / "skill-os-control.md",
        {
            "id": "skill-os-control",
            "title": "OS Control Skill",
            "tags": ["skill", "os"],
            "created": "2026-08-31T13:00:00+00:00",
            "modified": "2026-08-31T13:00:00+00:00",
        },
        "Controles del sistema operativo.\n",
    )

    # Create an output file with a wikilink to the note
    _write_markdown(
        outputs_dir / "skill-os-control-131200.md",
        {
            "id": "skill-os-control-131200",
            "title": "skill.os_control — 13:12:00",
            "tags": ["skill-execution", "skill-os-control"],
            "skill": "skill.os_control",
            "created": "2026-08-31T13:12:00+00:00",
            "modified": "2026-08-31T13:12:00+00:00",
        },
        "Ejecución completada.\n\nLinks:\n- [[skill-os-control]]\n",
    )

    indexer = VaultIndexer(vault_root=vault)
    import asyncio
    result = asyncio.run(indexer.index(force_full=True))

    assert result.success is True
    assert result.data["indexed_count"] == 2

    # Verify backlink via the persisted index file
    index_path = vault / "wiki" / ".boveda_index.json"
    raw = index_path.read_text(encoding="utf-8")
    index = VaultIndex.model_validate(json.loads(raw))

    wiki_note = next(e for e in index.files.values() if e.rel_path == "wiki/skill-os-control.md")
    output_note = next(e for e in index.files.values() if e.rel_path.startswith("outputs/"))

    assert output_note.rel_path in wiki_note.links, (
        f"Wiki note should backlink to output, got links={wiki_note.links}"
    )


def test_indexer_preserves_existing_links(tmp_path: Path) -> None:
    """Re-indexing should not duplicate backlinks."""
    vault = tmp_path / "vault"
    wiki_dir = vault / "wiki"
    outputs_dir = vault / "outputs" / "2026-08-31"
    wiki_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)

    _write_markdown(
        wiki_dir / "note-a.md",
        {"id": "note-a", "title": "Note A", "tags": ["a"], "created": "2026-08-31T13:00:00+00:00", "modified": "2026-08-31T13:00:00+00:00"},
        "Content A.\n",
    )
    _write_markdown(
        outputs_dir / "out-1.md",
        {
            "id": "out-1",
            "title": "Output 1",
            "tags": ["exec"],
            "skill": "skill.a",
            "created": "2026-08-31T13:00:00+00:00",
            "modified": "2026-08-31T13:00:00+00:00",
        },
        "[[note-a]]\n",
    )

    indexer = VaultIndexer(vault_root=vault)
    import asyncio
    asyncio.run(indexer.index(force_full=True))
    asyncio.run(indexer.index(force_full=True))  # run twice

    index_path = vault / "wiki" / ".boveda_index.json"
    raw = index_path.read_text(encoding="utf-8")
    index = VaultIndex.model_validate(json.loads(raw))

    wiki_note = next(e for e in index.files.values() if e.rel_path == "wiki/note-a.md")
    assert wiki_note.links.count("outputs/2026-08-31/out-1.md") == 1


def test_deleted_output_removes_backlink(tmp_path: Path) -> None:
    """When an output file is removed, its backlink should be gone."""
    vault = tmp_path / "vault"
    wiki_dir = vault / "wiki"
    outputs_dir = vault / "outputs" / "2026-08-31"
    wiki_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)

    _write_markdown(
        wiki_dir / "note-b.md",
        {"id": "note-b", "title": "Note B", "tags": ["b"], "created": "2026-08-31T13:00:00+00:00", "modified": "2026-08-31T13:00:00+00:00"},
        "Content B.\n",
    )
    output_path = outputs_dir / "out-b.md"
    _write_markdown(
        output_path,
        {
            "id": "out-b",
            "title": "Output B",
            "tags": ["exec"],
            "skill": "skill.b",
            "created": "2026-08-31T13:00:00+00:00",
            "modified": "2026-08-31T13:00:00+00:00",
        },
        "[[note-b]]\n",
    )

    indexer = VaultIndexer(vault_root=vault)
    import asyncio
    asyncio.run(indexer.index(force_full=True))

    # Remove the output file and re-index
    output_path.unlink()
    asyncio.run(indexer.index(force_full=True))

    index_path = vault / "wiki" / ".boveda_index.json"
    raw = index_path.read_text(encoding="utf-8")
    index = VaultIndex.model_validate(json.loads(raw))

    wiki_note = next(e for e in index.files.values() if e.rel_path == "wiki/note-b.md")
    assert "outputs/2026-08-31/out-b.md" not in wiki_note.links

"""Vault validator: frontmatter schema and link consistency checks.

Provides ``parse_frontmatter_block`` for extracting YAML frontmatter from
markdown, plus :class:`VaultValidator` for full-vault validation passes.

Usage::

    from jarvis_os.vault.validator import parse_frontmatter_block, VaultValidator

    frontmatter, body = parse_frontmatter_block(raw_markdown)
    validator = VaultValidator(vault_root=Path("/app/vault"))
    report = await validator.validate()
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from jarvis_os.vault.models import (
    NOTE_ID_RE,
    ValidationIssue,
    ValidationReport,
    VaultIndex,
    VaultNote,
    VaultOperationResult,
    VaultBrokenLinkError,
    VaultDuplicateIdError,
    VaultInvalidFrontmatterError,
    VaultParseError,
)

logger = logging.getLogger(__name__)

# Frontmatter delimiter
_FRONTMATTER_DELIM = "---"


class VaultValidator:
    """Validates vault integrity and consistency.

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

    async def validate(self) -> VaultOperationResult:
        """Run a full validation pass across all active notes.

        Returns:
            A :class:`VaultOperationResult` with ``validation_report`` in
            ``data``.
        """
        index = await self._load_index()
        active_entries = [e for e in index.files.values() if not e.deleted]

        notes_by_id: dict[str, VaultNote] = {}
        issues: list[ValidationIssue] = []

        for entry in active_entries:
            note = await self._load_note(entry.rel_path, expected_id=entry.id)
            if note is None:
                issues.append(
                    ValidationIssue(
                        note_id=entry.id,
                        rel_path=entry.rel_path,
                        severity="error",
                        code="PARSE_ERROR",
                        message="Could not parse note file",
                    )
                )
                continue

            if note.id in notes_by_id:
                issues.append(
                    ValidationIssue(
                        note_id=note.id,
                        rel_path=entry.rel_path,
                        severity="error",
                        code="DUPLICATE_ID",
                        message=f"Duplicate id {note.id!r}",
                    )
                )
            else:
                notes_by_id[note.id] = note

        all_ids = set(notes_by_id.keys())
        for note in notes_by_id.values():
            self._validate_frontmatter(note, issues)
            self._validate_links(note, all_ids, issues)
            self._validate_dates(note, issues)

        report = ValidationReport(
            valid=not any(i.severity == "error" for i in issues),
            issues=issues,
            notes_checked=len(notes_by_id),
        )

        return VaultOperationResult.ok({"validation_report": report.model_dump(mode="json")})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_index(self) -> VaultIndex:
        if not self.index_path.exists():
            return VaultIndex()
        raw = await asyncio.to_thread(self.index_path.read_text, encoding="utf-8")
        data = json.loads(raw)
        return VaultIndex.model_validate(data)

    async def _load_note(self, rel_path: str, expected_id: str | None = None) -> VaultNote | None:
        abs_path = self.vault_root / rel_path
        if not abs_path.exists():
            return None
        try:
            text = await asyncio.to_thread(abs_path.read_text, encoding="utf-8")
            frontmatter, body = parse_frontmatter_block(text, expected_id=expected_id)
            from jarvis_os.vault.links import extract_wikilinks

            wikilinks = extract_wikilinks(body)
            return VaultNote(
                frontmatter=frontmatter,
                content=body,
                path=abs_path,
                rel_path=rel_path,
                word_count=len(body.split()),
                explicit_links=wikilinks,
            )
        except (VaultInvalidFrontmatterError, VaultParseError) as exc:
            logger.warning("Validation parse error in %s: %s", rel_path, exc)
            return None
        except Exception as exc:
            logger.warning("Unexpected error loading %s: %s", rel_path, exc)
            return None

    @staticmethod
    def _validate_frontmatter(note: VaultNote, issues: list[ValidationIssue]) -> None:
        required = ["id", "title", "created", "modified"]
        for field in required:
            if not getattr(note.frontmatter, field, None):
                issues.append(
                    ValidationIssue(
                        note_id=note.id,
                        rel_path=note.rel_path,
                        severity="error",
                        code="INVALID_FRONTMATTER",
                        message=f"Missing required field {field!r}",
                        field=field,
                    )
                )
        if not note.tags:
            issues.append(
                ValidationIssue(
                    note_id=note.id,
                    rel_path=note.rel_path,
                    severity="warning",
                    code="INVALID_FRONTMATTER",
                    message="Missing tags",
                    field="tags",
                )
            )

    @staticmethod
    def _validate_links(note: VaultNote, all_ids: set[str], issues: list[ValidationIssue]) -> None:
        for link in note.explicit_links:
            if link.target not in all_ids:
                issues.append(
                    ValidationIssue(
                        note_id=note.id,
                        rel_path=note.rel_path,
                        severity="warning",
                        code="BROKEN_LINK",
                        message=f"Link target {link.target!r} does not exist",
                    )
                )

    @staticmethod
    def _validate_dates(note: VaultNote, issues: list[ValidationIssue]) -> None:
        if note.frontmatter.created > note.frontmatter.modified:
            issues.append(
                ValidationIssue(
                    note_id=note.id,
                    rel_path=note.rel_path,
                    severity="warning",
                    code="INVALID_FRONTMATTER",
                    message="created > modified",
                    field="created",
                )
            )


def parse_frontmatter_block(
    text: str,
    expected_id: str | None = None,
) -> tuple[Any, str]:
    """Extract and parse the YAML frontmatter block from a markdown text.

    Args:
        text: Raw markdown file content.
        expected_id: Optional id to assert against the parsed frontmatter.

    Returns:
        A tuple of ``(frontmatter, body)`` where ``frontmatter`` is a
        :class:`jarvis_os.vault.models.NoteFrontmatter` instance and
        ``body`` is the remaining markdown.

    Raises:
        VaultInvalidFrontmatterError: If the YAML is missing, malformed, or
            fails model validation.
        VaultParseError: If the markdown structure is invalid.
    """
    stripped = text.lstrip()
    if not stripped.startswith(_FRONTMATTER_DELIM):
        raise VaultParseError("Missing opening '---' frontmatter delimiter")

    first_newline = stripped.find("\n")
    if first_newline == -1:
        raise VaultParseError("Unterminated frontmatter")

    rest = stripped[first_newline + 1 :]
    if not rest.startswith(_FRONTMATTER_DELIM):
        closing = rest.find("\n---\n")
        if closing == -1:
            raise VaultParseError("Missing closing '---' delimiter")
        block = rest[:closing]
        body = rest[closing + 4 :]
    else:
        block = ""
        body = rest[4:]

    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:
        raise VaultInvalidFrontmatterError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise VaultInvalidFrontmatterError(
            f"Frontmatter must be a YAML mapping, got {type(data).__name__}"
        )

    # Normalize datetime fields
    for field in ("created", "modified"):
        val = data.get(field)
        if isinstance(val, str):
            try:
                data[field] = datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                pass

    from jarvis_os.vault.models import NoteFrontmatter

    try:
        frontmatter = NoteFrontmatter(**data)
    except Exception as exc:
        raise VaultInvalidFrontmatterError(f"Frontmatter validation failed: {exc}") from exc

    if expected_id is not None and frontmatter.id != expected_id:
        raise VaultInvalidFrontmatterError(
            f"Frontmatter id {frontmatter.id!r} does not match expected {expected_id!r}"
        )

    return frontmatter, body.lstrip("\n")

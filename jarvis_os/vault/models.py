"""Data models for the vault subsystem (Zettelkasten).

Mirrors ``.skills/boveda.md`` contract: note frontmatter (``id``, ``title``,
``tags``, ``links[[...]]``, ``created``, ``modified``), the on-disk index
``.boveda_index.json``, search results, the knowledge graph, and the
validation report. Error classes carry the stable ``code`` values from the
boveda error table (``INVALID_FRONTMATTER``, ``DUPLICATE_ID``, ``BROKEN_LINK``,
``INDEX_CORRUPT``, ``VAULT_WRITE_FAILED``, ``PARSE_ERROR``).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# --- Constants ---

# Note id: permissive but must be URL/path safe (Obsidian-style ids).
NOTE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*$")
# Inline wiki link inside a note body: [[target]] or [[target|alias]].
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]")

INDEX_VERSION = 1
DEFAULT_SNIPPET_CHARS = 100
MAX_SEARCH_RESULTS = 50
MAX_GRAPH_DEPTH = 5


# --- Exceptions ---


class VaultError(Exception):
    """Base error for the vault module.

    Every subclass carries a ``code`` matching the stable error table in
    ``.skills/boveda.md`` so callers can switch on machine-readable codes.
    """

    code = "VAULT_ERROR"

    def __init__(self, message: str = "", *, note_id: Optional[str] = None) -> None:
        self.note_id = note_id
        if note_id and not message:
            message = f"note {note_id!r}"
        super().__init__(message)

    @property
    def message(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)!r})"


class VaultInvalidFrontmatterError(VaultError):
    """Raised when a note's frontmatter fails validation."""

    code = "INVALID_FRONTMATTER"


class VaultDuplicateIdError(VaultError):
    """Raised when two notes share the same id."""

    code = "DUPLICATE_ID"


class VaultBrokenLinkError(VaultError):
    """Raised when a note links to a target that does not exist in the vault."""

    code = "BROKEN_LINK"


class VaultIndexCorruptError(VaultError):
    """Raised when ``.boveda_index.json`` is missing, unreadable or inconsistent."""

    code = "INDEX_CORRUPT"


class VaultWriteError(VaultError):
    """Raised when writing to the vault (index, master index, exports) fails."""

    code = "VAULT_WRITE_FAILED"


class VaultParseError(VaultError):
    """Raised when a note body cannot be parsed."""

    code = "PARSE_ERROR"


# --- Enums ---


class LinkKind(StrEnum):
    """Classification of a relationship between notes."""

    WIKI_LINK = "wiki_link"  # [[target]] in a note body
    TAG = "tag"  # frontmatter tag
    DATE = "date"  # date reference (created/modified)
    REFERENCE = "reference"  # explicit `links[[...]]` frontmatter entry


class IssueSeverity(StrEnum):
    """Severity of a validation finding."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class GraphFormat(StrEnum):
    """Supported knowledge graph export formats."""

    JSON = "json"
    GRAPHML = "graphml"
    DOT = "dot"
    MARKDOWN = "markdown"


class VaultAction(StrEnum):
    """The seven capabilities exposed by the boveda skill."""

    INDEX = "index"
    REBUILD = "rebuild"
    GRAPH = "graph"
    LINKS = "links"
    SEARCH = "search"
    STATS = "stats"
    VALIDATE = "validate"


class VaultChangeOperation(StrEnum):
    """Operation recorded in a vault change set."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LINK = "link"


# --- Note models ---


class NoteLink(BaseModel):
    """One relationship from a note to another target."""

    target: str = Field(..., description="Target note id or path")
    kind: LinkKind = Field(default=LinkKind.WIKI_LINK, description="Relationship type")
    alias: Optional[str] = Field(default=None, description="Display alias ([[target|alias]])")
    resolved: bool = Field(
        default=True, description="False when the target is missing (broken link)"
    )


class NoteFrontmatter(BaseModel):
    """Validated YAML frontmatter of a vault note.

    Mirrors the required fields enforced by ``VaultSettings.required_frontmatter_fields``
    plus the optional ``tags`` and ``links[[...]]`` fields from the spec (RF-06).
    """

    id: str = Field(..., description="Unique note id")
    title: str = Field(..., min_length=1, max_length=200, description="Note title")
    tags: list[str] = Field(default_factory=list, description="Tags attached to the note")
    links: list[str] = Field(
        default_factory=list, description="Explicit links[[...]] targets from frontmatter"
    )
    created: datetime = Field(..., description="Creation timestamp (UTC)")
    modified: datetime = Field(..., description="Last modification timestamp (UTC)")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not NOTE_ID_RE.match(v):
            raise ValueError(
                f"Note id must match /^[a-zA-Z0-9][a-zA-Z0-9._:-]*$/ — got {v!r}"
            )
        return v

    @field_validator("tags", "links")
    @classmethod
    def dedupe_lists(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for item in v:
            if item not in seen:
                seen.append(item)
        return seen


class VaultNote(BaseModel):
    """A fully parsed vault note: frontmatter, body and derived links."""

    frontmatter: NoteFrontmatter = Field(..., description="Validated frontmatter")
    content: str = Field(default="", description="Note body (markdown, without frontmatter)")
    path: Path = Field(..., description="Absolute path of the note file")
    rel_path: str = Field(..., description="Path relative to the vault root")
    word_count: int = Field(default=0, description="Words in the note body")
    explicit_links: list[NoteLink] = Field(
        default_factory=list, description="Links from links[[...]] and inline wikilinks"
    )
    implicit_links: list[NoteLink] = Field(
        default_factory=list, description="Links inferred from shared tags and dates"
    )

    @property
    def id(self) -> str:
        return self.frontmatter.id

    @property
    def title(self) -> str:
        return self.frontmatter.title

    @property
    def tags(self) -> list[str]:
        return self.frontmatter.tags

    @property
    def all_links(self) -> list[NoteLink]:
        """Explicit then implicit links, in deterministic order."""
        return [*self.explicit_links, *self.implicit_links]


# --- Index models ---


class IndexEntry(BaseModel):
    """One entry in ``.boveda_index.json``."""

    id: str = Field(..., description="Note id")
    title: str = Field(..., description="Note title")
    rel_path: str = Field(..., description="Path relative to the vault root")
    tags: list[str] = Field(default_factory=list, description="Tags attached to the note")
    links: list[str] = Field(default_factory=list, description="Explicit link targets")
    sha256: str = Field(..., description="SHA-256 of the note file")
    mtime_ns: int = Field(..., description="File modification time (ns since epoch)")
    size_bytes: int = Field(default=0, description="File size in bytes")
    deleted: bool = Field(default=False, description="True when the entry is a tombstone")


class VaultIndex(BaseModel):
    """On-disk index file (``.boveda_index.json``) schema."""

    version: int = Field(default=INDEX_VERSION, description="Index format version")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Index build time (UTC)"
    )
    files: dict[str, IndexEntry] = Field(
        default_factory=dict, description="Mapping of note id to index entry"
    )

    def get(self, note_id: str) -> Optional[IndexEntry]:
        """Look up an entry by id, ignoring tombstones."""
        entry = self.files.get(note_id)
        if entry is not None and entry.deleted:
            return None
        return entry


# --- Search models ---


class SearchResult(BaseModel):
    """One search hit, ranked by relevance score."""

    id: str = Field(..., description="Note id")
    title: str = Field(..., description="Note title")
    rel_path: str = Field(..., description="Path relative to the vault root")
    snippet: str = Field(default="", description="Highlighted excerpt around the first match")
    score: float = Field(default=0.0, description="Relevance score (higher is better)")
    tags: list[str] = Field(default_factory=list, description="Note tags")
    matched_terms: list[str] = Field(default_factory=list, description="Query terms that matched")


# --- Graph models ---


class GraphNode(BaseModel):
    """A node in the knowledge graph (one note)."""

    id: str = Field(..., description="Note id")
    title: str = Field(..., description="Note title")
    tags: list[str] = Field(default_factory=list, description="Note tags")
    depth: int = Field(default=0, description="Hop distance from the root note (0 = root or all)")
    is_orphan: bool = Field(default=False, description="True when the note has no links")


class GraphEdge(BaseModel):
    """A directed edge between two graph nodes."""

    source: str = Field(..., description="Source note id")
    target: str = Field(..., description="Target note id")
    kind: LinkKind = Field(default=LinkKind.WIKI_LINK, description="Relationship type")


class GraphStats(BaseModel):
    """Aggregate statistics of a knowledge graph."""

    node_count: int = Field(default=0, description="Number of nodes")
    edge_count: int = Field(default=0, description="Number of edges")
    orphan_count: int = Field(default=0, description="Number of orphan nodes")
    broken_link_count: int = Field(default=0, description="Number of edges to missing notes")
    average_degree: float = Field(default=0.0, description="Mean node degree")


class KnowledgeGraph(BaseModel):
    """The vault knowledge graph, exportable as json/graphml/dot/markdown."""

    nodes: list[GraphNode] = Field(default_factory=list, description="Graph nodes")
    edges: list[GraphEdge] = Field(default_factory=list, description="Graph edges")
    stats: GraphStats = Field(
        default_factory=GraphStats, description="Graph aggregates"
    )
    root_note_id: Optional[str] = Field(
        default=None, description="Note id the graph was expanded from (max_depth)"
    )


# --- Stats models ---


class VaultStats(BaseModel):
    """Aggregate statistics of the vault (boveda.stats)."""

    total_notes: int = Field(default=0, description="Number of indexed notes")
    total_words: int = Field(default=0, description="Total words across note bodies")
    total_links: int = Field(default=0, description="Total explicit links")
    broken_links: int = Field(default=0, description="Links whose target is missing")
    orphan_notes: int = Field(default=0, description="Notes with no links in or out")
    notes_by_tag: dict[str, int] = Field(default_factory=dict, description="Tag -> note count")
    notes_by_dir: dict[str, int] = Field(default_factory=dict, description="Rel dir -> note count")
    notes_by_year: dict[int, int] = Field(default_factory=dict, description="Year -> note count")
    index_updated_at: Optional[datetime] = Field(
        default=None, description="Timestamp of the index the stats were computed from"
    )


# --- Validation models ---


class ValidationIssue(BaseModel):
    """One finding from a vault validation pass."""

    note_id: Optional[str] = Field(default=None, description="Affected note id, if any")
    rel_path: Optional[str] = Field(default=None, description="Affected file, if any")
    severity: IssueSeverity = Field(
        default=IssueSeverity.ERROR, description="Severity of the finding"
    )
    code: str = Field(..., description="Machine-readable code (boveda error table)")
    message: str = Field(..., description="Human-readable description")
    field: Optional[str] = Field(default=None, description="Frontmatter field, when applicable")


class ValidationReport(BaseModel):
    """Full result of ``boveda.validate``."""

    valid: bool = Field(..., description="True when no ERROR-severity issues exist")
    issues: list[ValidationIssue] = Field(default_factory=list, description="All findings")
    notes_checked: int = Field(default=0, description="Number of notes inspected")

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)


# --- Change tracking ---


class VaultChange(BaseModel):
    """One mutation recorded during a vault operation."""

    operation: VaultChangeOperation = Field(..., description="What changed")
    note_id: str = Field(..., description="Affected note id")
    rel_path: Optional[str] = Field(default=None, description="Affected file, if any")
    detail: str = Field(default="", description="Human-readable detail")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Change time (UTC)"
    )


class VaultOperationResult(BaseModel):
    """Standard result envelope for all boveda actions (``success`` + ``data``)."""

    success: bool = Field(..., description="True when the action completed")
    data: dict[str, Any] = Field(default_factory=dict, description="Action-specific payload")
    changes: list[VaultChange] = Field(default_factory=list, description="Mutations applied")
    error: Optional[str] = Field(default=None, description="Error message when success is False")
    error_code: Optional[str] = Field(
        default=None, description="Machine-readable error code from the boveda error table"
    )

    @classmethod
    def ok(cls, data: Optional[dict[str, Any]] = None) -> "VaultOperationResult":
        return cls(success=True, data=data or {})

    @classmethod
    def failed(
        cls, err: VaultError, data: Optional[dict[str, Any]] = None
    ) -> "VaultOperationResult":
        return cls(
            success=False,
            data=data or {},
            error=str(err),
            error_code=err.code,
        )


__all__ = [
    "DEFAULT_SNIPPET_CHARS",
    "INDEX_VERSION",
    "GraphEdge",
    "GraphFormat",
    "GraphNode",
    "GraphStats",
    "IndexEntry",
    "IssueSeverity",
    "KnowledgeGraph",
    "LinkKind",
    "MAX_GRAPH_DEPTH",
    "MAX_SEARCH_RESULTS",
    "NoteFrontmatter",
    "NoteLink",
    "NOTE_ID_RE",
    "SearchResult",
    "VaultAction",
    "VaultBrokenLinkError",
    "VaultChange",
    "VaultChangeOperation",
    "VaultDuplicateIdError",
    "VaultError",
    "VaultIndex",
    "VaultIndexCorruptError",
    "VaultInvalidFrontmatterError",
    "VaultNote",
    "VaultOperationResult",
    "VaultParseError",
    "VaultStats",
    "VaultWriteError",
    "ValidationIssue",
    "ValidationReport",
    "WIKILINK_RE",
]

"""Vault subsystem: indexer, search, knowledge graph, stats and validation.

Exposes the public API for the boveda Zettelkasten vault::

    from jarvis_os.vault import (
        KnowledgeGraphBuilder,
        VaultIndexer,
        VaultSearch,
        VaultStatsComputer,
        VaultValidator,
        VaultNote,
        VaultIndex,
        VaultOperationResult,
    )

The subsystem is pure logic with no IO on import; callers wire the indexer,
search, graph, stats, validator and link services together (typically via
the boveda skill service layer).
"""

from __future__ import annotations

from jarvis_os.vault.models import (
    DEFAULT_SNIPPET_CHARS,
    INDEX_VERSION,
    GraphEdge,
    GraphFormat,
    GraphNode,
    GraphStats,
    IndexEntry,
    IssueSeverity,
    KnowledgeGraph,
    LinkKind,
    MAX_GRAPH_DEPTH,
    MAX_SEARCH_RESULTS,
    NoteFrontmatter,
    NoteLink,
    NOTE_ID_RE,
    SearchResult,
    VaultAction,
    VaultBrokenLinkError,
    VaultChange,
    VaultChangeOperation,
    VaultDuplicateIdError,
    VaultError,
    VaultIndex,
    VaultIndexCorruptError,
    VaultInvalidFrontmatterError,
    VaultNote,
    VaultOperationResult,
    VaultParseError,
    VaultStats,
    VaultWriteError,
    ValidationIssue,
    ValidationReport,
    WIKILINK_RE,
)
from jarvis_os.vault.indexer import VaultIndexer
from jarvis_os.vault.output_logger import VaultOutputLogger, parse_output_frontmatter
from jarvis_os.vault.search import VaultSearch
from jarvis_os.vault.graph import KnowledgeGraphBuilder
from jarvis_os.vault.stats import VaultStatsComputer
from jarvis_os.vault.validator import VaultValidator, parse_frontmatter_block
from jarvis_os.vault.links import extract_wikilinks, extract_frontmatter_links, resolve_links, backlinks_for

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
    "KnowledgeGraphBuilder",
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
    "VaultIndexer",
    "VaultNote",
    "VaultOperationResult",
    "VaultOutputLogger",
    "VaultParseError",
    "VaultSearch",
    "VaultStats",
    "VaultStatsComputer",
    "VaultValidator",
    "VaultWriteError",
    "ValidationIssue",
    "ValidationReport",
    "WIKILINK_RE",
    "backlinks_for",
    "extract_frontmatter_links",
    "extract_wikilinks",
    "parse_frontmatter_block",
    "parse_output_frontmatter",
    "resolve_links",
]

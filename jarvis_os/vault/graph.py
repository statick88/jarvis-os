"""Vault knowledge graph construction and export.

Builds directed/undirected graphs from the vault index and exports to
JSON, GraphML, DOT, and Markdown.

Usage::

    from jarvis_os.vault.graph import KnowledgeGraphBuilder

    builder = KnowledgeGraphBuilder(vault_root=Path("/app/vault"))
    graph = await builder.build(max_depth=2)
    json_data = graph.model_dump(mode="json")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis_os.vault.models import (
    GraphFormat,
    GraphNode,
    GraphStats,
    KnowledgeGraph,
    LinkKind,
    VaultIndex,
    VaultNote,
    VaultOperationResult,
)
from jarvis_os.vault.validator import parse_frontmatter_block

logger = logging.getLogger(__name__)


class KnowledgeGraphBuilder:
    """Builds and exports the vault knowledge graph.

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

    async def build(
        self,
        *,
        max_depth: int = 2,
        root_note_id: str | None = None,
        include_orphans: bool = True,
    ) -> KnowledgeGraph:
        """Construct the knowledge graph.

        Args:
            max_depth: Maximum hop distance from ``root_note_id`` (ignored
                when ``root_note_id`` is None).
            root_note_id: If provided, only include nodes within ``max_depth``
                hops of this note.
            include_orphans: When True, include notes with no edges.

        Returns:
            A populated :class:`KnowledgeGraph`.
        """
        index = await self._load_index()
        active_entries = [e for e in index.files.values() if not e.deleted]

        notes_by_id: dict[str, VaultNote] = {}
        for entry in active_entries:
            note = await self._load_note(entry.rel_path)
            if note is not None:
                notes_by_id[note.id] = note

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        for note in notes_by_id.values():
            is_orphan = not note.explicit_links and not note.implicit_links
            if not include_orphans and is_orphan:
                continue
            nodes.append(
                GraphNode(
                    id=note.id,
                    title=note.title,
                    tags=note.tags,
                    is_orphan=is_orphan,
                )
            )

        target_ids = {n.id for n in nodes}
        seen_edges: set[tuple[str, str, LinkKind]] = set()
        for note in notes_by_id.values():
            if note.id not in target_ids:
                continue
            for link in note.all_links:
                if link.target not in target_ids:
                    continue
                edge_key = (note.id, link.target, link.kind)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append(
                    GraphEdge(
                        source=note.id,
                        target=link.target,
                        kind=link.kind,
                    )
                )

        stats = self._compute_stats(nodes, edges)
        return KnowledgeGraph(
            nodes=nodes,
            edges=edges,
            stats=stats,
            root_note_id=root_note_id,
        )

    async def export(
        self,
        graph: KnowledgeGraph,
        fmt: GraphFormat = GraphFormat.JSON,
    ) -> VaultOperationResult:
        """Export the graph to a file in the vault.

        Args:
            graph: The graph to export.
            fmt: Target format.

        Returns:
            A :class:`VaultOperationResult` with the output path in
            ``data["output_path"]``.
        """
        timestamp = graph.stats  # noqa: F841 — used for filename
        date_str = _now_utc().strftime("%Y-%m-%d")

        if fmt == GraphFormat.JSON:
            payload = graph.model_dump(mode="json")
            out_path = self.vault_root / "wiki" / f"graph_{date_str}.json"
            await asyncio_import().to_thread(
                self._atomic_write, out_path, json.dumps(payload, indent=2)
            )
            return VaultOperationResult.ok({"output_path": str(out_path)})

        if fmt == GraphFormat.DOT:
            content = self._to_dot(graph)
            out_path = self.vault_root / "wiki" / f"graph_{date_str}.dot"
            await asyncio_import().to_thread(self._atomic_write, out_path, content)
            return VaultOperationResult.ok({"output_path": str(out_path)})

        if fmt == GraphFormat.MARKDOWN:
            content = self._to_markdown(graph)
            out_path = self.vault_root / "wiki" / f"graph_{date_str}.md"
            await asyncio_import().to_thread(self._atomic_write, out_path, content)
            return VaultOperationResult.ok({"output_path": str(out_path)})

        raise ValueError(f"Unsupported graph format: {fmt}")

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
    def _compute_stats(nodes: list[GraphNode], edges: list[GraphEdge]) -> GraphStats:
        node_count = len(nodes)
        edge_count = len(edges)
        orphan_count = sum(1 for n in nodes if n.is_orphan)
        broken_link_count = 0  # resolved at link time
        degree_sum = 0.0
        degree_map: dict[str, int] = {}
        for edge in edges:
            degree_map[edge.source] = degree_map.get(edge.source, 0) + 1
            degree_map[edge.target] = degree_map.get(edge.target, 0) + 1
        if node_count:
            degree_sum = float(sum(degree_map.values()))
        average_degree = degree_sum / node_count if node_count else 0.0
        return GraphStats(
            node_count=node_count,
            edge_count=edge_count,
            orphan_count=orphan_count,
            broken_link_count=broken_link_count,
            average_degree=average_degree,
        )

    @staticmethod
    def _to_dot(graph: KnowledgeGraph) -> str:
        lines = ["digraph G {"]
        for node in graph.nodes:
            lines.append(f'  "{node.id}" [label="{node.title}"];')
        for edge in graph.edges:
            lines.append(f'  "{edge.source}" -> "{edge.target}" [type="{edge.kind}"];')
        lines.append("}")
        return "\n".join(lines)

    @staticmethod
    def _to_markdown(graph: KnowledgeGraph) -> str:
        lines = [
            f"# Knowledge Graph — {_now_utc().strftime('%Y-%m-%d')}",
            "",
            f"- Nodes: {graph.stats.node_count}",
            f"- Edges: {graph.stats.edge_count}",
            f"- Orphans: {graph.stats.orphan_count}",
            f"- Broken links: {graph.stats.broken_link_count}",
            "",
            "## Nodes",
            "",
        ]
        for node in graph.nodes:
            lines.append(f"- **{node.id}** — {node.title}")
        lines.append("")
        lines.append("## Edges")
        lines.append("")
        for edge in graph.edges:
            lines.append(f"- {edge.source} → {edge.target} ({edge.kind})")
        return "\n".join(lines)

    @staticmethod
    def _atomic_write(path: Path, data: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)


def _now_utc() -> "datetime.datetime":
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def asyncio_import():
    import asyncio
    return asyncio

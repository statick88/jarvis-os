"""Regression tests for the vault graph exporter.

Two latent defects lived here:

1. ``json`` was never imported at module scope, so the ``GraphFormat.JSON`` branch
   called ``json.dumps`` and raised ``NameError`` at export time. The default
   ``fmt`` for ``export`` is ``GraphFormat.JSON``, so the default export path was
   broken.
2. ``GraphEdge`` was referenced in annotations without being imported, and
   ``_now_utc`` annotated its return as ``"datetime.datetime"`` while only
   importing ``datetime`` inside the function body. Both survive at runtime
   because the module uses ``from __future__ import annotations``, but
   ``typing.get_type_hints()`` on either would fail.

These are cheap guards: they cost nothing and pin the two names in place.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest

from jarvis_os.vault import graph as graph_module
from jarvis_os.vault.models import GraphFormat, KnowledgeGraph
from jarvis_os.vault.validator import parse_frontmatter_block


def _builder(vault: Path):
    return graph_module.KnowledgeGraphBuilder(vault_root=vault)


class TestModuleNames:
    def test_json_is_imported_at_module_scope(self) -> None:
        assert hasattr(graph_module, "json"), (
            "graph.py must import json at module level; the JSON export branch "
            "calls json.dumps and would raise NameError"
        )

    def test_annotations_resolve(self) -> None:
        """get_type_hints resolves lazily-created annotations; it catches
        annotation-only names that never get flagged at runtime."""
        assert typing.get_type_hints(graph_module._now_utc)["return"] is not None

    def test_parse_frontmatter_block_is_importable(self) -> None:
        assert callable(parse_frontmatter_block)


class TestJsonExport:
    @pytest.mark.asyncio
    async def test_export_to_json_writes_valid_json(self, tmp_path: Path) -> None:
        builder = _builder(tmp_path)
        graph = KnowledgeGraph()

        result = await builder.export(graph, GraphFormat.JSON)

        assert result.success is True, result.error
        out = Path(result.data["output_path"])
        assert out.exists()
        assert out.name.endswith(".json")

        # Must be parseable, which it cannot be if json.dumps raised.
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        assert "nodes" in loaded
        assert "edges" in loaded

    @pytest.mark.asyncio
    async def test_json_is_the_default_format(self, tmp_path: Path) -> None:
        """The default fmt is JSON, so the default call must not raise."""
        builder = _builder(tmp_path)

        result = await builder.export(KnowledgeGraph())

        assert result.success is True, result.error

    @pytest.mark.asyncio
    async def test_export_never_leaks_a_nameerror(self, tmp_path: Path) -> None:
        result = await _builder(tmp_path).export(KnowledgeGraph(), GraphFormat.JSON)

        assert "is not defined" not in str(result.error or "")


class TestNowUtc:
    def test_returns_timezone_aware_datetime(self) -> None:
        value = graph_module._now_utc()

        assert value.tzinfo is not None

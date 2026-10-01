"""Regression tests for the hours_back window in the tendencias handler.

``hours_back`` is declared in ``.skills/tendencias.md`` (integer, minimum 1,
maximum 168, default 24) and the module docstring shows it being passed::

    tendencias.run({"action": "fetch", "hours_back": 24})

The handler read the value into a local and never used it, so every item of
every age was processed. A caller narrowing the window got the same result as
one not narrowing it, with no error and no signal.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from jarvis_os.skills.handlers import tendencias as t

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def _rfc822(delta: timedelta) -> str:
    return (NOW - delta).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _iso(delta: timedelta) -> str:
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed_xml(items: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<item><title>{title}</title><link>u</link>"
        f"<pubDate>{published}</pubDate>"
        f"<description>keyword</description></item>"
        for title, published in items
    )
    return f"<rss><channel>{body}</channel></rss>"


class TestParsePublished:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Tue, 01 Oct 2026 10:00:00 GMT", datetime(2026, 10, 1, 10, tzinfo=timezone.utc)),
            ("2026-10-01T10:00:00Z", datetime(2026, 10, 1, 10, tzinfo=timezone.utc)),
            (
                "2026-10-01T10:00:00+02:00",
                datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
            ),
        ],
    )
    def test_rss_and_atom_formats(self, raw: str, expected: datetime) -> None:
        assert t._parse_published(raw) == expected

    def test_named_zone_is_converted_to_utc(self) -> None:
        """10:00 EST is 15:00 UTC; a naive compare would be 5h wrong."""
        assert t._parse_published("Wed, 02 Oct 2024 10:00:00 EST") == datetime(
            2024, 10, 2, 15, tzinfo=timezone.utc
        )

    def test_naive_datetime_is_assumed_utc(self) -> None:
        assert t._parse_published("2026-10-01 10:00:00") == datetime(
            2026, 10, 1, 10, tzinfo=timezone.utc
        )

    @pytest.mark.parametrize("raw", ["", "   ", "no es una fecha", "ayer"])
    def test_unparseable_returns_none(self, raw: str) -> None:
        assert t._parse_published(raw) is None

    def test_result_is_always_aware(self) -> None:
        for raw in ("Tue, 01 Oct 2026 10:00:00 GMT", "2026-10-01T10:00:00Z", "2026-10-01 10:00"):
            parsed = t._parse_published(raw)
            assert parsed is not None
            assert parsed.tzinfo is not None


class TestIsWithinWindow:
    def test_fresh_item_is_kept(self) -> None:
        cutoff = NOW - timedelta(hours=24)
        assert t._is_within_window({"published": _rfc822(timedelta(hours=2))}, cutoff)

    def test_stale_item_is_dropped(self) -> None:
        cutoff = NOW - timedelta(hours=24)
        assert not t._is_within_window({"published": _rfc822(timedelta(days=9))}, cutoff)

    def test_undated_item_is_kept(self) -> None:
        """Fail open: a feed that omits dates must not be silently emptied."""
        cutoff = NOW - timedelta(hours=24)
        assert t._is_within_window({"published": ""}, cutoff)
        assert t._is_within_window({}, cutoff)
        assert t._is_within_window({"published": "basura"}, cutoff)

    def test_boundary_is_inclusive(self) -> None:
        cutoff = NOW - timedelta(hours=24)
        assert t._is_within_window({"published": _iso(timedelta(hours=24))}, cutoff)


class TestFetchAppliesTheWindow:
    """These drive ``_fetch`` itself with a stubbed transport.

    The first version of this class re-implemented the filtering inside the test
    body, so it kept passing when the filter was removed from the handler -- a
    test that cannot fail is not a test. Everything here goes through the real
    code path.
    """

    @staticmethod
    def _patch_fetch(monkeypatch: pytest.MonkeyPatch, xml: str) -> list[dict[str, Any]]:
        """Stub the network, record the feeds the handler actually fetched."""
        fetched: list[dict[str, Any]] = []

        class _Resp:
            def read(self) -> bytes:
                return xml.encode("utf-8")

            def __enter__(self) -> _Resp:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        def _urlopen(req: Any, timeout: int = 10) -> _Resp:
            fetched.append({"url": getattr(req, "full_url", str(req))})
            return _Resp()

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
        return fetched

    def test_stale_items_are_excluded_from_the_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        stale = (now - timedelta(days=9)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        xml = _feed_xml([("reciente", fresh), ("antiguo", stale)])
        self._patch_fetch(monkeypatch, xml)

        result = t.run(
            {
                "action": "fetch",
                "context": {"vault_path": str(tmp_path)},
                "feed_urls": ["https://example.test/rss"],
                "hours_back": 24,
                "min_relevance_score": 0.0,
                "enqueue_async": False,
            }
        )

        assert result["success"] is True
        assert result["data"]["skipped_stale_count"] == 1
        assert result["data"]["fetched_count"] == 1
        titles = [topic["topic"] for topic in result["data"]["top_topics"]]
        assert "antiguo" not in titles

    def test_a_wider_window_brings_the_old_item_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The widest window the schema allows is 168h (7 days), so a 5-day-old
        item is excluded at 24h and included at the maximum."""
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        five_days = (now - timedelta(days=5)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        xml = _feed_xml([("reciente", fresh), ("cinco dias", five_days)])
        self._patch_fetch(monkeypatch, xml)

        narrow = t.run(
            {
                "action": "fetch",
                "context": {"vault_path": str(tmp_path)},
                "feed_urls": ["https://example.test/rss"],
                "hours_back": 24,
                "min_relevance_score": 0.0,
                "enqueue_async": False,
            }
        )
        wide = t.run(
            {
                "action": "fetch",
                "context": {"vault_path": str(tmp_path)},
                "feed_urls": ["https://example.test/rss"],
                "hours_back": 168,
                "min_relevance_score": 0.0,
                "enqueue_async": False,
            }
        )

        assert narrow["data"]["skipped_stale_count"] == 1
        assert narrow["data"]["fetched_count"] == 1
        assert wide["data"]["skipped_stale_count"] == 0
        assert wide["data"]["fetched_count"] == 2

    def test_hours_back_is_reported_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ignored window must be visible, not silent."""
        self._patch_fetch(monkeypatch, _feed_xml([]))

        result = t.run(
            {
                "action": "fetch",
                "context": {"vault_path": str(tmp_path)},
                "feed_urls": ["https://example.test/rss"],
                "hours_back": 6,
            }
        )

        assert result["data"]["hours_back"] == 6

    def test_undated_items_survive_and_are_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail open: a feed without dates must not be silently emptied."""
        xml = (
            "<rss><channel><item><title>sin fecha</title><link>u</link>"
            "<description>kw</description></item></channel></rss>"
        )
        self._patch_fetch(monkeypatch, xml)

        result = t.run(
            {
                "action": "fetch",
                "context": {"vault_path": str(tmp_path)},
                "feed_urls": ["https://example.test/rss"],
                "hours_back": 1,
                "min_relevance_score": 0.0,
                "enqueue_async": False,
            }
        )

        assert result["data"]["skipped_stale_count"] == 0
        assert result["data"]["fetched_count"] == 1
        assert result["data"]["undated_count"] == 1

    def test_filter_runs_before_max_items(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Slicing first would let stale items consume the budget and evict fresh
        ones, making max_items mean "first N regardless of age"."""
        now = datetime.now(timezone.utc)
        stale = [
            (f"stale{i}", (now - timedelta(days=5)).strftime("%a, %d %b %Y %H:%M:%S GMT"))
            for i in range(5)
        ]
        fresh = [
            (f"fresh{i}", (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT"))
            for i in range(3)
        ]
        self._patch_fetch(monkeypatch, _feed_xml(stale + fresh))

        result = t.run(
            {
                "action": "fetch",
                "context": {"vault_path": str(tmp_path)},
                "feed_urls": ["https://example.test/rss"],
                "hours_back": 24,
                "max_items_per_feed": 3,
                "min_relevance_score": 0.0,
                "enqueue_async": False,
            }
        )

        # Three fresh items exist; a stale-first slice would have returned 0.
        assert result["data"]["fetched_count"] == 3
        assert result["data"]["skipped_stale_count"] == 5


class TestHoursBackIsNotDeadCode:
    def test_local_is_consumed(self) -> None:
        """Direct guard on the original defect: the value must reach the cutoff.

        Reverting the fix makes this fail because hours_back is read and then
        discarded, leaving the loop with no window at all.
        """
        import inspect

        source = inspect.getsource(t._fetch)

        assert "cutoff" in source, "_fetch must build a cutoff from hours_back"
        assert "_is_within_window" in source, (
            "_fetch must apply the window to each item; reading hours_back and "
            "ignoring it was the original bug"
        )

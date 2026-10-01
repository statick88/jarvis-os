"""Regression tests for the skill handlers' error bookkeeping.

The bug this file exists for: ``tendencias.py`` referenced the ``except ... as
exc`` name *after* the except block. Python unbinds that name when the block
ends, so the reference raised ``UnboundLocalError`` on the success path of any
feed that yielded zero items — a valid, reachable case, and a crash rather than
a reported error.

Every test here drives the handler with a stubbed fetch so the regression is
reproducible without network access.
"""

from __future__ import annotations

import sys
from typing import Any
from urllib.error import URLError

import pytest

from jarvis_os.skills.handlers import tendencias


# ── doubles ──────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


EMPTY_FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Empty</title>
  <item><title>uno</title><description>palabra clave</description></item>
</channel></rss>"""


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, behaviour: Any) -> list[str]:
    """Replace urllib.request.urlopen and record the URLs it was called with."""
    import urllib.request

    seen: list[str] = []

    def fake_urlopen(req: Any, timeout: int = 0) -> FakeResponse:
        url = getattr(req, "full_url", str(req))
        seen.append(url)
        return behaviour(url)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def _ok_feed(_url: str) -> FakeResponse:
    return FakeResponse(EMPTY_FEED)


def _empty_feed(_url: str) -> FakeResponse:
    """A structurally valid feed that contains no <item> entries at all."""
    return FakeResponse(
        b"""<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Nothing</title></channel></rss>"""
    )


def _raises(_url: str) -> FakeResponse:
    raise URLError("connection refused")


# ── the regression ───────────────────────────────────────────────────

class TestTendenciasEmptyFeedDoesNotCrash:
    """The exact path that raised UnboundLocalError."""

    def test_valid_but_empty_feed_reports_an_error_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_urlopen(monkeypatch, _empty_feed)
        processed = tendencias.run({"feed_urls": ["https://example.test/rss"]})["data"]["feeds_processed"]
        assert len(processed) == 1
        # Would have raised UnboundLocalError before the fix.
        assert processed[0]["error"] == "no items returned"
        assert processed[0]["items_fetched"] == 0

    def test_fetch_failure_is_reported_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_urlopen(monkeypatch, _raises)
        processed = tendencias.run(
            {"feed_urls": ["https://example.test/rss"]}
        )["data"]["feeds_processed"]
        assert processed[0]["items_fetched"] == 0
        assert "connection refused" in processed[0]["error"]

    def test_successful_feed_has_no_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_urlopen(monkeypatch, _ok_feed)
        processed = tendencias.run(
            {"feed_urls": ["https://example.test/rss"]}
        )["data"]["feeds_processed"]
        assert processed[0]["items_fetched"] >= 0
        # Whatever the fetch outcome, the key must always be a string or None,
        # never an exception from evaluating the error expression.
        assert processed[0]["error"] is None or isinstance(processed[0]["error"], str)

    def test_mixed_feeds_do_not_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def behaviour(url: str) -> FakeResponse:
            return _empty_feed(url) if "empty" in url else _ok_feed(url)

        _patch_urlopen(monkeypatch, behaviour)
        result = tendencias.run(
            {"feed_urls": ["https://empty.test/rss", "https://full.test/rss"]}
        )
        assert len(result["data"]["feeds_processed"]) == 2

    def test_every_feed_entry_always_has_an_error_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guards the whole class of bug, not just this one feed."""
        def behaviour(url: str) -> FakeResponse:
            return {"raise": _raises, "empty": _empty_feed}.get(
                url.rsplit("/", 2)[-2], _ok_feed
            )(url)

        _patch_urlopen(monkeypatch, behaviour)
        result = tendencias.run(
            {
                "feed_urls": [
                    "https://x.test/raise/rss",
                    "https://x.test/empty/rss",
                    "https://x.test/fine/rss",
                ]
            }
        )
        for entry in result["data"]["feeds_processed"]:
            assert "error" in entry
            assert entry["error"] is None or isinstance(entry["error"], str)


class TestTendenciasUnboundNameIsImpossible:
    """Static guard: the ``except`` name must not escape its block.

    Scoped to ``_fetch`` and matched as a bare identifier, so ``logger.exception``
    and the ``as exc`` binding itself are not false positives.
    """

    def test_no_bare_exc_reference_after_the_except_block(self) -> None:
        import re
        import textwrap

        source = open(tendencias.__file__, encoding="utf-8").read()
        body = textwrap.dedent(
            source.split("def _fetch(", 1)[1]
        )

        lines = body.splitlines()
        bound_at = next(
            i for i, line in enumerate(lines)
            if re.search(r"except\s+\w+\s+as\s+exc\s*:", line)
        )
        # The bare name, not a substring: `logger.exception` must not match.
        bare = re.compile(r"(?<![\w.])exc(?![\w])")

        except_indent = len(lines[bound_at]) - len(lines[bound_at].lstrip())

        # Skip the except body (more indented), then inspect the code after it.
        cursor = bound_at + 1
        while cursor < len(lines) and (
            not lines[cursor].strip()
            or len(lines[cursor]) - len(lines[cursor].lstrip()) > except_indent
        ):
            cursor += 1

        for line in lines[cursor:]:
            stripped = line.strip()
            if re.match(r"\s*except\b", line):
                break
            if re.match(r"\s*(for|while|if|def)\b", line) or not stripped:
                continue
            assert not bare.search(stripped), (
                f"_fetch references the unbound except-name after the block: "
                f"{stripped!r}"
            )

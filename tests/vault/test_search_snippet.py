"""Regression tests for the vault search snippet window.

``VaultSearch._snippet`` declared a ``best_count`` local, initialised it to -1
and never updated it, while anchoring the window with ``max(best_pos, idx)``
over every hit. The result was that the snippet was always centred on the *last*
match in the document, no matter how sparse that region was, and the intended
"densest cluster" behaviour did not exist.

The tie-break is to the earliest qualifying position so output is deterministic,
which matters because search results feed the receipt chain and the golden
comparison downstream.
"""

from __future__ import annotations

import pytest

from jarvis_os.vault.search import VaultSearch

FILLER = "lorem ipsum dolor sit amet " * 12


def _densest(text: str, terms: list[str], window: int = 60) -> int:
    return text.count(terms[0])


class TestAnchorsOnTheDensestCluster:
    def test_late_cluster_beats_an_earlier_single_hit(self) -> None:
        content = FILLER + "alpha " + "ruido " * 10 + " beta gamma beta gamma beta gamma beta"

        out = VaultSearch._snippet(content, ["beta", "gamma", "alpha"], window=60)

        assert out.count("beta") >= 3, out
        assert "alpha" not in out, "a single early hit must not win over a cluster"

    def test_ignores_a_hit_far_earlier_in_the_document(self) -> None:
        early = "zzz " * 40
        late = "beta beta beta beta"
        content = early + "relleno " * 20 + late

        out = VaultSearch._snippet(content, ["beta"], window=40)

        assert out.count("beta") == 4, out


class TestPreviousBehaviourIsGone:
    def test_does_not_anchor_to_the_last_match(self) -> None:
        """The old code took max(best_pos) over every hit, so a lone early hit
        lost to any later hit. With a single term there is no cluster to
        prefer, so the only hit must be the one returned."""
        content = "beta " + "x " * 200 + "gamma"

        out = VaultSearch._snippet(content, ["beta"], window=30)

        assert "beta" in out
        assert "gamma" not in out, "a term that never matched must not appear"


class TestEdgeCases:
    def test_no_hits_returns_the_head(self) -> None:
        assert VaultSearch._snippet("contenido", ["nada"], window=40) == "contenido"

    def test_short_content_is_returned_intact(self) -> None:
        assert VaultSearch._snippet("beta gamma", ["beta"], window=100) == "beta gamma"

    def test_empty_term_is_ignored_not_infinite_looped(self) -> None:
        """An empty needle would match at every offset and loop forever."""
        assert VaultSearch._snippet("abc", [""], window=10) == "abc"

    def test_no_terms_returns_the_head(self) -> None:
        # No hits at all, so the head of the content truncated to the window.
        assert VaultSearch._snippet("contenido largo", [], window=10) == "contenido "

    def test_window_is_respected(self) -> None:
        content = FILLER + "beta " * 50
        out = VaultSearch._snippet(content, ["beta"], window=40)
        # Content plus the two optional ellipsis markers.
        assert len(out) <= 46, len(out)

    def test_start_of_document_has_no_leading_ellipsis(self) -> None:
        out = VaultSearch._snippet("beta " + "x" * 200, ["beta"], window=50)
        assert not out.startswith("..."), out

    def test_end_of_document_has_no_trailing_ellipsis(self) -> None:
        out = VaultSearch._snippet("x" * 200 + " beta", ["beta"], window=50)
        assert not out.endswith("..."), out

    def test_case_insensitive(self) -> None:
        out = VaultSearch._snippet(FILLER + "BETA BETA BETA", ["beta"], window=40)
        assert "BETA" in out

    def test_overlapping_matches_are_counted(self) -> None:
        content = "aaaa " * 30
        out = VaultSearch._snippet(content, ["aa"], window=30)
        assert out.count("a") > 1


class TestDeterminism:
    def test_repeated_calls_are_identical(self) -> None:
        content = FILLER + "beta gamma " * 5
        results = {
            VaultSearch._snippet(content, ["beta", "gamma"], window=60) for _ in range(10)
        }
        assert len(results) == 1, "snippet generation must be deterministic"

    def test_ties_resolve_to_the_earliest_cluster(self) -> None:
        """Two clusters of equal density: the earlier one must win, so the same
        document always yields the same snippet."""
        content = FILLER + "beta " * 3 + "y " * 100 + "beta " * 3
        first = VaultSearch._snippet(content, ["beta"], window=40)
        second = VaultSearch._snippet(content, ["beta"], window=40)
        assert first == second

    @pytest.mark.parametrize("window", [10, 25, 50, 100, 250])
    def test_never_crashes_across_window_sizes(self, window: int) -> None:
        content = FILLER + "beta gamma beta " * 5
        out = VaultSearch._snippet(content, ["beta", "gamma"], window=window)
        assert isinstance(out, str)
        assert len(out) <= window + 6

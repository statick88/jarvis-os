"""Tests for ``jarvis_os.policy`` — the ODD feedback layer.

The central claim under test: **the policy learns only from verified receipt
chains, and a tampered chain is treated as no evidence at all.** Everything else
(minimum samples, neutral prior, shadow mode) exists to make that claim safe in
the presence of noise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jarvis_os import policy
from jarvis_os.policy import (
    MIN_SAMPLES,
    NEUTRAL_SCORE,
    ToolStats,
    collect_stats,
    dump_stats,
    observe_skills,
    policy_mode,
    rank_candidates,
    recommend,
    score_for,
    suggest_timeout,
)
from jarvis_os.receipt import Receipt, ReceiptChain, run_directory


# ── helpers ──────────────────────────────────────────────────────────

def _day(root: Path, day: str = "2026-10-01") -> ReceiptChain:
    run_dir = root / day
    run_dir.mkdir(parents=True, exist_ok=True)
    return ReceiptChain(run_dir)


def _fill(chain: ReceiptChain, tool: str, *, successes: int, failures: int = 0,
          timeouts: int = 0, duration_ms: float = 100.0) -> None:
    for _ in range(successes):
        chain.append(
            Receipt(tool_name=tool, status="success", execution_time_ms=duration_ms)
        )
    for _ in range(failures):
        chain.append(
            Receipt(tool_name=tool, status="failed", execution_time_ms=duration_ms,
                    error="boom")
        )
    for _ in range(timeouts):
        chain.append(
            Receipt(tool_name=tool, status="timeout", execution_time_ms=duration_ms)
        )


class FakeFrontmatter:
    def __init__(self, capabilities: list[str]) -> None:
        self.capabilities = capabilities


class FakeSkill:
    def __init__(self, skill_id: str, capabilities: list[str]) -> None:
        self.id = skill_id
        self.frontmatter = FakeFrontmatter(capabilities)


class FakeRegistry:
    def __init__(self, skills: list[FakeSkill]) -> None:
        self._skills = skills

    def list_all(self) -> list[FakeSkill]:
        return self._skills


# ── mode ─────────────────────────────────────────────────────────────

class TestMode:
    def test_shadow_by_default(self) -> None:
        assert policy_mode() == "shadow"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JARVIS_POLICY_MODE", "active")
        assert policy_mode() == "active"

    def test_shadow_returns_registry_order_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_POLICY_MODE", "shadow")
        stats = {"b": _stats("b", runs=10, successes=1),
                 "a": _stats("a", runs=10, successes=10)}
        assert recommend(stats, ["a", "b"]) == ["a", "b"]

    def test_active_applies_the_ranking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JARVIS_POLICY_MODE", "active")
        stats = {"b": _stats("b", runs=10, successes=1),
                 "a": _stats("a", runs=10, successes=10)}
        assert recommend(stats, ["a", "b"]) == ["a", "b"]  # a already first

    def test_active_reorders_towards_reliability(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_POLICY_MODE", "active")
        stats = {"broken": _stats("broken", runs=10, successes=0),
                 "solid": _stats("solid", runs=10, successes=10)}
        assert recommend(stats, ["broken", "solid"]) == ["solid", "broken"]


def _stats(skill_id: str, *, runs: int, successes: int,
           p95_ms: float = 100.0) -> ToolStats:
    failures = runs - successes
    return ToolStats(
        skill_id=skill_id, runs=runs, successes=successes, failures=failures,
        timeouts=0, p95_ms=p95_ms, median_ms=p95_ms,
        failure_rate=round(1 - successes / runs, 4),
    )


# ── statistics ───────────────────────────────────────────────────────

class TestCollectStats:
    def test_empty_root(self, tmp_path: Path) -> None:
        assert collect_stats(tmp_path) == {}

    def test_aggregates_per_skill(self, tmp_path: Path) -> None:
        chain = _day(tmp_path)
        _fill(chain, "skill.a", successes=8, failures=2)
        stats = collect_stats(tmp_path)
        assert set(stats) == {"skill.a"}
        assert stats["skill.a"].runs == 10
        assert stats["skill.a"].successes == 8
        assert stats["skill.a"].failures == 2
        assert stats["skill.a"].reliability == 0.8

    def test_counts_timeouts_separately(self, tmp_path: Path) -> None:
        chain = _day(tmp_path)
        _fill(chain, "skill.a", successes=5, timeouts=5)
        stat = collect_stats(tmp_path)["skill.a"]
        assert stat.timeouts == 5
        assert stat.successes == 5
        assert stat.failure_rate == 0.5

    def test_spans_multiple_day_directories(self, tmp_path: Path) -> None:
        _fill(_day(tmp_path, "2026-10-01"), "skill.a", successes=3)
        _fill(_day(tmp_path, "2026-10-02"), "skill.a", successes=2)
        assert collect_stats(tmp_path)["skill.a"].runs == 5

    def test_percentiles(self, tmp_path: Path) -> None:
        chain = _day(tmp_path)
        for i in range(1, 11):
            chain.append(
                Receipt(tool_name="skill.a", status="success", execution_time_ms=float(i * 100))
            )
        stat = collect_stats(tmp_path)["skill.a"]
        assert stat.p95_ms == 1000.0
        assert stat.median_ms == 550.0

    def test_ignores_ignorable_directories(self, tmp_path: Path) -> None:
        chain = _day(tmp_path)
        _fill(chain, "skill.a", successes=3)
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "index.jsonl").write_text("garbage\n")
        assert collect_stats(tmp_path)["skill.a"].runs == 3


# ── the tamper story ─────────────────────────────────────────────────

class TestTamperResistance:
    """A forged chain must contribute nothing, not a wrong answer."""

    def _tamper(self, tmp_path: Path) -> None:
        # A mixed history, so the forgery actually changes something.
        chain = _day(tmp_path)
        _fill(chain, "skill.good", successes=9, failures=1)
        path = tmp_path / "2026-10-01" / "index.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        # Forge: claim every failed run was actually a success, without fixing hashes.
        for record in records:
            if record["receipt"]["status"] != "success":
                record["receipt"]["status"] = "success"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))

    def test_forged_chain_is_excluded_entirely(self, tmp_path: Path) -> None:
        self._tamper(tmp_path)
        assert collect_stats(tmp_path) == {}

    def test_a_good_day_still_teaches_when_another_is_forged(
        self, tmp_path: Path
    ) -> None:
        _fill(_day(tmp_path, "2026-10-02"), "skill.honest", successes=6)
        self._tamper(tmp_path)  # poisons 2026-10-01
        stats = collect_stats(tmp_path)
        assert "skill.honest" in stats
        assert "skill.good" not in stats

    def test_forgery_is_logged_as_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._tamper(tmp_path)
        with caplog.at_level("WARNING", logger="jarvis_os.policy"):
            collect_stats(tmp_path)
        assert any("rejected as untrustworthy" in r.getMessage() for r in caplog.records)

    def test_forged_success_cannot_promote_a_broken_skill(
        self, tmp_path: Path
    ) -> None:
        """The scenario the tamper story exists for: inflate a broken skill."""
        chain = _day(tmp_path)
        _fill(chain, "skill.broken", successes=0, failures=8)
        path = tmp_path / "2026-10-01" / "index.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        for record in records:
            record["receipt"]["status"] = "success"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))

        stats = collect_stats(tmp_path)
        # No evidence at all, so the neutral prior applies instead of a forged 1.0.
        assert "skill.broken" not in stats
        assert score_for(stats, "skill.broken") == NEUTRAL_SCORE

    def test_truncated_file_is_rejected_not_crashed(self, tmp_path: Path) -> None:
        chain = _day(tmp_path)
        _fill(chain, "skill.a", successes=3)
        with (tmp_path / "2026-10-01" / "index.jsonl").open("a") as handle:
            handle.write('{"receipt": {"seq": 4, "ha\n')
        assert collect_stats(tmp_path) == {}


# ── scoring ──────────────────────────────────────────────────────────

class TestScoring:
    def test_unknown_skill_is_neutral(self) -> None:
        assert score_for({}, "never-seen") == NEUTRAL_SCORE

    def test_below_min_samples_is_neutral(self) -> None:
        stat = _stats("skill.a", runs=MIN_SAMPLES - 1, successes=MIN_SAMPLES - 1)
        assert score_for({"skill.a": stat}, "skill.a") == NEUTRAL_SCORE

    def test_at_min_samples_the_score_applies(self) -> None:
        stat = _stats("skill.a", runs=MIN_SAMPLES, successes=MIN_SAMPLES)
        assert score_for({"skill.a": stat}, "skill.a") == 1.0

    def test_always_failing_skill_stays_neutral(self) -> None:
        """100% failure carries no reliability information, only absence."""
        stat = _stats("skill.a", runs=10, successes=0)
        assert stat.usable is False
        assert score_for({"skill.a": stat}, "skill.a") == NEUTRAL_SCORE

    def test_mixed_skill_scores_proportionally(self) -> None:
        stat = _stats("skill.a", runs=10, successes=7)
        assert score_for({"skill.a": stat}, "skill.a") == 0.7


class TestRanking:
    def test_orders_by_reliability(self) -> None:
        stats = {
            "c": _stats("c", runs=10, successes=5),
            "a": _stats("a", runs=10, successes=10),
            "b": _stats("b", runs=10, successes=8),
        }
        assert rank_candidates(stats, ["c", "a", "b"]) == [
            ("a", 1.0), ("b", 0.8), ("c", 0.5)
        ]

    def test_ties_break_alphabetically_for_determinism(self) -> None:
        stats = {
            "z": _stats("z", runs=10, successes=10),
            "a": _stats("a", runs=10, successes=10),
        }
        assert [s for s, _ in rank_candidates(stats, ["z", "a"])] == ["a", "z"]

    def test_unknown_candidates_tie_at_neutral(self) -> None:
        ranked = rank_candidates({}, ["x", "y"])
        assert ranked == [("x", NEUTRAL_SCORE), ("y", NEUTRAL_SCORE)]


class TestTimeoutSuggestion:
    def test_no_evidence_returns_none(self) -> None:
        assert suggest_timeout({}, "skill.a") is None

    def test_too_few_samples_returns_none(self) -> None:
        stat = _stats("skill.a", runs=2, successes=2, p95_ms=5000)
        assert suggest_timeout({"skill.a": stat}, "skill.a") is None

    def test_scales_p95_with_headroom(self) -> None:
        stat = _stats("skill.a", runs=10, successes=10, p95_ms=2000)
        assert suggest_timeout({"skill.a": stat}, "skill.a") == 5

    def test_never_suggests_zero(self) -> None:
        stat = _stats("skill.a", runs=10, successes=10, p95_ms=1)
        assert suggest_timeout({"skill.a": stat}, "skill.a") == 1

    def test_fast_skill_still_gets_a_floor(self) -> None:
        stat = _stats("skill.a", runs=10, successes=10, p95_ms=0)
        assert suggest_timeout({"skill.a": stat}, "skill.a") is None


# ── the ODD-facing entry point ───────────────────────────────────────

class TestObserveSkills:
    def _registry(self) -> FakeRegistry:
        return FakeRegistry([
            FakeSkill("skill.plan", ["plan.create"]),
            FakeSkill("skill.metricas", ["metrics.collect"]),
            FakeSkill("skill.bfla", ["sec.bfla"]),
        ])

    def test_groups_by_capability(self, tmp_path: Path) -> None:
        summary = observe_skills(self._registry(), tmp_path)
        assert summary["skills_known"] == 3
        assert set(summary["capabilities"]) == {"plan.create", "metrics.collect", "sec.bfla"}

    def test_shadow_mode_reports_but_does_not_reorder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_POLICY_MODE", "shadow")
        chain = _day(tmp_path)
        _fill(chain, "skill.plan", successes=0, failures=9)
        _fill(chain, "skill.metricas", successes=9)

        summary = observe_skills(self._registry(), tmp_path)
        capability = summary["capabilities"]["plan.create"]
        assert capability["candidates"] == ["skill.plan"]
        assert capability["ranked"] == ["skill.plan"]  # unchanged
        # A 0-success skill is 100% failure, which is no reliability signal at
        # all, so it reads as the neutral prior rather than as 0.0. Reporting
        # 0.0 would imply "we know it is bad" when we only know it never worked.
        assert capability["scores"]["skill.plan"] == NEUTRAL_SCORE

    def test_active_mode_reorders_by_capability(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_POLICY_MODE", "active")
        chain = _day(tmp_path)
        _fill(chain, "skill.plan", successes=0, failures=9)
        _fill(chain, "skill.metricas", successes=9)

        summary = observe_skills(self._registry(), tmp_path)
        assert summary["capabilities"]["metrics.collect"]["scores"]["skill.metricas"] == 1.0

    def test_counts_skills_with_usable_evidence(self, tmp_path: Path) -> None:
        chain = _day(tmp_path)
        _fill(chain, "skill.metricas", successes=9)
        _fill(chain, "skill.plan", successes=1)  # below MIN_SAMPLES
        summary = observe_skills(self._registry(), tmp_path)
        assert summary["skills_with_evidence"] == 1

    def test_skill_without_receipts_is_neutral(self, tmp_path: Path) -> None:
        summary = observe_skills(self._registry(), tmp_path)
        assert summary["skills_with_evidence"] == 0


def test_dump_stats_is_valid_json(tmp_path: Path) -> None:
    chain = _day(tmp_path)
    _fill(chain, "skill.a", successes=9, failures=1)
    payload = json.loads(dump_stats(tmp_path))
    assert payload["mode"] in {"shadow", "active"}
    assert payload["min_samples"] == MIN_SAMPLES
    assert payload["skills"][0]["skill_id"] == "skill.a"
    assert payload["skills"][0]["runs"] == 10


def test_dump_stats_on_empty_root(tmp_path: Path) -> None:
    assert json.loads(dump_stats(tmp_path))["skills"] == []


def test_percentile_helpers() -> None:
    assert policy._percentile([], 0.95) == 0.0
    assert policy._percentile([5.0], 0.95) == 5.0
    assert policy._median([]) == 0.0
    assert policy._median([3.0, 1.0, 2.0]) == 2.0
    assert policy._median([4.0, 1.0, 3.0, 2.0]) == 2.5


def test_stats_to_dict_shape() -> None:
    payload = _stats("skill.a", runs=10, successes=8).to_dict()
    assert set(payload) == {
        "skill_id", "runs", "successes", "failures", "timeouts",
        "p95_ms", "median_ms", "failure_rate", "reliability", "usable",
    }

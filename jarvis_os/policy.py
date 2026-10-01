"""ODD Phase 2: turn verified receipts into a selection signal.

This is the ``policy`` layer the ODD loop needs. It reads the hash-chained
receipts produced by :mod:`jarvis_os.receipt` and derives, per skill, how often
it ran, how often it worked and how long it took. That is the first machine
readable feedback the project has: the previous signal was
``_Nightly_Reports/*.md``, which is prose and cannot steer anything.

Three properties are deliberate, and all three are defensive:

1. **Only verified chains are learned from.** A tampered history is treated as
   *no data*, which degrades to a neutral prior. Learning from a forged chain
   would let an attacker steer tool selection.
2. **Below ``MIN_SAMPLES`` a skill is neutral.** A single lucky run is not a
   reliability signal. Without this, one success makes a broken skill look
   perfect.
3. **Shadow by default.** The policy *computes* a recommendation but, unless
   explicitly enabled, the caller ignores it. Behaviour change is a separate,
   explicit decision made once the data justifies it.

The dependency direction stays one-way: skills -> policy -> receipt. Nothing
here imports the executor.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from jarvis_os.receipt import ReceiptChain, ReceiptChainError

logger = logging.getLogger(__name__)

#: Below this many receipts, a skill keeps the neutral prior. One run proves
#: nothing; five is the smallest sample that is not dominated by noise.
MIN_SAMPLES = 5

#: Prior used when there is no usable evidence.
NEUTRAL_SCORE = 0.5

#: Shadow mode is the default: the policy is computed and logged, and the caller
#: is expected to ignore it. Flip JARVIS_POLICY_MODE=active to let it steer.
DEFAULT_MODE = "shadow"

#: Reliability below which a skill is actively avoided, in active mode only.
UNRELIABLE_THRESHOLD = 0.25

#: Safety factor over the observed p95 when proposing a timeout.
TIMEOUT_HEADROOM = 2.0


def policy_mode() -> str:
    """``"active"`` or ``"shadow"``, from the environment."""
    return os.getenv("JARVIS_POLICY_MODE", DEFAULT_MODE).strip().lower()


def is_active() -> bool:
    return policy_mode() == "active"


@dataclass(frozen=True)
class ToolStats:
    """Observed behaviour of one skill, derived from verified receipts."""

    skill_id: str
    runs: int
    successes: int
    failures: int
    timeouts: int
    p95_ms: float
    median_ms: float
    failure_rate: float

    @property
    def reliability(self) -> float:
        """Share of runs that succeeded, in [0, 1]."""
        return self.successes / self.runs if self.runs else NEUTRAL_SCORE

    @property
    def has_enough_samples(self) -> bool:
        return self.runs >= MIN_SAMPLES

    @property
    def usable(self) -> bool:
        """Enough evidence to justify a non-neutral opinion."""
        return self.has_enough_samples and self.failure_rate < 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "runs": self.runs,
            "successes": self.successes,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "p95_ms": self.p95_ms,
            "median_ms": self.median_ms,
            "failure_rate": round(self.failure_rate, 4),
            "reliability": round(self.reliability, 4),
            "usable": self.usable,
        }


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * len(ordered))) - 1))
    return ordered[index]


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _verified_receipts(run_dir: Path) -> tuple[list[Any], str | None]:
    """Return the receipts of one run directory, or a rejection reason.

    Verification happens here and nowhere else, so a caller cannot accidentally
    learn from an unverified chain.
    """
    chain = ReceiptChain(run_dir)
    try:
        ok, detail = chain.verify()
        if not ok:
            return [], f"{run_dir.name}: {detail}"
        return list(chain.read_all()), None
    except ReceiptChainError as exc:
        return [], f"{run_dir.name}: {exc}"


def _aggregate(buckets: dict[str, list[dict[str, Any]]]) -> dict[str, ToolStats]:
    """Reduce per-skill receipt records into observed statistics."""
    stats: dict[str, ToolStats] = {}
    for skill_id, records in buckets.items():
        runs = len(records)
        successes = sum(1 for r in records if r["status"] == "success")
        failures = sum(1 for r in records if r["status"] == "failed")
        timeouts = sum(1 for r in records if r["status"] == "timeout")
        durations = [float(r.get("execution_time_ms") or 0.0) for r in records]
        stats[skill_id] = ToolStats(
            skill_id=skill_id,
            runs=runs,
            successes=successes,
            failures=failures,
            timeouts=timeouts,
            p95_ms=round(_percentile(durations, 0.95), 3),
            median_ms=round(_median(durations), 3),
            failure_rate=round(1 - (successes / runs), 4) if runs else 0.0,
        )
    return stats


def collect_stats(root: Path | str | None = None) -> dict[str, ToolStats]:
    """Aggregate every verified run directory under *root* into per-skill stats.

    A day whose chain fails verification contributes nothing: its receipts are
    treated as untrusted. This is the whole tamper story, and it is why
    verification happens in :func:`_verified_receipts` before any record is read.

    Returns:
        Mapping of skill id to its observed behaviour. Empty when there is no
        trustworthy evidence, which callers must handle as "no opinion".
    """
    base = Path(root) if root is not None else Path("receipts")
    if not base.exists():
        return {}

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejected: list[str] = []

    for index_path in sorted(base.glob("*/index.jsonl")):
        receipts, reason = _verified_receipts(index_path.parent)
        if reason is not None:
            rejected.append(reason)
            continue
        for receipt in receipts:
            buckets[receipt.tool_name].append(receipt.model_dump())

    if rejected:
        # Loud, because a rejected run means the audit trail has a hole.
        logger.warning(
            "policy: %d receipt run(s) rejected as untrustworthy and excluded "
            "from learning: %s", len(rejected), "; ".join(rejected),
        )

    return _aggregate(buckets)


def score_for(stats: dict[str, ToolStats], skill_id: str) -> float:
    """Selection score for one skill, in [0, 1].

    Neutral when there is no usable evidence. The caller decides what to do with
    it; :func:`rank_candidates` is the convenient wrapper.
    """
    stat = stats.get(skill_id)
    if stat is None or not stat.usable:
        return NEUTRAL_SCORE
    return stat.reliability


def rank_candidates(
    stats: dict[str, ToolStats], candidates: Iterable[str]
) -> list[tuple[str, float]]:
    """Order candidates best-first, with the neutral prior for unknown skills.

    Ties break alphabetically so the ordering is deterministic; a policy that
    reorders between equal runs makes behaviour impossible to test.
    """
    scored = [(skill_id, round(score_for(stats, skill_id), 4)) for skill_id in candidates]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0]))


def recommend(
    stats: dict[str, ToolStats], candidates: Iterable[str]
) -> list[str]:
    """Ranked skill ids, honouring shadow mode.

    In shadow mode the *registry order* is returned unchanged and the ranking is
    only logged, so enabling the policy is never a silent behaviour change.
    """
    ordered = [skill_id for skill_id, _ in rank_candidates(stats, candidates)]
    if not is_active():
        logger.info(
            "policy: shadow mode, ranking computed but not applied: %s", ordered,
        )
        return list(candidates)
    logger.info("policy: active mode, ranking applied: %s", ordered)
    return ordered


def suggest_timeout(
    stats: dict[str, ToolStats], skill_id: str, *, headroom: float = TIMEOUT_HEADROOM
) -> int | None:
    """Propose a timeout in seconds from the observed p95, or ``None``.

    ``None`` means "no opinion": either there is not enough evidence, or every
    observed run was too fast for a p95 to mean anything.
    """
    stat = stats.get(skill_id)
    if stat is None or not stat.usable or stat.p95_ms <= 0:
        return None
    return max(1, int(stat.p95_ms * headroom / 1000) + 1)


def observe_skills(
    registry: Any, root: Path | str | None = None
) -> dict[str, Any]:
    """Rank the skills a registry knows about. The ODD-facing entry point.

    Args:
        registry: Anything exposing ``list_all()`` returning objects with an
            ``id`` and a ``frontmatter.capabilities`` list, i.e. the existing
            ``SkillRegistry``.
        root: Receipts root override.

    Returns:
        A summary dict, useful for logging and for the self-improvement loop.
    """
    stats = collect_stats(root)
    skills = list(registry.list_all())
    by_capability: dict[str, list[str]] = defaultdict(list)
    for skill in skills:
        for capability in getattr(skill.frontmatter, "capabilities", []) or []:
            by_capability[str(capability)].append(skill.id)

    summary: dict[str, Any] = {
        "mode": policy_mode(),
        "skills_known": len(skills),
        "skills_with_evidence": sum(1 for s in stats.values() if s.usable),
        "capabilities": {},
    }
    for capability, ids in sorted(by_capability.items()):
        ranked = recommend(stats, ids)
        summary["capabilities"][capability] = {
            "candidates": ids,
            "ranked": ranked,
            "scores": dict(rank_candidates(stats, ids)),
        }
    return summary


def dump_stats(root: Path | str | None = None) -> str:
    """JSON snapshot of the current policy state, for inspection or a report."""
    stats = collect_stats(root)
    return json.dumps(
        {
            "mode": policy_mode(),
            "min_samples": MIN_SAMPLES,
            "neutral_score": NEUTRAL_SCORE,
            "skills": [s.to_dict() for _, s in sorted(stats.items())],
        },
        indent=2,
        sort_keys=True,
    )

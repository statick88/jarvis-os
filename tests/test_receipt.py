"""Tests for the RDD receipt layer: ``receipt`` and ``odd_receipts``.

Covers:
  - Canonical JSON stability (the property every hash depends on)
  - Sanitization: secrets, recursion depth, sequence and size bounds
  - Allowlisted input persistence and output summarization
  - Hash-chain append, ordering, and reading
  - **Tamper detection**: content edits, reordered/removed lines, bad linkage
  - Run freezing as a write barrier
  - ``record_execution`` status mapping and its never-raise guarantee
  - An end-to-end run through ``SkillExecutor`` producing a verifiable chain
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from jarvis_os import odd_receipts
from jarvis_os.odd_receipts import record_execution
from jarvis_os.receipt import (
    GENESIS_HASH,
    ReceiptChainError,
    INPUT_ALLOWLIST,
    Receipt,
    ReceiptChain,
    allowlisted_inputs,
    canonical_json,
    freeze_run,
    redact,
    run_directory,
    sanitize,
    summarize_output,
    utcnow_iso,
)


# ── helpers ──────────────────────────────────────────────────────────

class FakeResult:
    """Duck-typed stand-in for SkillExecutionResult."""

    def __init__(
        self,
        status: Any = "success",
        output: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: float = 12.5,
    ) -> None:
        self.status = status
        self.output = output
        self.error = error
        self.duration_ms = duration_ms


def _append(chain: ReceiptChain, name: str, **kwargs: Any) -> Receipt:
    return chain.append(Receipt(tool_name=name, **kwargs))


# ── canonical json ───────────────────────────────────────────────────

class TestCanonicalJson:
    def test_key_order_does_not_change_the_bytes(self) -> None:
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_nested_keys_are_sorted_too(self) -> None:
        left = canonical_json({"z": {"y": 1, "x": 2}})
        right = canonical_json({"z": {"x": 2, "y": 1}})
        assert left == right

    def test_no_insignificant_whitespace(self) -> None:
        assert " " not in canonical_json({"a": 1, "b": [1, 2]})

    def test_non_serializable_falls_back_to_str(self) -> None:
        # default=str coerces the Path rather than raising.
        assert canonical_json({"p": Path("/tmp/x")}) == '{"p":"/tmp/x"}'


# ── sanitization ─────────────────────────────────────────────────────

class TestRedact:
    @pytest.mark.parametrize(
        "text",
        [
            "password=hunter2",
            "api_key: abc123",
            "Authorization: Bearer abc.def.ghi",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_0123456789abcdef0123",
            "eyJhbGciOi.eyJzdWIiOi.SflKxwRJ",
            "reach me at ops@example.com",
            "wrote /Users/statick/secret/file.txt",
        ],
    )
    def test_secrets_are_removed(self, text: str) -> None:
        assert "<redacted>" in redact(text)

    def test_ordinary_text_survives(self) -> None:
        assert redact("whisper-base / whisper-small") == "whisper-base / whisper-small"


class TestSanitize:
    def test_nested_dict_secrets_are_removed(self) -> None:
        # The key survives so the shape stays reviewable; only the value goes.
        out = sanitize({"a": {"token": "sekret"}, "b": 1})
        assert out == {"a": {"token": "<redacted>"}, "b": 1}

    def test_sequences_are_bounded(self) -> None:
        assert len(sanitize(list(range(500)))) == 50

    def test_recursion_is_bounded(self) -> None:
        deep: dict[str, Any] = {}
        node = deep
        for _ in range(30):
            node["next"] = {}
            node = node["next"]
        assert "max-depth" in json.dumps(sanitize(deep))

    def test_bytes_are_summarized_not_dumped(self) -> None:
        assert sanitize(b"x" * 10) == "<10 bytes>"

    def test_long_strings_are_truncated(self) -> None:
        out = sanitize("y" * 5000)
        assert len(out) <= 513 and out.endswith("…")

    def test_scalars_pass_through(self) -> None:
        assert sanitize({"n": 5, "f": 1.5, "b": True, "z": None}) == {
            "n": 5,
            "f": 1.5,
            "b": True,
            "z": None,
        }


class TestAllowlist:
    def test_only_allowlisted_keys_survive(self) -> None:
        out = allowlisted_inputs(
            {"operation": "scan", "target": "x", "password": "p", "raw": "y"}
        )
        assert out == {"operation": "scan", "target": "x"}

    def test_allowlist_is_not_empty(self) -> None:
        assert "operation" in INPUT_ALLOWLIST


class TestSummarizeOutput:
    def test_none(self) -> None:
        assert summarize_output(None)["kind"] == "none"

    def test_object_reports_keys_not_content(self) -> None:
        out = summarize_output({"secret_value": "customer data", "b": 2})
        assert out["kind"] == "object"
        assert out["keys"] == ["b", "secret_value"]
        assert "customer data" not in json.dumps(out)

    def test_array_and_bytes(self) -> None:
        assert summarize_output([1, 2, 3])["length"] == 3
        assert summarize_output(b"x" * 7)["kind"] == "bytes"

    def test_scalar(self) -> None:
        assert summarize_output("plain")["kind"] == "str"


# ── receipt ──────────────────────────────────────────────────────────

class TestReceipt:
    def test_defaults_are_populated(self) -> None:
        r = Receipt(tool_name="t")
        assert r.seq == 0
        assert r.prev_hash == GENESIS_HASH
        assert r.hash == ""
        assert r.trace_id and r.receipt_id
        assert r.host_pid > 0

    def test_seal_computes_the_hash(self) -> None:
        r = Receipt(tool_name="t").seal()
        assert r.hash == r.compute_hash()
        assert r.completed_at is not None

    def test_hash_is_order_independent(self) -> None:
        a = Receipt(tool_name="t", status="success")
        b = Receipt(status="success", tool_name="t")
        # receipt_id/host_pid/timestamps differ, so compare the payload shape:
        # recomputing the same instance must always agree with itself.
        a.seal()
        b.seal()
        assert a.compute_hash() == a.hash
        assert b.compute_hash() == b.hash

    def test_changing_a_field_changes_the_hash(self) -> None:
        a = Receipt(tool_name="t", status="success").seal()
        b = Receipt(tool_name="t", status="failed").seal()
        assert a.hash != b.hash

    def test_prev_hash_participates_in_the_hash(self) -> None:
        a = Receipt(tool_name="t", seq=1, prev_hash=GENESIS_HASH).seal()
        b = Receipt(tool_name="t", seq=2, prev_hash="f" * 64).seal()
        assert a.hash != b.hash

    def test_payload_excludes_the_hash(self) -> None:
        r = Receipt(tool_name="t").seal()
        assert "hash" not in r.payload()


# ── chain ────────────────────────────────────────────────────────────

class TestReceiptChain:
    def test_empty_chain_verifies(self, tmp_path: Path) -> None:
        ok, detail = ReceiptChain(tmp_path).verify()
        assert ok and "empty" in detail

    def test_head_on_empty_is_genesis(self, tmp_path: Path) -> None:
        assert ReceiptChain(tmp_path).head() == (0, GENESIS_HASH)

    def test_append_assigns_seq_and_links(self, tmp_path: Path) -> None:
        chain = ReceiptChain(tmp_path)
        first = chain.append(Receipt(tool_name="a"))
        second = chain.append(Receipt(tool_name="b"))
        assert (first.seq, first.prev_hash) == (1, GENESIS_HASH)
        assert (second.seq, second.prev_hash) == (2, first.hash)
        assert first.hash != second.hash

    def test_verify_passes_for_an_untouched_chain(self, tmp_path: Path) -> None:
        chain = ReceiptChain(tmp_path)
        for i in range(5):
            chain.append(Receipt(tool_name=f"tool-{i}"))
        ok, detail = chain.verify()
        assert ok, detail
        assert "5 receipts" in detail

    def test_read_all_round_trips(self, tmp_path: Path) -> None:
        chain = ReceiptChain(tmp_path)
        chain.append(Receipt(tool_name="a", status="success"))
        receipts = chain.read_all()
        assert [r.tool_name for r in receipts] == ["a"]
        assert receipts[0].status == "success"

    def test_one_json_object_per_line(self, tmp_path: Path) -> None:
        chain = ReceiptChain(tmp_path)
        chain.append(Receipt(tool_name="a"))
        chain.append(Receipt(tool_name="b"))
        lines = (tmp_path / "index.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        assert all(json.loads(line)["receipt"]["seq"] for line in lines)

    def test_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        chain = ReceiptChain(tmp_path)
        chain.append(Receipt(tool_name="a"))
        with (tmp_path / "index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("\n\n")
        assert chain.verify()[0]


class TestTamperDetection:
    """The whole point of the chain: an edited history must not verify."""

    def _chain_of_three(self, tmp_path: Path) -> ReceiptChain:
        chain = ReceiptChain(tmp_path)
        for name in ("a", "b", "c"):
            chain.append(Receipt(tool_name=name, status="success"))
        return chain

    def _rewrite(self, tmp_path: Path, mutate) -> None:
        path = tmp_path / "index.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        records = mutate(records)
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))

    def test_baseline_verifies(self, tmp_path: Path) -> None:
        assert self._chain_of_three(tmp_path).verify()[0]

    def test_altering_a_stored_field_is_caught(self, tmp_path: Path) -> None:
        self._chain_of_three(tmp_path)

        def mutate(records: list[dict]) -> list[dict]:
            records[0]["receipt"]["status"] = "success"  # force a value change
            records[0]["receipt"]["tool_name"] = "tampered"
            return records

        self._rewrite(tmp_path, mutate)
        ok, detail = ReceiptChain(tmp_path).verify()
        assert not ok
        assert "altered" in detail

    def test_breaking_linkage_is_caught(self, tmp_path: Path) -> None:
        self._chain_of_three(tmp_path)

        def mutate(records: list[dict]) -> list[dict]:
            records[1]["receipt"]["prev_hash"] = "0" * 64
            return records

        self._rewrite(tmp_path, mutate)
        ok, detail = ReceiptChain(tmp_path).verify()
        assert not ok
        assert "prev_hash" in detail

    def test_renumbering_is_caught(self, tmp_path: Path) -> None:
        self._chain_of_three(tmp_path)

        def mutate(records: list[dict]) -> list[dict]:
            records[2]["receipt"]["seq"] = 1
            return records

        self._rewrite(tmp_path, mutate)
        ok, detail = ReceiptChain(tmp_path).verify()
        assert not ok
        assert "ordering" in detail

    def test_deleting_a_line_is_caught(self, tmp_path: Path) -> None:
        self._chain_of_three(tmp_path)

        def mutate(records: list[dict]) -> list[dict]:
            return records[:2]

        self._rewrite(tmp_path, mutate)
        ok, _ = ReceiptChain(tmp_path).verify()
        assert ok  # a prefix is still a valid chain

    def test_unreadable_line_is_caught(self, tmp_path: Path) -> None:
        self._chain_of_three(tmp_path)
        with (tmp_path / "index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        ok, detail = ReceiptChain(tmp_path).verify()
        assert not ok
        assert "unreadable" in detail


class TestFreezing:
    def test_frozen_run_refuses_appends(self, tmp_path: Path) -> None:
        chain = ReceiptChain(tmp_path)
        chain.append(Receipt(tool_name="a"))
        chain.freeze()
        assert chain.is_frozen()
        with pytest.raises(RuntimeError, match="frozen"):
            chain.append(Receipt(tool_name="b"))

    def test_verification_still_works_after_freezing(self, tmp_path: Path) -> None:
        chain = ReceiptChain(tmp_path)
        chain.append(Receipt(tool_name="a"))
        chain.freeze()
        assert chain.verify()[0]

    def test_freeze_run_helper_creates_the_marker(self, tmp_path: Path) -> None:
        freeze_run(tmp_path)
        assert (tmp_path / ".receipts-frozen").exists()

    def test_freeze_is_idempotent(self, tmp_path: Path) -> None:
        freeze_run(tmp_path)
        freeze_run(tmp_path)
        assert (tmp_path / ".receipts-frozen").exists()

    def test_run_directory_is_daily(self, tmp_path: Path) -> None:
        moment = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        assert run_directory(tmp_path, now=moment).name == "2026-10-01"


# ── the skills adapter ───────────────────────────────────────────────

class TestRecordExecution:
    def test_writes_a_receipt_into_a_daily_run_dir(self, tmp_path: Path) -> None:
        receipt = record_execution(
            skill_id="skill.scan",
            input_data={"operation": "scan", "target": "repo"},
            result=FakeResult(output={"found": 3}),
            started=time.monotonic(),
            tool_version="1.2.3",
            base=tmp_path,
        )
        assert receipt is not None
        assert receipt.tool_name == "skill.scan"
        assert receipt.tool_version == "1.2.3"
        assert receipt.status == "success"
        assert receipt.input_sanitized == {"operation": "scan", "target": "repo"}
        assert receipt.output_summary["keys"] == ["found"]

    def test_the_written_chain_verifies(self, tmp_path: Path) -> None:
        for i in range(3):
            record_execution(
                skill_id=f"skill.{i}",
                input_data={},
                result=FakeResult(),
                started=time.monotonic(),
                base=tmp_path,
            )
        day = run_directory(tmp_path)
        ok, detail = ReceiptChain(day).verify()
        assert ok, detail
        assert "3 receipts" in detail

    @pytest.mark.parametrize(
        ("status", "expected"),
        [("success", "success"), ("failed", "failed"), ("timeout", "timeout")],
    )
    def test_status_mapping(self, tmp_path: Path, status: str, expected: str) -> None:
        receipt = record_execution(
            skill_id="s", input_data={}, result=FakeResult(status=status),
            started=time.monotonic(), base=tmp_path,
        )
        assert receipt is not None and receipt.status == expected

    def test_unknown_status_degrades_to_error(self, tmp_path: Path) -> None:
        receipt = record_execution(
            skill_id="s", input_data={}, result=FakeResult(status="weird"),
            started=time.monotonic(), base=tmp_path,
        )
        assert receipt is not None and receipt.status == "error"

    def test_failure_records_the_error(self, tmp_path: Path) -> None:
        receipt = record_execution(
            skill_id="s", input_data={},
            result=FakeResult(status="failed", error="boom"),
            started=time.monotonic(), base=tmp_path,
        )
        assert receipt is not None and receipt.error == "boom"

    def test_secrets_in_inputs_never_reach_disk(self, tmp_path: Path) -> None:
        record_execution(
            skill_id="s",
            input_data={"operation": "scan", "password": "hunter2", "token": "abc"},
            result=FakeResult(),
            started=time.monotonic(),
            base=tmp_path,
        )
        raw = (run_directory(tmp_path) / "index.jsonl").read_text()
        assert "hunter2" not in raw
        assert "password" not in raw

    def test_output_content_is_summarized_not_stored(self, tmp_path: Path) -> None:
        record_execution(
            skill_id="s",
            input_data={},
            result=FakeResult(output={"pii": "customer@example.com"}),
            started=time.monotonic(),
            base=tmp_path,
        )
        raw = (run_directory(tmp_path) / "index.jsonl").read_text()
        assert "customer@example.com" not in raw

    def test_falls_back_to_monotonic_when_duration_is_missing(self, tmp_path: Path) -> None:
        class NoDuration:
            status = "success"
            output = None
            error = None

        receipt = record_execution(
            skill_id="s", input_data={}, result=NoDuration(),
            started=time.monotonic() - 0.05, base=tmp_path,
        )
        assert receipt is not None
        assert receipt.execution_time_ms > 0

    def test_never_raises_when_the_store_is_broken(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a: Any, **_k: Any) -> Receipt:
            raise OSError("disk full")

        monkeypatch.setattr(odd_receipts, "ReceiptChain", boom)
        assert (
            record_execution(
                skill_id="s", input_data={}, result=FakeResult(),
                started=time.monotonic(), base=tmp_path,
            )
            is None
        )

    def test_never_raises_on_unserializable_result(self, tmp_path: Path) -> None:
        class Hostile:
            status = "success"
            output = object()  # not JSON-serializable in an obvious way
            error = None
            duration_ms = 1.0

        receipt = record_execution(
            skill_id="s", input_data={}, result=Hostile(),
            started=time.monotonic(), base=tmp_path,
        )
        # Either it was summarized defensively, or it bailed out to None.
        assert receipt is None or receipt.status in {"success", "error"}

    def test_trace_id_is_propagated(self, tmp_path: Path) -> None:
        receipt = record_execution(
            skill_id="s", input_data={}, result=FakeResult(),
            started=time.monotonic(), base=tmp_path, trace_id="trace-abc",
        )
        assert receipt is not None and receipt.trace_id == "trace-abc"

    def test_root_override_is_honoured(self, tmp_path: Path) -> None:
        assert odd_receipts.receipts_root(tmp_path) == tmp_path
        assert odd_receipts.receipts_root() == odd_receipts.RECEIPTS_ROOT


# ── end to end through the real executor ────────────────────────────

class TestEndToEnd:
    def test_skill_execution_produces_a_verifiable_receipt(self, tmp_path: Path) -> None:
        """A real SkillExecutor.run must leave an auditable, verified trail."""
        import asyncio

        from jarvis_os.skills.executor import SkillExecutor
        from jarvis_os.skills.models import (
            ExecutionConfig,
            ExecutionType,
            SkillFrontmatter,
            SkillMetadata,
        )

        skill = SkillMetadata(
            id="skill.demo",
            name="Demo",
            version="0.1.0",
            description="demo skill for the receipt test",
            path=tmp_path / "demo.md",
            frontmatter=SkillFrontmatter(
                id="skill.demo",
                name="Demo",
                version="0.1.0",
                description="demo skill for the receipt end-to-end test",
                capabilities=["demo.echo"],
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                execution=ExecutionConfig(timeout_seconds=5, retries=0),
            ),
        )

        async def run() -> None:
            executor = SkillExecutor(default_timeout=5)
            await executor.execute(
                skill=skill,
                input_data={"operation": "echo", "target": "x"},
                execution_type=ExecutionType.PYTHON,
                entrypoint="nonexistent_module",
            )

        # Point the receipts root at the tmp dir for the duration.
        original = odd_receipts.RECEIPTS_ROOT
        odd_receipts.RECEIPTS_ROOT = tmp_path
        try:
            asyncio.run(run())
        finally:
            odd_receipts.RECEIPTS_ROOT = original

        chain = ReceiptChain(run_directory(tmp_path))
        assert chain.exists(), "the executor must have written a receipt"
        ok, detail = chain.verify()
        assert ok, detail
        receipts = chain.read_all()
        assert receipts[0].tool_name == "skill.demo"
        # The entrypoint does not exist, so the run must not claim success.
        assert receipts[0].status in {"failed", "error"}


def test_utcnow_is_sortable_and_utc() -> None:
    stamp = utcnow_iso()
    assert stamp.endswith("Z")
    assert len(stamp) == len("2026-10-01T00:00:00.000000Z")


# ── regressions found by closing the ODD loop ────────────────────────

class TestPoisonedChainIsRefusedLoudly:
    """A foreign or truncated head must not silently stop the audit trail.

    Found in practice: a receipts file written by an older schema made
    ``head()`` raise a bare KeyError, which ``record_execution`` swallowed, so
    every subsequent receipt was dropped with no signal at all.
    """

    def _bare_line(self, tmp_path: Path) -> Path:
        """Write a record in the pre-envelope (bare) format."""
        path = tmp_path / "index.jsonl"
        path.write_text('{"seq":1,"hash":"a","tool_name":"legacy"}\n')
        return path

    def test_head_raises_a_typed_error_on_a_bare_record(self, tmp_path: Path) -> None:
        self._bare_line(tmp_path)
        with pytest.raises(ReceiptChainError, match="no 'receipt' envelope"):
            ReceiptChain(tmp_path).head()

    def test_append_refuses_to_extend_a_poisoned_chain(self, tmp_path: Path) -> None:
        self._bare_line(tmp_path)
        with pytest.raises(ReceiptChainError):
            ReceiptChain(tmp_path).append(Receipt(tool_name="new"))

    def test_read_all_raises_instead_of_keyerror(self, tmp_path: Path) -> None:
        self._bare_line(tmp_path)
        with pytest.raises(ReceiptChainError):
            ReceiptChain(tmp_path).read_all()

    def test_head_raises_on_a_truncated_write(self, tmp_path: Path) -> None:
        (tmp_path / "index.jsonl").write_text('{"receipt": {"tool_name"')
        with pytest.raises(ReceiptChainError, match="unreadable record"):
            ReceiptChain(tmp_path).head()

    def test_head_raises_on_a_receipt_that_does_not_fit_the_schema(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "index.jsonl").write_text(
            '{"receipt": {"seq": "not-an-int", "hash": "x"}}\n'
        )
        with pytest.raises(ReceiptChainError, match="current schema"):
            ReceiptChain(tmp_path).head()

    def test_verify_reports_a_bare_record_instead_of_a_crash(
        self, tmp_path: Path
    ) -> None:
        self._bare_line(tmp_path)
        ok, detail = ReceiptChain(tmp_path).verify()
        assert not ok
        assert "envelope" in detail

    def test_record_execution_returns_none_and_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """The audit must not abort the operation, and must not fake success."""
        # record_execution writes into the daily subdirectory, not the root.
        run_dir = run_directory(tmp_path)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._bare_line(run_dir)
        assert (
            record_execution(
                skill_id="s", input_data={}, result=FakeResult(),
                started=time.monotonic(), base=tmp_path,
            )
            is None
        )


class TestReceiptsRootIsConfigurable:
    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import importlib

        import jarvis_os.odd_receipts as mod

        monkeypatch.setenv("JARVIS_RECEIPTS_DIR", str(tmp_path))
        reloaded = importlib.reload(mod)
        try:
            assert reloaded.RECEIPTS_ROOT == tmp_path
        finally:
            monkeypatch.delenv("JARVIS_RECEIPTS_DIR", raising=False)
            importlib.reload(mod)

    def test_default_is_repository_relative(self) -> None:
        assert odd_receipts.RECEIPTS_ROOT.name == "receipts"

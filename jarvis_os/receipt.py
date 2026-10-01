"""Execution Receipt — deterministic, hash-chained, immutable audit artifact.

Design constraints
------------------
- **stdlib + pydantic only.** No imports from ``jarvis_os``, so this module has
  no circular dependency and can be unit-tested in isolation.
- **Canonical JSON.** ``canonical_json`` is what makes hashes stable. Changing
  it invalidates every previously stored hash; bump ``RECEIPT_SCHEMA_VERSION``
  if you ever need to.
- **Allowlist sanitization.** ``sanitize`` redacts by pattern, and callers
  additionally restrict *which* keys are persisted. A denylist always leaks
  something eventually; an allowlist cannot.
- **A failed audit must never break the runtime.** Writers are expected to wrap
  calls in try/except (see :mod:`jarvis_os.odd_receipts`).

This module intentionally does *not* import the skills package. The receipt is
the audit primitive; the skill executor is a consumer of it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# Bump when the receipt layout changes in a way that invalidates stored hashes.
RECEIPT_SCHEMA_VERSION = 1

GENESIS_HASH = "0" * 64

#: Redaction patterns. Applied to values and to ``"key: value"`` renderings.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # key/value pairs naming a credential
    re.compile(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|"
        r"access[_-]?key|private[_-]?key|credential)s?\b\s*[:=]\s*\S+"
    ),
    # Authorization headers
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+"),
    # common provider key shapes
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    # JWTs
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    # emails
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    # absolute filesystem paths
    re.compile(r"(?<![\w.])/(?:Users|home|root|opt|var|etc|tmp)/[\w.\-/]+"),
)

#: Keys safe to persist verbatim in ``input_sanitized``.
INPUT_ALLOWLIST: frozenset[str] = frozenset(
    {"operation", "target", "limit", "offset", "format", "depth", "dry_run", "recursive"}
)

#: Bounds so one pathological payload cannot bloat the chain.
MAX_DEPTH = 6
MAX_SEQUENCE_ITEMS = 50
MAX_STRING_CHARS = 512


def utcnow_iso() -> str:
    """Timestamp with microsecond precision, UTC, lexicographically sortable."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_json(payload: Any) -> str:
    """Deterministic serialization: sorted keys, no padding, UTF-8.

    Hash stability depends on this exact form. Do not "improve" it.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def redact(text: str) -> str:
    """Apply every redaction pattern to a single string."""
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("<redacted>", out)
    return out


def sanitize(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact secrets and bound depth and sequence length."""
    if depth > MAX_DEPTH:
        return "<max-depth>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            skey = str(key)
            rendered = f"{skey}: {item}"
            if any(p.search(rendered) for p in _SECRET_PATTERNS):
                out[skey] = "<redacted>"
            else:
                out[skey] = sanitize(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:MAX_SEQUENCE_ITEMS]
        return [sanitize(v, depth=depth + 1) for v in items]
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = redact(str(value))
    if len(text) > MAX_STRING_CHARS:
        return text[:MAX_STRING_CHARS] + "…"
    return text


def allowlisted_inputs(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only allowlisted keys, then sanitize what remains."""
    return {k: sanitize(v) for k, v in data.items() if k in INPUT_ALLOWLIST}


def summarize_output(output: Any) -> dict[str, Any]:
    """Shape of an output, not its content.

    Storing full outputs would make receipts huge and would persist customer
    data into an audit log. The keys and sizes are what a reviewer needs.
    """
    if output is None:
        return {"keys": [], "bytes": 0, "kind": "none"}
    if isinstance(output, dict):
        return {
            "keys": sorted(str(k) for k in output)[:25],
            "bytes": len(canonical_json(output)),
            "kind": "object",
        }
    if isinstance(output, (list, tuple)):
        return {"keys": [], "bytes": len(canonical_json(output)), "kind": "array",
                "length": len(output)}
    if isinstance(output, (bytes, bytearray)):
        return {"keys": [], "bytes": len(output), "kind": "bytes"}
    return {"keys": [], "bytes": len(str(output)), "kind": type(output).__name__}


class Receipt(BaseModel):
    """One immutable record of a single tool or skill run."""

    schema_version: int = RECEIPT_SCHEMA_VERSION
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    tool_name: str
    tool_version: str | None = None

    input_sanitized: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    execution_time_ms: float = 0.0
    status: Literal["success", "failed", "timeout", "error"] = "error"

    started_at: str = Field(default_factory=utcnow_iso)
    completed_at: str | None = None
    host_pid: int = Field(default_factory=os.getpid)

    # Chain linkage. seq is 1-based; prev_hash is GENESIS_HASH for the first.
    seq: int = 0
    prev_hash: str = GENESIS_HASH
    hash: str = ""

    def payload(self) -> dict[str, Any]:
        """The hashed body: everything except the hash itself."""
        return self.model_dump(exclude={"hash"})

    def compute_hash(self) -> str:
        """Hash this receipt together with its predecessor's hash.

        Including ``prev_hash`` is what makes the chain tamper-evident: editing
        any historical receipt invalidates every hash after it.
        """
        return hashlib.sha256(
            (canonical_json(self.payload()) + self.prev_hash).encode("utf-8")
        ).hexdigest()

    def seal(self) -> "Receipt":
        """Freeze ``completed_at`` and compute the hash. Idempotent per state."""
        if self.completed_at is None:
            self.completed_at = utcnow_iso()
        self.hash = self.compute_hash()
        return self

    def to_line(self) -> str:
        """One JSONL record.

        The receipt is wrapped rather than written bare so the envelope can
        later carry chain metadata (writer identity, schema migration notes)
        without breaking existing readers.
        """
        return canonical_json({"receipt": self.model_dump()})


class ReceiptChainError(RuntimeError):
    """The chain cannot be extended or trusted in its current state.

    Raised instead of a bare KeyError so the failure is actionable: a corrupted
    or foreign head line must not silently stop the audit trail.
    """


class ReceiptChain:
    """Append-only, hash-chained store rooted at ``root``.

    Layout::

        receipts/
          2026-10-01/            # one directory per UTC day
            index.jsonl          # append-only, one sealed receipt per line
            .receipts-frozen     # present => no more writes accepted
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.index_path = self.root / "index.jsonl"
        self.freeze_marker = self.root / ".receipts-frozen"

    # -- state ---------------------------------------------------------

    def exists(self) -> bool:
        return self.index_path.exists()

    def is_frozen(self) -> bool:
        return self.freeze_marker.exists()

    def _read_receipt(self, raw: str) -> Receipt:
        """Parse one JSONL record, or raise a typed, actionable error.

        A record written by an older schema, a truncated write, or a foreign
        writer must not surface as KeyError deep inside the caller, because the
        caller is an audit path that is designed to swallow exceptions. If this
        raises quietly, the audit trail stops without anyone noticing.
        """
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReceiptChainError(
                f"{self.index_path}: unreadable record ({exc}); "
                f"run verify() for the exact position, then start a new run "
                f"directory or repair the file"
            ) from exc
        if not isinstance(record, dict) or "receipt" not in record:
            raise ReceiptChainError(
                f"{self.index_path}: record has no 'receipt' envelope; this file "
                f"was written by an incompatible schema version. Do not append "
                f"to it - start a new run directory so the chain stays auditable"
            )
        try:
            return Receipt(**record["receipt"])
        except Exception as exc:
            raise ReceiptChainError(
                f"{self.index_path}: receipt does not match the current schema; "
                f"start a new run directory ({exc})"
            ) from exc

    def head(self) -> tuple[int, str]:
        """Return ``(last_seq, last_hash)``; genesis values when empty.

        Raises:
            ReceiptChainError: if the last line cannot be parsed. Propagating
                is deliberate: appending after an unreadable head would fork the
                audit trail.
        """
        if not self.index_path.exists():
            return 0, GENESIS_HASH
        last_line = ""
        with self.index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line
        if not last_line:
            return 0, GENESIS_HASH
        receipt = self._read_receipt(last_line)
        return int(receipt.seq), receipt.hash

    def read_all(self) -> list[Receipt]:
        if not self.index_path.exists():
            return []
        out: list[Receipt] = []
        with self.index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    out.append(self._read_receipt(line))
        return out

    # -- writes --------------------------------------------------------

    def append(self, receipt: Receipt) -> Receipt:
        """Seal and append one receipt. Never rewrites an existing line.

        Raises:
            RuntimeError: if the run directory was already frozen.
        """
        if self.is_frozen():
            raise RuntimeError(
                f"receipt run {self.root} is frozen; refusing to append"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        seq, prev = self.head()
        receipt.seq = seq + 1
        receipt.prev_hash = prev
        receipt.seal()
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(receipt.to_line() + "\n")
            handle.flush()
            os.fsync(handle.fileno())  # survive a crash mid-write
        return receipt

    def freeze(self) -> None:
        """Mark the run immutable. Verification still works after freezing."""
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.freeze_marker.exists():
            self.freeze_marker.write_text(utcnow_iso() + "\n", encoding="utf-8")

    # -- verification --------------------------------------------------

    def verify(self) -> tuple[bool, str]:
        """Recompute the entire chain from genesis.

        Returns ``(ok, detail)``. ``detail`` names the first offending line so a
        tampered history is actionable rather than just "invalid".
        """
        if not self.index_path.exists():
            return True, "empty chain"
        prev = GENESIS_HASH
        count = 0
        with self.index_path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                count += 1
                try:
                    receipt = self._read_receipt(line)
                except ReceiptChainError as exc:
                    return False, f"line {lineno}: {exc}"
                if receipt.seq != count:
                    return False, (
                        f"line {lineno}: seq {receipt.seq} breaks ordering "
                        f"(expected {count})"
                    )
                if receipt.prev_hash != prev:
                    return False, f"line {lineno}: prev_hash does not match predecessor"
                if receipt.compute_hash() != receipt.hash:
                    return False, f"line {lineno}: content altered (hash mismatch)"
                prev = receipt.hash
        return True, f"{count} receipts verified"


def run_directory(root: Path | str, *, now: datetime | None = None) -> Path:
    """Daily run directory. A process artifact: gitignored by design."""
    moment = now or datetime.now(timezone.utc)
    return Path(root) / moment.strftime("%Y-%m-%d")


def freeze_run(root: Path | str) -> Path:
    """Mark a run directory immutable.

    Convenience wrapper over :meth:`ReceiptChain.freeze` for callers that hold a
    directory rather than a chain. Verification keeps working after freezing.
    """
    ReceiptChain(root).freeze()
    return Path(root)

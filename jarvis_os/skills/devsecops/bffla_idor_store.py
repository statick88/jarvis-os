"""Local findings persistence for the BFLA/IDOR skill.

JSON store with a stable Engram topic-key format so findings can be mirrored
into the vault later. Path override: ``input_data["context"]["findings_path"]``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STORE_VERSION = 1
DEFAULT_FINDINGS_PATH = Path(".state/bfla_idor_findings.json")
CONFIRMED_FINDING_IDS = frozenset(f"F{i:02d}" for i in range(1, 23))
TOPIC_KEY_TEMPLATE = "sdd/pentest-methodology/finding-{finding_id}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class FindingsStore:
    """JSON-backed findings store with confirmed-id guardrails."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_FINDINGS_PATH
        self._findings: list[dict[str, Any]] = []
        self._confirmed: set[str] = set(CONFIRMED_FINDING_IDS)
        self.load()

    @property
    def confirmed_ids(self) -> set[str]:
        return set(self._confirmed)

    def is_confirmed(self, finding_id: str) -> bool:
        return finding_id in self._confirmed

    @staticmethod
    def topic_key(finding_id: str) -> str:
        return TOPIC_KEY_TEMPLATE.format(finding_id=finding_id)

    def load(self) -> None:
        self._findings = []
        self._confirmed = set(CONFIRMED_FINDING_IDS)
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load findings store %s: %s", self.path, exc)
            return
        if not isinstance(raw, dict):
            return
        for fid in raw.get("confirmed_ids", []) or []:
            if isinstance(fid, str):
                self._confirmed.add(fid)
        for item in raw.get("findings", []) or []:
            if isinstance(item, dict) and item.get("id"):
                self._findings.append(item)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STORE_VERSION,
            "updated_at": _utcnow(),
            "confirmed_ids": sorted(self._confirmed),
            "findings": self._findings,
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def add_finding(self, finding: dict[str, Any]) -> bool:
        """Persist a finding; return False when skipped (missing id, confirmed, or duplicate)."""
        finding_id = finding.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            return False
        if self.is_confirmed(finding_id):
            return False
        if any(f.get("id") == finding_id for f in self._findings):
            return False
        entry = dict(finding)
        entry["topic_key"] = self.topic_key(finding_id)
        entry["persisted_at"] = _utcnow()
        self._findings.append(entry)
        self.save()
        return True

    def list_findings(self) -> list[dict[str, Any]]:
        return list(self._findings)

    def mark_confirmed(self, finding_id: str) -> bool:
        if not finding_id:
            return False
        self._confirmed.add(finding_id)
        self.save()
        return True

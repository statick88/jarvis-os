"""Skill handler: bffla_idor (BFLA/IDOR tests + local findings store).

Usage::

    result = bffla_idor.run({"action": "list_findings", "context": {"findings_path": ".state/bfla_idor_findings.json"}})
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from jarvis_os.skills.devsecops import bffla_idor as bffla_module
from jarvis_os.skills.devsecops.bffla_idor import BfflaIdorSkill
from jarvis_os.skills.devsecops.bffla_idor_store import FindingsStore

logger = logging.getLogger(__name__)

_SKILL_ACTIONS = frozenset(
    {"enumerate_endpoints", "test_bfla", "test_idor", "get_confirmed", "mark_confirmed"}
)
_PERSIST_ACTIONS = frozenset({"test_bfla", "test_idor"})


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    action = input_data.get("action") or input_data.get("operation", "list_findings")
    context = input_data.get("context") or {}
    findings_path = context.get("findings_path")
    store = FindingsStore(findings_path)

    try:
        if action == "list_findings":
            findings = store.list_findings()
            return {
                "success": True,
                "data": {"findings": findings, "count": len(findings)},
            }
        if action not in _SKILL_ACTIONS:
            return {"success": False, "error": f"Unknown action: {action}"}
        return _run_skill_action(action, input_data, context, store)
    except Exception as exc:
        logger.exception("bffla_idor skill failed")
        return {"success": False, "error": str(exc)}


def _run_skill_action(
    action: str,
    input_data: dict[str, Any],
    context: dict[str, Any],
    store: FindingsStore,
) -> dict[str, Any]:
    # Cross-session recovery: skill probes must skip store-confirmed ids too.
    bffla_module._CONFIRMED_FINDING_IDS.update(store.confirmed_ids)

    skill = BfflaIdorSkill()
    parameters = {
        k: v
        for k, v in input_data.items()
        if k not in {"action", "operation", "context"}
    }
    result = asyncio.run(_execute(skill, action, parameters, context))
    normalized = _normalize(result)
    if not normalized.get("success"):
        return normalized

    data = normalized["data"]
    if action in _PERSIST_ACTIONS:
        persisted = 0
        for finding in data.get("findings") or []:
            if store.add_finding(finding):
                persisted += 1
        data["persisted_count"] = persisted

    if action == "get_confirmed":
        ids = set(data.get("confirmed_ids") or []) | store.confirmed_ids
        data["confirmed_ids"] = sorted(ids)
    elif action == "mark_confirmed":
        finding_id = input_data.get("finding_id") or parameters.get("finding_id")
        if isinstance(finding_id, str) and finding_id:
            store.mark_confirmed(finding_id)
        data["confirmed_ids"] = sorted(
            set(data.get("confirmed_ids") or []) | store.confirmed_ids
        )
    return normalized


async def _execute(
    skill: BfflaIdorSkill,
    action: str,
    parameters: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    await skill.load()
    return await skill.execute(action, parameters, context)


def _normalize(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"success": False, "error": "Invalid skill result"}
    status = result.get("status")
    if status == "success":
        data = {k: v for k, v in result.items() if k not in {"status", "message"}}
        return {"success": True, "data": data}
    error = result.get("message") or result.get("error") or "Skill execution failed"
    return {"success": False, "error": str(error)}

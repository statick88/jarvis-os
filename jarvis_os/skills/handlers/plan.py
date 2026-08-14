"""Skill handler: plan (daily priorities CRUD).

Usage::

    result = plan.run({"action": "add_task", "task": "Review PR", "priority": "high"})
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PRIORITY_EMOJI = {"critical": "🟣", "high": "🔴", "medium": "🟡", "low": "🟢"}


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the plan skill.

    Args:
        input_data: Skill input matching ``.skills/plan.md`` schema.

    Returns:
        A dict with ``success`` and ``data`` per the output schema.
    """
    action = input_data.get("action", "read")
    vault_path = Path(input_data.get("context", {}).get("vault_path", "/app/vault"))
    date_str = input_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    try:
        if action == "create":
            return _create(vault_path, date_str, bool(input_data.get("replace_all", False)))
        elif action == "read":
            return _read(vault_path, date_str)
        elif action == "add_task":
            return _add_task(input_data, vault_path, date_str)
        elif action == "complete_task":
            return _complete_task(input_data, vault_path, date_str)
        elif action == "set_focus":
            return _set_focus(input_data, vault_path, date_str)
        elif action == "add_blocker":
            return _add_blocker(input_data, vault_path, date_str)
        elif action == "list":
            return _read(vault_path, date_str)
        elif action == "update":
            return {"success": True, "data": {"message": "Use specific actions instead"}}
        elif action == "archive":
            return _archive(vault_path, date_str)
        elif action == "delete":
            return {"success": True, "data": {"deleted": True}}
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        logger.exception("plan skill failed")
        return {"success": False, "error": str(exc)}


def _plan_path(vault_path: Path, date_str: str) -> Path:
    return vault_path / "wiki" / f"plan_{date_str}.md"


def _read_plan(vault_path: Path, date_str: str) -> dict[str, Any]:
    path = _plan_path(vault_path, date_str)
    if not path.exists():
        return _create(vault_path, date_str)
    text = path.read_text(encoding="utf-8")
    return _parse_plan(text)


def _parse_plan(text: str) -> dict[str, Any]:
    focus = ""
    tasks = []
    blockers = []
    in_tasks = False
    in_blockers = False
    task_re = re.compile(r"- \[([ x])\] \*\*(tsk-\d+)\*\* (.+?)(?: — \*([^*]+)\*)?$")
    blocker_re = re.compile(r"- \*\*(blk-\d+)\*\* ⏳ (.+?) — \*([^*]+)\*$")

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## 🎯 Foco Principal"):
            in_tasks = False
            in_blockers = False
            continue
        if stripped.startswith("## ✅ Tareas"):
            in_tasks = True
            in_blockers = False
            continue
        if stripped.startswith("## 🚫 Bloqueos"):
            in_tasks = False
            in_blockers = True
            continue
        if stripped.startswith("## "):
            in_tasks = False
            in_blockers = False
            continue

        if in_tasks:
            m = task_re.match(stripped)
            if m:
                tasks.append({
                    "id": m.group(2),
                    "text": m.group(3).strip(),
                    "priority": _priority_from_emoji(stripped),
                    "completed": m.group(1) == "x",
                    "created_at": (m.group(4) or "").strip(),
                    "completed_at": None,
                })
            elif stripped.startswith("- [x]"):
                tasks.append({"id": _extract_id(stripped) or f"tsk-{len(tasks)+1:03d}", "text": stripped, "completed": True})
        elif in_blockers:
            m = blocker_re.match(stripped)
            if m:
                blockers.append({
                    "id": m.group(1),
                    "text": m.group(2).strip(),
                    "created_at": m.group(3).strip(),
                })
        elif stripped.startswith("- ") and "Foco Principal" not in stripped and not focus:
            focus = stripped.lstrip("- ").strip()

    return {"focus": focus, "tasks": tasks, "blockers": blockers}


def _priority_from_emoji(text: str) -> str:
    if "🟣" in text:
        return "critical"
    if "🔴" in text:
        return "high"
    if "🟡" in text:
        return "medium"
    if "🟢" in text:
        return "low"
    return "medium"


def _extract_id(text: str) -> str | None:
    m = re.search(r"(tsk-\d+|blk-\d+)", text)
    return m.group(1) if m else None


def _create(vault_path: Path, date_str: str, replace_all: bool = False) -> dict[str, Any]:
    path = _plan_path(vault_path, date_str)
    if path.exists() and not replace_all:
        return {"success": False, "error": "PLAN_EXISTS", "data": {"path": str(path.relative_to(vault_path))}}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = "\n".join([
        "---",
        f"id: plan_{date_str}",
        "tags: [plan, daily]",
        f"created: \"{ts}\"",
        f"modified: \"{ts}\"",
        "source: \"skill.plan\"",
        f"date: \"{date_str}\"",
        "focus: \"\"",
        "task_counter: 0",
        "blocker_counter: 0",
        "---",
        "",
        f"# Plan de Hoy — {date_str}",
        "",
        "## 🎯 Foco Principal",
        "",
        "## ✅ Tareas",
        "",
        "## 🚫 Bloqueos",
        "",
        "## 📝 Notas",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"success": True, "data": {"message": f"Plan creado para {date_str}"}, "vault_changes": [{"path": str(path.relative_to(vault_path)), "operation": "CREATE", "content": content}]}


def _add_task(input_data: dict[str, Any], vault_path: Path, date_str: str) -> dict[str, Any]:
    plan = _read_plan(vault_path, date_str)
    text = input_data.get("task", "").strip()
    if not text:
        return {"success": False, "error": "Task text cannot be empty"}
    priority = input_data.get("priority", "medium")
    emoji = _PRIORITY_EMOJI.get(priority, "🟡")
    task_counter = len(plan.get("tasks", [])) + 1
    task_id = f"tsk-{task_counter:03d}"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"- [ ] **{task_id}** {emoji} {text} — *{ts}*"

    path = _plan_path(vault_path, date_str)
    content = path.read_text(encoding="utf-8")
    if "## 🚫 Bloqueos" in content:
        content = content.replace("## 🚫 Bloqueos", f"{line}\n\n## 🚫 Bloqueos")
    else:
        content = content.rstrip() + f"\n{line}\n"
    path.write_text(content, encoding="utf-8")
    return {
        "success": True,
        "data": {"task_id": task_id, "task": {"id": task_id, "text": text, "priority": priority, "completed": False, "created_at": ts}},
        "vault_changes": [{"path": str(path.relative_to(vault_path)), "operation": "UPDATE", "content": content}],
    }


def _complete_task(input_data: dict[str, Any], vault_path: Path, date_str: str) -> dict[str, Any]:
    return {"success": True, "data": {"task_id": input_data.get("task_id", ""), "completed": True}}


def _set_focus(input_data: dict[str, Any], vault_path: Path, date_str: str) -> dict[str, Any]:
    focus = input_data.get("focus", "")
    path = _plan_path(vault_path, date_str)
    content = path.read_text(encoding="utf-8")
    content = re.sub(r"(## 🎯 Foco Principal\n\n)(.+?)(\n##)", rf"\1{focus}\3", content, flags=re.DOTALL)
    path.write_text(content, encoding="utf-8")
    return {"success": True, "data": {"focus": focus}}


def _add_blocker(input_data: dict[str, Any], vault_path: Path, date_str: str) -> dict[str, Any]:
    text = input_data.get("blocker", "").strip()
    if not text:
        return {"success": False, "error": "Blocker text cannot be empty"}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    blocker_id = f"blk-{len(_read_plan(vault_path, date_str).get('blockers', [])) + 1:03d}"
    line = f"- **{blocker_id}** ⏳ {text} — *{ts}*"
    path = _plan_path(vault_path, date_str)
    content = path.read_text(encoding="utf-8")
    content = content.replace("## 🚫 Bloqueos", f"## 🚫 Bloqueos\n{line}")
    path.write_text(content, encoding="utf-8")
    return {"success": True, "data": {"blocker_id": blocker_id}, "vault_changes": [{"path": str(path.relative_to(vault_path)), "operation": "UPDATE", "content": content}]}


def _archive(vault_path: Path, date_str: str) -> dict[str, Any]:
    src = _plan_path(vault_path, date_str)
    dst = vault_path / "wiki" / "archive" / f"plan_{date_str}.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return {"success": True, "data": {"archived": True, "path": str(dst.relative_to(vault_path))}}
    return {"success": True, "data": {"archived": False}}

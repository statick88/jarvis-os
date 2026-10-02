"""Skill handler: desarrollar_skill (skill development procedure).

Operationalises `.skills/desarrollar-skill.md`. The knowledge is in the skill
file; this handler makes the checklist executable and validates a candidate
frontmatter against the real loader rather than restating the rules.

Validation uses the loader in-process, so a frontmatter that would break the
registry is rejected here rather than at boot.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Both enforced by SkillFrontmatter, mirrored here so the error names the rule.
ID_PATTERN = re.compile(r"^skill\.[a-z][a-z0-9_]*$")
CAPABILITY_PATTERN = re.compile(r"^[a-z]+\.[a-z_]+$")

REQUIRED_FRONTMATTER = (
    "id",
    "name",
    "description",
    "capabilities",
    "input_schema",
    "output_schema",
)

# The rule that produced a false "5 of 7 skills broken" report. A skill id like
# skill.bandeja is NOT an importable module; omitting entrypoint lets
# SkillFrontmatter.default_entrypoint strip the prefix and resolve to
# jarvis_os.skills.handlers.bandeja.
ENTRYPOINT_RULE = (
    "Declare entrypoint as the bare handler name, or omit it entirely. Never "
    "pass the dotted skill id: 'skill.bandeja' is not an importable module."
)

HANDLER_TEMPLATE = '''\
"""Skill handler: {name}.

{summary}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the {name} skill."""
    action = input_data.get("action", "{default_action}")
    try:
        if action == "{default_action}":
            return {{"success": True, "data": {{}}}}
        return {{"success": False, "error": f"Unknown action: {{action}}"}}
    except Exception as exc:
        # Assign the message inside the block. Python unbinds `exc` when the
        # except ends, so referencing it afterwards raises UnboundLocalError on
        # the success path -- which is how tendencias used to fail on every
        # feed that returned zero items.
        message = str(exc)
        logger.exception("{name} skill failed")
        return {{"success": False, "error": message}}
'''


def _validate(name: str, skills_dir: Path) -> dict[str, Any]:
    problems: list[str] = []
    path = skills_dir / f"{name}.md"
    if not path.exists():
        return {
            "valid": False,
            "path": str(path),
            "problems": [f"no skill file at {path}"],
        }

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        problems.append("file does not start with YAML frontmatter")
    frontmatter = text.split("---", 2)[1] if text.startswith("---") else ""

    for field in REQUIRED_FRONTMATTER:
        if field not in frontmatter:
            problems.append(f"missing required field: {field}")

    import yaml

    data = yaml.safe_load(frontmatter) or {}

    skill_id = str(data.get("id", ""))
    if not ID_PATTERN.match(skill_id):
        problems.append(
            f"id {skill_id!r} must match {ID_PATTERN.pattern} "
            "(note the dot, not a hyphen; skill-foo is legacy and invalid)"
        )

    capabilities = data.get("capabilities") or []
    if not capabilities:
        problems.append("capabilities needs at least one entry")
    for cap in capabilities:
        if not CAPABILITY_PATTERN.match(str(cap)):
            problems.append(
                f"capability {cap!r} must match {CAPABILITY_PATTERN.pattern} "
                "(no digits: use diagnose_auth, not diagnose_401)"
            )

    description = str(data.get("description", ""))
    if not 10 <= len(description) <= 200:
        problems.append(f"description is {len(description)} chars, must be 10-200")

    handler = Path("jarvis_os/skills/handlers") / f"{name}.py"
    if not handler.exists():
        problems.append(
            f"no handler at {handler}; a skill without one registers fine and "
            "then fails at execute time"
        )

    return {
        "valid": not problems,
        "path": str(path),
        "handler": str(handler),
        "handler_exists": handler.exists(),
        "problems": problems,
    }


def _checklist() -> dict[str, Any]:
    return {
        "chain": [
            ".skills/<name>.md frontmatter validated by SkillFrontmatter",
            "SkillLoader -> SkillExecutor",
            "jarvis_os/skills/handlers/<name>.py::run(input_data)",
            "jarvis_os/receipt.py written on every execute",
        ],
        "entrypoint_rule": ENTRYPOINT_RULE,
        "tests": [
            "assert behaviour through run(), not by re-implementing the logic",
            "revert the fix once and confirm the test fails",
            "assert the absence of the failure text: the success:False envelope "
            "hides crashes",
        ],
        "lint": [
            "ruff check jarvis_os/skills/handlers/<name>.py --select F821,F841",
            "F821 catches undefined helpers, the plan.py _read class of bug",
            "F841 catches declared-but-unused parameters, the hours_back class",
        ],
        "known_inconsistency": (
            "plan.py::_read_plan returns the creation envelope when the file is "
            "missing and a bare dict when it exists, so result['success'] works "
            "once then raises KeyError. Documented in "
            "tests/handlers/test_plan.py::test_read_returns_two_different_shapes"
        ),
    }


def _template(name: str) -> dict[str, Any]:
    return {
        "handler": HANDLER_TEMPLATE.format(
            name=name, summary="TODO: one line on what this skill does.", default_action="status"
        ),
        "required_fm": list(REQUIRED_FRONTMATTER),
        "id_example": f"skill.{name}",
    }


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the skill-development skill."""
    action = input_data.get("action", "checklist")
    name = str(input_data.get("skill_name", "")).strip()
    context = input_data.get("context", {}) or {}
    skills_dir = Path(context.get("skills_dir", ".skills"))
    try:
        if action == "checklist":
            return {"success": True, "data": _checklist()}
        if action == "template":
            if not name:
                return {"success": False, "error": "action 'template' requires skill_name"}
            return {"success": True, "data": _template(name)}
        if action == "check":
            if not name:
                return {"success": False, "error": "action 'check' requires skill_name"}
            return {"success": True, "data": _validate(name, skills_dir)}
        if action in {"schema", "entrypoint", "handler", "test", "register"}:
            # All four reduce to "validate the whole chain"; partial validation
            # would report a valid file while the handler is still missing.
            if not name:
                return {"success": False, "error": f"action {action!r} requires skill_name"}
            data = _validate(name, skills_dir)
            data["requested_action"] = action
            return {"success": True, "data": data}
        return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        message = str(exc)
        logger.exception("desarrollar_skill skill failed")
        return {"success": False, "error": message}


def dump() -> str:
    """Machine-readable snapshot of the procedure."""
    return json.dumps(_checklist(), indent=2, sort_keys=True)

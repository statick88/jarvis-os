"""Skills API routes for JARVIS-OS.

Uses the canonical skills stack: SkillLoader → SkillRegistry → SkillExecutor.
PluginRegistry is deprecated but kept as fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis_os.skills.executor import SkillExecutor
from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.models import SkillMetadata
from jarvis_os.skills.registry import SkillRegistry
from jarvis_os.skills.plugin_registry_instance import shared_registry as plugin_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

_skills_dir = Path("/app/.skills")
_executor = SkillExecutor(default_timeout=30)
_registry = SkillRegistry()
_loader = SkillLoader(skills_dir=_skills_dir)


class ExecuteRequest(BaseModel):
    operation: str = Field(..., description="Operation name to execute")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Operation parameters")
    context: dict[str, Any] = Field(default_factory=dict, description="Runtime context")


@router.get("")
async def list_skills() -> dict[str, Any]:
    """List all registered skills and their schemas."""
    legacy = plugin_registry.list_skills()
    try:
        metadata_list = await _loader.load_all()
        canonical = [
            {
                "name": meta.frontmatter.id,
                "version": meta.frontmatter.version,
                "permissions": [],
                "schema": meta.frontmatter.input_schema,
            }
            for meta in metadata_list.values()
        ]
        return {"skills": canonical + legacy}
    except Exception as exc:
        logger.warning("Canonical skill listing failed, falling back to legacy: %s", exc)
        return {"skills": legacy}


@router.post("/{skill_name}/execute")
async def execute_skill(skill_name: str, request: ExecuteRequest) -> dict[str, Any]:
    """Execute an operation on a registered skill."""
    try:
        metadata_list = await _loader.load_all()
        skill = metadata_list.get(skill_name) or metadata_list.get(skill_name.replace("-", "."))
        if skill is not None:
            # Forward the requested operation into the canonical input payload
            # so skill handlers can dispatch on it.
            input_data = {**request.parameters, "operation": request.operation}
            result = await _executor.execute(
                skill=skill,
                input_data=input_data,
                execution_type=skill.frontmatter.execution_type,
            )
            return _executor_result_to_response(result)
    except Exception as exc:
        logger.warning("Canonical execution path failed for %s: %s", skill_name, exc)

    legacy = plugin_registry.get(skill_name)
    if legacy is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    result = await legacy.execute(request.operation, request.parameters, request.context)
    return result


@router.get("/{skill_name}/health")
async def skill_health(skill_name: str) -> dict[str, Any]:
    """Health check for a specific skill."""
    legacy = plugin_registry.get(skill_name)
    if legacy is not None:
        return {
            "skill": skill_name,
            "status": "healthy" if legacy.is_loaded else "not_loaded",
            "version": legacy.version,
            "path": "legacy-plugin",
        }

    try:
        metadata_list = await _loader.load_all()
        skill = metadata_list.get(skill_name) or metadata_list.get(skill_name.replace("-", "."))
        if skill is not None:
            return {
                "skill": skill_name,
                "status": "healthy",
                "version": skill.frontmatter.version,
                "path": str(skill.path),
            }
    except Exception as exc:
        logger.warning("Canonical health check failed for %s: %s", skill_name, exc)

    raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")


def _executor_result_to_response(result: Any) -> dict[str, Any]:
    status = "success" if result.ok else "error"
    payload: dict[str, Any] = {"status": status}
    if result.ok:
        payload["result"] = result.output
    else:
        payload["message"] = result.error
    return payload

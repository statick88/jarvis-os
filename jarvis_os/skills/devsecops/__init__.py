"""DevSecOps skill plugin package."""

from __future__ import annotations

from jarvis_os.skills.devsecops.bffla_idor import BfflaIdorSkill
from jarvis_os.skills.devsecops.plugin import DevSecOpsSkill

__all__ = ["BfflaIdorSkill", "DevSecOpsSkill"]

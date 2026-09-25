"""Skill handlers package for JARVIS-OS.

Each submodule exposes a ``run(input: dict) -> dict`` function matching
the corresponding ``.skills/*.md`` contract.
"""

from __future__ import annotations

from jarvis_os.skills.handlers.metricas import run as metricas_run
from jarvis_os.skills.handlers.bandeja import run as bandeja_run
from jarvis_os.skills.handlers.tendencias import run as tendencias_run
from jarvis_os.skills.handlers.plan import run as plan_run
from jarvis_os.skills.handlers.boveda import run as boveda_run
from jarvis_os.skills.handlers.obsidian import run as obsidian_run
from jarvis_os.skills.handlers.bffla_idor import run as bffla_idor_run

__all__ = [
    "metricas_run",
    "bandeja_run",
    "tendencias_run",
    "plan_run",
    "boveda_run",
    "obsidian_run",
    "bffla_idor_run",
]

"""
Nightly Labs Skill
==================
Autonomous nightly worker for JARVIS OS. Scans Obsidian vault for tagged notes,
processes them with local LLM engines, and generates daily reports.

Pipeline: scan_vault → extract_notes → process_with_llm → generate_report
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis_os.skills.base import BaseSkill, SkillPermission
from jarvis_os.vault.models import VaultNote
from jarvis_os.vault.search import VaultSearch

logger = logging.getLogger(__name__)

# Tag-to-type mapping for nightly processing
TAG_TYPE_MAP: dict[str, str] = {
    "#idea": "idea",
    "#todo": "todo",
    "#research": "research",
}

# Prompt templates per note type
PROMPT_TEMPLATES: dict[str, str] = {
    "idea": (
        "You are JARVIS, an AI assistant. Analyze this idea note and provide:\n"
        "1. A brief summary (2-3 sentences)\n"
        "2. Key insights or potential applications\n"
        "3. Suggested next steps or related topics to explore\n\n"
        "Note content:\n{content}"
    ),
    "todo": (
        "You are JARVIS, an AI assistant. Analyze this task note and provide:\n"
        "1. Priority assessment (high/medium/low)\n"
        "2. Estimated complexity (simple/moderate/complex)\n"
        "3. Suggested breakdown if complex\n\n"
        "Note content:\n{content}"
    ),
    "research": (
        "You are JARVIS, an AI assistant. Analyze this research note and provide:\n"
        "1. Key findings summary\n"
        "2. Implications or applications\n"
        "3. Gaps or areas needing further investigation\n\n"
        "Note content:\n{content}"
    ),
}

# Report frontmatter template
REPORT_FRONTMATTER = """---
date: "{date}"
tasks_executed:
{tasks_executed}
ideas_extracted:
{ideas_extracted}
tasks_pending:
{tasks_pending}
research_findings:
{research_findings}
resource_metrics:
  cpu_average: {cpu_average}
  ram_peak_mb: {ram_peak_mb}
---
"""


class NightlyLabsSkill(BaseSkill):
    """Autonomous nightly worker for vault scanning and LLM processing."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(
            name="nightly-labs",
            version="0.0.1",
            permissions=[SkillPermission.READ_VAULT, SkillPermission.WRITE_VAULT],
        )
        self.description = "Autonomous nightly worker: scans vault, processes notes with local LLM, generates reports"
        self.supported_operations = ["scan_vault", "extract_notes", "process_with_llm", "generate_report"]
        self._config = config
        self._vault_search: VaultSearch | None = None
        self._llm_available: bool = False
        self._llm_engine: str | None = None
        self._report_dir: Path | None = None

    async def load(self) -> None:
        """Load the skill and initialize vault/LLM connections."""
        await super().load()

        config = self._config

        # Initialize vault search
        vault_root = Path(config.get("vault_root", "/app/vault")) if config else Path("/app/vault")
        index_path = Path(config["index_path"]) if config and "index_path" in config else None
        self._vault_search = VaultSearch(vault_root, index_path=index_path)

        # Initialize report directory
        self._report_dir = vault_root / "_Nightly_Reports"
        self._report_dir.mkdir(parents=True, exist_ok=True)

        # Detect LLM engine
        self._detect_llm_engine()

        logger.info(
            "NightlyLabsSkill loaded",
            extra={"llm_available": self._llm_available, "llm_engine": self._llm_engine},
        )

    def _detect_llm_engine(self) -> None:
        """Detect available local LLM engine in preference order."""
        # Check llama.cpp first
        if shutil.which("llama-cli"):
            self._llm_engine = "llama.cpp"
            self._llm_available = True
            logger.info("Detected LLM engine: llama.cpp")
            return

        # Check Ollama
        try:
            result = subprocess.run(
                ["curl", "-s", "http://localhost:11434/api/tags"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                self._llm_engine = "ollama"
                self._llm_available = True
                logger.info("Detected LLM engine: Ollama")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Check for .gguf model directories
        gguf_dirs = list(Path("/app/models").glob("**/*.gguf")) if Path("/app/models").exists() else []
        if gguf_dirs:
            self._llm_engine = "local_gguf"
            self._llm_available = True
            logger.info("Detected LLM engine: local GGUF models")
            return

        # No LLM available
        self._llm_engine = None
        self._llm_available = False
        logger.warning("No local LLM engine detected - nightly processing will skip LLM steps")

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "nightly-labs",
            "version": self.version,
            "operations": {
                "scan_vault": {
                    "description": "Scan Obsidian vault for notes with nightly tags (#idea, #todo, #research)",
                    "parameters": {
                        "vault_root": {"type": "string", "description": "Override vault root path"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Override tag list"},
                    },
                },
                "extract_notes": {
                    "description": "Read full content of vault notes found during scan",
                    "parameters": {
                        "vault_root": {"type": "string", "description": "Override vault root path"},
                    },
                },
                "process_with_llm": {
                    "description": "Process extracted notes with local LLM engine (llama.cpp / ollama)",
                    "parameters": {
                        "timeout": {"type": "integer", "description": "Per-note LLM timeout in seconds", "default": 30},
                    },
                },
                "generate_report": {
                    "description": "Generate daily processing report with metrics and summaries",
                    "parameters": {
                        "report_dir": {"type": "string", "description": "Directory to save report files"},
                    },
                },
            },
        }

    async def execute(self, operation: str, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Execute a nightly labs operation."""
        if not self.is_loaded:
            return {"error": "Skill not loaded", "success": False}

        operations = {
            "scan_vault": self.scan_vault,
            "extract_notes": self.extract_notes,
            "process_with_llm": self.process_with_llm,
            "generate_report": self.generate_report,
        }

        if operation not in operations:
            return {"error": f"Unknown operation: {operation}", "success": False}

        try:
            return await operations[operation](parameters, context)
        except Exception as e:
            logger.error(f"Operation {operation} failed: {e}", exc_info=True)
            return {"error": str(e), "success": False}

    async def scan_vault(self, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Scan vault for notes with nightly tags (#idea, #todo, #research)."""
        if not self._vault_search:
            return {"error": "Vault search not initialized", "success": False}

        target_tags = parameters.get("tags", list(TAG_TYPE_MAP.keys()))
        notes_found: list[dict[str, Any]] = []

        for tag in target_tags:
            result = await self._vault_search.search(query="", tags=[tag])
            if result.success and result.data.get("search_results"):
                for entry in result.data["search_results"]:
                    notes_found.append({
                        "id": entry.get("id", ""),
                        "title": entry.get("title", ""),
                        "path": entry.get("rel_path", ""),
                        "tags": entry.get("tags", []),
                        "matched_tag": tag,
                        "note_type": TAG_TYPE_MAP.get(tag, "unknown"),
                    })

        # Deduplicate by note_id
        seen_ids: set[str] = set()
        unique_notes: list[dict[str, Any]] = []
        for note in notes_found:
            if note["id"] not in seen_ids:
                seen_ids.add(note["id"])
                unique_notes.append(note)

        return {
            "success": True,
            "notes_found": unique_notes,
            "total_count": len(unique_notes),
            "tags_scanned": target_tags,
        }

    async def extract_notes(self, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Extract full content from scanned notes."""
        notes = parameters.get("notes", [])
        if not notes:
            return {"error": "No notes provided for extraction", "success": False}

        extracted: list[dict[str, Any]] = []
        for note_meta in notes:
            note_path = Path(note_meta.get("path", ""))
            if not note_path.exists():
                logger.warning(f"Note file not found: {note_path}")
                continue

            try:
                content = note_path.read_text(encoding="utf-8")
                extracted.append({
                    **note_meta,
                    "content": content,
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.error(f"Failed to extract note {note_path}: {e}")

        return {
            "success": True,
            "extracted_notes": extracted,
            "total_extracted": len(extracted),
            "total_failed": len(notes) - len(extracted),
        }

    async def process_with_llm(self, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Process extracted notes with local LLM engine."""
        notes = parameters.get("extracted_notes", [])
        if not notes:
            return {"error": "No extracted notes provided", "success": False}

        if not self._llm_available:
            logger.info("LLM unavailable - marking all tasks as skipped")
            return {
                "success": True,
                "processed": [],
                "skipped": [{"note": n["id"], "reason": "no_llm_available"} for n in notes],
                "llm_engine": None,
            }

        processed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for note in notes:
            note_type = note.get("note_type", "unknown")
            template = PROMPT_TEMPLATES.get(note_type)
            if not template:
                skipped.append({"note": note["id"], "reason": "unknown_note_type"})
                continue

            prompt = template.format(content=note.get("content", "")[:2000])  # Limit content length

            try:
                result = await self._run_llm_prompt(prompt, timeout=30)
                processed.append({
                    "note_id": note["id"],
                    "note_type": note_type,
                    "prompt_used": note_type,
                    "llm_response": result,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                })
            except asyncio.TimeoutError:
                skipped.append({"note": note["id"], "reason": "llm_timeout"})
            except Exception as e:
                skipped.append({"note": note["id"], "reason": f"llm_error: {e}"})

        return {
            "success": True,
            "processed": processed,
            "skipped": skipped,
            "llm_engine": self._llm_engine,
        }

    async def _run_llm_prompt(self, prompt: str, timeout: int = 30) -> str:
        """Run a prompt against the detected LLM engine."""
        if self._llm_engine == "llama.cpp":
            return await self._run_llama_cpp(prompt, timeout)
        elif self._llm_engine == "ollama":
            return await self._run_ollama(prompt, timeout)
        elif self._llm_engine == "local_gguf":
            return await self._run_local_gguf(prompt, timeout)
        else:
            raise RuntimeError(f"Unknown LLM engine: {self._llm_engine}")

    async def _run_llama_cpp(self, prompt: str, timeout: int) -> str:
        """Run prompt using llama.cpp CLI."""
        process = await asyncio.create_subprocess_exec(
            "llama-cli",
            "-p", prompt,
            "-n", "256",  # Max tokens
            "--temp", "0.7",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return stdout.decode("utf-8").strip()

    async def _run_ollama(self, prompt: str, timeout: int) -> str:
        """Run prompt using Ollama API."""
        import aiohttp

        payload = {
            "model": "llama3.2",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:11434/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                data = await response.json()
                return data.get("message", {}).get("content", "")

    async def _run_local_gguf(self, prompt: str, timeout: int) -> str:
        """Run prompt using local GGUF model (via llama-cli)."""
        # Find first available .gguf model
        model_paths = list(Path("/app/models").glob("**/*.gguf"))
        if not model_paths:
            raise RuntimeError("No .gguf model files found")

        model_path = model_paths[0]
        process = await asyncio.create_subprocess_exec(
            "llama-cli",
            "-m", str(model_path),
            "-p", prompt,
            "-n", "256",
            "--temp", "0.7",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return stdout.decode("utf-8").strip()

    async def generate_report(self, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Generate nightly report in Markdown format."""
        scan_results = parameters.get("scan_results", {})
        extraction_results = parameters.get("extraction_results", {})
        llm_results = parameters.get("llm_results", {})
        metrics = parameters.get("metrics", {"cpu_average": 0.0, "ram_peak_mb": 0})

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report_path = self._report_dir / f"{today}.md" if self._report_dir else Path(f"_Nightly_Reports/{today}.md")

        # Build frontmatter sections
        tasks_executed = self._format_tasks_executed(llm_results)
        ideas_extracted = self._format_ideas_extracted(llm_results)
        tasks_pending = self._format_tasks_pending(scan_results)
        research_findings = self._format_research_findings(llm_results)

        frontmatter = REPORT_FRONTMATTER.format(
            date=today,
            tasks_executed=tasks_executed,
            ideas_extracted=ideas_extracted,
            tasks_pending=tasks_pending,
            research_findings=research_findings,
            cpu_average=metrics.get("cpu_average", 0.0),
            ram_peak_mb=metrics.get("ram_peak_mb", 0),
        )

        # Build report body
        body = self._build_report_body(scan_results, llm_results)

        # Write report
        report_content = frontmatter + "\n" + body
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        logger.info(f"Nightly report generated: {report_path}")

        return {
            "success": True,
            "report_path": str(report_path),
            "date": today,
            "sections": {
                "tasks_executed": len(llm_results.get("processed", [])),
                "ideas_extracted": sum(
                    1 for p in llm_results.get("processed", []) if p.get("note_type") == "idea"
                ),
                "tasks_pending": len(scan_results.get("notes_found", [])),
                "research_findings": sum(
                    1 for p in llm_results.get("processed", []) if p.get("note_type") == "research"
                ),
            },
        }

    def _format_tasks_executed(self, llm_results: dict[str, Any]) -> str:
        """Format tasks_executed for frontmatter."""
        processed = llm_results.get("processed", [])
        skipped = llm_results.get("skipped", [])

        lines: list[str] = []
        for i, task in enumerate(processed, 1):
            lines.append(
                f'  - {{id: "{i}", status: "completed", duration_ms: 0, prompt: "{task.get("prompt_used", "unknown")}"}}'
            )
        for i, task in enumerate(skipped, len(processed) + 1):
            lines.append(
                f'  - {{id: "{i}", status: "skipped", reason: "{task.get("reason", "unknown")}"}}'
            )

        return "\n".join(lines) if lines else "  []"

    def _format_ideas_extracted(self, llm_results: dict[str, Any]) -> str:
        """Format ideas_extracted for frontmatter."""
        ideas = [p for p in llm_results.get("processed", []) if p.get("note_type") == "idea"]

        lines: list[str] = []
        for idea in ideas:
            lines.append(
                f'  - {{title: "{idea.get("note_id", "untitled")}", source: "vault", confidence: 0.85}}'
            )

        return "\n".join(lines) if lines else "  []"

    def _format_tasks_pending(self, scan_results: dict[str, Any]) -> str:
        """Format tasks_pending for frontmatter."""
        todos = [
            n for n in scan_results.get("notes_found", [])
            if n.get("note_type") == "todo"
        ]

        lines: list[str] = []
        for todo in todos:
            lines.append(
                f'  - {{title: "{todo.get("title", "untitled")}", source: "{todo.get("path", "vault")}"}}'
            )

        return "\n".join(lines) if lines else "  []"

    def _format_research_findings(self, llm_results: dict[str, Any]) -> str:
        """Format research_findings for frontmatter."""
        research = [p for p in llm_results.get("processed", []) if p.get("note_type") == "research"]

        lines: list[str] = []
        for r in research:
            lines.append(
                f'  - {{topic: "{r.get("note_id", "untitled")}", source: "vault", summary: "Processed by nightly worker"}}'
            )

        return "\n".join(lines) if lines else "  []"

    def _build_report_body(self, scan_results: dict[str, Any], llm_results: dict[str, Any]) -> str:
        """Build the Markdown body of the report."""
        sections: list[str] = []

        sections.append("# Nightly Labs Report\n")

        # Ideas section
        ideas = [p for p in llm_results.get("processed", []) if p.get("note_type") == "idea"]
        if ideas:
            sections.append("## Ideas Processed\n")
            for idea in ideas:
                sections.append(f"### {idea.get('note_id', 'Untitled')}\n")
                sections.append(f"{idea.get('llm_response', 'No response')}\n")

        # Research section
        research = [p for p in llm_results.get("processed", []) if p.get("note_type") == "research"]
        if research:
            sections.append("## Research Findings\n")
            for r in research:
                sections.append(f"### {r.get('note_id', 'Untitled')}\n")
                sections.append(f"{r.get('llm_response', 'No response')}\n")

        # Pending tasks section
        todos = [n for n in scan_results.get("notes_found", []) if n.get("note_type") == "todo"]
        if todos:
            sections.append("## Pending Tasks\n")
            for todo in todos:
                sections.append(f"- [ ] {todo.get('title', 'Untitled')} ({todo.get('path', 'vault')})")

        # Skipped tasks
        skipped = llm_results.get("skipped", [])
        if skipped:
            sections.append("\n## Skipped Tasks\n")
            for s in skipped:
                sections.append(f"- {s.get('note', 'unknown')}: {s.get('reason', 'unknown')}")

        return "\n".join(sections)

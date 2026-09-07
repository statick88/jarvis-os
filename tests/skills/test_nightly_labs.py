"""
Tests for NightlyLabsSkill
==========================
Comprehensive tests covering: init, load, LLM detection, execute dispatch,
scan_vault, extract_notes, process_with_llm, generate_report, and helpers.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis_os.skills.base import SkillPermission
from jarvis_os.skills.nightly_labs import (
    TAG_TYPE_MAP,
    PROMPT_TEMPLATES,
    NightlyLabsSkill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault_search_result(
    notes: list[dict[str, Any]] | None = None,
    success: bool = True,
) -> MagicMock:
    """Create a mock VaultOperationResult with search_results."""
    result = MagicMock()
    result.success = success
    result.data = {"search_results": notes or [], "total": len(notes or [])}
    return result


def _make_note_meta(
    note_id: str = "note-1",
    title: str = "Test Note",
    path: str = "/tmp/test-note.md",
    tags: list[str] | None = None,
    note_type: str = "idea",
    content: str = "Test content",
) -> dict[str, Any]:
    """Create note metadata dict as returned by scan_vault."""
    return {
        "id": note_id,
        "title": title,
        "path": path,
        "tags": tags or ["#idea"],
        "matched_tag": "#idea",
        "note_type": note_type,
    }


def _make_extracted_note(
    note_id: str = "note-1",
    note_type: str = "idea",
    content: str = "Test content here",
) -> dict[str, Any]:
    """Create extracted note dict as returned by extract_notes."""
    return {
        "id": note_id,
        "title": "Test",
        "path": "/tmp/test.md",
        "tags": ["#idea"],
        "matched_tag": "#idea",
        "note_type": note_type,
        "content": content,
        "extracted_at": "2026-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------

class TestNightlyLabsInit:
    def test_default_init(self) -> None:
        skill = NightlyLabsSkill()
        assert skill.name == "nightly-labs"
        assert skill.version == "0.0.1"
        assert SkillPermission.READ_VAULT in skill.permissions
        assert SkillPermission.WRITE_VAULT in skill.permissions
        assert len(skill.permissions) == 2

    def test_init_with_config(self) -> None:
        config = {"vault_root": "/custom/vault", "index_path": "/custom/index"}
        skill = NightlyLabsSkill(config=config)
        assert skill._config == config

    def test_init_sets_description(self) -> None:
        skill = NightlyLabsSkill()
        assert "nightly" in skill.description.lower()

    def test_init_sets_supported_operations(self) -> None:
        skill = NightlyLabsSkill()
        expected = {"scan_vault", "extract_notes", "process_with_llm", "generate_report"}
        assert set(skill.supported_operations) == expected

    def test_init_internal_state(self) -> None:
        skill = NightlyLabsSkill()
        assert skill._vault_search is None
        assert skill._llm_available is False
        assert skill._llm_engine is None
        assert skill._report_dir is None


# ---------------------------------------------------------------------------
# Load tests
# ---------------------------------------------------------------------------

class TestNightlyLabsLoad:
    @pytest.mark.asyncio
    async def test_load_initializes_vault_search(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        with patch.object(skill, "_detect_llm_engine"):
            await skill.load()
        assert skill._vault_search is not None
        assert skill.is_loaded

    @pytest.mark.asyncio
    async def test_load_creates_report_dir(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        with patch.object(skill, "_detect_llm_engine"):
            await skill.load()
        assert skill._report_dir is not None
        assert skill._report_dir.exists()

    @pytest.mark.asyncio
    async def test_load_calls_detect_llm(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        with patch.object(skill, "_detect_llm_engine") as mock_detect:
            await skill.load()
        mock_detect.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_default_vault_root(self) -> None:
        skill = NightlyLabsSkill()
        with (
            patch("jarvis_os.skills.nightly_labs.VaultSearch"),
            patch("pathlib.Path.mkdir"),
            patch.object(skill, "_detect_llm_engine"),
        ):
            await skill.load()
        assert skill._vault_search is not None


# ---------------------------------------------------------------------------
# LLM Detection tests
# ---------------------------------------------------------------------------

class TestDetectLLMEngine:
    def test_detect_llama_cpp(self) -> None:
        skill = NightlyLabsSkill()
        with patch("jarvis_os.skills.nightly_labs.shutil.which", return_value="/usr/bin/llama-cli"):
            skill._detect_llm_engine()
        assert skill._llm_engine == "llama.cpp"
        assert skill._llm_available is True

    def test_detect_ollama(self) -> None:
        skill = NightlyLabsSkill()
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("jarvis_os.skills.nightly_labs.shutil.which", return_value=None),
            patch("jarvis_os.skills.nightly_labs.subprocess.run", return_value=mock_result),
            patch("pathlib.Path.exists", return_value=False),
        ):
            skill._detect_llm_engine()
        assert skill._llm_engine == "ollama"
        assert skill._llm_available is True

    def test_detect_local_gguf(self) -> None:
        skill = NightlyLabsSkill()
        mock_result = MagicMock()
        mock_result.returncode = 1  # curl fails
        with (
            patch("jarvis_os.skills.nightly_labs.shutil.which", return_value=None),
            patch("jarvis_os.skills.nightly_labs.subprocess.run", return_value=mock_result),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.glob", return_value=[Path("/app/models/model.gguf")]),
        ):
            skill._detect_llm_engine()
        assert skill._llm_engine == "local_gguf"
        assert skill._llm_available is True

    def test_detect_no_llm(self) -> None:
        skill = NightlyLabsSkill()
        mock_result = MagicMock()
        mock_result.returncode = 1
        with (
            patch("jarvis_os.skills.nightly_labs.shutil.which", return_value=None),
            patch("jarvis_os.skills.nightly_labs.subprocess.run", return_value=mock_result),
            patch("pathlib.Path.exists", return_value=False),
        ):
            skill._detect_llm_engine()
        assert skill._llm_engine is None
        assert skill._llm_available is False

    def test_detect_ollama_timeout(self) -> None:
        skill = NightlyLabsSkill()
        with (
            patch("jarvis_os.skills.nightly_labs.shutil.which", return_value=None),
            patch(
                "jarvis_os.skills.nightly_labs.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="curl", timeout=5),
            ),
            patch("pathlib.Path.exists", return_value=False),
        ):
            skill._detect_llm_engine()
        assert skill._llm_engine is None
        assert skill._llm_available is False


# ---------------------------------------------------------------------------
# Execute dispatch tests
# ---------------------------------------------------------------------------

class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_not_loaded(self) -> None:
        skill = NightlyLabsSkill()
        result = await skill.execute("scan_vault", {}, {})
        assert result["success"] is False
        assert "not loaded" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_execute_unknown_operation(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        result = await skill.execute("nonexistent_op", {}, {})
        assert result["success"] is False
        assert "unknown" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_execute_dispatches_scan_vault(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        with patch.object(skill, "scan_vault", return_value={"success": True}) as mock:
            result = await skill.execute("scan_vault", {"tags": ["#idea"]}, {})
        mock.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_dispatches_extract_notes(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        with patch.object(skill, "extract_notes", return_value={"success": True}) as mock:
            result = await skill.execute("extract_notes", {"notes": []}, {})
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_dispatches_process_with_llm(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        with patch.object(skill, "process_with_llm", return_value={"success": True}) as mock:
            result = await skill.execute("process_with_llm", {}, {})
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_dispatches_generate_report(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        with patch.object(skill, "generate_report", return_value={"success": True}) as mock:
            result = await skill.execute("generate_report", {}, {})
        mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_catches_exceptions(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        with patch.object(
            skill, "scan_vault", side_effect=RuntimeError("boom")
        ):
            result = await skill.execute("scan_vault", {}, {})
        assert result["success"] is False
        assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# scan_vault tests
# ---------------------------------------------------------------------------

class TestScanVault:
    @pytest.mark.asyncio
    async def test_scan_no_vault_search(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._vault_search = None
        result = await skill.scan_vault({}, {})
        assert result["success"] is False
        assert "not initialized" in result["error"]

    @pytest.mark.asyncio
    async def test_scan_with_default_tags(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._vault_search = AsyncMock()
        skill._vault_search.search.return_value = _make_vault_search_result()
        result = await skill.scan_vault({}, {})
        assert result["success"] is True
        assert result["tags_scanned"] == list(TAG_TYPE_MAP.keys())
        assert result["total_count"] == 0

    @pytest.mark.asyncio
    async def test_scan_finds_notes(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        notes = [
            {"id": "n1", "title": "Idea 1", "rel_path": "/v/idea1.md", "tags": ["#idea"]},
            {"id": "n2", "title": "Idea 2", "rel_path": "/v/idea2.md", "tags": ["#idea"]},
        ]
        skill._vault_search = AsyncMock()
        skill._vault_search.search.return_value = _make_vault_search_result(notes)
        result = await skill.scan_vault({"tags": ["#idea"]}, {})
        assert result["success"] is True
        assert result["total_count"] == 2
        assert result["notes_found"][0]["note_type"] == "idea"

    @pytest.mark.asyncio
    async def test_scan_deduplicates_notes(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        # Same note_id returned for two different tags
        notes_tag1 = [{"id": "n1", "title": "Note", "rel_path": "/v/n.md", "tags": ["#idea", "#todo"]}]
        notes_tag2 = [{"id": "n1", "title": "Note", "rel_path": "/v/n.md", "tags": ["#idea", "#todo"]}]
        call_count = 0

        async def fake_search(query: str, tags: list[str] | None = None) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_vault_search_result(notes_tag1)
            return _make_vault_search_result(notes_tag2)

        skill._vault_search = AsyncMock()
        skill._vault_search.search.side_effect = fake_search
        result = await skill.scan_vault({}, {})
        # n1 should appear only once
        ids = [n["id"] for n in result["notes_found"]]
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_scan_search_failure(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._vault_search = AsyncMock()
        skill._vault_search.search.return_value = _make_vault_search_result(success=False)
        result = await skill.scan_vault({"tags": ["#idea"]}, {})
        assert result["success"] is True
        assert result["total_count"] == 0


# ---------------------------------------------------------------------------
# extract_notes tests
# ---------------------------------------------------------------------------

class TestExtractNotes:
    @pytest.mark.asyncio
    async def test_extract_no_notes(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        result = await skill.extract_notes({}, {})
        assert result["success"] is False
        assert "no notes" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_scan_vault_uses_vault_search(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        note_file = tmp_path / "note1.md"
        note_file.write_text("# My Idea\n\nSome content here", encoding="utf-8")
        notes = [_make_note_meta(note_id="n1", path=str(note_file))]
        result = await skill.extract_notes({"notes": notes}, {})
        assert result["success"] is True
        assert result["total_extracted"] == 1
        assert "My Idea" in result["extracted_notes"][0]["content"]

    @pytest.mark.asyncio
    async def test_extract_skips_missing_files(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        notes = [_make_note_meta(note_id="n1", path="/nonexistent/file.md")]
        result = await skill.extract_notes({"notes": notes}, {})
        assert result["success"] is True
        assert result["total_extracted"] == 0
        assert result["total_failed"] == 1

    @pytest.mark.asyncio
    async def test_extract_multiple_notes(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        files = []
        for i in range(3):
            f = tmp_path / f"note{i}.md"
            f.write_text(f"Content {i}", encoding="utf-8")
            files.append(f)
        notes = [_make_note_meta(note_id=f"n{i}", path=str(f)) for i, f in enumerate(files)]
        result = await skill.extract_notes({"notes": notes}, {})
        assert result["total_extracted"] == 3
        assert result["total_failed"] == 0


# ---------------------------------------------------------------------------
# process_with_llm tests
# ---------------------------------------------------------------------------

class TestProcessWithLLM:
    @pytest.mark.asyncio
    async def test_process_no_notes(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        result = await skill.process_with_llm({}, {})
        assert result["success"] is False
        assert "no extracted notes" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_process_llm_unavailable(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._llm_available = False
        notes = [_make_extracted_note(note_id="n1")]
        result = await skill.process_with_llm({"extracted_notes": notes}, {})
        assert result["success"] is True
        assert len(result["processed"]) == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "no_llm_available"

    @pytest.mark.asyncio
    async def test_process_with_llama_cpp(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._llm_available = True
        skill._llm_engine = "llama.cpp"
        notes = [_make_extracted_note(note_id="n1", note_type="idea")]
        with patch.object(skill, "_run_llm_prompt", new_callable=AsyncMock, return_value="LLM output"):
            result = await skill.process_with_llm({"extracted_notes": notes}, {})
        assert result["success"] is True
        assert len(result["processed"]) == 1
        assert result["processed"][0]["llm_response"] == "LLM output"
        assert result["llm_engine"] == "llama.cpp"

    @pytest.mark.asyncio
    async def test_process_unknown_note_type(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._llm_available = True
        skill._llm_engine = "llama.cpp"
        notes = [_make_extracted_note(note_id="n1", note_type="unknown_type")]
        result = await skill.process_with_llm({"extracted_notes": notes}, {})
        assert result["success"] is True
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "unknown_note_type"

    @pytest.mark.asyncio
    async def test_process_llm_timeout(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._llm_available = True
        skill._llm_engine = "llama.cpp"
        notes = [_make_extracted_note(note_id="n1", note_type="todo")]
        with patch.object(
            skill, "_run_llm_prompt", side_effect=TimeoutError
        ):
            result = await skill.process_with_llm({"extracted_notes": notes}, {})
        assert result["success"] is True
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "llm_timeout"

    @pytest.mark.asyncio
    async def test_process_llm_error(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._llm_available = True
        skill._llm_engine = "llama.cpp"
        notes = [_make_extracted_note(note_id="n1", note_type="research")]
        with patch.object(
            skill, "_run_llm_prompt", side_effect=RuntimeError("LLM crashed")
        ):
            result = await skill.process_with_llm({"extracted_notes": notes}, {})
        assert result["success"] is True
        assert len(result["skipped"]) == 1
        assert "LLM crashed" in result["skipped"][0]["reason"]

    @pytest.mark.asyncio
    async def test_process_mixed_results(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._llm_available = True
        skill._llm_engine = "ollama"
        notes = [
            _make_extracted_note(note_id="n1", note_type="idea"),
            _make_extracted_note(note_id="n2", note_type="bad_type"),
            _make_extracted_note(note_id="n3", note_type="todo"),
        ]

        async def fake_run(prompt: str, timeout: int = 30) -> str:
            return "OK"

        with patch.object(skill, "_run_llm_prompt", side_effect=fake_run):
            result = await skill.process_with_llm({"extracted_notes": notes}, {})
        assert len(result["processed"]) == 2
        assert len(result["skipped"]) == 1
        assert result["llm_engine"] == "ollama"


# ---------------------------------------------------------------------------
# _run_llm_prompt routing tests
# ---------------------------------------------------------------------------

class TestRunLLMPrompt:
    @pytest.mark.asyncio
    async def test_run_routes_to_llama_cpp(self) -> None:
        skill = NightlyLabsSkill()
        skill._llm_engine = "llama.cpp"
        with patch.object(skill, "_run_llama_cpp", new_callable=AsyncMock, return_value="out") as mock:
            result = await skill._run_llm_prompt("test prompt", timeout=10)
        mock.assert_called_once_with("test prompt", 10)
        assert result == "out"

    @pytest.mark.asyncio
    async def test_run_routes_to_ollama(self) -> None:
        skill = NightlyLabsSkill()
        skill._llm_engine = "ollama"
        with patch.object(skill, "_run_ollama", new_callable=AsyncMock, return_value="out") as mock:
            result = await skill._run_llm_prompt("test prompt", timeout=15)
        mock.assert_called_once_with("test prompt", 15)

    @pytest.mark.asyncio
    async def test_run_routes_to_local_gguf(self) -> None:
        skill = NightlyLabsSkill()
        skill._llm_engine = "local_gguf"
        with patch.object(skill, "_run_local_gguf", new_callable=AsyncMock, return_value="out") as mock:
            result = await skill._run_llm_prompt("test prompt")
        mock.assert_called_once_with("test prompt", 30)

    @pytest.mark.asyncio
    async def test_run_unknown_engine_raises(self) -> None:
        skill = NightlyLabsSkill()
        skill._llm_engine = "nonexistent"
        with pytest.raises(RuntimeError, match="Unknown LLM engine"):
            await skill._run_llm_prompt("prompt")


# ---------------------------------------------------------------------------
# generate_report tests
# ---------------------------------------------------------------------------

class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_generate_report_writes_file(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._report_dir = tmp_path
        result = await skill.generate_report(
            {
                "scan_results": {"notes_found": []},
                "extraction_results": {},
                "llm_results": {"processed": [], "skipped": []},
                "metrics": {"cpu_average": 12.5, "ram_peak_mb": 256},
            },
            {},
        )
        assert result["success"] is True
        report_path = Path(result["report_path"])
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "# Nightly Labs Report" in content
        assert "cpu_average: 12.5" in content
        assert "ram_peak_mb: 256" in content

    @pytest.mark.asyncio
    async def test_generate_report_includes_ideas(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._report_dir = tmp_path
        llm_results = {
            "processed": [
                {"note_id": "idea-1", "note_type": "idea", "llm_response": "Great idea!"},
            ],
            "skipped": [],
        }
        result = await skill.generate_report(
            {"scan_results": {"notes_found": []}, "llm_results": llm_results},
            {},
        )
        content = Path(result["report_path"]).read_text(encoding="utf-8")
        assert "Ideas Processed" in content
        assert "Great idea!" in content

    @pytest.mark.asyncio
    async def test_generate_report_includes_pending_tasks(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._report_dir = tmp_path
        scan_results = {
            "notes_found": [
                {"title": "Buy milk", "path": "/v/todo.md", "note_type": "todo"},
            ]
        }
        result = await skill.generate_report(
            {"scan_results": scan_results, "llm_results": {"processed": [], "skipped": []}},
            {},
        )
        content = Path(result["report_path"]).read_text(encoding="utf-8")
        assert "Pending Tasks" in content
        assert "Buy milk" in content

    @pytest.mark.asyncio
    async def test_generate_report_sections_counts(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._report_dir = tmp_path
        llm_results = {
            "processed": [
                {"note_id": "i1", "note_type": "idea", "llm_response": "idea resp"},
                {"note_id": "r1", "note_type": "research", "llm_response": "research resp"},
                {"note_id": "i2", "note_type": "idea", "llm_response": "idea resp 2"},
            ],
            "skipped": [],
        }
        scan_results = {
            "notes_found": [
                {"title": "Task 1", "path": "/v/t1.md", "note_type": "todo"},
                {"title": "Task 2", "path": "/v/t2.md", "note_type": "todo"},
            ]
        }
        result = await skill.generate_report(
            {"scan_results": scan_results, "llm_results": llm_results},
            {},
        )
        sections = result["sections"]
        assert sections["tasks_executed"] == 3
        assert sections["ideas_extracted"] == 2
        assert sections["tasks_pending"] == 2
        assert sections["research_findings"] == 1

    @pytest.mark.asyncio
    async def test_generate_report_creates_dir(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        nested_dir = tmp_path / "deep" / "nested"
        skill._report_dir = nested_dir
        result = await skill.generate_report(
            {"scan_results": {}, "llm_results": {"processed": [], "skipped": []}},
            {},
        )
        assert result["success"] is True
        assert Path(result["report_path"]).exists()

    @pytest.mark.asyncio
    async def test_generate_report_includes_skipped(self, tmp_path: Path) -> None:
        skill = NightlyLabsSkill(config={"vault_root": str(tmp_path)})
        await skill.load()
        skill._report_dir = tmp_path
        llm_results = {
            "processed": [],
            "skipped": [{"note": "n1", "reason": "no_llm_available"}],
        }
        result = await skill.generate_report(
            {"scan_results": {}, "llm_results": llm_results},
            {},
        )
        content = Path(result["report_path"]).read_text(encoding="utf-8")
        assert "Skipped Tasks" in content
        assert "no_llm_available" in content


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_format_tasks_executed_empty(self) -> None:
        skill = NightlyLabsSkill()
        result = skill._format_tasks_executed({})
        assert result == "  []"

    def test_format_tasks_executed_with_processed(self) -> None:
        skill = NightlyLabsSkill()
        llm_results = {
            "processed": [{"prompt_used": "idea"}],
            "skipped": [],
        }
        result = skill._format_tasks_executed(llm_results)
        assert "completed" in result
        assert "idea" in result

    def test_format_tasks_executed_with_skipped(self) -> None:
        skill = NightlyLabsSkill()
        llm_results = {
            "processed": [],
            "skipped": [{"reason": "no_llm_available"}],
        }
        result = skill._format_tasks_executed(llm_results)
        assert "skipped" in result
        assert "no_llm_available" in result

    def test_format_ideas_extracted_empty(self) -> None:
        skill = NightlyLabsSkill()
        result = skill._format_ideas_extracted({})
        assert result == "  []"

    def test_format_ideas_extracted_with_ideas(self) -> None:
        skill = NightlyLabsSkill()
        llm_results = {
            "processed": [{"note_type": "idea", "note_id": "idea-1"}],
        }
        result = skill._format_ideas_extracted(llm_results)
        assert "idea-1" in result
        assert "confidence: 0.85" in result

    def test_format_tasks_pending_empty(self) -> None:
        skill = NightlyLabsSkill()
        result = skill._format_tasks_pending({})
        assert result == "  []"

    def test_format_tasks_pending_with_todos(self) -> None:
        skill = NightlyLabsSkill()
        scan_results = {
            "notes_found": [{"title": "My Task", "path": "/v/todo.md", "note_type": "todo"}],
        }
        result = skill._format_tasks_pending(scan_results)
        assert "My Task" in result

    def test_format_research_findings_empty(self) -> None:
        skill = NightlyLabsSkill()
        result = skill._format_research_findings({})
        assert result == "  []"

    def test_format_research_findings_with_research(self) -> None:
        skill = NightlyLabsSkill()
        llm_results = {
            "processed": [{"note_type": "research", "note_id": "res-1"}],
        }
        result = skill._format_research_findings(llm_results)
        assert "res-1" in result
        assert "Processed by nightly worker" in result

    def test_build_report_body_empty(self) -> None:
        skill = NightlyLabsSkill()
        body = skill._build_report_body({}, {"processed": [], "skipped": []})
        assert "# Nightly Labs Report" in body

    def test_build_report_body_full(self) -> None:
        skill = NightlyLabsSkill()
        scan = {
            "notes_found": [
                {"title": "Task A", "path": "/v/a.md", "note_type": "todo"},
            ]
        }
        llm = {
            "processed": [
                {"note_id": "idea-1", "note_type": "idea", "llm_response": "Idea analysis"},
                {"note_id": "res-1", "note_type": "research", "llm_response": "Research findings"},
            ],
            "skipped": [{"note": "n-skip", "reason": "timeout"}],
        }
        body = skill._build_report_body(scan, llm)
        assert "Ideas Processed" in body
        assert "Research Findings" in body
        assert "Pending Tasks" in body
        assert "Skipped Tasks" in body
        assert "Idea analysis" in body
        assert "Task A" in body


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_tag_type_map_keys(self) -> None:
        assert "#idea" in TAG_TYPE_MAP
        assert "#todo" in TAG_TYPE_MAP
        assert "#research" in TAG_TYPE_MAP

    def test_prompt_templates_cover_all_types(self) -> None:
        for note_type in TAG_TYPE_MAP.values():
            assert note_type in PROMPT_TEMPLATES

    def test_tag_type_map_values_match_templates(self) -> None:
        for note_type in TAG_TYPE_MAP.values():
            assert note_type in PROMPT_TEMPLATES
            template = PROMPT_TEMPLATES[note_type]
            assert "{content}" in template

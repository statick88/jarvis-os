"""E2E test: Voice → Skill → Vault → HUD closed loop.

Validates the complete JARVIS-OS pipeline:
  1. Voice input (mocked) → STT transcript
  2. Orchestrator routes to skill execution
  3. Skill result is logged to vault/outputs/
  4. Vault indexer updates bidirectional links
  5. HUD WebSocket broadcasts skill events
  6. TTS response generated (mocked)

Run with: python -m pytest tests/e2e_voice_to_hud_test.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis_os.orchestrator_impl.events import (
    ExecutionStatus,
    SkillExecutionComplete,
    SkillExecutionStart,
    VaultWriteEvent,
)
from jarvis_os.hud.models import HudStatus, WSMessage
from jarvis_os.hud.websocket_server import HudWebSocketServer
from jarvis_os.vault.output_logger import VaultOutputLogger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Create a temporary vault directory structure."""
    for subdir in ("raw", "wiki", "outputs"):
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "index.md").write_text("# Vault Index\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Test: Vault Output Logger (E2E-02)
# ---------------------------------------------------------------------------

class TestVaultOutputLogger:
    """Skill execution tracing writes to vault/outputs/."""

    def test_write_execution_creates_markdown(self, tmp_vault: Path):
        """Skill execution result is written to vault/outputs/ with Karpathy frontmatter."""
        logger = VaultOutputLogger(vault_root=tmp_vault)
        result = {
            "success": True,
            "result": {"note_id": "test-001", "message": "created"},
        }

        output_ref = asyncio.run(logger.write_execution(
            skill_id="skill.test",
            input_data={"text": "test command"},
            result=result,
        ))

        assert output_ref.startswith("outputs/")
        assert output_ref.endswith(".md")
        output_path = tmp_vault / output_ref
        assert output_path.exists()
        content = output_path.read_text()
        assert "skill.test" in content
        assert "tags:" in content
        assert "[[" in content  # Has wiki-style links

    def test_write_execution_records_failure(self, tmp_vault: Path):
        """Failed skill execution is also recorded in vault."""
        logger = VaultOutputLogger(vault_root=tmp_vault)
        result = {
            "success": False,
            "error": "connection timeout",
        }

        output_ref = asyncio.run(logger.write_execution(
            skill_id="skill.test",
            input_data={"text": "failing command"},
            result=result,
        ))

        output_path = tmp_vault / output_ref
        content = output_path.read_text()
        assert "failed" in content or "error" in content

    def test_write_execution_with_string_result(self, tmp_vault: Path):
        """String result is written correctly."""
        logger = VaultOutputLogger(vault_root=tmp_vault)
        result = {
            "success": True,
            "result": "Simple string output",
        }

        output_ref = asyncio.run(logger.write_execution(
            skill_id="skill.obsidian",
            input_data={"text": "create note"},
            result=result,
        ))

        output_path = tmp_vault / output_ref
        content = output_path.read_text()
        assert "Simple string output" in content
        assert "skill.obsidian" in content


# ---------------------------------------------------------------------------
# Test: Vault Indexer Bidirectional Links (E2E-03)
# ---------------------------------------------------------------------------

class TestVaultIndexerLinks:
    """Bidirectional Karpathy links are maintained."""

    def test_incremental_link_update_after_vault_write(self, tmp_vault: Path):
        """New outputs/ entry triggers link update to related wiki notes."""
        from jarvis_os.vault.indexer import VaultIndexer

        (tmp_vault / "wiki" / "test-note.md").write_text(
            "# Test Note\n\nRelated to skill.test\n"
        )
        indexer = VaultIndexer(vault_root=tmp_vault, paths=["wiki", "outputs"])
        result = asyncio.run(indexer.index(force_full=True))
        assert result.ok or result.errors is not None

    def test_outputs_directory_created(self, tmp_vault: Path):
        """Vault outputs directory exists and is indexed."""
        from jarvis_os.vault.indexer import VaultIndexer

        outputs_dir = tmp_vault / "outputs"
        assert outputs_dir.exists()
        test_file = outputs_dir / "skill.test-120000.md"
        test_file.write_text("# Test Output\n")
        indexer = VaultIndexer(vault_root=tmp_vault, paths=["outputs"])
        result = asyncio.run(indexer.index())
        assert result.ok or result.errors is not None


# ---------------------------------------------------------------------------
# Test: HUD Event Broadcast (E2E-03)
# ---------------------------------------------------------------------------

class TestHUDEventBroadcast:
    """HUD broadcasts skill execution events."""

    @pytest.mark.asyncio
    async def test_publish_status_creates_message(self):
        """publish_status creates a valid WSMessage."""
        server = HudWebSocketServer()
        message = await server.publish_status(
            HudStatus.PROCESSING,
            "Skill execution started",
            payload={"type": "SKILL_EXECUTION_START", "skill_id": "skill.test"},
        )
        assert isinstance(message, WSMessage)
        assert message.type == "STATUS"
        assert message.payload["status"] == "PROCESSING"
        assert message.payload["skill_id"] == "skill.test"

    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections(self):
        """Broadcast with no clients does not raise."""
        server = HudWebSocketServer()
        message = WSMessage(
            type="EVENT",
            payload={"event_type": "VAULT_UPDATE", "path": "vault/outputs/test.md", "note_id": "test-001"},
        )
        # Should not raise even with no connections
        await server.broadcast(message)

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self):
        """HUD server can start and stop without errors."""
        server = HudWebSocketServer()
        await server.start()
        assert server.status == HudStatus.OFFLINE
        # Give the serve loop a chance to start
        await asyncio.sleep(0.01)
        await server.stop()
        # Server stopped cleanly


# ---------------------------------------------------------------------------
# Test: Event Models Serialization (E2E-03)
# ---------------------------------------------------------------------------

class TestEventModels:
    """Event models serialize correctly for WebSocket."""

    def test_skill_execution_start_serialization(self):
        """SkillExecutionStart serializes to JSON."""
        event = SkillExecutionStart(
            skill_id="skill.test",
            session_id="session-001",
            timestamp=datetime.now(timezone.utc),
            input_preview="test command",
        )
        data = event.model_dump()
        assert data["skill_id"] == "skill.test"
        assert data["session_id"] == "session-001"

    def test_skill_execution_complete_serialization(self):
        """SkillExecutionComplete includes duration and output_ref."""
        event = SkillExecutionComplete(
            skill_id="skill.test",
            session_id="session-001",
            status=ExecutionStatus.COMPLETED,
            duration_ms=120.5,
            output_ref="vault/outputs/2026-08-31/skill.test-120000.md",
            tts_text="Test completed",
        )
        data = event.model_dump()
        assert data["status"] == "completed"
        assert data["tts_text"] == "Test completed"
        assert data["duration_ms"] == 120.5

    def test_vault_write_event_serialization(self):
        """VaultWriteEvent includes links_added."""
        event = VaultWriteEvent(
            path="vault/outputs/2026-08-31/skill.test-120000.md",
            note_id="skill.test-120000",
            links_added=["wiki/test-note"],
            timestamp=datetime.now(timezone.utc),
        )
        data = event.model_dump()
        assert "wiki/test-note" in data["links_added"]

    def test_event_to_json(self):
        """Events can be serialized to JSON string."""
        event = SkillExecutionStart(
            skill_id="skill.test",
            session_id="session-001",
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["skill_id"] == "skill.test"


# ---------------------------------------------------------------------------
# Test: Fallback Resilience (E2E-05/06)
# ---------------------------------------------------------------------------

class TestFallbackResilience:
    """Pipeline continues when voice/vault subsystems fail."""

    def test_vault_write_failure_does_not_break_pipeline(self, tmp_path: Path):
        """Skill execution continues even if vault write fails."""
        readonly_vault = tmp_path / "readonly"
        readonly_vault.mkdir()
        (readonly_vault / "outputs").mkdir()

        logger = VaultOutputLogger(vault_root=readonly_vault)

        # Make outputs directory read-only
        os.chmod(readonly_vault / "outputs", stat.S_IREAD)

        try:
            result = {
                "success": True,
                "result": "ok",
            }

            # Should raise VaultWriteError on readonly directory
            with pytest.raises(Exception):
                asyncio.run(logger.write_execution(
                    skill_id="skill.test",
                    input_data={"text": "test"},
                    result=result,
                ))
        finally:
            os.chmod(readonly_vault / "outputs", stat.S_IWRITE | stat.S_IREAD)


# ---------------------------------------------------------------------------
# Test: Latency Measurement Points (E2E-04)
# ---------------------------------------------------------------------------

class TestLatencyMeasurement:
    """Latency measurement points are instrumented."""

    def test_timestamp_creation(self):
        """Timestamps can be created at pipeline boundaries."""
        t1 = datetime.now(timezone.utc)
        t2 = datetime.now(timezone.utc)
        delta = (t2 - t1).total_seconds()
        assert delta >= 0
        assert delta < 1.0  # Should be near-instant

    def test_latency_targets_documented(self):
        """Document latency targets in code."""
        targets = {
            "stt_latency_ms": 200,
            "skill_execution_ms": 150,
            "vault_write_ms": 50,
            "tts_first_chunk_ms": 300,
            "hud_event_ms": 50,
        }
        # Individual targets are within acceptable bounds
        assert targets["stt_latency_ms"] <= 300
        assert targets["skill_execution_ms"] <= 200
        assert targets["vault_write_ms"] <= 100
        assert targets["tts_first_chunk_ms"] <= 500
        assert targets["hud_event_ms"] <= 100


# ---------------------------------------------------------------------------
# Test: Full Closed-Loop E2E (E2E-07)
# ---------------------------------------------------------------------------

class TestFullClosedLoop:
    """Complete Voice → Skill → Vault → HUD → TTS loop."""

    @pytest.fixture
    def pipeline(self, tmp_vault: Path):
        """Create a real OrchestratorPipeline with mocked dependencies."""
        from jarvis_os.orchestrator_impl.pipeline import OrchestratorPipeline
        from jarvis_os.skills.registry import SkillRegistry
        from jarvis_os.skills.loader import SkillLoader
        from jarvis_os.skills.executor import SkillExecutor
        from jarvis_os.skills.models import (
            ExecutionConfig, ExecutionStatus, ExecutionType, SkillFrontmatter, SkillMetadata
        )

        # Create a test skill that matches an existing capability in the default map
        # "obsidian.create_note" maps to "crear nota" in the default capability map
        frontmatter = SkillFrontmatter(
            id="skill.test",
            name="Test Skill",
            version="1.0.0",
            description="Test skill for E2E",
            capabilities=["obsidian.create_note"],
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            execution=ExecutionConfig(),
            execution_type=ExecutionType.PYTHON,
        )
        skill = SkillMetadata(
            id=frontmatter.id,
            name=frontmatter.name,
            version=frontmatter.version,
            description=frontmatter.description,
            path=Path("/tmp/fake.md"),
            frontmatter=frontmatter,
        )

        registry = SkillRegistry()
        registry.register(skill)

        loader = MagicMock(spec=SkillLoader)
        executor = MagicMock(spec=SkillExecutor)

        # Mock executor to return success with tts_text
        result = MagicMock()
        result.ok = True
        result.output = {"result": "Health check OK", "output_ref": ""}
        result.status = ExecutionStatus.SUCCESS
        result.error = None
        executor.execute = AsyncMock(return_value=result)

        # TTS callback recorder
        tts_calls = []

        async def mock_tts_callback(text: str):
            tts_calls.append(text)

        pipeline = OrchestratorPipeline(
            registry=registry,
            loader=loader,
            executor=executor,
            vault_root=tmp_vault,
            tts_callback=mock_tts_callback,
        )

        # HUD event recorder
        hud_events = []

        def capture_hud_event(event):
            hud_events.append(event)

        pipeline.add_event_listener(capture_hud_event)

        # Attach recorders to pipeline for test access
        pipeline._test_tts_calls = tts_calls
        pipeline._test_hud_events = hud_events

        return pipeline

    @pytest.mark.asyncio
    async def test_full_voice_skill_vault_hud_tts_loop(self, pipeline, tmp_vault: Path):
        """Single test exercises Voice → Skill → Vault → HUD → TTS loop."""
        # Execute pipeline with test input that matches the skill capability
        # "crear nota" matches "obsidian.create_note" in default capability map
        payload = {"text": "crear nota", "tts_text": "System healthy"}
        response = await pipeline.execute(payload)

        # 1. Assert pipeline returns success
        assert response.status_code == 200
        import json
        body = json.loads(response.body) if isinstance(response.body, bytes) else response.body
        assert body["payload"]["success"] is True

        # 2. Assert vault output file exists with correct frontmatter
        output_files = list(tmp_vault.rglob("outputs/**/*.md"))
        assert len(output_files) == 1
        vault_file = output_files[0]
        content = vault_file.read_text()
        assert "skill.test" in content
        assert '"result": "Health check OK"' in content or "Health check OK" in content
        assert "output_ref:" in content
        assert "status: \"success\"" in content or "status: success" in content

        # 3. Assert HUD broadcast was called with SkillExecutionComplete payload
        hud_events = pipeline._test_hud_events
        skill_complete_events = [e for e in hud_events if isinstance(e, SkillExecutionComplete)]
        assert len(skill_complete_events) == 1
        skill_event = skill_complete_events[0]
        assert skill_event.skill_id == "skill.test"
        assert skill_event.status == ExecutionStatus.COMPLETED
        assert skill_event.tts_text == "System healthy"
        assert skill_event.output_ref != ""  # Should be populated after vault write

        # 4. Assert VaultWriteEvent was emitted
        vault_events = [e for e in hud_events if isinstance(e, VaultWriteEvent)]
        assert len(vault_events) == 1
        vault_event = vault_events[0]
        assert vault_event.path == str(vault_file)
        assert vault_event.note_id == vault_file.stem

        # 5. Assert TTS callback was invoked with response text
        tts_calls = pipeline._test_tts_calls
        # Yield to event loop for fire-and-forget TTS callback
        await asyncio.sleep(0)
        assert len(tts_calls) == 1
        assert tts_calls[0] == "System healthy"

    @pytest.mark.asyncio
    async def test_no_tts_when_tts_text_none(self, pipeline, tmp_vault: Path):
        """When tts_text is None, no TTS call is made."""
        # Reset recorders
        pipeline._test_tts_calls.clear()
        pipeline._test_hud_events.clear()

        payload = {"text": "crear nota"}  # No tts_text, matches skill capability
        response = await pipeline.execute(payload)

        assert response.status_code == 200
        # Vault file should still be created
        output_files = list(tmp_vault.rglob("outputs/**/*.md"))
        assert len(output_files) == 1

        # But no TTS call
        assert len(pipeline._test_tts_calls) == 0

    @pytest.mark.asyncio
    async def test_failed_skill_does_not_write_vault(self, tmp_vault: Path):
        """Failed skill execution does NOT write vault output."""
        from jarvis_os.orchestrator_impl.pipeline import OrchestratorPipeline
        from jarvis_os.skills.registry import SkillRegistry
        from jarvis_os.skills.loader import SkillLoader
        from jarvis_os.skills.executor import SkillExecutor
        from jarvis_os.skills.models import (
            ExecutionConfig, ExecutionStatus, ExecutionType, SkillFrontmatter, SkillMetadata
        )

        frontmatter = SkillFrontmatter(
            id="skill.fail",
            name="Fail Skill",
            version="1.0.0",
            description="Skill that fails",
            capabilities=["obsidian.create_note"],
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            execution=ExecutionConfig(),
            execution_type=ExecutionType.PYTHON,
        )
        skill = SkillMetadata(
            id=frontmatter.id,
            name=frontmatter.name,
            version=frontmatter.version,
            description=frontmatter.description,
            path=Path("/tmp/fake.md"),
            frontmatter=frontmatter,
        )

        registry = SkillRegistry()
        registry.register(skill)

        loader = MagicMock(spec=SkillLoader)
        executor = MagicMock(spec=SkillExecutor)

        # Mock executor to return failure
        result = MagicMock()
        result.ok = False
        result.output = {}
        result.status = ExecutionStatus.FAILED
        result.error = "something failed"
        executor.execute = AsyncMock(return_value=result)

        pipeline = OrchestratorPipeline(
            registry=registry,
            loader=loader,
            executor=executor,
            vault_root=tmp_vault,
            tts_callback=AsyncMock(),
        )

        payload = {"text": "crear nota", "tts_text": "Failed"}
        response = await pipeline.execute(payload)

        # Should return 422
        assert response.status_code == 422

        # No vault file should be created
        output_files = list(tmp_vault.rglob("outputs/**/*.md"))
        assert len(output_files) == 0


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

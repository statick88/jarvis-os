"""Minimal orchestrator stub for container healthchecks and integration tests.

This module intentionally provides a minimal FastAPI application so the
`gentle-orchestrator` container can pass its Docker healthcheck during
integration tests. Real orchestration logic is intentionally omitted at this
stage.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from jarvis_os.api.routes.skills import router as skills_router
from jarvis_os.core.scheduler import IdleScheduler
from jarvis_os.hud.models import HudStatus
from jarvis_os.hud.websocket_server import HudWebSocketServer
from jarvis_os.orchestrator_impl.pipeline import OrchestratorPipeline
from jarvis_os.skills.executor import SkillExecutor
from jarvis_os.skills.loader import SkillLoader
from jarvis_os.skills.plugin_registry_instance import shared_registry as plugin_registry
from jarvis_os.skills.registry import SkillRegistry
from jarvis_os.skills.obsidian import ObsidianSkill
from jarvis_os.skills.os_control import OSControlSkill
from jarvis_os.skills.devsecops import DevSecOpsSkill

logger = logging.getLogger(__name__)

# Voice client singleton (lazily initialized)
_voice_client: Any = None

# Pipeline singleton
_pipeline: OrchestratorPipeline | None = None

# HUD WebSocket server singleton
_hud_server: HudWebSocketServer | None = None

# Idle scheduler singleton (started in lifespan)
_idle_scheduler: IdleScheduler | None = None


def _get_hud_server() -> HudWebSocketServer | None:
    """Lazy-build the HUD WebSocket server."""
    global _hud_server
    if _hud_server is None:
        try:
            _hud_server = HudWebSocketServer()
        except Exception as exc:
            logger.warning("HUD WebSocket server not available: %s", exc)
            _hud_server = None
    return _hud_server


def _get_voice_client() -> Any:
    """Lazy-load the OrchestratorVoiceClient."""
    global _voice_client
    if _voice_client is None:
        try:
            from jarvis_os.voice_bridge.orchestrator_client import OrchestratorVoiceClient
            _voice_client = OrchestratorVoiceClient(
                host="jarvis-voice",
                port=8080,
                max_sessions=10,
                idle_timeout_s=300,
            )
        except ImportError:
            logger.warning("OrchestratorVoiceClient not available")
            _voice_client = None
    return _voice_client


def _get_pipeline(registry: SkillRegistry | None = None) -> OrchestratorPipeline:
    """Lazy-build the OrchestratorPipeline singleton."""
    global _pipeline
    if _pipeline is None:
        if registry is None:
            registry = SkillRegistry()
        loader = SkillLoader(skills_dir=Path(".skills"))
        executor = SkillExecutor(default_timeout=30)
        vc = _get_voice_client()
        _pipeline = OrchestratorPipeline(
            registry=registry,
            loader=loader,
            executor=executor,
            voice_client=vc,
        )
        # Wire pipeline events to HUD WebSocket broadcasts
        _wire_pipeline_to_hud(_pipeline)
    elif registry is not None and not getattr(registry, "_skills", None):
        pass
    return _pipeline


def _wire_pipeline_to_hud(pipeline: OrchestratorPipeline) -> None:
    """Register HUD broadcast listener on the pipeline event bus."""
    hud = _get_hud_server()
    if hud is None:
        return

    def _hud_listener(event: Any) -> None:
        try:
            from jarvis_os.orchestrator_impl.events import (
                SkillExecutionComplete,
                SkillExecutionStart,
                VaultWriteEvent,
            )
        except ImportError:
            return

        if isinstance(event, SkillExecutionStart):
            hud.publish_status(
                HudStatus.PROCESSING,
                summary=f"Ejecutando {event.skill_id}",
                payload=event.model_dump(mode="json"),
            )
        elif isinstance(event, SkillExecutionComplete):
            status = HudStatus.IDLE if event.status == "completed" else HudStatus.ERROR
            hud.publish_status(
                status,
                summary=f"{event.skill_id} {event.status.value}",
                payload=event.model_dump(mode="json"),
            )
        elif isinstance(event, VaultWriteEvent):
            hud.publish_status(
                HudStatus.IDLE,
                summary="Vault actualizado",
                payload=event.model_dump(mode="json"),
            )

    pipeline.add_event_listener(_hud_listener)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _idle_scheduler

    await plugin_registry.register(ObsidianSkill())
    await plugin_registry.register(OSControlSkill())
    await plugin_registry.register(DevSecOpsSkill())
    logger.info("Registered %d skill plugins", len(plugin_registry._skills))

    # Load SkillRegistry from .skills/ directory for the execution pipeline
    skill_registry = SkillRegistry()
    skill_loader = SkillLoader(skills_dir=Path(".skills"))
    try:
        count = await skill_registry.load_from_directory(
            skills_dir=Path(".skills"), loader=skill_loader
        )
        logger.info("Loaded %d skills into execution registry", count)
    except Exception as exc:
        logger.warning("Could not load skills directory: %s", exc)

    # Store on app state so pipeline can access the populated registry
    app.state.skill_registry = skill_registry
    app.state.skill_loader = skill_loader

    # Start voice client pool
    vc = _get_voice_client()
    if vc is not None:
        await vc.start()
        logger.info("Voice client pool started")

    # Start HUD WebSocket server
    hud = _get_hud_server()
    if hud is not None:
        await hud.start()
        logger.info("HUD WebSocket server started")

    # Start idle scheduler for nightly labs
    _idle_scheduler = IdleScheduler()
    _idle_scheduler.start()
    logger.info("Idle scheduler started")
    yield
    # Shutdown idle scheduler
    if _idle_scheduler is not None:
        _idle_scheduler.stop()
        logger.info("Idle scheduler stopped")
    # Shutdown voice client pool
    if vc is not None:
        await vc.stop()
    # Shutdown HUD WebSocket server
    if hud is not None:
        await hud.stop()


app = FastAPI(title="jarvis-os gentle orchestrator", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    """Extended health check with voice pipeline status."""
    vc = _get_voice_client()
    voice_pipeline_status = {
        "websocket_enabled": True,
        "active_voice_sessions": 0,
        "voice_pipeline_available": False,
    }
    if vc is not None:
        metrics = vc.metrics()
        voice_pipeline_status["active_voice_sessions"] = metrics.get("active_sessions", 0)
        voice_pipeline_status["voice_pipeline_available"] = True

    return JSONResponse({
        "status": "ok",
        "service": "gentle-orchestrator",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "voice_pipeline_status": voice_pipeline_status,
    })


# ============================================================================
# Voice Session REST Proxy Endpoints
# ============================================================================

@app.post("/v1/audio/session/open")
async def audio_session_open(payload: dict[str, Any]) -> JSONResponse:
    """Open a new voice session via WebSocket."""
    vc = _get_voice_client()
    if vc is None:
        return JSONResponse({"error": "Voice client not available"}, status_code=503)

    session_id = payload.get("session_id")
    try:
        ack = await vc.open_session(session_id)
        return JSONResponse({
            "session_id": ack.session_id,
            "websocket_enabled": ack.websocket_enabled,
            "stt_model": ack.stt_model,
            "tts_voice": ack.tts_voice,
            "status": "opened",
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/v1/audio/session/{session_id}/send-audio")
async def audio_session_send_audio(session_id: str, payload: dict[str, Any]) -> JSONResponse:
    """Send audio data to an existing voice session."""
    vc = _get_voice_client()
    if vc is None:
        return JSONResponse({"error": "Voice client not available"}, status_code=503)

    audio_b64 = payload.get("audio_data", "")
    import base64
    try:
        pcm_bytes = base64.b64decode(audio_b64)
    except Exception:
        return JSONResponse({"error": "Invalid base64 audio_data"}, status_code=400)

    try:
        await vc.send_audio(session_id, pcm_bytes)
        return JSONResponse({"session_id": session_id, "status": "audio_sent"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/v1/audio/session/{session_id}/send-text")
async def audio_session_send_text(session_id: str, payload: dict[str, Any]) -> JSONResponse:
    """Send text for TTS synthesis via an existing voice session."""
    vc = _get_voice_client()
    if vc is None:
        return JSONResponse({"error": "Voice client not available"}, status_code=503)

    text = payload.get("text", "")
    try:
        await vc.send_text(session_id, text)
        return JSONResponse({"session_id": session_id, "status": "text_sent"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/v1/audio/session/{session_id}")
async def audio_session_close(session_id: str) -> JSONResponse:
    """Close an active voice session."""
    vc = _get_voice_client()
    if vc is None:
        return JSONResponse({"error": "Voice client not available"}, status_code=503)

    try:
        await vc.close_session(session_id)
        return JSONResponse({"session_id": session_id, "status": "closed"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/v1/audio/sessions")
async def audio_sessions_list() -> JSONResponse:
    """List active voice sessions."""
    vc = _get_voice_client()
    if vc is None:
        return JSONResponse({"sessions": [], "voice_client_available": False})

    metrics = vc.metrics()
    return JSONResponse({
        "sessions": metrics,
        "voice_client_available": True,
    })


# ============================================================================
# Nightly Scheduler Endpoints
# ============================================================================

@app.post("/v1/nightly/scheduler/toggle")
async def nightly_scheduler_toggle(payload: dict[str, Any] | None = None) -> JSONResponse:
    """Toggle the idle scheduler on/off or control its state.

    Body (optional):
        {"action": "start"|"stop"|"pause"|"resume"}
    Defaults to start/stop toggle when no action is provided.
    """
    if _idle_scheduler is None:
        return JSONResponse(
            {"error": "Scheduler not initialized"}, status_code=503
        )

    action = (payload or {}).get("action")
    status_before = _idle_scheduler.get_status()

    if action == "start" or (action is None and not status_before.get("running")):
        _idle_scheduler.start()
    elif action == "stop" or (action is None and status_before.get("running")):
        _idle_scheduler.stop()
    elif action == "pause":
        _idle_scheduler.pause()
    elif action == "resume":
        _idle_scheduler.resume()
    else:
        return JSONResponse(
            {"error": f"Unknown action: {action}"},
            status_code=400,
        )

    status_after = _idle_scheduler.get_status()
    return JSONResponse({
        "status": "ok",
        "action": action or ("start" if status_after["running"] else "stop"),
        "scheduler": status_after,
    })


@app.get("/v1/nightly/scheduler/status")
async def nightly_scheduler_status() -> JSONResponse:
    """Return current status of the idle scheduler."""
    if _idle_scheduler is None:
        return JSONResponse(
            {"error": "Scheduler not initialized"}, status_code=503
        )

    return JSONResponse({
        "status": "ok",
        "scheduler": _idle_scheduler.get_status(),
    })


@app.get("/v1/nightly/reports")
async def nightly_reports_list() -> JSONResponse:
    """List all generated nightly reports.

    Returns a list of available report dates sorted newest-first.
    """
    reports_dir = Path("_Nightly_Reports")
    if not reports_dir.exists():
        return JSONResponse({"status": "ok", "reports": []})

    reports = []
    for f in sorted(reports_dir.glob("*.md"), reverse=True):
        if f.stem and len(f.stem) == 10:  # YYYY-MM-DD format
            reports.append({
                "date": f.stem,
                "filename": f.name,
                "size_bytes": f.stat().st_size,
            })

    return JSONResponse({"status": "ok", "reports": reports})


@app.get("/v1/nightly/reports/{date}")
async def nightly_reports_get(date: str) -> JSONResponse:
    """Fetch a specific nightly report by date (YYYY-MM-DD).

    Returns the full report content with frontmatter and body.
    """
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return JSONResponse(
            {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."},
            status_code=400,
        )

    report_path = Path("_Nightly_Reports") / f"{date}.md"
    if not report_path.exists():
        return JSONResponse(
            {"status": "error", "message": f"Report not found for date: {date}"},
            status_code=404,
        )

    content = report_path.read_text(encoding="utf-8")

    # Split frontmatter from body
    body = content
    frontmatter = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()

    return JSONResponse({
        "status": "ok",
        "date": date,
        "frontmatter": frontmatter,
        "body": body,
    })


@app.post("/v1/execute")
async def execute(payload: dict[str, Any]) -> JSONResponse:
    """Skill execution pipeline with optional TTS streaming.

    If the payload contains ``tts_text``, the response is streamed to the
    voice pipeline via the active session identified by ``session_id``.
    """
    registry = getattr(app.state, "skill_registry", None)
    pipeline = getattr(app.state, "pipeline", None)
    if pipeline is None:
        pipeline = _get_pipeline(registry=registry)
        app.state.pipeline = pipeline
    elif registry is not None and getattr(registry, "_skills", None):
        pipeline._registry = registry
    return await pipeline.execute(payload)


app.include_router(skills_router)


if __name__ == "__main__":
    import os
    port = int(os.getenv("ORCHESTRATOR_PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

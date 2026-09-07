"""Execution pipeline for JARVIS-OS orchestrator.

Implements the 4-phase flow: intent analysis → skill resolution → execution
→ response formatting.  Integrates ``SkillExecutor`` for PYTHON/BASH/HYBRID
runs and ``OpenCodeClient`` for code execution requests.  Supports skill
composition/chaining and optional TTS streaming via ``OrchestratorVoiceClient``.

Response envelope::

    {
        "id": "<uuid>",
        "timestamp": "<ISO-8601 UTC>",
        "type": "RESPONSE",
        "payload": {
            "success": true,
            "result": { ... }   # on success
            # or
            "error": "..."      # on failure
        }
    }
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi.responses import JSONResponse

from jarvis_os.orchestrator_impl.events import (
    ExecutionStatus,
    SkillExecutionComplete,
    SkillExecutionStart,
)
from jarvis_os.orchestrator_impl.errors import (
    IntentAnalysisError,
    SkillExecutionPipelineError,
    SkillResolutionError,
)
from jarvis_os.orchestrator_impl.intent import IntentAnalyzer, IntentResult
from jarvis_os.orchestrator_impl.resolver import ResolvedSkill, SkillResolver
from jarvis_os.skills.executor import SkillExecutor
from jarvis_os.skills.models import SkillMetadata

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrchestratorPipeline:
    """Four-phase execution pipeline.

    Args:
        registry: Populated ``SkillRegistry`` for capability lookup.
        loader: ``SkillLoader`` for on-demand disk fallback.
        executor: ``SkillExecutor`` for running resolved skills.
        voice_client: Optional ``OrchestratorVoiceClient`` for TTS streaming.
        opencode_client: Optional ``OpenCodeClient`` for code execution.
    """

    def __init__(
        self,
        registry: Any,
        loader: Any,
        executor: SkillExecutor,
        voice_client: Any = None,
        opencode_client: Any = None,
    ) -> None:
        self._registry = registry
        self._loader = loader
        self._executor = executor
        self._voice_client = voice_client
        self._opencode_client = opencode_client
        self._intent_analyzer = IntentAnalyzer()
        self._event_listeners: list[Any] = []

    # --- Public API ----------------------------------------------------------

    def add_event_listener(self, listener: Any) -> None:
        """Register a callable that receives every pipeline event."""
        self._event_listeners.append(listener)

    async def _emit(self, event: Any) -> None:
        for listener in self._event_listeners:
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Event listener failed: %s", exc)

    async def execute(self, payload: dict[str, Any]) -> JSONResponse:
        """Run the full pipeline and return a JSON response.

        Phases:
        1. Analyze intent from ``payload["text"]``.
        2. Resolve the best skill for the detected intent.
        3. Execute the skill (or delegate to OpenCode).
        4. Format the response envelope.

        Optional post-execution step: fire TTS streaming if ``tts_text`` and
        ``session_id`` are present in the payload.
        """
        envelope: dict[str, Any]
        try:
            intent_result = self._analyze_intent(payload)
            resolved = self._resolve_skill(intent_result, payload)
            exec_result = await self._execute_skill(resolved, payload)
            envelope = self._format_response(exec_result)
        except IntentAnalysisError as exc:
            envelope = self._error_envelope(str(exc))
            return JSONResponse(envelope, status_code=exc.status_code)
        except SkillResolutionError as exc:
            envelope = self._error_envelope(str(exc))
            return JSONResponse(envelope, status_code=exc.status_code)
        except SkillExecutionPipelineError as exc:
            envelope = self._error_envelope(str(exc))
            return JSONResponse(envelope, status_code=exc.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected pipeline error")
            envelope = self._error_envelope(f"internal error: {exc}")
            return JSONResponse(envelope, status_code=500)

        # Post-execution: TTS streaming (fire-and-forget)
        tts_text = payload.get("tts_text")
        session_id = payload.get("session_id")
        if tts_text and session_id and self._voice_client is not None:
            try:
                asyncio.create_task(
                    self._voice_client.send_text(session_id, tts_text)
                )
                envelope["payload"]["tts_streamed"] = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS streaming failed: %s", exc)
                envelope["payload"]["tts_streamed"] = False

        status_code = 200 if envelope["payload"].get("success") else 422
        return JSONResponse(envelope, status_code=status_code)

    # --- Phase 1: Intent Analysis --------------------------------------------

    def _analyze_intent(self, payload: dict[str, Any]) -> IntentResult:
        """Classify the user text into a capability intent.

        Args:
            payload: Incoming request payload.

        Returns:
            ``IntentResult`` with the detected intent and confidence.

        Raises:
            IntentAnalysisError: If the text is missing or empty.
        """
        text = payload.get("text", "")
        if not text or not text.strip():
            raise IntentAnalysisError("input 'text' is required")
        return self._intent_analyzer.classify(text)

    # --- Phase 2: Skill Resolution -------------------------------------------

    def _resolve_skill(
        self, intent_result: IntentResult, payload: dict[str, Any]
    ) -> ResolvedSkill:
        """Resolve the best skill for the detected intent.

        Args:
            intent_result: Output from :meth:`_analyze_intent`.
            payload: Incoming request payload (used for explicit skill id).

        Returns:
            ``ResolvedSkill`` with the matched skill metadata.

        Raises:
            SkillResolutionError: When no skill can handle the intent and
                OpenCode is not available or the intent is not code-related.
        """
        intent = intent_result.intent
        text = payload.get("text", "")

        # Check if this is a code execution request
        if intent == "code.execute" or payload.get("skill_id") == "opencode":
            if self._opencode_client is not None:
                return ResolvedSkill(
                    skill=None, confidence=1.0, source="opencode"
                )
            raise SkillResolutionError(
                "OpenCode client is not available for code execution"
            )

        # Normal skill resolution
        resolver = SkillResolver(registry=self._registry, loader=self._loader)
        resolved = resolver.resolve(intent, text)

        if resolved.skill is None:
            raise SkillResolutionError(
                f"No skill found for intent {intent!r}"
            )
        return resolved

    # --- Phase 3: Execution --------------------------------------------------

    async def _execute_skill(
        self, resolved: ResolvedSkill, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute the resolved skill and return its outcome.

        Args:
            resolved: Output from :meth:`_resolve_skill`.
            payload: Incoming request payload (forwarded as input_data).

        Returns:
            Execution result dict with ``success`` and either ``result`` or
            ``error``.
        """
        # OpenCode path
        if resolved.source == "opencode":
            return await self._execute_via_opencode(payload)

        skill = resolved.skill
        input_data = {
            k: v
            for k, v in payload.items()
            if k not in ("text", "tts_text", "session_id", "skill_id")
        }

        # Skill composition: check for chained skills
        composition = payload.get("composition", [])
        if composition and len(composition) > 1:
            return await self._execute_composition(input_data, composition)

        # Single skill execution
        # skill is non-None here: _resolve_skill raises SkillResolutionError otherwise
        assert skill is not None
        start_event = SkillExecutionStart(
            skill_id=skill.id,
            session_id=str(payload.get("session_id", "")),
            input_preview=payload.get("text", "")[:120],
        )
        await self._emit(start_event)
        t0 = _utcnow()
        execution_type = skill.frontmatter.execution_type
        result = await self._executor.execute(
            skill=skill,
            input_data=input_data,
            execution_type=execution_type,
        )
        duration_ms = (_utcnow() - t0).total_seconds() * 1000
        complete_event = SkillExecutionComplete(
            skill_id=skill.id,
            session_id=str(payload.get("session_id", "")),
            status=ExecutionStatus.COMPLETED if result.ok else ExecutionStatus.FAILED,
            duration_ms=duration_ms,
            error=None if result.ok else result.error,
        )
        await self._emit(complete_event)

        if result.ok:
            return {"success": True, "result": result.output}
        raise SkillExecutionPipelineError(
            f"skill {skill.id!r} failed: {result.error}"
        )

    async def _execute_via_opencode(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Delegate execution to OpenCodeClient.

        Args:
            payload: Incoming request payload.

        Returns:
            Execution result dict.
        """
        from jarvis_os.opencode_adapter.protocol import create_request
        from jarvis_os.opencode_adapter.models import SkillContext

        code = payload.get("text", "")
        context = SkillContext(
            session_id=uuid.uuid4(),
            user_id=payload.get("session_id"),
        )
        request = create_request(skill="opencode", input={"code": code}, context=context)

        try:
            response = await self._opencode_client.execute_skill(request)
        except Exception as exc:  # noqa: BLE001
            logger.error("OpenCode execution failed: %s", exc)
            raise SkillExecutionPipelineError(
                f"OpenCode execution failed: {exc}"
            ) from exc

        if response.status == "success":
            return {"success": True, "result": response.result}
        return {"success": False, "error": response.error or "OpenCode error"}

    async def _execute_composition(
        self,
        input_data: dict[str, Any],
        composition: list[str],
    ) -> dict[str, Any]:
        """Execute a chain of skills sequentially, merging outputs.

        Args:
            input_data: Initial input for the first skill.
            composition: Ordered list of skill ids to execute.

        Returns:
            Merged result from all chained skills.
        """
        current_input = dict(input_data)
        merged_output: dict[str, Any] = {}

        for skill_id in composition:
            skill = self._registry.get(skill_id)
            result = await self._executor.execute(
                skill=skill,
                input_data=current_input,
                execution_type=skill.frontmatter.execution_type,
            )
            if not result.ok:
                raise SkillExecutionPipelineError(
                    f"Composition step {skill_id!r} failed: {result.error}"
                )
            # Merge this skill's output into the chain
            if result.output:
                merged_output.update(result.output)
            current_input = {**current_input, **(result.output or {})}

        return {"success": True, "result": merged_output}

    def _format_response(self, exec_result: dict[str, Any]) -> dict[str, Any]:
        """Wrap the execution result in the standard response envelope.

        Args:
            exec_result: Outcome dict from :meth:`_execute_skill`.

        Returns:
            Response envelope dict.
        """
        return {
            "id": str(uuid.uuid4()),
            "timestamp": _utcnow().isoformat(),
            "type": "RESPONSE",
            "payload": exec_result,
        }

    def _error_envelope(self, message: str) -> dict[str, Any]:
        """Build a standard error envelope.

        Args:
            message: Human-readable error description.

        Returns:
            Error envelope dict.
        """
        return {
            "id": str(uuid.uuid4()),
            "timestamp": _utcnow().isoformat(),
            "type": "ERROR",
            "payload": {"success": False, "error": message},
        }

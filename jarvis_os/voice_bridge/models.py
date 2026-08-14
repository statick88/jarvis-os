"""
Voice Bridge — Pydantic Models
===============================
Pydantic models mirroring the gRPC protobuf messages for type-safe usage
in the application layer. These provide validation, serialization, and
easy conversion to/from protobuf messages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

# Import protobuf classes for conversion
try:
    from jarvis_os.voice_bridge.gen.voice_api_pb2 import (
        AudioChunk as PbAudioChunk,
        HealthRequest as PbHealthRequest,
        HealthResponse as PbHealthResponse,
        ListModelsRequest as PbListModelsRequest,
        ListModelsResponse as PbListModelsResponse,
        ModelInfo as PbModelInfo,
        SegmentTimestamp as PbSegmentTimestamp,
        STTResponse as PbSTTResponse,
        SynthesizeResponse as PbSynthesizeResponse,
        TTSRequest as PbTTSRequest,
        TranscribeRequest as PbTranscribeRequest,
        WordTimestamp as PbWordTimestamp,
    )
    PB_AVAILABLE = True
except ImportError:
    PB_AVAILABLE = False


# ============================================================================
# STT Models
# ============================================================================

class AudioChunk(BaseModel):
    """Audio chunk for streaming STT."""
    data: bytes = Field(..., description="PCM 16kHz 16-bit mono audio data")
    is_final: bool = Field(False, description="True if this is the last chunk")
    session_id: str = Field(default_factory=lambda: str(uuid4()), description="Session identifier")
    timestamp_ms: int = Field(0, description="Timestamp of first sample (Unix ms)")

    def to_protobuf(self) -> "PbAudioChunk":
        """Convert to protobuf AudioChunk."""
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbAudioChunk(
            data=self.data,
            is_final=self.is_final,
            session_id=self.session_id,
            timestamp_ms=self.timestamp_ms,
        )

    @classmethod
    def from_protobuf(cls, pb: "PbAudioChunk") -> "AudioChunk":
        """Create from protobuf AudioChunk."""
        return cls(
            data=pb.data,
            is_final=pb.is_final,
            session_id=pb.session_id,
            timestamp_ms=pb.timestamp_ms,
        )


class TranscribeRequest(BaseModel):
    """Request for one-shot transcription."""
    audio_data: bytes = Field(..., description="Complete audio data (WAV/PCM)")
    model: str = Field("whisper-base", description="STT model: whisper-tiny, whisper-base, whisper-small, whisper-medium")
    language: str = Field("auto", description="Language hint: es, en, auto")
    temperature: float = Field(0.0, ge=0.0, le=1.0, description="Sampling temperature")
    format: str = Field("wav", description="Audio format: wav, pcm, ogg, mp3")
    word_timestamps: bool = Field(False, description="Enable word-level timestamps")

    def to_protobuf(self) -> "PbTranscribeRequest":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbTranscribeRequest(
            audio_data=self.audio_data,
            model=self.model,
            language=self.language,
            temperature=self.temperature,
            format=self.format,
            word_timestamps=self.word_timestamps,
        )

    @classmethod
    def from_protobuf(cls, pb: "PbTranscribeRequest") -> "TranscribeRequest":
        return cls(
            audio_data=pb.audio_data,
            model=pb.model,
            language=pb.language,
            temperature=pb.temperature,
            format=pb.format,
            word_timestamps=pb.word_timestamps,
        )


class WordTimestamp(BaseModel):
    """Word-level timestamp from STT."""
    word: str
    start_ms: float
    end_ms: float
    confidence: float

    def to_protobuf(self) -> "PbWordTimestamp":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbWordTimestamp(
            word=self.word,
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            confidence=self.confidence,
        )

    @classmethod
    def from_protobuf(cls, pb: "PbWordTimestamp") -> "WordTimestamp":
        return cls(
            word=pb.word,
            start_ms=pb.start_ms,
            end_ms=pb.end_ms,
            confidence=pb.confidence,
        )


class SegmentTimestamp(BaseModel):
    """Segment-level timestamp from STT (Whisper native segments)."""
    text: str
    start_ms: float
    end_ms: float
    avg_confidence: float
    speaker_id: int = -1

    def to_protobuf(self) -> "PbSegmentTimestamp":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbSegmentTimestamp(
            text=self.text,
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            avg_confidence=self.avg_confidence,
            speaker_id=self.speaker_id,
        )

    @classmethod
    def from_protobuf(cls, pb: "PbSegmentTimestamp") -> "SegmentTimestamp":
        return cls(
            text=pb.text,
            start_ms=pb.start_ms,
            end_ms=pb.end_ms,
            avg_confidence=pb.avg_confidence,
            speaker_id=pb.speaker_id,
        )


class STTResponse(BaseModel):
    """Response from STT (streaming or unary)."""
    text: str = Field("", description="Transcribed text")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Overall confidence")
    language: str = Field("", description="Detected language (ISO 639-1)")
    duration_ms: int = Field(0, description="Duration of processed audio")
    is_final: bool = Field(True, description="True for final result")
    words: list[WordTimestamp] = Field(default_factory=list, description="Word-level timestamps")
    segments: list[SegmentTimestamp] = Field(default_factory=list, description="Segment-level timestamps")

    def to_protobuf(self) -> "PbSTTResponse":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbSTTResponse(
            text=self.text,
            confidence=self.confidence,
            language=self.language,
            duration_ms=self.duration_ms,
            is_final=self.is_final,
            words=[w.to_protobuf() for w in self.words],
            segments=[s.to_protobuf() for s in self.segments],
        )

    @classmethod
    def from_protobuf(cls, pb: "PbSTTResponse") -> "STTResponse":
        return cls(
            text=pb.text,
            confidence=pb.confidence,
            language=pb.language,
            duration_ms=pb.duration_ms,
            is_final=pb.is_final,
            words=[WordTimestamp.from_protobuf(w) for w in pb.words],
            segments=[SegmentTimestamp.from_protobuf(s) for s in pb.segments],
        )


# ============================================================================
# TTS Models
# ============================================================================

class TTSRequest(BaseModel):
    """Request for speech synthesis."""
    text: str = Field(..., max_length=5000, description="Text to synthesize")
    voice: str = Field("es_ES-pacifico", description="Voice ID: es_ES-pacifico, es_ES-dave, kokoro-es, etc.")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech rate multiplier")
    format: str = Field("wav", description="Output format: wav, mp3, opus, pcm, flac")
    sample_rate: int = Field(22050, description="Sample rate: 16000, 22050, 44100, 48000")
    ssml: Optional[str] = Field(None, description="Optional SSML markup (overrides text)")

    def to_protobuf(self) -> "PbTTSRequest":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbTTSRequest(
            text=self.text,
            voice=self.voice,
            speed=self.speed,
            format=self.format,
            sample_rate=self.sample_rate,
            ssml=self.ssml or "",
        )

    @classmethod
    def from_protobuf(cls, pb: "PbTTSRequest") -> "TTSRequest":
        return cls(
            text=pb.text,
            voice=pb.voice,
            speed=pb.speed,
            format=pb.format,
            sample_rate=pb.sample_rate,
            ssml=pb.ssml if pb.ssml else None,
        )


class SynthesizeResponse(BaseModel):
    """Response from one-shot synthesis."""
    audio_data: bytes = Field(..., description="Complete audio data")
    format: str = Field(..., description="Actual format used")
    sample_rate: int = Field(..., description="Actual sample rate used")
    duration_ms: int = Field(0, description="Duration of generated audio")
    characters: int = Field(0, description="Number of characters synthesized")

    def to_protobuf(self) -> "PbSynthesizeResponse":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbSynthesizeResponse(
            audio_data=self.audio_data,
            format=self.format,
            sample_rate=self.sample_rate,
            duration_ms=self.duration_ms,
            characters=self.characters,
        )

    @classmethod
    def from_protobuf(cls, pb: "PbSynthesizeResponse") -> "SynthesizeResponse":
        return cls(
            audio_data=pb.audio_data,
            format=pb.format,
            sample_rate=pb.sample_rate,
            duration_ms=pb.duration_ms,
            characters=pb.characters,
        )


# ============================================================================
# Health & Model Discovery Models
# ============================================================================

class HealthRequest(BaseModel):
    """Health check request (empty)."""
    def to_protobuf(self) -> "PbHealthRequest":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbHealthRequest()

    @classmethod
    def from_protobuf(cls, pb: "PbHealthRequest") -> "HealthRequest":
        return cls()


class HealthResponse(BaseModel):
    """Health check response."""
    healthy: bool = Field(..., description="Service readiness")
    version: str = Field("", description="Service version (semver)")
    stt_model: str = Field("", description="Currently loaded STT model")
    tts_voice: str = Field("", description="Currently loaded/default TTS voice")
    uptime_ms: int = Field(0, description="Uptime in milliseconds")
    gpu_acceleration: bool = Field(False, description="GPU/Metal acceleration status")
    memory_bytes: int = Field(0, description="Memory usage in bytes (RSS)")

    def to_protobuf(self) -> "PbHealthResponse":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbHealthResponse(
            healthy=self.healthy,
            version=self.version,
            stt_model=self.stt_model,
            tts_voice=self.tts_voice,
            uptime_ms=self.uptime_ms,
            gpu_acceleration=self.gpu_acceleration,
            memory_bytes=self.memory_bytes,
        )

    @classmethod
    def from_protobuf(cls, pb: "PbHealthResponse") -> "HealthResponse":
        return cls(
            healthy=pb.healthy,
            version=pb.version,
            stt_model=pb.stt_model,
            tts_voice=pb.tts_voice,
            uptime_ms=pb.uptime_ms,
            gpu_acceleration=pb.gpu_acceleration,
            memory_bytes=pb.memory_bytes,
        )


class ModelInfo(BaseModel):
    """Model/voice information."""
    id: str = Field(..., description="Unique identifier")
    name: str = Field(..., description="Human-readable name")
    language: str = Field(..., description="Primary language (ISO 639-1)")
    loaded: bool = Field(False, description="True if model is loaded in memory")
    size_mb: int = Field(0, description="Approximate model size in MB")
    sample_rates: list[int] = Field(default_factory=list, description="Supported sample rates (TTS)")
    description: str = Field("", description="Description / capabilities")

    def to_protobuf(self) -> "PbModelInfo":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbModelInfo(
            id=self.id,
            name=self.name,
            language=self.language,
            loaded=self.loaded,
            size_mb=self.size_mb,
            sample_rates=self.sample_rates,
            description=self.description,
        )

    @classmethod
    def from_protobuf(cls, pb: "PbModelInfo") -> "ModelInfo":
        return cls(
            id=pb.id,
            name=pb.name,
            language=pb.language,
            loaded=pb.loaded,
            size_mb=pb.size_mb,
            sample_rates=list(pb.sample_rates),
            description=pb.description,
        )


class ListModelsRequest(BaseModel):
    """List models request (empty)."""
    def to_protobuf(self) -> "PbListModelsRequest":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbListModelsRequest()

    @classmethod
    def from_protobuf(cls, pb: "PbListModelsRequest") -> "ListModelsRequest":
        return cls()


class ListModelsResponse(BaseModel):
    """List models response."""
    stt_models: list[ModelInfo] = Field(default_factory=list)
    tts_voices: list[ModelInfo] = Field(default_factory=list)

    def to_protobuf(self) -> "PbListModelsResponse":
        if not PB_AVAILABLE:
            raise RuntimeError("Protobuf not available")
        return PbListModelsResponse(
            stt_models=[m.to_protobuf() for m in self.stt_models],
            tts_voices=[m.to_protobuf() for m in self.tts_voices],
        )

    @classmethod
    def from_protobuf(cls, pb: "PbListModelsResponse") -> "ListModelsResponse":
        return cls(
            stt_models=[ModelInfo.from_protobuf(m) for m in pb.stt_models],
            tts_voices=[ModelInfo.from_protobuf(m) for m in pb.tts_voices],
        )


# ============================================================================
# Conversion Helpers
# ============================================================================

def stt_response_from_protobuf(pb: "PbSTTResponse") -> STTResponse:
    """Convenience function to convert protobuf STTResponse."""
    return STTResponse.from_protobuf(pb)


def synthesize_response_from_protobuf(pb: "PbSynthesizeResponse") -> SynthesizeResponse:
    """Convenience function to convert protobuf SynthesizeResponse."""
    return SynthesizeResponse.from_protobuf(pb)


def health_response_from_protobuf(pb: "PbHealthResponse") -> HealthResponse:
    """Convenience function to convert protobuf HealthResponse."""
    return HealthResponse.from_protobuf(pb)


def list_models_response_from_protobuf(pb: "PbListModelsResponse") -> ListModelsResponse:
    """Convenience function to convert protobuf ListModelsResponse."""
    return ListModelsResponse.from_protobuf(pb)


# ============================================================================
# WebSocket Audio Streaming Models
# ============================================================================

class SessionOpen(BaseModel):
    """Client initiates a streaming session."""
    session_id: str = Field(..., description="UUIDv4 session identifier")
    format: str = Field("pcm", description="Audio format: pcm, wav, opus")
    sample_rate: int = Field(16000, description="Sample rate in Hz")
    vad_mode: str = Field("none", description="VAD mode: none, energy, silero")


class SessionAck(BaseModel):
    """Server acknowledges session opening."""
    type: str = Field("session_ack", description="Message type discriminator")
    session_id: str = Field(..., description="Echoed session identifier")
    websocket_enabled: bool = Field(True, description="True if WebSocket streaming supported")
    stt_model: str = Field("whisper-base", description="Loaded STT model")
    tts_voice: str = Field("es_ES-pacifico", description="Default TTS voice")


class SessionClose(BaseModel):
    """Either side closes the session."""
    session_id: str = Field(..., description="Session identifier")
    reason: str = Field("client_disconnect", description="Close reason")


class ErrorMsg(BaseModel):
    """Server sends error to client."""
    session_id: str = Field(..., description="Session identifier")
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")


class AudioChunkMsg(BaseModel):
    """Binary audio chunk metadata (binary frame carries raw PCM)."""
    session_id: str = Field(..., description="Session identifier")
    is_final: bool = Field(False, description="True if this is the last chunk")
    timestamp_ms: int = Field(0, description="Timestamp of first sample (Unix ms)")


class STTPartial(BaseModel):
    """Partial transcription result."""
    session_id: str = Field(..., description="Session identifier")
    text: str = Field("", description="Partial transcribed text")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score")


class STTFinal(BaseModel):
    """Final transcription result."""
    session_id: str = Field(..., description="Session identifier")
    text: str = Field("", description="Final transcribed text")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score")
    duration_ms: int = Field(0, description="Duration of processed audio in ms")
    segments: list[SegmentTimestamp] = Field(default_factory=list, description="Segment timestamps")


class TTSInput(BaseModel):
    """Text chunk from LLM orchestrator for TTS synthesis."""
    session_id: str = Field(..., description="Session identifier")
    text: str = Field("", description="Text chunk to synthesize")
    voice: str = Field("es_ES-pacifico", description="Voice identifier")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech rate multiplier")


class TTSChunk(BaseModel):
    """Synthesized audio chunk metadata (binary frame carries audio bytes)."""
    session_id: str = Field(..., description="Session identifier")
    format: str = Field("pcm", description="Audio format: pcm, wav, opus")
    sample_rate: int = Field(22050, description="Sample rate in Hz")
    is_final: bool = Field(False, description="True if this is the last chunk")
    duration_ms: int = Field(0, description="Duration of audio chunk in ms")
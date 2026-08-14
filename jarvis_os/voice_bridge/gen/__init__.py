"""
Voice Bridge — Generated gRPC Stubs
====================================
This package contains the generated gRPC stubs from voice_api.proto.
Do not edit manually - regenerate from spec/contracts/voice_api.proto
"""

from jarvis_os.voice_bridge.gen.voice_api_pb2 import (
    AudioChunk,
    HealthRequest,
    HealthResponse,
    ListModelsRequest,
    ListModelsResponse,
    ModelInfo,
    SegmentTimestamp,
    STTResponse,
    SynthesizeResponse,
    TTSRequest,
    TranscribeRequest,
    WordTimestamp,
)

from jarvis_os.voice_bridge.gen.voice_api_pb2_grpc import (
    VoicePipelineServicer,
    VoicePipelineStub,
    add_VoicePipelineServicer_to_server,
)

__all__ = [
    # Messages
    "AudioChunk",
    "HealthRequest",
    "HealthResponse",
    "ListModelsRequest",
    "ListModelsResponse",
    "ModelInfo",
    "SegmentTimestamp",
    "STTResponse",
    "SynthesizeResponse",
    "TTSRequest",
    "TranscribeRequest",
    "WordTimestamp",
    # Services
    "VoicePipelineServicer",
    "VoicePipelineStub",
    "add_VoicePipelineServicer_to_server",
]
"""Voice Bridge — async gRPC client for speech-to-text and text-to-speech."""

from jarvis_os.voice_bridge.client import JarvisVoiceBridge, JarvisVoiceError

__all__ = [
    "AudioChunk",
    "TranscribeRequest",
        "STTResponse",
    "TTSRequest",
    "SynthesizeResponse",
    "HealthRequest",
    "HealthResponse",
    "JarvisVoiceBridge",
    "JarvisVoiceError",
    "__version__",
]

__version__ = "0.1.0"

# Lazy imports so the module remains importable even if models aren't available yet.
# The explicit imports above cover the common case.


def __getattr__(name: str):
    if name in (
        "AudioChunk",
        "TranscribeRequest",
    "STTResponse",
        "TTSRequest",
        "SynthesizeResponse",
        "HealthRequest",
        "HealthResponse",
    ):
        from jarvis_os.voice_bridge import models

        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

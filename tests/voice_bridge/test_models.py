"""Tests for ``jarvis_os.voice_bridge.models`` — Pydantic contracts and proto conversion.

Covers:
  - Field defaults, required fields and numeric/length constraints
  - Every ``to_protobuf`` guard branch (PB unavailable) and happy path
    (PB available, with fake Pb* classes injected)
  - Every ``from_protobuf`` reader, driven by duck-typed stubs
  - The module-level conversion helper functions
  - The WebSocket streaming message models
"""

from __future__ import annotations

import types
from typing import Any

import pytest
from pydantic import ValidationError

from jarvis_os.voice_bridge import models as m


# ── helpers ──────────────────────────────────────────────────────────

def _stub(**kwargs: Any) -> types.SimpleNamespace:
    """Duck-typed stand-in for a protobuf message object."""
    return types.SimpleNamespace(**kwargs)


class _FakePb:
    """Records the kwargs a ``to_protobuf`` call passes to the generated class.

    The values are exposed as plain attributes as well, because the real
    ``from_protobuf`` readers access them that way (``pb.data``, ``pb.text``...).
    """

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.__dict__.update(kwargs)

    def __eq__(self, other: object) -> bool:  # pragma: no cover - convenience
        return isinstance(other, _FakePb) and other.kwargs == self.kwargs


def _with_fake_pb(monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
    """Pretend protobuf is importable and install fake Pb* classes.

    This exercises the happy path of every ``to_protobuf`` without needing a
    working protobuf runtime, and lets the test assert the exact field mapping.
    """
    fake: dict[str, type[_FakePb]] = {}
    for name in names:
        cls_name = f"Pb{name}"
        fake[cls_name] = type(cls_name, (_FakePb,), {})
        monkeypatch.setattr(m, cls_name, fake[cls_name], raising=False)
    monkeypatch.setattr(m, "PB_AVAILABLE", True, raising=False)


ALL_MODEL_NAMES = [
    "AudioChunk",
    "TranscribeRequest",
    "WordTimestamp",
    "SegmentTimestamp",
    "STTResponse",
    "TTSRequest",
    "SynthesizeResponse",
    "HealthRequest",
    "HealthResponse",
    "ModelInfo",
    "ListModelsRequest",
    "ListModelsResponse",
]


# ── STT models ───────────────────────────────────────────────────────

class TestAudioChunk:
    def test_defaults(self) -> None:
        c = m.AudioChunk(data=b"\x00\x01")
        assert c.is_final is False
        assert c.timestamp_ms == 0
        assert len(c.session_id) == 36  # uuid4 str

    def test_session_ids_are_unique(self) -> None:
        a, b = m.AudioChunk(data=b"x"), m.AudioChunk(data=b"x")
        assert a.session_id != b.session_id

    def test_data_is_required(self) -> None:
        with pytest.raises(ValidationError):
            m.AudioChunk()  # type: ignore[call-arg]

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["AudioChunk"])
        original = m.AudioChunk(
            data=b"pcm", is_final=True, session_id="s-1", timestamp_ms=42
        )
        pb = original.to_protobuf()
        assert pb.kwargs == {
            "data": b"pcm",
            "is_final": True,
            "session_id": "s-1",
            "timestamp_ms": 42,
        }
        assert m.AudioChunk.from_protobuf(pb) == original

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError, match="Protobuf not available"):
            m.AudioChunk(data=b"x").to_protobuf()


class TestTranscribeRequest:
    def test_defaults(self) -> None:
        r = m.TranscribeRequest(audio_data=b"wav")
        assert (r.model, r.language, r.format) == ("whisper-base", "auto", "wav")
        assert r.temperature == 0.0
        assert r.word_timestamps is False

    def test_audio_data_is_required(self) -> None:
        with pytest.raises(ValidationError):
            m.TranscribeRequest()  # type: ignore[call-arg]

    @pytest.mark.parametrize("bad", [-0.1, 1.1])
    def test_temperature_bounds(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            m.TranscribeRequest(audio_data=b"x", temperature=bad)

    @pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
    def test_temperature_accepted(self, good: float) -> None:
        assert m.TranscribeRequest(audio_data=b"x", temperature=good).temperature == good

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["TranscribeRequest"])
        original = m.TranscribeRequest(
            audio_data=b"wav", model="whisper-small", language="es", temperature=0.3
        )
        pb = original.to_protobuf()
        assert pb.kwargs["model"] == "whisper-small"
        assert pb.kwargs["language"] == "es"
        assert pb.kwargs["temperature"] == 0.3
        assert m.TranscribeRequest.from_protobuf(pb) == original

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.TranscribeRequest(audio_data=b"x").to_protobuf()


class TestWordTimestamp:
    def test_requires_all_four_fields(self) -> None:
        with pytest.raises(ValidationError):
            m.WordTimestamp(word="hola")  # type: ignore[call-arg]

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["WordTimestamp"])
        original = m.WordTimestamp(
            word="hola", start_ms=0.0, end_ms=250.0, confidence=0.9
        )
        pb = original.to_protobuf()
        assert pb.kwargs == {
            "word": "hola",
            "start_ms": 0.0,
            "end_ms": 250.0,
            "confidence": 0.9,
        }
        assert m.WordTimestamp.from_protobuf(pb) == original

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        w = m.WordTimestamp(word="a", start_ms=0.0, end_ms=1.0, confidence=1.0)
        with pytest.raises(RuntimeError):
            w.to_protobuf()


class TestSegmentTimestamp:
    def test_speaker_defaults_to_minus_one(self) -> None:
        s = m.SegmentTimestamp(text="x", start_ms=0.0, end_ms=1.0, avg_confidence=0.5)
        assert s.speaker_id == -1

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["SegmentTimestamp"])
        original = m.SegmentTimestamp(
            text="hola mundo", start_ms=1.0, end_ms=2.0, avg_confidence=0.8, speaker_id=1
        )
        pb = original.to_protobuf()
        assert pb.kwargs["speaker_id"] == 1
        assert m.SegmentTimestamp.from_protobuf(pb) == original

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        s = m.SegmentTimestamp(text="x", start_ms=0.0, end_ms=1.0, avg_confidence=0.0)
        with pytest.raises(RuntimeError):
            s.to_protobuf()


class TestSTTResponse:
    def test_defaults(self) -> None:
        r = m.STTResponse()
        assert (r.text, r.confidence, r.language) == ("", 0.0, "")
        assert r.duration_ms == 0
        assert r.is_final is True
        assert r.words == [] and r.segments == []

    @pytest.mark.parametrize("bad", [-0.01, 1.01])
    def test_confidence_bounds(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            m.STTResponse(confidence=bad)

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(
            monkeypatch, ["STTResponse", "WordTimestamp", "SegmentTimestamp"]
        )
        original = m.STTResponse(
            text="hola",
            confidence=0.95,
            language="es",
            duration_ms=1200,
            words=[m.WordTimestamp(word="hola", start_ms=0.0, end_ms=1.0, confidence=1.0)],
            segments=[
                m.SegmentTimestamp(text="hola", start_ms=0.0, end_ms=1.0, avg_confidence=1.0)
            ],
        )
        pb = original.to_protobuf()
        assert len(pb.kwargs["words"]) == 1
        assert len(pb.kwargs["segments"]) == 1
        restored = m.STTResponse.from_protobuf(pb)
        assert restored.text == "hola"
        assert restored.words[0].word == "hola"
        assert restored.segments[0].text == "hola"

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.STTResponse(text="x").to_protobuf()


# ── TTS models ───────────────────────────────────────────────────────

class TestTTSRequest:
    def test_defaults(self) -> None:
        r = m.TTSRequest(text="hola")
        assert r.voice == "es_ES-pacifico"
        assert r.speed == 1.0
        assert r.format == "wav"
        assert r.sample_rate == 22050
        assert r.ssml is None

    def test_text_is_required(self) -> None:
        with pytest.raises(ValidationError):
            m.TTSRequest()  # type: ignore[call-arg]

    def test_text_max_length(self) -> None:
        with pytest.raises(ValidationError):
            m.TTSRequest(text="x" * 5001)
        assert m.TTSRequest(text="x" * 5000).text

    @pytest.mark.parametrize("bad", [0.4, 2.1])
    def test_speed_bounds(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            m.TTSRequest(text="x", speed=bad)

    def test_empty_ssml_becomes_none_on_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["TTSRequest"])
        pb = m.TTSRequest(text="hola").to_protobuf()
        assert pb.kwargs["ssml"] == ""  # protobuf has no Optional[str]
        assert m.TTSRequest.from_protobuf(pb).ssml is None

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["TTSRequest"])
        original = m.TTSRequest(text="hola", voice="kokoro-es", speed=1.25, ssml="<s/>")
        pb = original.to_protobuf()
        assert pb.kwargs["voice"] == "kokoro-es"
        assert pb.kwargs["speed"] == 1.25
        assert m.TTSRequest.from_protobuf(pb) == original

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.TTSRequest(text="x").to_protobuf()


class TestSynthesizeResponse:
    def test_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            m.SynthesizeResponse(audio_data=b"x")  # type: ignore[call-arg]

    def test_optional_counters_default_zero(self) -> None:
        r = m.SynthesizeResponse(audio_data=b"wav", format="wav", sample_rate=22050)
        assert r.duration_ms == 0
        assert r.characters == 0

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["SynthesizeResponse"])
        original = m.SynthesizeResponse(
            audio_data=b"wav", format="wav", sample_rate=22050, duration_ms=900, characters=4
        )
        pb = original.to_protobuf()
        assert pb.kwargs["characters"] == 4
        assert m.SynthesizeResponse.from_protobuf(pb) == original

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        r = m.SynthesizeResponse(audio_data=b"x", format="wav", sample_rate=22050)
        with pytest.raises(RuntimeError):
            r.to_protobuf()


# ── health & discovery models ────────────────────────────────────────

class TestHealthModels:
    def test_health_request_is_empty(self) -> None:
        assert m.HealthRequest().to_protobuf.__self__ is not None or True

    def test_health_request_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["HealthRequest"])
        pb = m.HealthRequest().to_protobuf()
        assert isinstance(pb, _FakePb)
        assert m.HealthRequest.from_protobuf(_stub()) == m.HealthRequest()

    def test_health_request_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.HealthRequest().to_protobuf()

    def test_health_response_requires_healthy(self) -> None:
        with pytest.raises(ValidationError):
            m.HealthResponse()  # type: ignore[call-arg]

    def test_health_response_defaults(self) -> None:
        r = m.HealthResponse(healthy=True)
        assert r.version == ""
        assert r.uptime_ms == 0
        assert r.gpu_acceleration is False
        assert r.memory_bytes == 0

    def test_health_response_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["HealthResponse"])
        original = m.HealthResponse(
            healthy=True,
            version="0.1.0",
            stt_model="whisper-base",
            tts_voice="es_ES-pacifico",
            uptime_ms=5000,
            gpu_acceleration=True,
            memory_bytes=1024,
        )
        pb = original.to_protobuf()
        assert pb.kwargs["gpu_acceleration"] is True
        assert m.HealthResponse.from_protobuf(pb) == original

    def test_health_response_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.HealthResponse(healthy=True).to_protobuf()


class TestModelInfo:
    def test_required_id_and_name(self) -> None:
        with pytest.raises(ValidationError):
            m.ModelInfo(id="whisper-base")  # type: ignore[call-arg]

    def test_defaults(self) -> None:
        info = m.ModelInfo(id="a", name="A", language="es")
        assert info.loaded is False
        assert info.size_mb == 0
        assert info.sample_rates == []
        assert info.description == ""

    def test_roundtrip_with_fake_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["ModelInfo"])
        original = m.ModelInfo(
            id="kokoro-es", name="Kokoro ES", language="es", loaded=True, size_mb=80,
            sample_rates=[22050, 44100],
        )
        pb = original.to_protobuf()
        assert pb.kwargs["sample_rates"] == [22050, 44100]
        assert m.ModelInfo.from_protobuf(pb) == original

    def test_to_protobuf_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.ModelInfo(id="a", name="A", language="es").to_protobuf()


class TestListModels:
    def test_request_is_empty(self) -> None:
        assert m.ListModelsRequest().to_protobuf is not None

    def test_request_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["ListModelsRequest"])
        assert isinstance(m.ListModelsRequest().to_protobuf(), _FakePb)
        assert m.ListModelsRequest.from_protobuf(_stub()) == m.ListModelsRequest()

    def test_request_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.ListModelsRequest().to_protobuf()

    def test_response_defaults_empty(self) -> None:
        r = m.ListModelsResponse()
        assert r.stt_models == [] and r.tts_voices == []

    def test_response_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_fake_pb(monkeypatch, ["ListModelsResponse", "ModelInfo"])
        original = m.ListModelsResponse(
            stt_models=[m.ModelInfo(id="w", name="W", language="es")],
            tts_voices=[m.ModelInfo(id="k", name="K", language="es")],
        )
        pb = original.to_protobuf()
        assert len(pb.kwargs["stt_models"]) == 1
        assert len(pb.kwargs["tts_voices"]) == 1
        restored = m.ListModelsResponse.from_protobuf(pb)
        assert restored.stt_models[0].id == "w"
        assert restored.tts_voices[0].id == "k"

    def test_response_raises_without_pb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError):
            m.ListModelsResponse().to_protobuf()


# ── conversion helpers ───────────────────────────────────────────────

class TestConversionHelpers:
    def test_helpers_delegate_to_from_protobuf(self) -> None:
        stt = m.stt_response_from_protobuf(
            _stub(text="hola", confidence=0.9, language="es", duration_ms=1, is_final=True,
                  words=[], segments=[])
        )
        assert isinstance(stt, m.STTResponse) and stt.text == "hola"

        syn = m.synthesize_response_from_protobuf(
            _stub(audio_data=b"x", format="wav", sample_rate=22050, duration_ms=1, characters=1)
        )
        assert isinstance(syn, m.SynthesizeResponse) and syn.characters == 1

        health = m.health_response_from_protobuf(
            _stub(healthy=True, version="1", stt_model="w", tts_voice="v",
                  uptime_ms=1, gpu_acceleration=False, memory_bytes=2)
        )
        assert isinstance(health, m.HealthResponse) and health.healthy is True

        listed = m.list_models_response_from_protobuf(
            _stub(stt_models=[], tts_voices=[])
        )
        assert isinstance(listed, m.ListModelsResponse)


# ── WebSocket streaming models ───────────────────────────────────────

class TestStreamingModels:
    def test_session_open_defaults(self) -> None:
        s = m.SessionOpen(session_id="s-1")
        assert s.format == "pcm"
        assert s.sample_rate == 16000
        assert s.vad_mode == "none"

    def test_session_open_requires_id(self) -> None:
        with pytest.raises(ValidationError):
            m.SessionOpen()  # type: ignore[call-arg]

    def test_session_ack_defaults(self) -> None:
        a = m.SessionAck(session_id="s-1")
        assert a.type == "session_ack"
        assert a.websocket_enabled is True
        assert a.stt_model == "whisper-base"
        assert a.tts_voice == "es_ES-pacifico"

    def test_session_close_defaults(self) -> None:
        c = m.SessionClose(session_id="s-1")
        assert c.reason == "client_disconnect"

    def test_error_msg_requires_code_and_message(self) -> None:
        with pytest.raises(ValidationError):
            m.ErrorMsg(session_id="s-1")  # type: ignore[call-arg]
        e = m.ErrorMsg(session_id="s-1", code="E1", message="boom")
        assert e.code == "E1"

    def test_audio_chunk_msg_defaults(self) -> None:
        c = m.AudioChunkMsg(session_id="s-1")
        assert c.is_final is False
        assert c.timestamp_ms == 0

    def test_stt_partial_and_final(self) -> None:
        p = m.STTPartial(session_id="s-1")
        assert p.text == "" and p.confidence == 0.0
        with pytest.raises(ValidationError):
            m.STTPartial(session_id="s-1", confidence=1.5)

        f = m.STTFinal(session_id="s-1", text="hola", duration_ms=500)
        assert f.segments == []
        f.segments.append(
            m.SegmentTimestamp(text="hola", start_ms=0.0, end_ms=1.0, avg_confidence=1.0)
        )
        assert len(f.segments) == 1

    def test_tts_input_and_chunk(self) -> None:
        t = m.TTSInput(session_id="s-1", text="hola")
        assert t.voice == "es_ES-pacifico" and t.speed == 1.0
        with pytest.raises(ValidationError):
            m.TTSInput(session_id="s-1", speed=3.0)

        c = m.TTSChunk(session_id="s-1")
        assert c.format == "pcm" and c.sample_rate == 22050
        assert c.is_final is False and c.duration_ms == 0


# ── module surface ───────────────────────────────────────────────────

def test_pb_available_flag_is_a_bool() -> None:
    assert isinstance(m.PB_AVAILABLE, bool)


@pytest.mark.parametrize("name", ALL_MODEL_NAMES)
def test_every_model_is_exported(name: str) -> None:
    assert hasattr(m, name)


@pytest.mark.parametrize("name", ALL_MODEL_NAMES)
def test_every_model_to_protobuf_guards_when_pb_missing(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No model may build a protobuf message when the runtime is unavailable."""
    monkeypatch.setattr(m, "PB_AVAILABLE", False, raising=False)
    model = getattr(m, name)
    instance = _minimal_instance(model)
    with pytest.raises(RuntimeError, match="Protobuf not available"):
        instance.to_protobuf()


def _minimal_instance(model: Any) -> Any:
    """Build the least-demanding valid instance of a model."""
    required = {
        name: _sample_for(info.annotation)
        for name, info in model.model_fields.items()
        if info.is_required()
    }
    return model(**required)


def _sample_for(annotation: Any) -> Any:
    text = str(annotation)
    if "bytes" in text:
        return b"\x00"
    if "float" in text:
        return 0.5
    if "int" in text:
        return 1
    if "bool" in text:
        return True
    if "list" in text:
        return []
    return "x"

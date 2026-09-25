import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';

// ============================================================================
// Data Models
// ============================================================================

class STTPartial {
  final String text;
  final double confidence;
  final String sessionId;

  STTPartial({required this.text, required this.confidence, required this.sessionId});

  @override
  String toString() => 'STTPartial(text: "$text", confidence: $confidence)';
}

class STTFinal {
  final String text;
  final double confidence;
  final String sessionId;
  final int durationMs;

  STTFinal({
    required this.text,
    required this.confidence,
    required this.sessionId,
    required this.durationMs,
  });

  @override
  String toString() => 'STTFinal(text: "$text", durationMs: $durationMs)';
}

class TTSChunk {
  final Uint8List audioData;
  final String sessionId;
  final String format;
  final int sampleRate;
  final bool isFinal;
  final int durationMs;

  TTSChunk({
    required this.audioData,
    required this.sessionId,
    required this.format,
    required this.sampleRate,
    required this.isFinal,
    required this.durationMs,
  });
}

class ConnectionStateChanged {
  final String state;
  ConnectionStateChanged(this.state);
}

// ============================================================================
// Circular Audio Buffer
// ============================================================================

class CircularAudioBuffer {
  final int bufferMs;
  final int sampleRate;
  final int bytesPerSample;

  late final int _capacity; // total bytes
  late final Uint8List _buffer;
  int _writePos = 0;
  int _readPos = 0;
  int _availableBytes = 0;
  bool _overflow = false;

  CircularAudioBuffer({
    this.bufferMs = 500,
    this.sampleRate = 22050,
    this.bytesPerSample = 2, // 16-bit = 2 bytes
  }) {
    // Calculate capacity: ms * sampleRate * bytesPerSample / 1000
    _capacity = (bufferMs * sampleRate * bytesPerSample) ~/ 1000;
    _buffer = Uint8List(_capacity);
  }

  int get capacity => _capacity;
  int get availableBytes => _availableBytes;
  double get fillRatio => _capacity > 0 ? _availableBytes / _capacity : 0.0;
  bool get isEmpty => _availableBytes == 0;
  bool get isFull => _availableBytes == _capacity;
  bool get hasOverflow => _overflow;

  /// Write bytes to the buffer. Returns bytes written (may be less on overflow).
  int write(Uint8List data) {
    if (data.isEmpty) return 0;
    if (_capacity == 0) return 0;

    _overflow = false;
    int written = 0;

    for (int i = 0; i < data.length; i++) {
      if (_availableBytes >= _capacity) {
        _overflow = true;
        // Overwrite oldest data (advance read pointer)
        _readPos = (_readPos + 1) % _capacity;
        _availableBytes--;
      }
      _buffer[_writePos] = data[i];
      _writePos = (_writePos + 1) % _capacity;
      _availableBytes++;
      written++;
    }

    return written;
  }

  /// Read up to `maxBytes` from the buffer.
  Uint8List read(int maxBytes) {
    if (_availableBytes == 0) return Uint8List(0);
    final toRead = min(maxBytes, _availableBytes);
    final result = Uint8List(toRead);

    for (int i = 0; i < toRead; i++) {
      result[i] = _buffer[_readPos];
      _readPos = (_readPos + 1) % _capacity;
      _availableBytes--;
    }

    return result;
  }

  /// Drain all remaining bytes.
  Uint8List drain() {
    return read(_availableBytes);
  }

  /// Clear the buffer.
  void clear() {
    _writePos = 0;
    _readPos = 0;
    _availableBytes = 0;
    _overflow = false;
  }
}

// ============================================================================
// Audio Stream Service
// ============================================================================

class AudioStreamService {
  final String host;
  final int port;
  final int bufferMs;
  final String token;

  WebSocket? _ws;
  final AudioPlayer _audioPlayer = AudioPlayer();
  final CircularAudioBuffer _ringBuffer;

  // Stream controllers
  final _partialController = StreamController<STTPartial>.broadcast();
  final _finalController = StreamController<STTFinal>.broadcast();
  final _audioChunkController = StreamController<TTSChunk>.broadcast();
  final _stateController = StreamController<ConnectionStateChanged>.broadcast();

  // Reconnection state
  int _reconnectAttempt = 0;
  static const int _maxReconnectAttempts = 10;
  static const double _backoffBase = 1.0; // seconds
  static const double _backoffMax = 30.0; // seconds
  static const double _jitter = 0.5;
  Timer? _reconnectTimer;
  Timer? _drainTimer;
  bool _manuallyClosed = false;

  // Playback state
  bool _isPlaying = false;
  List<Uint8List> _pendingChunks = [];
  Timer? _playbackTimer;

  AudioStreamService({
    this.host = '127.0.0.1',
    this.port = 8080,
    this.bufferMs = 500,
    this.token = '',
  }) : _ringBuffer = CircularAudioBuffer(bufferMs: bufferMs);

  // ------------------------------------------------------------------
  // Public getters
  // ------------------------------------------------------------------

  Stream<STTPartial> get onPartialTranscript => _partialController.stream;
  Stream<STTFinal> get onFinalTranscript => _finalController.stream;
  Stream<TTSChunk> get onAudioChunk => _audioChunkController.stream;
  Stream<ConnectionStateChanged> get onStateChange => _stateController.stream;
  double get bufferFillRatio => _ringBuffer.fillRatio;
  bool get isConnected => _ws != null;

  // ------------------------------------------------------------------
  // Connection
  // ------------------------------------------------------------------

  Future<void> connect(Uri endpoint, {String? token}) async {
    _manuallyClosed = false;
    _setState('connecting');

    final wsUrl = endpoint.toString();
    debugPrint('AudioStreamService: connecting to $wsUrl');

    try {
      _ws = await WebSocket.connect(
        wsUrl,
        headers: token != null && token.isNotEmpty ? {'Authorization': 'Bearer $token'} : {},
      );

      // Send session_open
      final sessionId = _generateSessionId();
      final openMsg = jsonEncode({
        'type': 'session_open',
        'session_id': sessionId,
        'format': 'pcm',
        'sample_rate': 16000,
        'vad_mode': 'none',
      });
      _ws!.add(utf8.encode(openMsg));
      debugPrint('AudioStreamService: session_open sent (session: $sessionId)');

      _reconnectAttempt = 0;
      _setState('connected');
      _startDrainLoop();
      _listen();
    } on WebSocketException catch (e) {
      debugPrint('AudioStreamService: WebSocket error: $e');
      _setState('error');
      _scheduleReconnect();
      rethrow;
    } catch (e) {
      debugPrint('AudioStreamService: connection error: $e');
      _setState('error');
      _scheduleReconnect();
      rethrow;
    }
  }

  void _listen() {
    if (_ws == null) return;

    _ws!.listen(
      (data) async {
        if (data is Uint8List) {
          // Binary audio frame — check if there's preceding JSON metadata
          // In this implementation, binary frames are pure PCM
          _ringBuffer.write(data);
          _schedulePlayback();
        } else if (data is String) {
          try {
            final msg = jsonDecode(data);
            final type = msg['type'] as String?;

            switch (type) {
              case 'session_ack':
                debugPrint('AudioStreamService: session_ack received');
                _reconnectAttempt = 0;
                break;

              case 'stt_partial':
                _partialController.add(STTPartial(
                  text: msg['text'] as String? ?? '',
                  confidence: (msg['confidence'] as num?)?.toDouble() ?? 0.0,
                  sessionId: msg['session_id'] as String? ?? '',
                ));
                break;

              case 'stt_final':
                _finalController.add(STTFinal(
                  text: msg['text'] as String? ?? '',
                  confidence: (msg['confidence'] as num?)?.toDouble() ?? 0.0,
                  sessionId: msg['session_id'] as String? ?? '',
                  durationMs: msg['duration_ms'] as int? ?? 0,
                ));
                break;

              case 'tts_chunk':
                // TTS metadata frame — audio data follows as binary frame
                // We buffer the metadata for the next binary frame
                _pendingMetadata = msg;
                break;

              case 'ping':
                _ws?.add(utf8.encode(jsonEncode({
                  'type': 'pong',
                  'timestamp_ms': msg['timestamp_ms'],
                })));
                break;

              case 'error':
                debugPrint('AudioStreamService: server error: ${msg['message']}');
                break;

              default:
                debugPrint('AudioStreamService: unknown message type: $type');
            }
          } on FormatException catch (e) {
            debugPrint('AudioStreamService: JSON parse error: $e');
          }
        }
      },
      onError: (error) {
        debugPrint('AudioStreamService: stream error: $error');
        _setState('error');
        if (!_manuallyClosed) {
          _scheduleReconnect();
        }
      },
      onDone: () {
        debugPrint('AudioStreamService: stream closed');
        _setState('disconnected');
        if (!_manuallyClosed) {
          _scheduleReconnect();
        }
        _stopPlayback();
        _drainTimer?.cancel();
      },
      cancelOnError: false,
    );
  }

  Map<String, dynamic>? _pendingMetadata;

  // ------------------------------------------------------------------
  // Audio send
  // ------------------------------------------------------------------

  void sendAudio(Uint8List pcmBytes, {bool isFinal = false}) {
    if (_ws == null) return;

    final meta = jsonEncode({
      'type': 'audio_chunk',
      'session_id': '', // server echoes from session_ack
      'is_final': isFinal,
      'timestamp_ms': DateTime.now().millisecondsSinceEpoch,
    });

    // Send JSON metadata frame first, then binary PCM
    _ws?.add(utf8.encode(meta));
    _ws?.add(pcmBytes);
  }

  void sendText(String text, {String voice = 'es_ES-pacifico', double speed = 1.0}) {
    if (_ws == null) return;

    final msg = jsonEncode({
      'type': 'tts_input',
      'session_id': '',
      'text': text,
      'voice': voice,
      'speed': speed,
    });

    _ws?.add(utf8.encode(msg));
  }

  // ------------------------------------------------------------------
  // Close
  // ------------------------------------------------------------------

  Future<void> close({String reason = 'client_disconnect'}) async {
    _manuallyClosed = true;
    _reconnectTimer?.cancel();
    _drainTimer?.cancel();
    _stopPlayback();

    if (_ws != null) {
      try {
        _ws!.add(utf8.encode(jsonEncode({
          'type': 'session_close',
          'session_id': '',
          'reason': reason,
        })));
        await _ws!.close();
      } catch (e) {
        debugPrint('AudioStreamService: close error: $e');
      }
      _ws = null;
    }

    _setState('disconnected');
    await _audioPlayer.dispose();
    await _partialController.close();
    await _finalController.close();
    await _audioChunkController.close();
    await _stateController.close();
  }

  // ------------------------------------------------------------------
  // Reconnection
  // ------------------------------------------------------------------

  void _scheduleReconnect() {
    if (_manuallyClosed) return;
    if (_reconnectAttempt >= _maxReconnectAttempts) {
      debugPrint('AudioStreamService: max reconnection attempts reached');
      _setState('error');
      return;
    }

    _reconnectAttempt++;
    final baseDelay = _backoffBase * pow(2, _reconnectAttempt - 1);
    final jitter = baseDelay * _jitter * (Random().nextDouble() * 2 - 1);
    final delay = min(baseDelay + jitter, _backoffMax);

    debugPrint('AudioStreamService: reconnecting in ${delay.toStringAsFixed(1)}s (attempt $_reconnectAttempt)');
    _setState('reconnecting');

    _reconnectTimer = Timer(Duration(milliseconds: (delay * 1000).round()), () async {
      try {
        final sessionId = _generateSessionId();
        final wsUrl = Uri.parse('ws://$host:$port/v1/audio/stream');
        await connect(wsUrl, token: token);
        debugPrint('AudioStreamService: reconnected successfully');
      } catch (e) {
        debugPrint('AudioStreamService: reconnection failed: $e');
        _scheduleReconnect();
      }
    });
  }

  // ------------------------------------------------------------------
  // Playback
  // ------------------------------------------------------------------

  void _schedulePlayback() {
    if (_isPlaying) return;
    _isPlaying = true;

    _playbackTimer?.cancel();
    _playbackTimer = Timer(const Duration(milliseconds: 50), _drainPlayback);
  }

  void _stopPlayback() {
    _isPlaying = false;
    _playbackTimer?.cancel();
    _playbackTimer = null;
    _pendingChunks.clear();
  }

  void _drainPlayback() {
    if (!_isPlaying) return;

    final data = _ringBuffer.read(_ringBuffer.capacity ~/ 4); // read 1/4 at a time
    if (data.isNotEmpty) {
      _audioPlayer.play(BytesSource(data));
    }

    _playbackTimer?.cancel();
    if (_ringBuffer.availableBytes > 0) {
      _playbackTimer = Timer(const Duration(milliseconds: 50), _drainPlayback);
    } else {
      _isPlaying = false;
    }
  }

  void _startDrainLoop() {
    _drainTimer?.cancel();
    _drainTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      if (_ringBuffer.availableBytes > 0 && !_isPlaying) {
        _schedulePlayback();
      }
    });
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  String _generateSessionId() {
    final bytes = List<int>.generate(16, (_) => Random().nextInt(256));
    return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  }

  void _setState(String state) {
    _stateController.add(ConnectionStateChanged(state));
  }
}

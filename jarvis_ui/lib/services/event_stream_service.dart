import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';

/// Wire-format event emitted by the HUD WebSocket server.
///
/// Mirrors the backend `WSMessage` envelope:
/// ```json
/// {
///   "id": "uuid",
///   "timestamp": "2026-08-31T13:00:00Z",
///   "type": "STATUS",
///   "payload": { ... }
/// }
/// ```
class HudEvent {
  final String id;
  final DateTime timestamp;
  final String type;
  final Map<String, dynamic> payload;

  HudEvent({
    required this.id,
    required this.timestamp,
    required this.type,
    required this.payload,
  });

  factory HudEvent.fromJson(Map<String, dynamic> json) {
    return HudEvent(
      id: json['id'] as String? ?? '',
      timestamp: json['timestamp'] != null
          ? DateTime.tryParse(json['timestamp'] as String) ?? DateTime.now()
          : DateTime.now(),
      type: json['type'] as String? ?? 'UNKNOWN',
      payload: Map<String, dynamic>.from(json['payload'] as Map? ?? {}),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'timestamp': timestamp.toIso8601String(),
        'type': type,
        'payload': payload,
      };

  @override
  String toString() => 'HudEvent(type: $type, payload: $payload)';
}

/// Typed skill execution event extracted from [HudEvent.payload].
class SkillExecutionEvent extends HudEvent {
  final String skillId;
  final String sessionId;
  final String status; // started | completed | failed
  final double durationMs;
  final String? error;

  SkillExecutionEvent({
    required this.skillId,
    required this.sessionId,
    required this.status,
    required this.durationMs,
    this.error,
    required super.id,
    required super.timestamp,
    required super.type,
    required super.payload,
  });

  factory SkillExecutionEvent.fromPayload(Map<String, dynamic> payload) {
    return SkillExecutionEvent(
      skillId: payload['skill_id'] as String? ?? 'unknown',
      sessionId: payload['session_id'] as String? ?? '',
      status: payload['status'] as String? ?? 'completed',
      durationMs: (payload['duration_ms'] as num?)?.toDouble() ?? 0.0,
      error: payload['error'] as String?,
      id: payload['id']?.toString() ?? '',
      timestamp: payload['timestamp'] != null
          ? DateTime.tryParse(payload['timestamp'] as String) ?? DateTime.now()
          : DateTime.now(),
      type: 'SKILL_EXECUTION',
      payload: payload,
    );
  }
}

/// Typed vault update event extracted from [HudEvent.payload].
class VaultUpdateEvent extends HudEvent {
  final String path;
  final String noteId;
  final List<String> linksAdded;

  VaultUpdateEvent({
    required this.path,
    required this.noteId,
    required this.linksAdded,
    required super.id,
    required super.timestamp,
    required super.type,
    required super.payload,
  });

  factory VaultUpdateEvent.fromPayload(Map<String, dynamic> payload) {
    return VaultUpdateEvent(
      path: payload['path'] as String? ?? '',
      noteId: payload['note_id'] as String? ?? '',
      linksAdded: (payload['links_added'] as List?)?.cast<String>() ?? const [],
      id: payload['id']?.toString() ?? '',
      timestamp: payload['timestamp'] != null
          ? DateTime.tryParse(payload['timestamp'] as String) ?? DateTime.now()
          : DateTime.now(),
      type: 'VAULT_UPDATE',
      payload: payload,
    );
  }
}

// ============================================================================
// Event Stream Service
// ============================================================================

class EventStreamService {
  final String host;
  final int port;
  final String path;
  final String token;

  WebSocket? _ws;
  final _eventController = StreamController<HudEvent>.broadcast();
  final _stateController = StreamController<String>.broadcast();

  // Reconnection state
  int _reconnectAttempt = 0;
  static const int _maxReconnectAttempts = 10;
  static const double _backoffBase = 1.0; // seconds
  static const double _backoffMax = 30.0; // seconds
  static const double _jitter = 0.5;
  Timer? _reconnectTimer;
  bool _manuallyClosed = false;

  EventStreamService({
    this.host = '127.0.0.1',
    this.port = 8083,
    this.path = '/voice',
    this.token = '',
  });

  // ------------------------------------------------------------------
  // Public getters
  // ------------------------------------------------------------------

  Stream<HudEvent> get onEvent => _eventController.stream;
  Stream<String> get onStateChange => _stateController.stream;
  bool get isConnected => _ws != null;

  // ------------------------------------------------------------------
  // Connection
  // ------------------------------------------------------------------

  Future<void> connect() async {
    _manuallyClosed = false;
    _setState('connecting');

    final wsUrl = Uri.parse('ws://$host:$port$path');
    debugPrint('EventStreamService: connecting to $wsUrl');

    try {
      _ws = await WebSocket.connect(
        wsUrl.toString(),
        headers: token.isNotEmpty ? {'Authorization': 'Bearer $token'} : {},
      );

      _reconnectAttempt = 0;
      _setState('connected');
      _listen();
    } on WebSocketException catch (e) {
      debugPrint('EventStreamService: WebSocket error: $e');
      _setState('error');
      _scheduleReconnect();
      rethrow;
    } catch (e) {
      debugPrint('EventStreamService: connection error: $e');
      _setState('error');
      _scheduleReconnect();
      rethrow;
    }
  }

  void _listen() {
    if (_ws == null) return;

    _ws!.listen(
      (data) async {
        if (data is String) {
          try {
            final json = jsonDecode(data) as Map<String, dynamic>;
            final event = HudEvent.fromJson(json);
            _eventController.add(event);
          } on FormatException catch (e) {
            debugPrint('EventStreamService: JSON parse error: $e');
          }
        }
      },
      onError: (error) {
        debugPrint('EventStreamService: stream error: $error');
        _setState('error');
        if (!_manuallyClosed) {
          _scheduleReconnect();
        }
      },
      onDone: () {
        debugPrint('EventStreamService: stream closed');
        _setState('disconnected');
        if (!_manuallyClosed) {
          _scheduleReconnect();
        }
      },
      cancelOnError: false,
    );
  }

  // ------------------------------------------------------------------
  // Close
  // ------------------------------------------------------------------

  Future<void> close({String reason = 'client_disconnect'}) async {
    _manuallyClosed = true;
    _reconnectTimer?.cancel();

    if (_ws != null) {
      try {
        await _ws!.close();
      } catch (e) {
        debugPrint('EventStreamService: close error: $e');
      }
      _ws = null;
    }

    _setState('disconnected');
    await _eventController.close();
    await _stateController.close();
  }

  // ------------------------------------------------------------------
  // Reconnection
  // ------------------------------------------------------------------

  void _scheduleReconnect() {
    if (_manuallyClosed) return;
    if (_reconnectAttempt >= _maxReconnectAttempts) {
      debugPrint('EventStreamService: max reconnection attempts reached');
      _setState('error');
      return;
    }

    _reconnectAttempt++;
    final baseDelay = _backoffBase * pow(2, _reconnectAttempt - 1);
    final jitter = baseDelay * _jitter * (Random().nextDouble() * 2 - 1);
    final delay = min(baseDelay + jitter, _backoffMax);

    debugPrint('EventStreamService: reconnecting in ${delay.toStringAsFixed(1)}s (attempt $_reconnectAttempt)');
    _setState('reconnecting');

    _reconnectTimer = Timer(Duration(milliseconds: (delay * 1000).round()), () async {
      try {
        await connect();
        debugPrint('EventStreamService: reconnected successfully');
      } catch (e) {
        debugPrint('EventStreamService: reconnection failed: $e');
        _scheduleReconnect();
      }
    });
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  void _setState(String state) {
    _stateController.add(state);
  }
}

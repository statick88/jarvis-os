import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:jarvis_ui/providers/jarvis_providers.dart';
import 'package:jarvis_ui/services/event_stream_service.dart';

enum HudConnectionState { connecting, connected, disconnected, error }

class HudState {
  final HudConnectionState connectionState;
  final List<HudEvent> events;
  final String? currentSkillId;
  final String? skillStatus;
  final bool isListening;
  final String? vaultPath;
  final String? activeNoteId;
  final String? error;

  HudState({
    this.connectionState = HudConnectionState.disconnected,
    this.events = const [],
    this.currentSkillId,
    this.skillStatus,
    this.isListening = false,
    this.vaultPath,
    this.activeNoteId,
    this.error,
  });

  HudState copyWith({
    HudConnectionState? connectionState,
    List<HudEvent>? events,
    String? currentSkillId,
    String? skillStatus,
    bool? isListening,
    String? vaultPath,
    String? activeNoteId,
    String? error,
  }) {
    return HudState(
      connectionState: connectionState ?? this.connectionState,
      events: events ?? this.events,
      currentSkillId: currentSkillId ?? this.currentSkillId,
      skillStatus: skillStatus ?? this.skillStatus,
      isListening: isListening ?? this.isListening,
      vaultPath: vaultPath ?? this.vaultPath,
      activeNoteId: activeNoteId ?? this.activeNoteId,
      error: error ?? this.error,
    );
  }
}

class HudEventNotifier extends StateNotifier<HudState> {
  StreamSubscription? _wsSubscription;
  final EventStreamService eventStreamService;

  HudEventNotifier(this.eventStreamService) : super(HudState()) {
    _connect();
  }

  Future<void> _connect() async {
    try {
      state = state.copyWith(
        connectionState: HudConnectionState.connecting,
        error: null,
      );

      await eventStreamService.connect();

      _wsSubscription = eventStreamService.onEvent.listen(
        (event) => _handleEvent(event),
        onError: (error) {
          state = state.copyWith(
            connectionState: HudConnectionState.error,
            error: error.toString(),
          );
        },
        onDone: () {
          state = state.copyWith(
            connectionState: HudConnectionState.disconnected,
          );
        },
      );

      state = state.copyWith(
        connectionState: HudConnectionState.connected,
      );
    } catch (e) {
      state = state.copyWith(
        connectionState: HudConnectionState.error,
        error: e.toString(),
      );
    }
  }

  void _handleEvent(HudEvent event) {
    state = state.copyWith(
      events: [event, ...state.events],
      currentSkillId: event is SkillExecutionEvent ? event.skillId : state.currentSkillId,
      skillStatus: event is SkillExecutionEvent ? event.status : state.skillStatus,
      isListening: event.payload['is_listening'] as bool? ?? state.isListening,
      vaultPath: event.payload['vault_path']?.toString() ?? state.vaultPath,
      activeNoteId: event.payload['note_id']?.toString() ?? state.activeNoteId,
    );
  }

  void reconnect() {
    _wsSubscription?.cancel();
    _connect();
  }

  void clearError() {
    state = state.copyWith(error: null);
  }

  @override
  void dispose() {
    _wsSubscription?.cancel();
    super.dispose();
  }
}

final hudEventProvider = StateNotifierProvider<HudEventNotifier, HudState>((ref) {
  final eventStreamService = ref.watch(eventStreamServiceProvider);
  return HudEventNotifier(eventStreamService);
});

final hudConnectionStateProvider = Provider<HudConnectionState>((ref) {
  return ref.watch(hudEventProvider).connectionState;
});

final currentSkillExecutionProvider = Provider<String?>((ref) {
  return ref.watch(hudEventProvider).currentSkillId;
});

final vaultUpdateProvider = Provider<VaultUpdateEvent?>((ref) {
  final events = ref.watch(hudEventProvider).events;
  return events.whereType<VaultUpdateEvent>().firstOrNull;
});

final recentHudEventsProvider = Provider<List<HudEvent>>((ref) {
  return ref.watch(hudEventProvider).events.take(20).toList();
});

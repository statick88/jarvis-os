import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:jarvis_ui/services/jarvis_api_service.dart';
import 'package:jarvis_ui/services/audio_voice_service.dart';
import 'package:jarvis_ui/services/event_stream_service.dart';

final jarvisApiServiceProvider = Provider<JarvisApiService>((ref) {
  return JarvisApiService();
});

final audioVoiceServiceProvider = Provider<AudioVoiceService>((ref) {
  return AudioVoiceService();
});

final eventStreamServiceProvider = Provider<EventStreamService>((ref) {
  return EventStreamService();
});

final orchestratorHealthProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  return ref.watch(jarvisApiServiceProvider).getOrchestratorHealth();
});

final voiceHealthProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  return ref.watch(jarvisApiServiceProvider).getVoiceHealth();
});

final flociHealthProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  return ref.watch(jarvisApiServiceProvider).getFlociHealth();
});

final chatMessagesProvider = StateProvider<List<Map<String, dynamic>>>((ref) => const []);

final isRecordingProvider = StateProvider<bool>((ref) => false);

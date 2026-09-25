import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:dio/dio.dart';
import 'package:record/record.dart';
import 'package:audioplayers/audioplayers.dart';

class AudioVoiceService {
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  final Dio _dio = Dio();

  String _resolveHost() => Platform.isAndroid ? 'http://10.0.2.2' : 'http://127.0.0.1';

  Future<void> startRecording() async {
    if (await _recorder.hasPermission()) {
      await _recorder.start(
        const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 22050, numChannels: 1),
        path: 'jarvis_recording.wav',
      );
    }
  }

  Future<String?> stopRecording() async {
    return await _recorder.stop();
  }

  Future<String> transcribe(File audioFile) async {
    try {
      final formData = FormData.fromMap({
        'file': await MultipartFile.fromFile(audioFile.path, filename: 'input.wav'),
      });
      final response = await _dio.post('${_resolveHost()}:8080/stt', data: formData);
      return response.data['text'] ?? '';
    } catch (e) {
      return 'Error STT: $e';
    }
  }

  Future<void> speak(String text) async {
    try {
      final response = await _dio.post('${_resolveHost()}:8080/tts', data: {'text': text});
      final bytes = Uint8List.fromList(response.data['audio'] ?? []);
      if (bytes.isNotEmpty) {
        await _player.play(BytesSource(bytes));
      }
    } catch (e) {
      debugPrint('TTS error: $e');
    }
  }
}

import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:jarvis_ui/providers/jarvis_providers.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  Future<void> _sendMessage(WidgetRef ref, String text) async {
    if (text.trim().isEmpty) return;
    final messages = ref.read(chatMessagesProvider.notifier);
    messages.state = [...messages.state, {'role': 'user', 'content': text}];
    final api = ref.read(jarvisApiServiceProvider);
    final response = await api.postCommand(text);
    final reply = response['response'] ?? response['message'] ?? 'Sin respuesta';
    messages.state = [...messages.state, {'role': 'assistant', 'content': reply.toString()}];
  }

  Future<void> _toggleRecording(WidgetRef ref) async {
    final audio = ref.read(audioVoiceServiceProvider);
    final recording = ref.read(isRecordingProvider.notifier);
    if (recording.state) {
      final path = await audio.stopRecording();
      if (path != null) {
        final file = File(path);
        final text = await audio.transcribe(file);
        if (text.isNotEmpty) {
          await _sendMessage(ref, text);
        }
      }
      recording.state = false;
    } else {
      await audio.startRecording();
      recording.state = true;
    }
  }

  Widget _buildHealthPill(String label, AsyncValue<Map<String, dynamic>> health, Color defaultColor) {
    final color = health.valueOrNull?['status'] == 'ok' ? Colors.green : Colors.red;
    return _StatusPill(label: label, color: color);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final messages = ref.watch(chatMessagesProvider);
    final isRecording = ref.watch(isRecordingProvider);
    final orchestratorHealth = ref.watch(orchestratorHealthProvider);
    final voiceHealth = ref.watch(voiceHealthProvider);
    final flociHealth = ref.watch(flociHealthProvider);
    final controller = TextEditingController();

    return Scaffold(
      appBar: AppBar(title: const Text('Jarvis OS'), backgroundColor: Theme.of(context).colorScheme.inversePrimary),
      body: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            child: Row(
              children: [
                _buildHealthPill('Orchestrator', orchestratorHealth, Colors.green),
                const SizedBox(width: 8),
                _buildHealthPill('Voice', voiceHealth, Colors.blue),
                const SizedBox(width: 8),
                _buildHealthPill('Floci', flociHealth, Colors.orange),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: messages.length,
              itemBuilder: (context, index) {
                final msg = messages[index];
                final isUser = msg['role'] == 'user';
                return Align(
                  alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                  child: Container(
                    margin: const EdgeInsets.symmetric(vertical: 6),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: isUser ? Theme.of(context).colorScheme.primaryContainer : Theme.of(context).colorScheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: isUser ? Text(msg['content']) : MarkdownBody(data: msg['content']),
                  ),
                );
              },
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: controller,
                    decoration: const InputDecoration(hintText: 'Escribe un comando...'),
                    onSubmitted: (value) async {
                      await _sendMessage(ref, value);
                      controller.clear();
                    },
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(onPressed: () async => await _sendMessage(ref, controller.text), icon: const Icon(Icons.send)),
                const SizedBox(width: 8),
                AnimatedScale(
                  scale: isRecording ? 1.2 : 1.0,
                  duration: const Duration(milliseconds: 150),
                  child: IconButton(
                    onPressed: () => _toggleRecording(ref),
                    icon: Icon(isRecording ? Icons.mic : Icons.mic_none, color: isRecording ? Colors.red : null),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  final String label;
  final Color color;
  const _StatusPill({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.2), borderRadius: BorderRadius.circular(20), border: Border.all(color: color)),
      child: Text(label, style: TextStyle(color: color, fontSize: 12)),
    );
  }
}

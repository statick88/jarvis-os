import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:jarvis_ui/providers/jarvis_providers.dart';
import 'package:jarvis_ui/providers/hud_event_providers.dart';

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

  Widget _buildHudVoiceVitalSigns(WidgetRef ref, BuildContext context) {
    final connectionState = ref.watch(hudConnectionStateProvider);
    final currentSkillId = ref.watch(currentSkillExecutionProvider);
    final hudState = ref.watch(hudEventProvider);
    final isRecording = ref.watch(isRecordingProvider);

    final isConnected = connectionState == HudConnectionState.connected;
    final isProcessing = currentSkillId != null && hudState.skillStatus != 'completed';

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: isProcessing ? Colors.orange : Colors.transparent),
      ),
      child: Row(
        children: [
          // Connection status dot
          _AnimatedDot(
            color: isConnected ? Colors.green : Colors.red,
            pulse: isProcessing,
          ),
          const SizedBox(width: 12),
          // Skill execution status
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isProcessing
                      ? 'Ejecutando: $currentSkillId'
                      : isConnected
                          ? 'Sistema listo'
                          : 'Desconectado',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                        color: isProcessing ? Colors.orange : null,
                      ),
                ),
                if (isProcessing && hudState.skillStatus != null)
                  Text(
                    '${hudState.skillStatus}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
            ),
          ),
          // Mic indicator
          if (isRecording)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.red.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Row(
                children: [
                  Icon(Icons.mic, size: 16, color: Colors.red),
                  SizedBox(width: 4),
                  Text('REC', style: TextStyle(color: Colors.red, fontSize: 12)),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildObsidianLiveMemoryLog(WidgetRef ref, BuildContext context) {
    final vaultUpdate = ref.watch(vaultUpdateProvider);
    final recentEvents = ref.watch(recentHudEventsProvider);

    final latestVault = vaultUpdate;
    final recentSkills = recentEvents
        .where((e) => e.type == 'STATUS' && e.payload['skill_id'] != null)
        .take(5)
        .toList();

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.memory, size: 18, color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 8),
              Text(
                'Obsidian Live Memory Log',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (latestVault != null)
            _VaultEntry(
              path: latestVault.path,
              noteId: latestVault.noteId,
              linksAdded: latestVault.linksAdded,
            ),
          const SizedBox(height: 8),
          if (recentSkills.isNotEmpty)
            ...recentSkills.map((event) {
              final payload = event.payload;
              return Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    const Icon(Icons.play_arrow, size: 14, color: Colors.grey),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        '${payload['skill_id'] ?? 'unknown'} — ${payload['status'] ?? 'done'}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              );
            }),
        ],
      ),
    );
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
          _buildHudVoiceVitalSigns(ref, context),
          _buildObsidianLiveMemoryLog(ref, context),
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

class _AnimatedDot extends StatefulWidget {
  final Color color;
  final bool pulse;
  const _AnimatedDot({required this.color, required this.pulse});

  @override
  State<_AnimatedDot> createState() => _AnimatedDotState();
}

class _AnimatedDotState extends State<_AnimatedDot> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 800),
      vsync: this,
    );
    _animation = Tween<double>(begin: 0.6, end: 1.0).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
    if (widget.pulse) {
      _controller.repeat(reverse: true);
    }
  }

  @override
  void didUpdateWidget(covariant _AnimatedDot oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.pulse && !_controller.isAnimating) {
      _controller.repeat(reverse: true);
    } else if (!widget.pulse && _controller.isAnimating) {
      _controller.stop();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, child) {
        return Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            color: widget.color.withValues(alpha: _animation.value),
            shape: BoxShape.circle,
          ),
        );
      },
    );
  }
}

class _VaultEntry extends StatelessWidget {
  final String path;
  final String noteId;
  final List<String> linksAdded;

  const _VaultEntry({
    required this.path,
    required this.noteId,
    required this.linksAdded,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primaryContainer.withValues(alpha: 0.3),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            path.split('/').last,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontFamily: 'monospace',
                ),
          ),
          const SizedBox(height: 2),
          Text(
            '→ $noteId',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (linksAdded.isNotEmpty)
            Text(
              'Links: ${linksAdded.join(', ')}',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.primary,
                  ),
            ),
        ],
      ),
    );
  }
}

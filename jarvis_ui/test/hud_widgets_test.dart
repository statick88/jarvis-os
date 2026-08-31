import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:jarvis_ui/main.dart';
import 'package:jarvis_ui/providers/jarvis_providers.dart';
import 'package:jarvis_ui/providers/hud_event_providers.dart';
import 'package:jarvis_ui/services/event_stream_service.dart';

class MockEventStreamService extends EventStreamService {
  @override
  Future<void> connect() async {
    // No-op for tests - don't actually connect to WebSocket
  }

  @override
  Future<void> close({String reason = 'client_disconnect'}) async {
    // No-op for tests
  }
}

void main() {
  group('HudEvent model', () {
    test('parses STATUS payload with skill execution', () {
      final json = {
        'id': 'test-1',
        'timestamp': '2026-08-31T13:00:00Z',
        'type': 'STATUS',
        'payload': {
          'status': 'PROCESSING',
          'summary': 'Ejecutando skill.obsidian',
          'skill_id': 'skill.obsidian',
          'session_id': 'sess-1',
        },
      };

      final event = HudEvent.fromJson(json);

      expect(event.id, 'test-1');
      expect(event.type, 'STATUS');
      expect(event.payload['skill_id'], 'skill.obsidian');
    });

    test('parses STATUS payload with vault update', () {
      final json = {
        'id': 'test-2',
        'timestamp': '2026-08-31T13:00:00Z',
        'type': 'STATUS',
        'payload': {
          'status': 'IDLE',
          'summary': 'Vault actualizado',
          'path': 'vault/outputs/2026-08-31/skill-obsidian-131200.md',
          'note_id': 'skill-obsidian-131200',
          'links_added': ['wiki/skill-os-control.md'],
        },
      };

      final event = HudEvent.fromJson(json);

      expect(event.payload['path'], contains('outputs'));
      expect(event.payload['note_id'], 'skill-obsidian-131200');
    });
  });

  group('SkillExecutionEvent', () {
    test('extracts typed fields from payload', () {
      final payload = {
        'skill_id': 'skill.test',
        'session_id': 'sess-42',
        'status': 'completed',
        'duration_ms': 1234.5,
      };

      final event = SkillExecutionEvent.fromPayload(payload);

      expect(event.skillId, 'skill.test');
      expect(event.sessionId, 'sess-42');
      expect(event.status, 'completed');
      expect(event.durationMs, 1234.5);
    });
  });

  group('VaultUpdateEvent', () {
    test('extracts typed fields from payload', () {
      final payload = {
        'path': 'outputs/2026-08-31/out.md',
        'note_id': 'out-131200',
        'links_added': ['wiki/note-a.md', 'wiki/note-b.md'],
      };

      final event = VaultUpdateEvent.fromPayload(payload);

      expect(event.path, 'outputs/2026-08-31/out.md');
      expect(event.noteId, 'out-131200');
      expect(event.linksAdded.length, 2);
    });
  });

  group('HUD widgets', () {
    testWidgets('HomeScreen renders HUD voice vital signs', (WidgetTester tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            eventStreamServiceProvider.overrideWith((ref) => MockEventStreamService()),
            orchestratorHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
            voiceHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
            flociHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
            hudConnectionStateProvider.overrideWith((ref) => HudConnectionState.connected),
            currentSkillExecutionProvider.overrideWith((ref) => 'skill.test'),
          ],
          child: const JarvisApp(),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Ejecutando: skill.test'), findsOneWidget);
      expect(find.text('Sistema listo'), findsNothing);
    });

    testWidgets('HomeScreen renders Obsidian Live Memory Log', (WidgetTester tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            eventStreamServiceProvider.overrideWith((ref) => MockEventStreamService()),
            orchestratorHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
            voiceHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
            flociHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
            vaultUpdateProvider.overrideWith((ref) => VaultUpdateEvent(
              noteId: 'skill-test-131200',
              linksAdded: const ['wiki/skill-test'],
              path: 'outputs/2026-08-31/skill-test-131200.md',
              id: 'test-vault-1',
              timestamp: DateTime.parse('2026-08-31T13:00:00Z'),
              type: 'VAULT_UPDATE',
              payload: const {'vault_path': 'outputs/2026-08-31/skill-test-131200.md'},
            )),
          ],
          child: const JarvisApp(),
        ),
      );

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Obsidian Live Memory Log'), findsOneWidget);
      expect(find.text('skill-test-131200.md'), findsOneWidget);
    });
  });
}

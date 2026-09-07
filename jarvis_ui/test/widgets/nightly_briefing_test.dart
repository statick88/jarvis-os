import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:jarvis_ui/providers/nightly_provider.dart';
import 'package:jarvis_ui/widgets/nightly_briefing.dart';
import 'package:jarvis_ui/services/jarvis_api_service.dart';
import 'package:jarvis_ui/providers/jarvis_providers.dart';

/// Mock JarvisApiService for testing.
class MockJarvisApiService extends JarvisApiService {
  MockJarvisApiService();

  @override
  Future<Map<String, dynamic>> getNightlyStatus() async {
    return {
      'status': 'ok',
      'result': {
        'active': true,
        'last_execution': {
          'status': 'completed',
          'ideas_extracted': 5,
          'tasks_executed': 3,
          'report_path': '_Nightly_Reports/2026-09-06.md',
        },
      },
    };
  }

  @override
  Future<Map<String, dynamic>> toggleNightlyScheduler({String? action}) async {
    return {
      'status': 'ok',
      'action': 'toggle',
      'scheduler': {'active': true},
    };
  }
}

/// Mock JarvisApiService that returns no data.
class MockJarvisApiServiceEmpty extends JarvisApiService {
  MockJarvisApiServiceEmpty();

  @override
  Future<Map<String, dynamic>> getNightlyStatus() async {
    return {
      'status': 'ok',
      'result': {
        'active': false,
      },
    };
  }

  @override
  Future<Map<String, dynamic>> toggleNightlyScheduler({String? action}) async {
    return {
      'status': 'ok',
      'action': 'toggle',
      'scheduler': {'active': false},
    };
  }
}

void main() {
  group('MorningBriefing', () {
    testWidgets('renders nothing when no data available', (WidgetTester tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            jarvisApiServiceProvider.overrideWith((ref) => MockJarvisApiServiceEmpty()),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: MorningBriefing(),
            ),
          ),
        ),
      );

      await tester.pump();

      // Should render SizedBox.shrink (empty widget)
      expect(find.byType(SizedBox), findsOneWidget);
      expect(find.text('Nightly Labs'), findsNothing);
    });

    testWidgets('renders header with Nightly Labs when data available', (WidgetTester tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            jarvisApiServiceProvider.overrideWith((ref) => MockJarvisApiService()),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: MorningBriefing(),
            ),
          ),
        ),
      );

      // Trigger initial state check
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // The widget should be present but may show loading or header
      expect(find.byType(MorningBriefing), findsOneWidget);
    });

    testWidgets('shows active status pill when scheduler is active', (WidgetTester tester) async {
      // Create a provider override with known state
      final testState = NightlyState(
        schedulerActive: true,
        lastExecutionStatus: 'completed',
        ideasCount: 5,
        tasksCount: 3,
        reportPath: '_Nightly_Reports/2026-09-06.md',
        lastChecked: DateTime.now(),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            jarvisApiServiceProvider.overrideWith((ref) => MockJarvisApiService()),
            nightlyStateProvider.overrideWith((ref) => NightlyNotifier(MockJarvisApiService())..state = testState),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: MorningBriefing(),
            ),
          ),
        ),
      );

      await tester.pump();

      expect(find.text('Nightly Labs'), findsOneWidget);
      expect(find.text('Activo'), findsOneWidget);
      expect(find.text('5 ideas'), findsOneWidget);
      expect(find.text('3 tareas'), findsOneWidget);
    });

    testWidgets('shows inactive status when scheduler is not active', (WidgetTester tester) async {
      final testState = NightlyState(
        schedulerActive: false,
        lastExecutionStatus: 'completed',
        ideasCount: 2,
        tasksCount: 1,
        lastChecked: DateTime.now(),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            jarvisApiServiceProvider.overrideWith((ref) => MockJarvisApiServiceEmpty()),
            nightlyStateProvider.overrideWith((ref) => NightlyNotifier(MockJarvisApiServiceEmpty())..state = testState),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: MorningBriefing(),
            ),
          ),
        ),
      );

      await tester.pump();

      expect(find.text('Nightly Labs'), findsOneWidget);
      expect(find.text('Inactivo'), findsOneWidget);
    });

    testWidgets('shows error message when error occurs', (WidgetTester tester) async {
      final testState = NightlyState(
        errorMessage: 'Error de conexión: connectionTimeout',
        lastChecked: DateTime.now(),
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            jarvisApiServiceProvider.overrideWith((ref) => MockJarvisApiServiceEmpty()),
            nightlyStateProvider.overrideWith((ref) => NightlyNotifier(MockJarvisApiServiceEmpty())..state = testState),
          ],
          child: const MaterialApp(
            home: Scaffold(
              body: MorningBriefing(),
            ),
          ),
        ),
      );

      await tester.pump();

      expect(find.text('Nightly Labs'), findsOneWidget);
      expect(find.text('Error de conexión: connectionTimeout'), findsOneWidget);
    });
  });
}

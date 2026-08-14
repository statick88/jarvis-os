import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:jarvis_ui/main.dart';
import 'package:jarvis_ui/providers/jarvis_providers.dart';

void main() {
  testWidgets('Jarvis UI smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          orchestratorHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
          voiceHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
          flociHealthProvider.overrideWith((ref) => Future.value({'status': 'ok'})),
        ],
        child: const JarvisApp(),
      ),
    );

    expect(find.text('Jarvis OS'), findsOneWidget);
  });
}

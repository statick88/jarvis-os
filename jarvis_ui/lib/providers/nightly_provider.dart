import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:jarvis_ui/providers/jarvis_providers.dart';
import 'package:jarvis_ui/services/jarvis_api_service.dart';

/// Estado del sistema nightly labs.
class NightlyState {
  final bool schedulerActive;
  final String? lastExecutionStatus;
  final int ideasCount;
  final int tasksCount;
  final String? reportPath;
  final String? errorMessage;
  final DateTime? lastChecked;

  const NightlyState({
    this.schedulerActive = false,
    this.lastExecutionStatus,
    this.ideasCount = 0,
    this.tasksCount = 0,
    this.reportPath,
    this.errorMessage,
    this.lastChecked,
  });

  NightlyState copyWith({
    bool? schedulerActive,
    String? lastExecutionStatus,
    int? ideasCount,
    int? tasksCount,
    String? reportPath,
    String? errorMessage,
    DateTime? lastChecked,
  }) {
    return NightlyState(
      schedulerActive: schedulerActive ?? this.schedulerActive,
      lastExecutionStatus: lastExecutionStatus ?? this.lastExecutionStatus,
      ideasCount: ideasCount ?? this.ideasCount,
      tasksCount: tasksCount ?? this.tasksCount,
      reportPath: reportPath ?? this.reportPath,
      errorMessage: errorMessage,
      lastChecked: lastChecked ?? this.lastChecked,
    );
  }
}

/// Notifier para el estado nightly, consulta el backend periódicamente.
class NightlyNotifier extends StateNotifier<NightlyState> {
  final JarvisApiService _api;

  NightlyNotifier(this._api) : super(const NightlyState());

  /// Consulta el endpoint /v1/nightly/scheduler/status del backend.
  Future<void> refresh() async {
    try {
      final data = await _api.getNightlyStatus();
      final result = data['result'] as Map<String, dynamic>? ?? {};
      final schedulerActive = result['active'] as bool? ?? false;
      final lastExecution = result['last_execution'] as Map<String, dynamic>?;

      String? lastStatus;
      int ideas = 0;
      int tasks = 0;
      String? report;

      if (lastExecution != null) {
        lastStatus = lastExecution['status'] as String?;
        ideas = lastExecution['ideas_extracted'] as int? ?? 0;
        tasks = lastExecution['tasks_executed'] as int? ?? 0;
        report = lastExecution['report_path'] as String?;
      }

      state = NightlyState(
        schedulerActive: schedulerActive,
        lastExecutionStatus: lastStatus,
        ideasCount: ideas,
        tasksCount: tasks,
        reportPath: report,
        lastChecked: DateTime.now(),
      );
    } on DioException catch (e) {
      state = state.copyWith(
        errorMessage: 'Error de conexión: ${e.type.name}',
        lastChecked: DateTime.now(),
      );
    } catch (e) {
      state = state.copyWith(
        errorMessage: e.toString(),
        lastChecked: DateTime.now(),
      );
    }
  }

  /// Activa o desactiva el scheduler nightly.
  Future<void> toggle() async {
    try {
      final data = await _api.toggleNightlyScheduler();
      final result = data['result'] as Map<String, dynamic>? ?? {};
      final active = result['active'] as bool? ?? false;
      state = state.copyWith(schedulerActive: active, errorMessage: null);
    } on DioException catch (e) {
      state = state.copyWith(errorMessage: 'Error al cambiar scheduler: ${e.type.name}');
    } catch (e) {
      state = state.copyWith(errorMessage: e.toString());
    }
  }
}

/// Provider principal del estado nightly.
final nightlyStateProvider = StateNotifierProvider<NightlyNotifier, NightlyState>((ref) {
  final api = ref.watch(jarvisApiServiceProvider);
  return NightlyNotifier(api);
});

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:jarvis_ui/providers/nightly_provider.dart';

/// Widget de Morning Briefing que muestra el resumen nightly en el HomeScreen.
///
/// Patrón: ConsumerWidget siguiendo la estructura de HomeScreen.
/// Muestra: estado de última ejecución, contador de ideas/tareas,
/// enlace directo al reporte diario.
class MorningBriefing extends ConsumerWidget {
  const MorningBriefing({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final nightly = ref.watch(nightlyStateProvider);

    // Si no hay datos aún, mostrar placeholder
    if (nightly.lastChecked == null && nightly.errorMessage == null) {
      return const SizedBox.shrink();
    }

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
          _buildHeader(context, nightly),
          const SizedBox(height: 8),
          _buildContent(context, nightly),
          if (nightly.errorMessage != null) _buildError(context, nightly),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context, NightlyState nightly) {
    final isActive = nightly.schedulerActive;
    final statusColor = isActive ? Colors.green : Colors.grey;

    return Row(
      children: [
        Icon(Icons.nightlight_round, size: 18, color: statusColor),
        const SizedBox(width: 8),
        Text(
          'Nightly Labs',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                fontWeight: FontWeight.w600,
              ),
        ),
        const Spacer(),
        _StatusPill(
          label: isActive ? 'Activo' : 'Inactivo',
          color: statusColor,
        ),
      ],
    );
  }

  Widget _buildContent(BuildContext context, NightlyState nightly) {
    if (nightly.lastExecutionStatus == null) {
      return Text(
        'Sin ejecuciones recientes',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Colors.grey,
            ),
      );
    }

    return Row(
      children: [
        _MetricChip(
          icon: Icons.lightbulb_outline,
          label: '${nightly.ideasCount} ideas',
        ),
        const SizedBox(width: 8),
        _MetricChip(
          icon: Icons.checklist,
          label: '${nightly.tasksCount} tareas',
        ),
        const Spacer(),
        if (nightly.reportPath != null)
          Icon(Icons.description, size: 16, color: Theme.of(context).colorScheme.primary),
      ],
    );
  }

  Widget _buildError(BuildContext context, NightlyState nightly) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Text(
        nightly.errorMessage!,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Colors.orange,
            ),
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
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.2),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 11),
      ),
    );
  }
}

class _MetricChip extends StatelessWidget {
  final IconData icon;
  final String label;
  const _MetricChip({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primaryContainer.withValues(alpha: 0.3),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 4),
          Text(
            label,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w500,
                ),
          ),
        ],
      ),
    );
  }
}

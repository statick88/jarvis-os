# Spec — Nightly Labs & Idle Worker

## Functional Requirements

### RF-NIGHT-01: Idle Scheduler
El sistema debe exponer un scheduler de tareas asíncronas configurables por
intervalo de tiempo. El scheduler debe:
- Ejecutarse en el intervalo 00:00-06:00 hora local.
- Aceptar definiciones de tarea con campo `priority` (low/medium/high).
- Aplicar throttling de recursos: CPU máximo 15%, RAM máxima 256MB por tarea.
- Garantizar que ninguna tarea nightly interrumpa sesiones de usuario activas.

### RF-NIGHT-02: Obsidian Vault Nightly Connector
El módulo nightly debe conectar con el Obsidian Vault y procesar notas
etiquetadas con `#idea`, `#todo` o `#research`. Debe:
- Escanear la raíz del vault en busca de notas con etiquetas nightly.
- Extraer el contenido y metadatos de cada nota etiquetada.
- Clasificar la nota por tipo (idea, todo, research) basado en la etiqueta.
- Pasar el contenido al motor de prompts para procesamiento autónomo.

### RF-NIGHT-03: LLM Prompt Engine (Local)
El motor de prompts debe ejecutar inferencia usando modelos LLM locales
disponibles en el entorno (llama.cpp / Ollama / Local Engines). Debe:
- Aceptar plantillas de prompt con variables dinámicas (nota, contexto, tipo).
- Ejecutar el modelo LLM localmente sin llamar a APIs externas.
- Manejar timeouts de ejecución (máximo 30 segundos por prompt).
- Degradado graceful: si el modelo local no está disponible, marcar como
  `skipped` y continuar con la siguiente tarea.

### RF-NIGHT-04: Automatic Nightly Report Generation
El sistema debe generar reportes automáticos en Obsidian bajo la ruta
`_Nightly_Reports/YYYY-MM-DD.md`. El reporte debe incluir:
- Fecha del reporte (formato YYYY-MM-DD).
- Lista de tareas ejecutadas con estado (completed/skipped/failed).
- Resumen de ideas extraídas de notas #idea.
- Lista de tareas pendientes (próximo #todo).
- Hallazgos de investigación (resumen de notas #research).
- Métricas de consumo de recursos (CPU/RAM promedio durante la noche).

### RF-NIGHT-05: REST Scheduler Control
El sistema debe exponer endpoints REST para controlar el scheduler nightly:
- `POST /v1/nightly/scheduler/toggle` — activar/desactivar el scheduler.
- `GET /v1/nightly/scheduler/status` — consultar estado actual (activo/inactivo, próxima ejecución).
- `GET /v1/nightly/reports` — listar reportes generados con metadatos.
- `GET /v1/nightly/reports/{date}` — obtener reporte específico por fecha.
- Patrón: `JSONResponse` consistente con shape `{"status": "success"|"error", "result": {...}}`.
- Seguridad: endpoints requieren autenticación existente del orchestrator.

### RF-NIGHT-06: Morning Briefing Widget
El sistema debe exponer un widget Flutter en el HomeScreen que muestre el resumen nightly:
- **Patrón**: Riverpod `ConsumerWidget` siguiendo la estructura de `HomeScreen`.
- **Estado**: `NightlyState` + `NightlyNotifier` en `nightly_provider.dart`.
- **Contenido**: Estado de la última ejecución,conteo de ideas/tareas procesadas, enlace directo al reporte diario.
- **Integración**: Agregado al header de HomeScreen mediante patrón `_build*`.
- **Ubicación**: `jarvis_ui/lib/widgets/nightly_briefing.dart`.

## Non-Functional Requirements

### RNF-NIGHT-01: Resource Throttling
Las tareas nightly nunca deben consumir más de:
- 15% de CPU promedio por ciclo de ejecución.
- 256MB de RAM máximo durante la ejecución.
- Si se exceden los límites, la tarea debe abortarse y registrarse como `failed`.

### RNF-NIGHT-02: Offline-First
Todo el procesamiento nightly debe funcionar 100% offline. No debe haber
dependencia de APIs externas, servicios en la nube o conectividad de red
durante la ejecución nightly. El único contacto con red es opcional para
sincronizar reportes por la mañana, pero la ejecución en sí es autónoma.

### RNF-NIGHT-03: User Session Protection
Las tareas nightly deben detectar sesiones de usuario activas y posponer o
modificar su ejecución para evitar interferencia. El scheduler debe ser
consciente del estado de actividad del usuario y no iniciar tareas intensivas
mientras el usuario está interactuando con el sistema.

### RNF-NIGHT-04: Idempotency
La ejecución nightly debe ser idempotente: ejecutar el mismo ciclo nightly
múltiples veces debe producir el mismo resultado sin efectos secundarios
negativos. Las notas ya procesadas deben identificarse y no repetirse.
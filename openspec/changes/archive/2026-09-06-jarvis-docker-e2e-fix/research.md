# Research: jarvis-docker-e2e-fix

## Problema

El test E2E (`scripts/test_jarvis_pipeline.sh`, 771 líneas) permanece bloqueado desde el ciclo `jarvis-nightly-labs` (tarea 4.5). El daemon Docker (Colima) no está ejecutándose, impidiendo la validación del pipeline completo.

## Evidencia

- **Colima**: Instalado, perfil `default`, arquitectura `aarch64`, 4 CPUs, 8GB RAM, 50GB disco. Estado: `Stopped`.
- **Docker context**: `colima *` (activa), endpoint `unix:///Users/statick/.colima/default/docker.sock`
- **Docker client**: v29.7.2, contexto `colima`
- **Error al ejecutar E2E**: `colima is not running` → Docker daemon no disponible → todos los tests fallan en prerequisite check
- **Script E2E**: `set -euo pipefail` + prerequisite check fail-hard (`command -v docker`)

## Análisis del Script E2E

El script tiene 12 tests en orden:

| # | Test | Requiere Docker |
|---|------|-----------------|
| 1 | Docker Compose Up & Health Checks | SÍ |
| 2 | Floci/LocalStack Resources | SÍ |
| 3A | STT/TTS Binaries | SÍ |
| 3 | Voice Pipeline API | SÍ |
| 3B | Skills API Coverage | SÍ |
| 3C | Path Traversal Rejection | SÍ |
| 3D | Operation Routing | SÍ |
| 4 | OpenCode Adapter Mock | No (mock Python) |
| 5 | Skill plan → Vault → SQS | Parcial (mock) |
| 6 | Skill tendencias → SQS | SÍ (verifica SQS real) |
| 7 | Vault Structure | SÍ (verifica desde contenedor) |
| 8 | Graceful Shutdown | SÍ |

**Conclusión**: 10 de 12 tests requieren Docker activo. Solo los tests 4 y 5 (mock) podrían ejecutarse sin Docker.

## Solución Propuesta

### Opción A: Wrapper script con auto-start de Colima (RECOMENDADA)

Crear un wrapper `scripts/e2e-wrapper.sh` que:
1. Verifique si Colima está corriendo
2. Si no, ejecute `colima start` automáticamente
3. Espere a que Docker daemon esté listo
4. Ejecute el test E2E original
5. Opcionalmente detenga Colima al finalizar

**Ventajas**: No modifica el script original, fail-safe, reusable.
**Desventajas**: Agrega un paso manual o de CI.

### Opción B: Modificar el script E2E para auto-start

Agregar al inicio de `test_jarvis_pipeline.sh`:
```bash
# Auto-start Colima if not running
if ! colima status >/dev/null 2>&1; then
    log_info "Colima no está ejecutándose. Iniciando..."
    colima start
    sleep 10
fi
```

**Ventajas**: Transparente, ejecución directa.
**Desventajas**: Modifica script existente, acoplamiento con Colima.

### Opción C: Modo `--check-only` para validación parcial

Agregar flag `--check-only` que ejecute solo los tests que NO requieren Docker:
- Test 4: OpenCode Adapter Mock
- Test 5: Skill plan → Vault → SQS (mock)

**Ventajas**: Permite validación parcial sin Docker.
**Desventajas**: Cobertura limitada.

## Recomendación

**Combinación de Opción A + C**:
1. Wrapper script con auto-start de Colima (Opción A)
2. Flag `--check-only` en el script original (Opción C)
3. Flag `--no-cleanup` para mantener contenedores tras test exitoso

## Archivos Afectados

- `scripts/test_jarvis_pipeline.sh` — Agregar flags `--check-only`, `--no-cleanup`
- `scripts/e2e-wrapper.sh` — Nuevo wrapper con auto-start Colima
- `openspec/specs/nightly/spec.md` — Actualizar para reflejar tests E2E habilitados

## Restricciones

- macOS Apple Silicon (M5) — Colima usa `aarch64`
- Docker Compose v2 (plugin `docker compose`)
- `jq`, `curl`, `uuidgen` requeridos como prerrequisitos
- Python 3 para mock server en tests 4/5

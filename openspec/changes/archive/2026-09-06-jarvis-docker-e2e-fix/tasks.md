# Tasks: jarvis-docker-e2e-fix

## T-01: Crear wrapper `scripts/e2e-wrapper.sh`
**Archivo**: `scripts/e2e-wrapper.sh` (nuevo)
**Descripción**: Script bash que detecta/-auto-inicia Colima y ejecuta test E2E.
**Pasos**:
1. Shebang + `set -euo pipefail`
2. Función `check_colima()`: ejecuta `colima status`, retorna 0 si running
3. Función `start_colima()`: ejecuta `colima start`, espera health
4. Función `wait_docker_ready()`: loop `docker info` cada 2s, max 60s
5. Main: parse args (`--keep-colima`), check/start Colima, exec test, cleanup
**Criterio**: `./scripts/e2e-wrapper.sh --verbose` ejecuta test completo tras auto-start

## T-02: Agregar flag --check-only a test_jarvis_pipeline.sh
**Archivo**: `scripts/test_jarvis_pipeline.sh`
**Descripción**: Flag que permite ejecutar solo tests mock sin Docker.
**Pasos**:
1. Agregar parse de `--check-only` en sección de argumentos
2. Setear `CHECK_ONLY=0` por defecto, `CHECK_ONLY=1` si flag presente
3. Envolver tests que requieren Docker en `if [ "$CHECK_ONLY" -eq 0 ]`
4. Tests 4 y 5 se ejecutan siempre (son mock)
**Criterio**: `./scripts/test_jarvis_pipeline.sh --check-only` pasa sin Docker

## T-03: Agregar flag --no-cleanup a test_jarvis_pipeline.sh
**Archivo**: `scripts/test_jarvis_pipeline.sh`
**Descripción**: Flag que preserva contenedores tras test.
**Pasos**:
1. Agregar parse de `--no-cleanup` en sección de argumentos
2. Setear `SKIP_CLEANUP=0` por defecto, `SKIP_CLEANUP=1` si flag presente
3. Envolver bloque de cleanup en `if [ "$SKIP_CLEANUP" -eq 0 ]`
**Criterio**: `./scripts/test_jarvis_pipeline.sh --no-cleanup` preserva contenedores

## T-04: Verificar comportamiento sin flags
**Archivo**: N/A
**Descripción**: Verificar que sin flags el comportamiento es idéntico al actual.
**Pasos**:
1. Ejecutar `./scripts/test_jarvis_pipeline.sh --help` (si existe) y verificar que no cambió
2. Ejecutar `./scripts/test_jarvis_pipeline.sh --verbose` y verificar que requiere Docker activo
**Criterio**: Sin flags, el script falla si Docker no está disponible (comportamiento actual)

## T-05: Test manual del wrapper
**Archivo**: N/A
**Descripción**: Ejecutar e2e-wrapper.sh y verificar que auto-inicia Colima.
**Pasos**:
1. Detener Colima si está corriendo (`colima stop`)
2. Ejecutar `./scripts/e2e-wrapper.sh --verbose`
3. Verificar que Colima se inicia y test pasa
**Criterio**: Test completo pasa con auto-start de Colima

# Spec: jarvis-docker-e2e-fix

## Requisitos Funcionales

### RF-E2E-01: Wrapper Script con Auto-Start Colima
**Criterio de aceptación**: `scripts/e2e-wrapper.sh` detecta Colima detenido, lo inicia automáticamente, espera health check de Docker, y ejecuta el test E2E original.

**Escenarios**:
1. **Happy path**: Colima corriendo → ejecuta test directamente
2. **Colima detenido**: inicia Colima → espera Docker ready → ejecuta test
3. **Colima falla al iniciar**: reporta error y sale con código != 0
4. **Docker daemon no responde tras start**: timeout tras 60s, error

**Entradas**: Argumentos pasados a `test_jarvis_pipeline.sh` (`--verbose`, `--cleanup`, etc.)
**Salidas**: Exit code del test E2E

### RF-E2E-02: Flag --check-only
**Criterio de aceptación**: `test_jarvis_pipeline.sh --check-only` ejecuta solo los tests mock (4 y 5) sin requerir Docker.

**Escenarios**:
1. **Con Docker**: ejecuta todos los tests (ignora --check-only)
2. **Sin Docker + --check-only**: ejecuta solo tests 4 y 5, pasa
3. **Sin Docker + sin flag**: falla con error descriptivo (comportamiento actual)

### RF-E2E-03: Flag --no-cleanup
**Criterio de aceptación**: `test_jarvis_pipeline.sh --no-cleanup` no ejecuta `docker compose down` al finalizar.

**Escenarios**:
1. **Test pasa + --no-cleanup**: contenedores permanecen ejecutándose
2. **Test falla + --no-cleanup**: contenedores permanecen ejecutándose
3. **Sin flag**: ejecuta cleanup (comportamiento actual)

### RF-E2E-04: Flag --keep-colima
**Criterio de aceptación**: `e2e-wrapper.sh --keep-colima` no detiene Colima al finalizar.

**Escenarios**:
1. **Con --keep-colima**: Colima permanece ejecutándose tras test
2. **Sin flag**: Colima permanece ejecutándose (wrapper no detiene Colima por defecto)

## Requisitos No Funcionales
- Compatible con macOS Apple Silicon (M5)
- Requiere: `colima`, `docker`, `docker compose`, `jq`, `curl`, `uuidgen`
- No rompe comportamiento existente sin flags
- Scripts en bash con `set -euo pipefail`

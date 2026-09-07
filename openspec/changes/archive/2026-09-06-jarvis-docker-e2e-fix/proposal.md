# Proposal: jarvis-docker-e2e-fix

## Problema
El test E2E (`scripts/test_jarvis_pipeline.sh`) permanece bloqueado desde `jarvis-nightly-labs` tarea 4.5. El daemon Docker (Colima) no está ejecutándose, impidiendo la validación del pipeline completo.

## Solución Propuesta

### Cambio 1: Wrapper script `scripts/e2e-wrapper.sh`
- Verifica si Colima está corriendo (`colima status`)
- Auto-inicia Colima si está detenido
- Espera a que Docker daemon esté listo (health check con `docker info`)
- Ejecuta `test_jarvis_pipeline.sh` con argumentos pasados
- Flag `--keep-colima` para no detener Colima al finalizar

### Cambio 2: Flags en `test_jarvis_pipeline.sh`
- `--check-only`: Ejecuta solo tests que NO requieren Docker (tests 4, 5)
- `--no-cleanup`: No ejecuta `docker compose down` al finalizar
- Sin flags: comportamiento actual (requiere Docker activo)

### Cambio 3: Auto-start en test script (opcional)
- Agregar bloque de auto-start de Colima al inicio del script
- Solo si `COLIMA_AUTO_START=1` está en `.env` o se pasa flag `--auto-start`

## Criterios de Éxito
1. `colima status` → running después de `e2e-wrapper.sh`
2. `e2e-wrapper.sh` ejecuta tests E2E exitosamente
3. `test_jarvis_pipeline.sh --check-only` pasa sin Docker
4. Tarea 4.5 de jarvis-nightly-labs se marca completa

## No incluye
- Modificación del docker-compose.yml
- Nuevos servicios Docker
- Cambios en la arquitectura de la app

## Estimación
- 2 archivos modificados, 1 archivo nuevo
- ~50 líneas de código nuevo
- Testing manual requerido

# Design: jarvis-docker-e2e-fix

## Arquitectura

```
scripts/
├── e2e-wrapper.sh          # Nuevo: wrapper con auto-start Colima
└── test_jarvis_pipeline.sh # Modificado: agregar flags --check-only, --no-cleanup
```

## Decisiones Técnicas

### D-01: Wrapper separado vs integración en script existente
**Decisión**: Wrapper separado (`e2e-wrapper.sh`)
**Razón**: Separación de responsabilidades. El wrapper maneja infraestructura (Colima), el test maneja lógica de validación. Permite reutilizar el wrapper para otros fines.

### D-02: Detección de Colima
**Decisión**: Usar `colima status` exit code (0=running, !=0=stopped)
**Razón**: Más confiable que parsear output. `colima status` retorna exit code 0 solo si está corriendo.

### D-03: Espera de Docker ready
**Decisión**: Loop con `docker info` cada 2s, máximo 60s
**Razón**: `docker info` es lightweight y confirma que el daemon responde. 60s es suficiente para Colima start en M5.

### D-04: --check-only ejecuta tests mock
**Decisión**: Flag en bash que setea variable `CHECK_ONLY=1`, luego en el script se saltan tests que requieren Docker
**Razón**: Implementación simple con variable de entorno. Los tests mock (4, 5) no dependen de Docker.

### D-05: --no-cleanup preserva contenedores
**Decisión**: Flag que setea `SKIP_CLEANUP=1`, se verifica antes de ejecutar `docker compose down`
**Razón**: Patrón consistente con otros scripts. Permite debugging post-test.

## Dependencias
- `colima` (ya instalado)
- `docker` (ya instalado, context colima)
- `docker compose` (plugin v2)
- `jq`, `curl`, `uuidgen` (prerrequisitos del test original)

## Testing
1. `./scripts/e2e-wrapper.sh --verbose` → Colima auto-start + test completo
2. `./scripts/test_jarvis_pipeline.sh --check-only` → solo tests 4, 5
3. `./scripts/test_jarvis_pipeline.sh --no-cleanup` → contenedores permanecen
4. Verificar que sin flags el comportamiento es idéntico al actual

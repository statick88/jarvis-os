# Contribuir

jarvis-os es un proyecto de Software Libre bajo la GPL v3.0. Agradecemos todas las contribuciones.

## Reportar issues

- Usa GitHub Issues para reportar bugs o solicitar features.
- Incluye pasos de reproducción, logs y entorno (macOS, Docker, etc.).

## Pull Requests

1. Haz fork del repositorio.
2. Crea una rama descriptiva: `git checkout -b feat/nueva-skill`.
3. Asegúrate de que `bash scripts/test_jarvis_pipeline.sh` pase en verde.
4. Envía el PR con una descripción clara del cambio.

## Estándares de código

- **Python**: `from __future__ import annotations`, tipado estricto, docstrings, logging.
- **Bash**: `set -euo pipefail`, funciones con nombres descriptivos.
- **YAML/Markdown**: frontmatter válido según `spec/contracts/skill_schema.yaml`.

## Pruebas

Antes de enviar un PR, ejecuta:

```bash
# Validación de imports Python
python3 -m py_compile jarvis_os/**/*.py

# Suite E2E
bash scripts/test_jarvis_pipeline.sh
```

## Código de conducta

Sé respetuoso y constructivo. Este proyecto sigue los principios de la comunidad de Software Libre.

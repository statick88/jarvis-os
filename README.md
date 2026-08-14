# jarvis-os

[![GPL v3.0](https://img.shields.io/badge/License-GPL%20v3.0-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.en.html)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Enabled-green.svg)](https://<tu-usuario-github>.github.io/jarvis-os/)

**jarvis-os** es un sistema operativo personal orquestado por voz y Markdown, construido sobre Docker en Apple Silicon M5. Combina un núcleo de orquestación `gentle-ai`, un pipeline de voz `voice-pipeline` y persistencia en frío mediante `floci-localstack` (S3/SQS), todo gestionado por un vault Zettelkasten en `./vault/`.

## Filosofía de Software Libre

Este proyecto es **Software Libre** bajo los términos de la **GNU General Public License v3.0 (GPLv3)**. Creemos en las cuatro libertades esenciales de la Free Software Foundation:

- **Libertad 0**: Ejecutar el programa para cualquier propósito.
- **Libertad 1**: Estudiar cómo funciona el programa y modificarlo.
- **Libertad 2**: Redistribuir copias del programa.
- **Libertad 3**: Distribuir copias de versiones modificadas.

El copyleft fuerte de la GPL v3.0 garantiza que todas las versiones modificadas y distribuciones mantengan estas libertades para toda la comunidad.

## Requisitos del sistema

- macOS Apple Silicon M1/M2/M3/M4/M5
- Docker Engine / Colima
- Python 3.11+ (para ejecución local opcional)
- Node.js 20+ (para desarrollo de skills)
- 16 GB RAM mínimo recomendado
- 20 GB espacio en disco

## Instalación rápida

```bash
# Clonar el repositorio
git clone https://github.com/<tu-usuario-github>/jarvis-os.git
cd jarvis-os

# Configurar variables de entorno
cp .env.example .env

# Levantar la pila completa
docker compose -f docker/docker-compose.yml up -d

# Verificar salud de servicios
docker compose -f docker/docker-compose.yml ps
```

## Documentación

La documentación oficial está disponible en GitHub Pages:  
**[https://<tu-usuario-github>.github.io/jarvis-os/](https://<tu-usuario-github>.github.io/jarvis-os/)**

## Licencia

Este proyecto se distribuye bajo la **GNU General Public License v3.0**.  
Ver el archivo [LICENSE](LICENSE) para más detalles.

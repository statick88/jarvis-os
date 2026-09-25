# Guía de Inicio Rápido

## Prerrequisitos

- Docker Engine o Colima en macOS Apple Silicon
- Git
- 16 GB RAM mínimo recomendado
- 20 GB espacio en disco

## Clonar el repositorio

```bash
git clone https://github.com/<tu-usuario-github>/jarvis-os.git
cd jarvis-os
```

## Configuración de variables de entorno

```bash
cp .env.example .env
```

Edita `.env` según tu entorno. Variables mínimas requeridas:

```env
JARVIS_TOKEN=changeme-secure-token
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=us-east-1
```

## Despliegue con Docker Compose

```bash
docker compose -f docker/docker-compose.yml up -d
```

## Verificación de salud

```bash
docker compose -f docker/docker-compose.yml ps
```

Debes ver tres servicios en estado `healthy`:

- `jarvis_floci`
- `jarvis_voice`
- `jarvis_orchestrator`

## Ejecutar suite de pruebas E2E

```bash
bash scripts/test_jarvis_pipeline.sh
```

## Acceder a la documentación local

```bash
pip install mkdocs-material
mkdocs serve
```

Abre [http://localhost:8000](http://localhost:8000).

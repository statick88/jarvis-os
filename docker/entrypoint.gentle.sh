#!/bin/bash
# ============================================================================
# JARVIS-OS — Entrypoint para gentle-orchestrator
# Espera a que dependencias estén listas y arranca el orquestador
# ============================================================================

set -euo pipefail

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[ORCHESTRATOR]${NC} $*"; }
log_success() { echo -e "${GREEN}[ORCHESTRATOR]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[ORCHESTRATOR]${NC} $*"; }
log_error() { echo -e "${RED}[ORCHESTRATOR]${NC} $*"; }

# Función para esperar servicio
wait_for_service() {
    local host=$1
    local port=$2
    local service_name=$3
    local max_attempts=${4:-30}
    local attempt=1

    log_info "Esperando $service_name en $host:$port..."
    while [ $attempt -le $max_attempts ]; do
        if nc -z "$host" "$port" 2>/dev/null; then
            log_success "$service_name está listo"
            return 0
        fi
        log_info "Intento $attempt/$max_attempts - esperando 2s..."
        sleep 2
        ((attempt++))
    done

    log_error "$service_name no respondió después de $max_attempts intentos"
    return 1
}

# Función para esperar HTTP health
wait_for_http() {
    local url=$1
    local service_name=$2
    local max_attempts=${3:-30}
    local attempt=1

    log_info "Esperando HTTP health de $service_name en $url..."
    while [ $attempt -le $max_attempts ]; do
        if curl -sf "$url" >/dev/null 2>&1; then
            log_success "$service_name HTTP health OK"
            return 0
        fi
        log_info "Intento $attempt/$max_attempts - esperando 3s..."
        sleep 3
        ((attempt++))
    done

    log_error "$service_name HTTP health falló después de $max_attempts intentos"
    return 1
}

# ============================================================================
# MAIN
# ============================================================================

log_info "=== JARVIS-OS Gentle Orchestrator Starting ==="
log_info "Usuario: $(whoami) (UID: $(id -u))"
log_info "Directorio: $(pwd)"
log_info "Python: $(python --version)"
log_info "Node: $(node --version)"

# Verificar variables críticas
if [ -z "${JARVIS_TOKEN:-}" ] || [ "${JARVIS_TOKEN}" = "changeme-secure-token" ]; then
    log_warn "JARVIS_TOKEN no configurado o usando default inseguro"
    log_warn "Configura JARVIS_TOKEN en docker-compose.yml o .env"
fi

# Esperar dependencias críticas
log_info "Verificando conectividad con dependencias..."

# Floci/LocalStack (S3/SQS)
wait_for_http "http://floci-localstack:4566/_localstack/health" "Floci/LocalStack" 20 || true

# Voice Pipeline
wait_for_http "http://voice-pipeline:8080/health" "Voice Pipeline" 30 || true

# Host OpenCode/Kilo (opcional - solo warning si no están)
if nc -z host.docker.internal 8081 2>/dev/null; then
    log_success "OpenCode detectado en host.docker.internal:8081"
else
    log_warn "OpenCode NO detectado en host.docker.internal:8081 (asegúrate de que esté corriendo)"
fi

if nc -z host.docker.internal 8082 2>/dev/null; then
    log_success "Kilo Code detectado en host.docker.internal:8082"
else
    log_warn "Kilo Code NO detectado en host.docker.internal:8082"
fi

# Verificar montajes
log_info "Verificando volúmenes montados..."
for mount in /app/vault /app/.skills /app/jarvis_os; do
    if [ -d "$mount" ] && [ -r "$mount" ]; then
        log_success "Montaje OK: $mount"
    else
        log_error "Montaje FALLÓ: $mount"
        exit 1
    fi
done

# Inicializar índice de boveda si no existe
if [ ! -f /app/vault/wiki/.boveda_index.json ]; then
    log_info "Inicializando índice de bóveda..."
    python -m jarvis_os.vault.indexer --init 2>/dev/null || log_warn "Indexador no disponible aún"
fi

# Ejecutar migraciones/validaciones previas
log_info "Ejecutando validaciones previas..."
python -c "
import sys
sys.path.insert(0, '/app')
try:
    from jarvis_os.config import validate_config
    validate_config()
    print('Config validation OK')
except Exception as e:
    print(f'Config validation warning: {e}')
" 2>/dev/null || log_warn "Validación de config omitida"

log_success "=== Iniciando Orchestrator ==="

# Ejecutar comando pasado como argumentos
exec "$@"
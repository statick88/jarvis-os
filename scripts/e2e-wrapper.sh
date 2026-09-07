#!/bin/bash
# ============================================================================
# JARVIS-OS — E2E Wrapper con auto-start de Colima
# Detecta si Colima está corriendo, lo inicia si es necesario, y ejecuta
# el test E2E completo. Al finaliza, detiene Colima a menos que --keep-colima.
#
# Uso: ./scripts/e2e-wrapper.sh [--keep-colima] [--verbose] [args...]
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Flags
KEEP_COLIMA=false
VERBOSE=false

# ============================================================================
# FUNCIONES
# ============================================================================

log_info()  { echo -e "${CYAN}[WRAPPER]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[WRAPPER]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WRAPPER]${NC} $*"; }
log_fail()  { echo -e "${RED}[WRAPPER]${NC} $*"; }

check_colima() {
    if colima status 2>/dev/null | grep -q "Running"; then
        return 0
    fi
    return 1
}

start_colima() {
    log_info "Iniciando Colima..."
    if [ "$VERBOSE" = true ]; then
        colima start --arch aarch64 --cpu 4 --memory 8 --disk 50
    else
        colima start --arch aarch64 --cpu 4 --memory 8 --disk 50 >/dev/null 2>&1
    fi
    log_ok "Colima iniciado"
}

wait_docker_ready() {
    local max_wait=60
    local interval=2
    local waited=0

    log_info "Esperando que Docker esté listo (max ${max_wait}s)..."
    while [ $waited -lt $max_wait ]; do
        if docker info >/dev/null 2>&1; then
            log_ok "Docker está listo"
            return 0
        fi
        sleep $interval
        waited=$((waited + interval))
        if [ "$VERBOSE" = true ]; then
            log_info "  Esperando Docker... (${waited}s/${max_wait}s)"
        fi
    done

    log_fail "Docker no estuvo listo en ${max_wait}s"
    return 1
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --keep-colima) KEEP_COLIMA=true; shift ;;
            --verbose)     VERBOSE=true; shift ;;
            -h|--help)
                echo "Uso: $0 [--keep-colima] [--verbose] [--help] [-- args...]"
                echo ""
                echo "Wrapper para tests E2E con auto-start de Colima."
                echo ""
                echo "Opciones:"
                echo "  --keep-colima  No detener Colima al finalizar"
                echo "  --verbose      Output detallado (se pasa al test)"
                echo "  --help         Mostrar esta ayuda"
                echo ""
                echo "Todos los flags después del wrapper (--check-only, --no-cleanup, etc.)"
                echo "se pasan directamente a test_jarvis_pipeline.sh."
                echo "Use -- para forzar que todo lo siguiente se pase al test."
                exit 0
                ;;
            --)           shift; TEST_ARGS+=("$@"); return ;;
            *)            TEST_ARGS+=("$1"); shift ;;
        esac
    done
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    local TEST_ARGS=()
    parse_args "$@"

    echo -e "${CYAN}═══════════════════════════════════════${NC}"
    echo -e "${CYAN}   JARVIS-OS E2E Wrapper${NC}"
    echo -e "${CYAN}═══════════════════════════════════════${NC}"
    echo ""

    # 1. Verificar Colima
    if check_colima; then
        log_ok "Colima ya está corriendo"
    else
        log_warn "Colima no está corriendo — iniciando..."
        start_colima
    fi

    # 2. Esperar Docker
    wait_docker_ready || exit 1

    # 3. Ejecutar test
    log_info "Ejecutando tests E2E..."
    local test_exit=0
    if [ ${#TEST_ARGS[@]} -gt 0 ]; then
        bash "$SCRIPT_DIR/test_jarvis_pipeline.sh" "${TEST_ARGS[@]}" || test_exit=$?
    else
        bash "$SCRIPT_DIR/test_jarvis_pipeline.sh" || test_exit=$?
    fi

    # 4. Cleanup (a menos que --keep-colima)
    if [ "$KEEP_COLIMA" = false ]; then
        log_info "Deteniendo Colima..."
        colima stop >/dev/null 2>&1 || true
        log_ok "Colima detenido"
    else
        log_info "Colima se mantiene corriendo (--keep-colima)"
    fi

    echo ""
    if [ $test_exit -eq 0 ]; then
        log_ok "E2E completado exitosamente"
    else
        log_fail "E2E terminó con errores (exit $test_exit)"
    fi

    exit $test_exit
}

main "$@"

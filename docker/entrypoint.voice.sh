#!/bin/bash
# ============================================================================
# JARVIS-OS — Entrypoint para voice-pipeline
# Descarga modelos si faltan y arranca servidor STT/TTS
# ============================================================================

set -euo pipefail

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[VOICE-PIPELINE]${NC} $*"; }
log_success() { echo -e "${GREEN}[VOICE-PIPELINE]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[VOICE-PIPELINE]${NC} $*"; }
log_error() { echo -e "${RED}[VOICE-PIPELINE]${NC} $*"; }

# ============================================================================
# FUNCIONES
# ============================================================================

download_whisper_model() {
    local model="${WHISPER_MODEL:-base}"
    local model_dir="/models/whisper"
    local model_file="${model_dir}/ggml-${model}.bin"
    local model_url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${model}.bin"

    mkdir -p "$model_dir"

    if [ -f "$model_file" ]; then
        log_success "Modelo Whisper '$model' ya existe en $model_file"
        return 0
    fi

    log_info "Descargando modelo Whisper '$model' desde Hugging Face..."
    if curl -fL --show-error -o "$model_file" "$model_url"; then
        log_success "Modelo descargado: $model_file ($(du -h "$model_file" | cut -f1))"
    else
        log_error "Falló descarga de modelo Whisper"
        return 1
    fi
}

download_whisper_cli() {
    log_info "whisper-cli no encontrado — intentando descargar binario precompilado..."
    local bin_dir="/usr/local/bin"
    local bin_file="${bin_dir}/whisper-cli"
    local tmp_dir="/tmp/whisper-cli-dl"
    rm -rf "$tmp_dir"
    mkdir -p "$tmp_dir"

    local url="https://github.com/ggerganov/whisper.cpp/releases/download/v1.7.4/whisper-cli-aarch64-unknown-linux-gnu.tar.gz"
    if curl -fL --show-error -o "${tmp_dir}/whisper-cli.tar.gz" "$url"; then
        tar -xzf "${tmp_dir}/whisper-cli.tar.gz" -C "$tmp_dir"
        if [ -f "${tmp_dir}/whisper-cli" ]; then
            mv "${tmp_dir}/whisper-cli" "$bin_file"
            chmod +x "$bin_file"
            log_success "whisper-cli descargado en $bin_file"
            rm -rf "$tmp_dir"
            return 0
        fi
    fi

    log_error "No se pudo descargar whisper-cli precompilado — se requiere compilación desde fuente"
    rm -rf "$tmp_dir"
    return 1
}

download_piper() {
    log_info "piper no encontrado — intentando descargar binario..."
    local bin_file="/usr/local/bin/piper"
    local tmp_dir="/tmp/piper-dl"
    rm -rf "$tmp_dir"
    mkdir -p "$tmp_dir"

    local version="${PIPER_VERSION:-2023.11.14-2}"
    local url="https://github.com/rhasspy/piper/releases/download/${version}/piper_linux_aarch64.tar.gz"
    if curl -fL --show-error -o "${tmp_dir}/piper.tar.gz" "$url"; then
        tar -xzf "${tmp_dir}/piper.tar.gz" -C "$tmp_dir"
        if [ -f "${tmp_dir}/piper" ]; then
            mv "${tmp_dir}/piper" "$bin_file"
            chmod +x "$bin_file"
            if [ -f "${tmp_dir}/libpiper_phonemize.so" ]; then
                mv "${tmp_dir}/libpiper_phonemize.so" /usr/local/lib/
                ldconfig
            fi
            log_success "piper descargado en $bin_file"
            rm -rf "$tmp_dir"
            return 0
        fi
    fi

    log_error "No se pudo descargar piper"
    rm -rf "$tmp_dir"
    return 1
}

download_kokoro_models() {
    local model_dir="/models/kokoro"
    mkdir -p "$model_dir"

    if [ -f "${model_dir}/kokoro-v1.0.onnx" ] && [ -f "${model_dir}/voices-v1.0.bin" ]; then
        log_success "Modelos Kokoro ya existen en $model_dir"
        return 0
    fi

    log_info "Descargando modelos Kokoro en runtime..."
    local attempt=1
    local max_attempts=3
    while [ $attempt -le $max_attempts ]; do
        log_info "Kokoro models download attempt $attempt/$max_attempts..."
        if curl -fL --show-error -o "${model_dir}/kokoro-v1.0.onnx" \
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" && \
           curl -fL --show-error -o "${model_dir}/voices-v1.0.bin" \
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" && \
           [ -s "${model_dir}/kokoro-v1.0.onnx" ] && [ -s "${model_dir}/voices-v1.0.bin" ]; then
             if [ "$(stat -c%s "${model_dir}/kokoro-v1.0.onnx" 2>/dev/null || echo 0)" -gt 1048576 ]; then
                 log_success "Modelos Kokoro descargados y verificados en $model_dir"
             else
                 log_warn "Kokoro ONNX model parece incompleto (<= 1MB), reintentando..."
                 rm -f "${model_dir}/kokoro-v1.0.onnx" "${model_dir}/voices-v1.0.bin"
                 continue
             fi
             return 0
        fi
        log_warn "Kokoro download attempt $attempt fallido, reintentando..."
        attempt=$((attempt + 1))
        sleep $((attempt * 2))
    done

    log_error "Falló descarga de modelos Kokoro tras $max_attempts intentos"
    return 1
}

verify_binaries() {
    log_info "Verificando binarios..."

    local missing_critical=0

    # Whisper.cpp (CRITICAL — STT sin esto el pipeline no funciona)
    if command -v whisper-cli >/dev/null 2>&1; then
        log_success "whisper-cli: $(whisper-cli --version 2>&1 | head -1)"
    else
        log_warn "whisper-cli NO encontrado en PATH — intentando descarga runtime..."
        if download_whisper_cli; then
            log_success "whisper-cli disponible tras descarga runtime"
        else
            log_error "whisper-cli NO disponible — FAIL-HARD"
            missing_critical=$((missing_critical + 1))
        fi
    fi

    # Piper (opcional si Kokoro está presente)
    local piper_available=0
    if command -v piper >/dev/null 2>&1; then
        log_success "piper: $(piper --version 2>&1 | head -1)"
        piper_available=1
    else
        log_warn "piper NO encontrado — intentando descarga runtime..."
        if download_piper; then
            piper_available=1
        else
            log_warn "piper NO disponible (se requiere Kokoro como fallback)"
        fi
    fi

    # Kokoro models (necesarios si Piper no está disponible)
    if [ -f "/models/kokoro/kokoro-v1.0.onnx" ] && [ -f "/models/kokoro/voices-v1.0.bin" ]; then
        log_success "Modelos Kokoro presentes"
        piper_available=1
    else
        log_warn "Modelos Kokoro NO encontrados en /models/kokoro/ — intentando descarga runtime..."
        if download_kokoro_models; then
            piper_available=1
        else
            log_error "Modelos Kokoro NO disponibles — FAIL-HARD"
            missing_critical=$((missing_critical + 1))
        fi
    fi

    # Al menos un motor TTS debe estar disponible
    if [ "$piper_available" -eq 0 ]; then
        log_error "Ni Piper ni Kokoro disponibles — no hay motor TTS"
        missing_critical=$((missing_critical + 1))
    fi

    # Librerías
    if ldconfig -p | grep -q libwhisper; then
        log_success "libwhisper.so cargada"
    else
        log_warn "libwhisper.so no en cache ldconfig (puede necesitar LD_LIBRARY_PATH)"
    fi

    if [ "$missing_critical" -gt 0 ]; then
        log_error "Faltan $missing_critical componentes críticos — abortando"
        return 1
    fi

    return 0
}

wait_for_dependencies() {
    log_info "Esperando dependencias externas..."

    # Floci/LocalStack para colas async (opcional para voice-pipeline)
    if [ "${WAIT_FOR_FLOCI:-true}" = "true" ]; then
        local max_attempts=20
        local attempt=1
        while [ $attempt -le $max_attempts ]; do
            if curl -sf "http://floci-localstack:4566/_localstack/health" >/dev/null 2>&1; then
                log_success "Floci/LocalStack disponible"
                break
            fi
            log_info "Esperando Floci... ($attempt/$max_attempts)"
            sleep 3
            attempt=$((attempt + 1))
        done
    fi
}

# ============================================================================
# MAIN
# ============================================================================

log_info "=== JARVIS-OS Voice Pipeline Starting ==="
log_info "Usuario: $(whoami) (UID: $(id -u))"
log_info "Directorio: $(pwd)"
log_info "Python: $(python --version)"
log_info "Config: WHISPER_MODEL=${WHISPER_MODEL}, PIPER_VOICE=${PIPER_VOICE}, KOKORO_VOICE=${KOKORO_VOICE}"

# Verificar binarios (fail-hard: si falla, el contenedor no arranca)
verify_binaries || { log_error "Verificación de binarios falló — abortando inicio"; exit 1; }

# Descargar modelo Whisper si no existe
download_whisper_model || log_error "No se pudo descargar modelo Whisper, STT puede fallar"

# Esperar dependencias
wait_for_dependencies

# Verificar montaje de modelos
if [ -d "/models" ] && [ -w "/models" ]; then
    log_success "Volumen /models montado y escribible"
else
    log_error "Volumen /models NO accesible"
    exit 1
fi

log_success "=== Iniciando Voice Pipeline Server ==="

# Ejecutar comando
exec "$@"
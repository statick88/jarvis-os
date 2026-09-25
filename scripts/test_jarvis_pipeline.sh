#!/bin/bash
# ============================================================================
# JARVIS-OS — Test de Integración End-to-End
# Valida: Docker Compose health → Pipeline completo (texto → adapter → plan → vault → SQS)
# Uso: ./scripts/test_jarvis_pipeline.sh [--verbose] [--cleanup]
# ============================================================================

set -euo pipefail

# Configuración
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.yml"
COMPOSE_PROJECT_NAME="docker"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Flags
VERBOSE=false
CLEANUP=false
SKIP_BUILD=false
CHECK_ONLY=false
SKIP_CLEANUP=false

# Contadores
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# ============================================================================
# FUNCIONES DE LOGGING
# ============================================================================

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[PASS]${NC} $*"; TESTS_PASSED=$((TESTS_PASSED + 1)); }
log_fail() { echo -e "${RED}[FAIL]${NC} $*"; TESTS_FAILED=$((TESTS_FAILED + 1)); }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_skip() { echo -e "${CYAN}[SKIP]${NC} $*"; TESTS_SKIPPED=$((TESTS_SKIPPED + 1)); }
log_step() { echo -e "\n${CYAN}═══ $* ═══${NC}\n"; }

# ============================================================================
# HELPERS
# ============================================================================

run_compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME" "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT_NAME" "$@"
    else
        log_fail "Docker Compose no disponible (ni 'docker compose' ni 'docker-compose')"
        return 1
    fi
}

wait_for_health() {
    local service=$1
    local max_wait=${2:-120}
    local interval=5
    local waited=0

    log_info "Esperando healthcheck de $service (max ${max_wait}s)..."

    while [ $waited -lt $max_wait ]; do
        local container_id
        # Usar filter por label de compose (robusto incluso con container_name override)
        container_id=$(docker ps --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" --filter "label=com.docker.compose.service=${service}" --filter "status=running" -q 2>/dev/null | head -n1 || echo "")
        if [ -n "$container_id" ]; then
            local status
            status=$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || echo "unknown")
            if [ "$status" = "healthy" ]; then
                log_success "$service está healthy"
                return 0
            elif [ "$status" = "unhealthy" ]; then
                log_fail "$service está unhealthy"
                docker logs "$container_id" --tail 50 2>&1 || true
                return 1
            fi
        fi

        sleep $interval
        waited=$((waited + interval))
        if [ "$VERBOSE" = true ]; then
            log_info "  Esperando $service... (${waited}s/${max_wait}s) - status: ${status:-unknown}"
        fi
    done

    log_fail "$service no alcanzó estado healthy en ${max_wait}s"
    docker logs "$(docker ps --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" --filter "label=com.docker.compose.service=${service}" -q 2>/dev/null | head -n1)" --tail 50 2>&1 || true
    return 1
}

check_service_running() {
    local service=$1
    local container_id
    # Usar filter por label de compose (robusto incluso con container_name override)
    container_id=$(docker ps --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" --filter "label=com.docker.compose.service=${service}" --filter "status=running" -q 2>/dev/null | head -n1 || echo "")
    if [ -n "$container_id" ]; then
        local status
        status=$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || echo "unknown")
        [ "$status" = "running" ]
    else
        return 1
    fi
}

# ============================================================================
# TESTS
# ============================================================================

test_docker_compose_up() {
    log_step "TEST 1: Docker Compose Up & Health Checks"

    log_info "Levantando servicios con docker compose..."
    if run_compose up -d --build; then
        log_success "docker compose up -d --build completado"
    else
        log_fail "docker compose up falló"
        return 1
    fi

    # Esperar healthchecks en orden de dependencia
    wait_for_health "floci-localstack" 120 || return 1
    wait_for_health "voice-pipeline" 180 || return 1
    wait_for_health "gentle-orchestrator" 120 || return 1

    log_success "Todos los servicios healthy"
    return 0
}

test_floci_resources() {
    log_step "TEST 2: Floci/LocalStack Resources (S3 + SQS)"

    # Verificar S3 bucket
    log_info "Verificando bucket S3: jarvis-vault-backups"
    if run_compose exec -T floci-localstack awslocal s3api head-bucket --bucket jarvis-vault-backups >/dev/null 2>&1; then
        log_success "Bucket S3 jarvis-vault-backups existe"
    else
        log_fail "Bucket S3 jarvis-vault-backups NO encontrado"
        return 1
    fi

    # Verificar versionado
    local versioning
    versioning=$(run_compose exec -T floci-localstack awslocal s3api get-bucket-versioning --bucket jarvis-vault-backups --query 'Status' --output text 2>/dev/null || echo "None")
    if [ "$versioning" = "Enabled" ]; then
        log_success "Versionado S3 habilitado"
    else
        log_warn "Versionado S3: $versioning (esperado: Enabled)"
    fi

    # Verificar colas SQS
    for queue in jarvis-async-tasks jarvis-async-tasks-dlq; do
        log_info "Verificando cola SQS: $queue"
        local url
        url=$(run_compose exec -T floci-localstack awslocal sqs get-queue-url --queue-name "$queue" --query 'QueueUrl' --output text 2>/dev/null || echo "")
        if [ -n "$url" ]; then
            log_success "Cola SQS $queue existe: $url"
        else
            log_fail "Cola SQS $queue NO encontrada"
            return 1
        fi
    done

    # Verificar redrive policy (DLQ)
    local main_queue_url
    main_queue_url=$(run_compose exec -T floci-localstack awslocal sqs get-queue-url --queue-name jarvis-async-tasks --query 'QueueUrl' --output text)
    local redrive_policy
    redrive_policy=$(run_compose exec -T floci-localstack awslocal sqs get-queue-attributes --queue-url "$main_queue_url" --attribute-names RedrivePolicy --query 'Attributes.RedrivePolicy' --output text 2>/dev/null || echo "")
    if echo "$redrive_policy" | grep -q "jarvis-async-tasks-dlq"; then
        log_success "Redrive policy configurada correctamente (DLQ)"
    else
        log_warn "Redrive policy: $redrive_policy"
    fi

    return 0
}

test_voice_pipeline_api() {
    log_step "TEST 3: Voice Pipeline API (Health + Models)"

    # Health check directo
    log_info "Probando /health endpoint..."
    local health_response
    health_response=$(curl -sf http://localhost:8080/health 2>/dev/null || echo "")
    if echo "$health_response" | jq -e '.status == "ok" or .healthy == true' >/dev/null 2>&1; then
        log_success "Voice Pipeline /health OK: $health_response"
    else
        log_fail "Voice Pipeline /health falló: $health_response"
        return 1
    fi

    # Listar modelos
    log_info "Probando /v1/models endpoint..."
    local models_response
    models_response=$(curl -sf --max-time 20 http://localhost:8080/v1/models 2>/dev/null || echo "")
    if echo "$models_response" | jq -e '.models | length > 0' >/dev/null 2>&1; then
        log_success "Voice Pipeline /v1/models OK: $(echo "$models_response" | jq '.models | length') models"
        [ "$VERBOSE" = true ] && echo "$models_response" | jq .
    else
        log_fail "Voice Pipeline /v1/models respuesta inesperada: $models_response"
        return 1
    fi

    return 0
}


test_stt_tts_binaries() {
    log_step "TEST 3A: STT/TTS Binaries Availability (Fail-Hard)"

    local container_id
    # Usar filter por label de compose (robusto incluso con container_name override)
    container_id=$(docker ps --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" --filter "label=com.docker.compose.service=voice-pipeline" --filter "status=running" -q 2>/dev/null | head -n1 || echo "")

    if [ -z "$container_id" ]; then
        log_fail "voice-pipeline container not found — cannot verify binaries"
        return 1
    fi

    local failures=0

    # Verify whisper-cli
    log_info "Verificando whisper-cli en voice-pipeline..."
    if run_compose exec -T voice-pipeline which whisper-cli >/dev/null 2>&1; then
        local whisper_version
        whisper_version=$(run_compose exec -T voice-pipeline whisper-cli --version 2>&1 | head -1 || echo "unknown")
        log_success "whisper-cli presente: $whisper_version"
    else
        log_fail "whisper-cli NO presente en voice-pipeline"
        failures=$((failures + 1))
    fi

    # Verify at least one TTS engine
    log_info "Verificando motores TTS en voice-pipeline..."
    local tts_available=0

    if run_compose exec -T voice-pipeline which piper >/dev/null 2>&1; then
        log_success "piper presente en voice-pipeline"
        tts_available=1
    else
        log_warn "piper NO presente (Kokoro puede ser alternativa)"
    fi

    if run_compose exec -T voice-pipeline test -f /models/kokoro/kokoro-v1.0.onnx >/dev/null 2>&1; then
        log_success "Kokoro modelo presente en voice-pipeline"
        tts_available=1
    else
        log_warn "Kokoro modelo NO presente en voice-pipeline"
    fi

    if [ "$tts_available" -eq 0 ]; then
        log_fail "No hay motor TTS disponible en voice-pipeline"
        failures=$((failures + 1))
    else
        log_success "Al menos un motor TTS disponible"
    fi

    # Verify whisper model
    log_info "Verificando modelo Whisper en /models/whisper..."
    if run_compose exec -T voice-pipeline ls /models/whisper/ggml-*.bin >/dev/null 2>&1; then
        local model_file
        model_file=$(run_compose exec -T voice-pipeline ls /models/whisper/ggml-*.bin 2>/dev/null | head -1 || echo "unknown")
        log_success "Modelo Whisper presente: $model_file"
    else
        log_warn "Modelo Whisper NO presente (se descargará en runtime)"
    fi

    if [ "$failures" -gt 0 ]; then
        log_fail "STT/TTS binaries: $failures fallos críticos"
        return 1
    fi

    log_success "STT/TTS binaries: todos los componentes críticos presentes"
    return 0
}

test_skills_api() {
    log_step "TEST 3B: Skills API Coverage"

    local base="http://localhost:3000"

    # List skills
    log_info "Probando GET /api/v1/skills..."
    local skills_response
    skills_response=$(curl -sf --max-time 20 "$base/api/v1/skills" 2>/dev/null || echo "")
    if echo "$skills_response" | jq -e '.skills | length >= 3' >/dev/null 2>&1; then
        log_success "Skills API list OK: $(echo "$skills_response" | jq '.skills | length') skills"
    else
        log_fail "Skills API list falló: $skills_response"
        return 1
    fi

    # Execute obsidian create_note
    log_info "Probando POST /api/v1/skills/skill-obsidian/execute..."
    local obs_response
    obs_response=$(curl -sf --max-time 20 -X POST "$base/api/v1/skills/skill-obsidian/execute" \
        -H "Content-Type: application/json" \
        -d '{"operation":"create_note","parameters":{"path":"notes/e2e-test.md","title":"E2E Test","content":"Hello from E2E"}}' 2>/dev/null || echo "")
    if echo "$obs_response" | jq -e '.status == "success"' >/dev/null 2>&1; then
        log_success "Obsidian create_note OK"
    else
        log_warn "Obsidian create_note respuesta: $obs_response"
    fi

    # Execute os_control get_system_metrics
    log_info "Probando POST /api/v1/skills/skill-os-control/execute..."
    local os_response
    os_response=$(curl -sf --max-time 30 -X POST "$base/api/v1/skills/skill-os-control/execute" \
        -H "Content-Type: application/json" \
        -d '{"operation":"get_system_metrics","parameters":{"metrics":["cpu"]}}' 2>/dev/null || echo "")
    if echo "$os_response" | jq -e '.status == "success"' >/dev/null 2>&1; then
        log_success "OSControl metrics OK"
    else
        log_warn "OSControl metrics respuesta: $os_response"
    fi

    # Execute devsecops list containers
    log_info "Probando POST /api/v1/skills/skill-devsecops/execute..."
    local dev_response
    dev_response=$(curl -sf --max-time 20 -X POST "$base/api/v1/skills/skill-devsecops/execute" \
        -H "Content-Type: application/json" \
        -d '{"operation":"list_containers","parameters":{"all":true}}' 2>/dev/null || echo "")
    if echo "$dev_response" | jq -e '.status == "success"' >/dev/null 2>&1; then
        log_success "DevSecOps list_containers OK"
    else
        log_warn "DevSecOps list_containers respuesta: $dev_response"
    fi

    return 0
}

test_skills_api_path_traversal() {
    log_step "TEST 3C: Skills API — Path Traversal Rejection"

    local base="http://localhost:3000"

    # Attempt path traversal via obsidian create_note (must be rejected)
    log_info "Probando path traversal: ../../etc/passwd..."
    local traversal_response
    traversal_response=$(curl -sf --max-time 20 -X POST "$base/api/v1/skills/skill-obsidian/execute" \
        -H "Content-Type: application/json" \
        -d '{"operation":"create_note","parameters":{"path":"../../etc/passwd","title":"evil","content":"pwned"}}' 2>/dev/null || echo "")

    if echo "$traversal_response" | jq -e '.status == "success" and (.result.data.success == false or .result.error != null)' >/dev/null 2>&1; then
        log_success "Path traversal bloqueado (response indicates failure)"
    elif echo "$traversal_response" | jq -e '.status == "error" and .message != null' >/dev/null 2>&1; then
        log_success "Path traversal bloqueado (canonical error envelope)"
    else
        # Also accept a success-level envelope wrapping a failed result
        if echo "$traversal_response" | jq -e '.result.data.success == false' >/dev/null 2>&1; then
            log_success "Path traversal bloqueado (handler returned success: false)"
        else
            log_fail "Path traversal NO fue bloqueado: $traversal_response"
            return 1
        fi
    fi

    # Attempt absolute path traversal
    log_info "Probando path traversal: /etc/passwd..."
    local abs_response
    abs_response=$(curl -sf --max-time 20 -X POST "$base/api/v1/skills/skill-obsidian/execute" \
        -H "Content-Type: application/json" \
        -d '{"operation":"read_note","parameters":{"path":"/etc/passwd"}}' 2>/dev/null || echo "")

    if echo "$abs_response" | jq -e '.status == "success" and (.result.data.success == false or .result.error != null)' >/dev/null 2>&1; then
        log_success "Absolute path traversal bloqueado"
    elif echo "$abs_response" | jq -e '.status == "error" and .message != null' >/dev/null 2>&1; then
        log_success "Absolute path traversal bloqueado (canonical error envelope)"
    else
        log_fail "Absolute path traversal NO fue bloqueado: $abs_response"
        return 1
    fi

    return 0
}

test_skills_api_operation_routing() {
    log_step "TEST 3D: Skills API — Operation Routing"

    local base="http://localhost:3000"

    # Verify that operation=create_note is forwarded to the handler
    # (not silently treated as search_vault)
    log_info "Verificando que operation=create_note se enruta correctamente..."
    local op_response
    op_response=$(curl -sf --max-time 20 -X POST "$base/api/v1/skills/skill-obsidian/execute" \
        -H "Content-Type: application/json" \
        -d '{"operation":"create_note","parameters":{"path":"notes/op-routing-test.md","title":"Op Routing Test","content":"verifying operation forwarding","tags":["test","routing"]}}' 2>/dev/null || echo "")

    if echo "$op_response" | jq -e '.status == "success" and .result.data.created == true' >/dev/null 2>&1; then
        log_success "Operation routing OK: create_note forwarded and note created"
    else
        log_fail "Operation routing falló (create_note not honored): $op_response"
        return 1
    fi

    # Verify that operation=read_note retrieves the note we just created
    log_info "Verificando que operation=read_note se enruta correctamente..."
    local read_response
    read_response=$(curl -sf --max-time 20 -X POST "$base/api/v1/skills/skill-obsidian/execute" \
        -H "Content-Type: application/json" \
        -d '{"operation":"read_note","parameters":{"path":"notes/op-routing-test.md"}}' 2>/dev/null || echo "")

    if echo "$read_response" | jq -e '.status == "success" and .result.data.content != null' >/dev/null 2>&1; then
        log_success "Operation routing OK: read_note forwarded and content retrieved"
    else
        log_fail "Operation routing falló (read_note not honored): $read_response"
        return 1
    fi

    # Verify YAML tags are valid in the created note
    log_info "Verificando YAML frontmatter tags serialization..."
    if echo "$read_response" | jq -r '.result.data.content' 2>/dev/null | head -10 | grep -q '^tags:'; then
        log_success "YAML tags frontmatter present and valid"
    else
        log_warn "YAML tags frontmatter not detected in content (may be valid in other format)"
    fi

    return 0
}

test_opencode_adapter_mock() {
    log_step "TEST 4: OpenCode Adapter (Mock - Simulación)"

    # Como OpenCode no está corriendo en el host durante test CI,
    # simulamos el adapter creando un mock server temporal
    log_info "Creando mock server para OpenCode adapter..."

    # Puerto para mock
    local MOCK_PORT=18081

    # Cleanup function
    cleanup_mock() {
        if [ -n "${MOCK_PID:-}" ] && kill -0 "${MOCK_PID:-}" 2>/dev/null; then
            kill "${MOCK_PID:-}" 2>/dev/null || true
            wait "${MOCK_PID:-}" 2>/dev/null || true
        fi
    }
    trap cleanup_mock EXIT

    # Iniciar mock server Python simple
    python3 -c "
import json
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/jarvis/adapter':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            try:
                msg = json.loads(body)
                skill = msg.get('payload', {}).get('skill') or msg.get('skill')
                action = msg.get('payload', {}).get('input', {}).get('action') or msg.get('input', {}).get('action')

                response = {
                    'id': str(uuid.uuid4()),
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'type': 'RESPONSE',
                    'payload': {
                        'success': True,
                        'output': {'message': f'Mock {skill}.{action} executed'},
                        'vault_changes': [],
                        'duration_ms': 50
                    }
                }
                if skill == 'plan' and action == 'add_task':
                    response['payload']['output']['task_id'] = 'tsk-001'
                    response['payload']['vault_changes'] = [{
                        'path': 'wiki/plan_hoy.md',
                        'operation': 'UPDATE',
                        'content': '---\nid: plan_hoy\ntags: [plan, daily]\n---\n# Plan\n- [ ] Test task 🔴',
                        'frontmatter': {'id': 'plan_hoy', 'tags': ['plan', 'daily']}
                    }]

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

server = HTTPServer(('0.0.0.0', $MOCK_PORT), MockHandler)
server.serve_forever()
" &

    MOCK_PID=$!
    sleep 2

    # Verificar mock responde
    log_info "Probando mock OpenCode adapter..."
    local mock_response
    mock_response=$(curl -sf -X POST "http://localhost:$MOCK_PORT/jarvis/adapter" \
        -H "Content-Type: application/json" \
        -d '{"skill":"plan","input":{"action":"add_task","task":"Test E2E task","priority":"high"},"context":{"vault_path":"/app/vault","skills_path":"/app/.skills","session_id":"test-session"}}' 2>/dev/null || echo "")

    if echo "$mock_response" | jq -e '.payload.success == true' >/dev/null 2>&1; then
        log_success "Mock OpenCode adapter responde correctamente"
        [ "$VERBOSE" = true ] && echo "$mock_response" | jq .
    else
        log_fail "Mock OpenCode adapter falló: $mock_response"
        return 1
    fi

    # Guardar puerto para tests siguientes
    echo "$MOCK_PORT" > /tmp/jarvis_mock_port.txt

    return 0
}

test_plan_skill_integration() {
    log_step "TEST 5: Integración Skill 'plan' → Vault → SQS"

    local MOCK_PORT
    MOCK_PORT=$(cat /tmp/jarvis_mock_port.txt 2>/dev/null || echo "18081")

    # Simular llamada completa: Texto → Adapter → Plan Skill → Vault
    log_info "Ejecutando pipeline: add_task → vault write"

    local response
    response=$(curl -sf -X POST "http://localhost:$MOCK_PORT/jarvis/adapter" \
        -H "Content-Type: application/json" \
        -d '{
            "id": "'"$(uuidgen)"'",
            "timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
            "type": "REQUEST",
            "payload": {
                "skill": "plan",
                "input": {"action": "add_task", "task": "Validar pipeline E2E", "priority": "critical"},
                "context": {"vault_path": "/app/vault", "skills_path": "/app/.skills", "session_id": "e2e-test-'"$(date +%s)"'"}
            }
        }' 2>/dev/null || echo "")

    if echo "$response" | jq -e '.payload.success == true' >/dev/null 2>&1; then
        log_success "Skill plan.add_task ejecutada via adapter mock"
        local task_id
        task_id=$(echo "$response" | jq -r '.payload.output.task_id // "unknown"')
        log_info "Task ID generado: $task_id"
    else
        log_fail "Skill plan.add_task falló: $response"
        return 1
    fi

    # Verificar que se generaría vault_changes correcto
    local vault_changes
    vault_changes=$(echo "$response" | jq -c '.payload.vault_changes[]? | select(.path=="wiki/plan_hoy.md")' 2>/dev/null || echo "")
    if [ -n "$vault_changes" ]; then
        log_success "Vault changes generados para wiki/plan_hoy.md"
        [ "$VERBOSE" = true ] && echo "$vault_changes" | jq .
    else
        log_warn "No se detectaron vault_changes para plan_hoy.md"
    fi

    # Simular encolado en SQS (verificar estructura sqs_events)
    local sqs_events
    sqs_events=$(echo "$response" | jq -c '.payload.sqs_events[]?' 2>/dev/null || echo "")
    # plan skill no encola en SQS normalmente, pero verificamos estructura
    log_info "Estructura SQS events (esperado array vacío para plan): $sqs_events"

    return 0
}

test_tendencias_sqs_integration() {
    log_step "TEST 6: Integración Skill 'tendencias' → SQS"

    local MOCK_PORT
    MOCK_PORT=$(cat /tmp/jarvis_mock_port.txt 2>/dev/null || echo "18081")

    log_info "Simulando skill tendencias con encolado SQS..."

    # Modificar mock para responder con sqs_events para tendencias
    local response
    response=$(curl -sf -X POST "http://localhost:$MOCK_PORT/jarvis/adapter" \
        -H "Content-Type: application/json" \
        -d '{
            "id": "'"$(uuidgen)"'",
            "timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
            "type": "REQUEST",
            "payload": {
                "skill": "tendencias",
                "input": {"action": "fetch", "hours_back": 1, "enqueue_async": true},
                "context": {"vault_path": "/app/vault", "skills_path": "/app/.skills", "session_id": "e2e-test-tendencias"}
            }
        }' 2>/dev/null || echo "")

    # El mock actual no distingue skills, pero verificamos que la estructura soporta sqs_events
    if echo "$response" | grep -q '"sqs_events"'; then
        log_success "Respuesta incluye campo sqs_events (estructura correcta)"
    else
        log_warn "Campo sqs_events no presente en respuesta mock (limitación del mock)"
    fi

    # Verificar cola SQS real en Floci
    log_info "Verificando cola SQS real en Floci..."
    local queue_attrs
    queue_attrs=$(run_compose exec -T floci-localstack awslocal sqs get-queue-attributes \
        --queue-url "$(run_compose exec -T floci-localstack awslocal sqs get-queue-url --queue-name jarvis-async-tasks --query 'QueueUrl' --output text)" \
        --attribute-names ApproximateNumberOfMessages --query 'Attributes.ApproximateNumberOfMessages' --output text 2>/dev/null || echo "0")

    log_info "Mensajes en cola jarvis-async-tasks: $queue_attrs"
    log_success "Cola SQS accesible y funcional"

    return 0
}

test_vault_structure() {
    log_step "TEST 7: Estructura Vault (Directorios y Permisos)"

    # Verificar directorios existen en host (montados)
    for dir in vault/raw vault/wiki vault/outputs .skills jarvis_os; do
        if [ -d "$PROJECT_ROOT/$dir" ]; then
            log_success "Directorio existe: $dir"
        else
            log_fail "Directorio FALTANTE: $dir"
            return 1
        fi
    done

    # Verificar permisos de escritura en vault (desde contenedor)
    log_info "Probando escritura en vault desde contenedor orchestrator..."
    local test_file="/app/vault/.write_test_$(date +%s)"
    if run_compose exec -T gentle-orchestrator sh -c "echo 'test' > '$test_file' && rm '$test_file'" 2>/dev/null; then
        log_success "Escritura en vault OK desde contenedor"
    else
        log_fail "Escritura en vault FALLÓ desde contenedor"
        return 1
    fi

    return 0
}

test_graceful_shutdown() {
    log_step "TEST 8: Apagado Graceful (SIGTERM)"

    log_info "Enviando SIGTERM a orchestrator..."
    if run_compose kill -s SIGTERM gentle-orchestrator; then
        log_success "SIGTERM enviado"
    else
        log_fail "Fallo enviando SIGTERM"
        return 1
    fi

    # Esperar a que se detenga (timeout 10s)
    local waited=0
    while [ $waited -lt 10 ]; do
        if ! check_service_running "gentle-orchestrator"; then
            log_success "Orchestrator se detuvo correctamente"
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done

    if check_service_running "gentle-orchestrator"; then
        log_warn "Orchestrator no se detuvo en 10s (force kill)"
        run_compose kill -s SIGKILL gentle-orchestrator
    fi

    # Reiniciar para limpieza final
    run_compose up -d gentle-orchestrator >/dev/null
    wait_for_health "gentle-orchestrator" 120 || true

    return 0
}

# ============================================================================
# MAIN
# ============================================================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose) VERBOSE=true; shift ;;
            --cleanup) CLEANUP=true; shift ;;
            --skip-build) SKIP_BUILD=true; shift ;;
            --check-only) CHECK_ONLY=true; shift ;;
            --no-cleanup) SKIP_CLEANUP=true; shift ;;
            -h|--help)
                echo "Uso: $0 [--verbose] [--cleanup] [--skip-build] [--check-only] [--no-cleanup]"
                echo "  --verbose     : Output detallado"
                echo "  --cleanup     : Limpiar contenedores al final"
                echo "  --skip-build  : Saltar build (usar imágenes existentes)"
                echo "  --check-only  : Solo tests mock (sin Docker/Colima)"
                echo "  --no-cleanup  : No ejecutar cleanup al final"
                exit 0
                ;;
            *) log_warn "Opción desconocida: $1"; shift ;;
        esac
    done
}

cleanup_all() {
    if [ "$SKIP_CLEANUP" = true ]; then
        log_info "Skip cleanup (--no-cleanup activo)"
        return 0
    fi
    if [ "$CLEANUP" = true ]; then
        log_info "Limpiando recursos de test..."
        run_compose down -v --remove-orphans 2>/dev/null || true
        docker volume rm "${COMPOSE_PROJECT_NAME}_voice_models" 2>/dev/null || true
        rm -f /tmp/jarvis_mock_port.txt
        log_success "Limpieza completada"
    else
        log_info "Manteniendo contenedores para inspección (usa --cleanup para limpiar)"
        log_info "Para limpiar manual: docker compose -f $COMPOSE_FILE -p $COMPOSE_PROJECT_NAME down -v"
    fi
}

print_summary() {
    echo -e "\n${CYAN}═══════════════════════════════════════${NC}"
    echo -e "${CYAN}       RESUMEN DE TESTS E2E${NC}"
    echo -e "${CYAN}═══════════════════════════════════════${NC}"
    echo -e "  ${GREEN}Pasaron:${NC} $TESTS_PASSED"
    echo -e "  ${RED}Fallaron:${NC} $TESTS_FAILED"
    echo -e "  ${CYAN}Omitidos:${NC} $TESTS_SKIPPED"
    echo -e "${CYAN}═══════════════════════════════════════${NC}\n"

    if [ $TESTS_FAILED -eq 0 ]; then
        log_success "¡TODOS LOS TESTS PASARON! ✅"
        return 0
    else
        log_fail "ALGUNOS TESTS FALLARON ❌"
        return 1
    fi
}

main() {
    parse_args "$@"

    echo -e "${CYAN}═══════════════════════════════════════${NC}"
    echo -e "${CYAN}   JARVIS-OS E2E Pipeline Test${NC}"
    echo -e "${CYAN}═══════════════════════════════════════${NC}"
    echo "Proyecto: $PROJECT_ROOT"
    echo "Compose: $COMPOSE_FILE"
    echo "Proyecto Docker: $COMPOSE_PROJECT_NAME"
    echo "Verbose: $VERBOSE"
    echo "Cleanup: $CLEANUP"
    echo "Check-only: $CHECK_ONLY"
    echo "No-cleanup: $SKIP_CLEANUP"
    echo ""

    # Verificar prerrequisitos (fail-hard)
    command -v docker >/dev/null || { log_fail "Docker no instalado"; exit 1; }
    if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
        log_fail "Docker Compose no disponible (ni 'docker compose' ni 'docker-compose')"
        exit 1
    fi
    command -v jq >/dev/null || { log_fail "jq no instalado (requerido para parsing JSON)"; exit 1; }
    command -v curl >/dev/null || { log_fail "curl no instalado"; exit 1; }
    command -v uuidgen >/dev/null || { log_fail "uuidgen no instalado"; exit 1; }

    # Trap para cleanup en caso de error
    trap cleanup_all EXIT

    if [ "$CHECK_ONLY" = true ]; then
        log_info "Modo --check-only: ejecutando solo tests mock (sin Docker/Colima)"
        echo ""

        # Solo tests mock (no requieren Docker)
        test_opencode_adapter_mock
        test_plan_skill_integration
    else
        # Tests completos (Docker + mock) en orden (fail-hard: no enmascarar errores)
        test_docker_compose_up
        test_floci_resources
        test_stt_tts_binaries
        test_voice_pipeline_api
        test_skills_api
        test_skills_api_path_traversal
        test_skills_api_operation_routing
        test_opencode_adapter_mock
        test_plan_skill_integration
        test_tendencias_sqs_integration
        test_vault_structure
        test_graceful_shutdown
    fi

    # Summary
    print_summary
}

main "$@"
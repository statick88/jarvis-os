#!/usr/bin/env bash
# ============================================================================
# JARVIS-OS — Floci/LocalStack Infrastructure Initialization
# Script idempotente para crear recursos S3 y SQS en LocalStack
# Se ejecuta automáticamente al iniciar floci-localstack (montado en /etc/localstack/init/ready.d/)
# ============================================================================

set -euo pipefail

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuración
AWS_ENDPOINT="${AWS_ENDPOINT_URL:-http://localhost:4566}"
AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
AWS_ACCESS_KEY="${AWS_ACCESS_KEY_ID:-test}"
AWS_SECRET_KEY="${AWS_SECRET_ACCESS_KEY:-test}"

# Nombres de recursos
S3_BUCKET="jarvis-vault-backups"
SQS_QUEUE="jarvis-async-tasks"
SQS_DLQ="jarvis-async-tasks-dlq"  # Dead Letter Queue

# Configurar AWS CLI para LocalStack
export AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$AWS_SECRET_KEY"
export AWS_DEFAULT_REGION="$AWS_REGION"

awslocal() {
    aws --endpoint-url="$AWS_ENDPOINT" "$@"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Esperar a que LocalStack esté listo
wait_for_localstack() {
    log_info "Esperando a LocalStack en $AWS_ENDPOINT..."
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if awslocal sts get-caller-identity >/dev/null 2>&1; then
            log_success "LocalStack está listo"
            return 0
        fi
        log_info "Intento $attempt/$max_attempts - esperando 2s..."
        sleep 2
        ((attempt++))
    done

    log_error "LocalStack no respondió después de $max_attempts intentos"
    return 1
}

# Crear bucket S3 con versionado y lifecycle
create_s3_bucket() {
    log_info "Configurando bucket S3: $S3_BUCKET"

    # Verificar si existe
    if awslocal s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
        log_warn "Bucket $S3_BUCKET ya existe"
    else
        log_info "Creando bucket $S3_BUCKET..."
        awslocal s3api create-bucket --bucket "$S3_BUCKET" --region "$AWS_REGION" >/dev/null
        log_success "Bucket $S3_BUCKET creado"
    fi

    # Habilitar versionado
    log_info "Habilitando versionado en $S3_BUCKET..."
    awslocal s3api put-bucket-versioning \
        --bucket "$S3_BUCKET" \
        --versioning-configuration Status=Enabled >/dev/null
    log_success "Versionado habilitado"

    # Configurar lifecycle policy: mover a Glacier a los 30 días, expirar a 365 días
    log_info "Aplicando lifecycle policy..."
    awslocal s3api put-bucket-lifecycle-configuration \
        --bucket "$S3_BUCKET" \
        --lifecycle-configuration '{
            "Rules": [
                {
                    "ID": "TransitionToIA",
                    "Status": "Enabled",
                    "Filter": {},
                    "Transitions": [
                        {
                            "Days": 30,
                            "StorageClass": "STANDARD_IA"
                        },
                        {
                            "Days": 90,
                            "StorageClass": "GLACIER"
                        }
                    ],
                    "Expiration": {
                        "Days": 365
                    },
                    "NoncurrentVersionTransitions": [
                        {
                            "NoncurrentDays": 30,
                            "StorageClass": "STANDARD_IA"
                        },
                        {
                            "NoncurrentDays": 90,
                            "StorageClass": "GLACIER"
                        }
                    ],
                    "NoncurrentVersionExpiration": {
                        "NoncurrentDays": 365
                    }
                }
            ]
        }' >/dev/null
    log_success "Lifecycle policy aplicada"

    # Configurar bucket encryption (SSE-S3)
    log_info "Configurando encriptación por defecto..."
    awslocal s3api put-bucket-encryption \
        --bucket "$S3_BUCKET" \
        --server-side-encryption-configuration '{
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256"
                    },
                    "BucketKeyEnabled": true
                }
            ]
        }' >/dev/null
    log_success "Encriptación AES256 configurada"

    # Block public access
    log_info "Bloqueando acceso público..."
    awslocal s3api put-public-access-block \
        --bucket "$S3_BUCKET" \
        --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" >/dev/null
    log_success "Acceso público bloqueado"
}

# Crear cola SQS principal con Dead Letter Queue
create_sqs_queues() {
    log_info "Configurando colas SQS..."

    # Crear/obtener Dead Letter Queue (idempotente)
    log_info "Configurando Dead Letter Queue: $SQS_DLQ"
    if ! DLQ_URL=$(awslocal sqs get-queue-url --queue-name "$SQS_DLQ" --query 'QueueUrl' --output text 2>/dev/null); then
        log_info "Creando DLQ: $SQS_DLQ"
        DLQ_URL=$(awslocal sqs create-queue --queue-name "$SQS_DLQ" --attributes '{
            "MessageRetentionPeriod": "1209600",
            "ReceiveMessageWaitTimeSeconds": "20"
        }' --query 'QueueUrl' --output text)
    else
        log_warn "DLQ ya existe, reutilizando URL"
    fi

    DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
    log_success "DLQ lista: $DLQ_URL (ARN: $DLQ_ARN)"

    # Crear/obtener cola principal con redrive policy a DLQ (idempotente)
    log_info "Configurando cola principal: $SQS_QUEUE"
    if ! QUEUE_URL=$(awslocal sqs get-queue-url --queue-name "$SQS_QUEUE" --query 'QueueUrl' --output text 2>/dev/null); then
        log_info "Creando cola principal: $SQS_QUEUE"
        local REDRIVE_POLICY
        REDRIVE_POLICY=$(python3 -c "import json,sys; print(json.dumps({'deadLetterTargetArn':'$DLQ_ARN','maxReceiveCount':3}))")
        local ATTRIBUTES
        ATTRIBUTES=$(python3 -c "import json,sys; print(json.dumps({
            'MessageRetentionPeriod': '1209600',
            'ReceiveMessageWaitTimeSeconds': '20',
            'VisibilityTimeout': '300',
            'RedrivePolicy': json.dumps(json.loads(sys.argv[1]))
        }))" "$REDRIVE_POLICY")
        QUEUE_URL=$(awslocal sqs create-queue --queue-name "$SQS_QUEUE" --attributes "$ATTRIBUTES" --query 'QueueUrl' --output text)
    else
        log_warn "Cola principal ya existe, reutilizando URL"
    fi

    log_success "Cola principal lista: $QUEUE_URL"

    # Configurar tags para identificación
    awslocal sqs tag-queue --queue-url "$QUEUE_URL" --tags '{
        "Project": "jarvis-os",
        "Environment": "development",
        "Component": "async-tasks",
        "ManagedBy": "floci-init"
    }' >/dev/null

    awslocal sqs tag-queue --queue-url "$DLQ_URL" --tags '{
        "Project": "jarvis-os",
        "Environment": "development",
        "Component": "async-tasks-dlq",
        "ManagedBy": "floci-init"
    }' >/dev/null

    log_success "Tags aplicados a ambas colas"
}

# Verificar recursos creados
verify_resources() {
    log_info "Verificando recursos creados..."

    # Verificar bucket
    if awslocal s3api head-bucket --bucket "$S3_BUCKET" >/dev/null 2>&1; then
        VERSIONING=$(awslocal s3api get-bucket-versioning --bucket "$S3_BUCKET" --query 'Status' --output text)
        log_success "Bucket $S3_BUCKET existe (Versionado: ${VERSIONING:-Disabled})"
    else
        log_error "Bucket $S3_BUCKET NO encontrado"
        return 1
    fi

    # Verificar colas
    for queue in "$SQS_QUEUE" "$SQS_DLQ"; do
        URL=$(awslocal sqs get-queue-url --queue-name "$queue" --query 'QueueUrl' --output text 2>/dev/null)
        if [ -n "$URL" ]; then
            ATTRS=$(awslocal sqs get-queue-attributes --queue-url "$URL" --attribute-names All --query 'Attributes' --output json)
            MSG_COUNT=$(echo "$ATTRS" | jq -r '.ApproximateNumberOfMessages // "0"')
            log_success "Cola $queue existe (URL: $URL, Mensajes: $MSG_COUNT)"
        else
            log_error "Cola $queue NO encontrada"
            return 1
        fi
    done

    return 0
}

# Mostrar resumen final
print_summary() {
    echo ""
    echo "============================================================================="
    echo "  JARVIS-OS Floci Infrastructure - RESUMEN"
    echo "============================================================================="
    echo ""
    echo "  S3 Bucket:     $S3_BUCKET"
    echo "    - Versionado: Habilitado"
    echo "    - Encriptación: AES256 (SSE-S3)"
    echo "    - Lifecycle: IA(30d) -> Glacier(90d) -> Expire(365d)"
    echo "    - Acceso público: Bloqueado"
    echo ""
    echo "  SQS Queue:     $SQS_QUEUE"
    echo "    - Retención: 14 días"
    echo "    - Long polling: 20s"
    echo "    - Visibility timeout: 300s (5 min)"
    echo "    - Max receive count: 3"
    echo "    - DLQ: $SQS_DLQ"
    echo ""
    echo "  Endpoint:      $AWS_ENDPOINT"
    echo "  Región:        $AWS_REGION"
    echo ""
    echo "  Uso desde contenedores (gentle-orchestrator):"
    echo "    AWS_ENDPOINT_URL=http://floci-localstack:4566"
    echo "    AWS_ACCESS_KEY_ID=test"
    echo "    AWS_SECRET_ACCESS_KEY=test"
    echo "============================================================================="
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    echo ""
    log_info "=== JARVIS-OS Floci Infrastructure Initialization ==="
    echo ""

    wait_for_localstack || exit 1
    create_s3_bucket
    create_sqs_queues
    verify_resources || exit 1
    print_summary

    log_success "Infraestructura JARVIS-OS inicializada correctamente"
}

# Ejecutar si se llama directamente (no source)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
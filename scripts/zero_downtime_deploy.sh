#!/usr/bin/env bash
# =============================================================================
# scripts/zero_downtime_deploy.sh
#
# Основной скрипт zero-downtime деплоя для SMDG (Docker Compose standalone).
#
# Стратегия:
#   1. Pull нового образа (по тегу из $IMAGE_TAG).
#   2. Запуск безопасных миграций БД (run_migrations_zero_downtime.py).
#   3. Scale smdg=2 (или N+1) — стартует новая реплика со старым образом.
#   4. Поднимаем контейнеры с новым образом (--no-deps, start-first).
#   5. Ждём readiness-check каждой новой реплики.
#   6. Graceful stop старых контейнеров (SIGTERM → 60s → SIGKILL).
#   7. nginx -s reload для перечитывания upstream.
#   8. Health-gate: если readiness упал — авто-rollback.
#
# Usage:
#   IMAGE_TAG=4.0.1 ./scripts/zero_downtime_deploy.sh
#   IMAGE_TAG=sha-abc123 DEPLOY_TIMEOUT=120 ./scripts/zero_downtime_deploy.sh
#
# Env vars:
#   IMAGE_TAG             — тег образа для деплоя (default: latest)
#   DESIRED_REPLICAS      — целевое количество реплик (default: 2)
#   DEPLOY_TIMEOUT        — общий таймаут деплоя в секундах (default: 300)
#   READINESS_TIMEOUT     — таймаут на readiness одной реплики (default: 90)
#   HEALTH_URL            — URL readiness-эндпоинта (default: http://localhost/health/ready)
#   COMPOSE_FILES         — compose-файлы (default: docker-compose.yml + prod)
#   SKIP_MIGRATIONS       — если "true", пропустить миграции (default: false)
#   ROLLBACK_ON_FAILURE   — авто-rollback при неудаче (default: true)
#   BUILD_LOCAL           — auto|true|false — сборка локально vs pull из registry
#                           (default: auto — pull, при неудаче fallback в build)
# =============================================================================

set -Eeuo pipefail
shopt -s inherit_errexit 2>/dev/null || true

# -----------------------------------------------------------------------------
# Конфигурация
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

IMAGE_TAG="${IMAGE_TAG:-latest}"
DESIRED_REPLICAS="${DESIRED_REPLICAS:-2}"
DEPLOY_TIMEOUT="${DEPLOY_TIMEOUT:-300}"
READINESS_TIMEOUT="${READINESS_TIMEOUT:-90}"
HEALTH_URL="${HEALTH_URL:-http://localhost/health/ready}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"
SKIP_MIGRATIONS="${SKIP_MIGRATIONS:-false}"
ROLLBACK_ON_FAILURE="${ROLLBACK_ON_FAILURE:-true}"
SERVICE_NAME="${SERVICE_NAME:-smdg}"

# BUILD_LOCAL:
#   auto  — сначала pull, при неудаче собираем локально (default; удобно для dev)
#   true  — всегда собираем локально, не пуллим (локальный prod-тест)
#   false — только pull, никаких build (чистый prod-deploy через registry)
BUILD_LOCAL="${BUILD_LOCAL:-auto}"

LOG_DIR="${PROJECT_ROOT}/audit_logs"
LOG_FILE="${LOG_DIR}/deploy_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "${LOG_DIR}"

# Автоподгрузка .env / .env.prod, чтобы DOCKER_USERNAME, REDIS_PASSWORD, DOMAIN
# и т.п. были доступны нашим preflight-проверкам. Compose-файл сам подхватит
# .env автоматически, но shell-скрипту нужно явное экспортирование.
#
# ВАЖНО: используем собственный парсер вместо `source`, потому что env-файлы
# часто содержат плейсхолдеры вроде <your_key> и другие символы (<, >, |),
# которые bash интерпретирует как редирект/pipe.
_load_env_file() {
    local file="$1"
    [[ -f "${file}" ]] || return 1

    local line key val
    while IFS= read -r line || [[ -n "${line}" ]]; do
        # Пропускаем комментарии и пустые строки
        [[ -z "${line}" || "${line}" =~ ^[[:space:]]*# ]] && continue
        # KEY=VALUE — берём всё справа от первого '=' как есть
        if [[ "${line}" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            val="${BASH_REMATCH[2]}"
            # Снимаем обрамляющие кавычки
            if [[ "${val}" =~ ^\"(.*)\"$ || "${val}" =~ ^\'(.*)\'$ ]]; then
                val="${BASH_REMATCH[1]}"
            fi
            # Не переопределяем уже экспортированные (приоритет shell > файла)
            if [[ -z "${!key:-}" ]]; then
                export "${key}=${val}"
            fi
        fi
    done < "${file}"
    return 0
}

for env_file in .env.prod .env; do
    if _load_env_file "${env_file}"; then
        log_line="loaded env from ${env_file}"
        break
    fi
done
unset _load_env_file

# Красивое логирование с таймстемпами
_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()      { printf "[%s] %s\n"     "$(_ts)" "$*" | tee -a "${LOG_FILE}"; }
log_info() { printf "[%s] ℹ️  %s\n" "$(_ts)" "$*" | tee -a "${LOG_FILE}"; }
log_ok()   { printf "[%s] ✅ %s\n"  "$(_ts)" "$*" | tee -a "${LOG_FILE}"; }
log_warn() { printf "[%s] ⚠️  %s\n" "$(_ts)" "$*" | tee -a "${LOG_FILE}" >&2; }
log_err()  { printf "[%s] ❌ %s\n"  "$(_ts)" "$*" | tee -a "${LOG_FILE}" >&2; }

# -----------------------------------------------------------------------------
# Очистка/сохранение состояния для rollback
# -----------------------------------------------------------------------------
PREVIOUS_IMAGE=""
DEPLOY_START_TS=0
DEPLOY_SUCCESS=false

on_exit() {
    local exit_code=$?
    local duration=$(( $(date +%s) - DEPLOY_START_TS ))

    if [[ ${exit_code} -ne 0 && "${DEPLOY_SUCCESS}" != "true" ]]; then
        log_err "Deploy FAILED после ${duration}s (exit=${exit_code})"
        if [[ "${ROLLBACK_ON_FAILURE}" == "true" && -n "${PREVIOUS_IMAGE}" ]]; then
            log_warn "Запускаем авто-rollback → ${PREVIOUS_IMAGE}"
            rollback_to "${PREVIOUS_IMAGE}" || log_err "Rollback тоже упал!"
        fi
        # Метрика: публикуем статус неудачи в Prometheus pushgateway при желании
        _emit_metric "deploy_failed" "${duration}"
    elif [[ "${DEPLOY_SUCCESS}" == "true" ]]; then
        log_ok "Deploy SUCCESS за ${duration}s (${IMAGE_TAG})"
        _emit_metric "deploy_success" "${duration}"
    fi
}
trap on_exit EXIT

# Pushgateway метрика (опциональная)
_emit_metric() {
    local status="$1"
    local duration="$2"
    local pg_url="${PUSHGATEWAY_URL:-}"
    [[ -z "${pg_url}" ]] && return 0

    cat <<EOF | curl -s --data-binary @- "${pg_url}/metrics/job/smdg_deploy/instance/$(hostname)" >/dev/null || true
# TYPE smdg_deploy_duration_seconds gauge
smdg_deploy_duration_seconds{status="${status}",tag="${IMAGE_TAG}"} ${duration}
# TYPE smdg_deploy_timestamp_seconds gauge
smdg_deploy_timestamp_seconds{status="${status}",tag="${IMAGE_TAG}"} $(date +%s)
EOF
}

# -----------------------------------------------------------------------------
# Shorthand для docker compose
# -----------------------------------------------------------------------------
dc() {
    docker compose ${COMPOSE_FILES} "$@"
}

# -----------------------------------------------------------------------------
# Предварительные проверки
# -----------------------------------------------------------------------------
preflight() {
    log_info "Preflight: проверка окружения"

    if ! command -v docker >/dev/null 2>&1; then
        log_err "docker не установлен"
        exit 127
    fi
    if ! docker compose version >/dev/null 2>&1; then
        log_err "docker compose v2 не доступен"
        exit 127
    fi

    local missing=()
    for var in DOCKER_USERNAME REDIS_PASSWORD; do
        if [[ -z "${!var:-}" ]]; then
            missing+=("$var")
        fi
    done
    if (( ${#missing[@]} > 0 )); then
        log_err "Не заданы обязательные переменные: ${missing[*]}"
        log_err "Пропишите их в .env.prod (или экспортируйте в shell) и повторите"
        exit 2
    fi

    if ! dc config --quiet 2>&1 | tee -a "${LOG_FILE}"; then
        log_err "Некорректный docker-compose конфиг"
        exit 2
    fi

    log_ok "Preflight OK (tag=${IMAGE_TAG}, replicas=${DESIRED_REPLICAS})"
}

# -----------------------------------------------------------------------------
# Сохранение текущего образа для rollback
# -----------------------------------------------------------------------------
save_previous_image() {
    local running_ids
    running_ids=$(dc ps -q "${SERVICE_NAME}" 2>/dev/null || true)
    if [[ -n "${running_ids}" ]]; then
        PREVIOUS_IMAGE=$(docker inspect \
            --format '{{.Config.Image}}' \
            $(echo "${running_ids}" | head -1) 2>/dev/null || echo "")
    fi

    if [[ -z "${PREVIOUS_IMAGE}" ]]; then
        log_warn "Не удалось определить текущий образ — rollback недоступен"
        return 0
    fi

    # Rollback возможен только если PREVIOUS_IMAGE имеет формат repo:tag
    # и совпадает по registry с prod-образом (${DOCKER_USERNAME}/smdg:...).
    # Локальные compose-образы вроде "smdg-smdg" автоматически rollback'нуть
    # нельзя (их image: переопределяется override-файлом на registry-путь).
    if [[ "${PREVIOUS_IMAGE}" != *":"* ]]; then
        log_warn "Текущий образ '${PREVIOUS_IMAGE}' — локальный (без tag)."
        log_warn "Авто-rollback отключен. Для отката выполните вручную:"
        log_warn "  docker compose ${COMPOSE_FILES} up -d --force-recreate ${SERVICE_NAME}"
        PREVIOUS_IMAGE=""
        return 0
    fi

    local expected_prefix="${DOCKER_USERNAME:-}/smdg:"
    if [[ -n "${DOCKER_USERNAME:-}" && "${PREVIOUS_IMAGE}" != "${expected_prefix}"* ]]; then
        log_warn "Текущий образ '${PREVIOUS_IMAGE}' не из prod-registry (${expected_prefix}*)"
        log_warn "Авто-rollback отключен"
        PREVIOUS_IMAGE=""
        return 0
    fi

    log_info "Текущий образ для возможного rollback: ${PREVIOUS_IMAGE}"
}

# -----------------------------------------------------------------------------
# Миграции БД (zero-downtime safe)
# -----------------------------------------------------------------------------
run_migrations() {
    if [[ "${SKIP_MIGRATIONS}" == "true" ]]; then
        log_warn "Миграции пропущены (SKIP_MIGRATIONS=true)"
        return 0
    fi

    log_info "Запуск безопасных миграций БД..."
    if dc run --rm --no-deps migrations; then
        log_ok "Миграции применены"
    else
        log_err "Миграции упали!"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Pull новой версии
# -----------------------------------------------------------------------------
pull_images() {
    local full_image="${DOCKER_USERNAME:-local}/smdg:${IMAGE_TAG}"

    if [[ "${BUILD_LOCAL}" == "true" ]]; then
        log_info "BUILD_LOCAL=true → собираем образ локально..."
        _build_local_image
        return 0
    fi

    log_info "Pull нового образа (${full_image})..."
    if IMAGE_TAG="${IMAGE_TAG}" dc pull --quiet "${SERVICE_NAME}" 2>&1 | tee -a "${LOG_FILE}"; then
        log_ok "Образ скачан из registry"
        return 0
    fi

    if [[ "${BUILD_LOCAL}" == "false" ]]; then
        log_err "Pull не удался, BUILD_LOCAL=false → прекращаем"
        return 1
    fi

    log_warn "Pull не удался. Fallback → собираем образ локально (BUILD_LOCAL=auto)"
    _build_local_image
}

# Собирает образ из Dockerfile и тегирует его под prod-имя, чтобы
# docker-compose.prod.yml смог поднять его как image: ${DOCKER_USERNAME}/smdg:${IMAGE_TAG}.
_build_local_image() {
    local username="${DOCKER_USERNAME:-local}"
    local full_image="${username}/smdg:${IMAGE_TAG}"

    log_info "docker build -t ${full_image} ."
    docker build \
        --build-arg "GIT_SHA=${GIT_SHA:-local}" \
        -t "${full_image}" \
        . 2>&1 | tee -a "${LOG_FILE}" | tail -20
    log_ok "Образ ${full_image} собран локально"
}

# -----------------------------------------------------------------------------
# Ожидание readiness
#
# Проверяет, что minimum ${DESIRED_REPLICAS} контейнеров проходят /health/ready
# -----------------------------------------------------------------------------
wait_for_readiness() {
    local deadline=$(( $(date +%s) + READINESS_TIMEOUT ))
    local attempts=0

    log_info "Ожидаем readiness (${HEALTH_URL}, timeout=${READINESS_TIMEOUT}s)..."

    while (( $(date +%s) < deadline )); do
        attempts=$((attempts + 1))

        local healthy_count=0
        local container_ids
        container_ids=$(dc ps -q "${SERVICE_NAME}" 2>/dev/null || true)

        for cid in ${container_ids}; do
            # Проверяем readiness изнутри каждого контейнера напрямую
            if docker exec "${cid}" curl -sf --max-time 3 \
                    http://localhost:8000/health/ready >/dev/null 2>&1; then
                healthy_count=$((healthy_count + 1))
            fi
        done

        if (( healthy_count >= DESIRED_REPLICAS )); then
            log_ok "Все ${healthy_count}/${DESIRED_REPLICAS} реплик готовы"
            return 0
        fi

        if (( attempts % 5 == 0 )); then
            log_info "  healthy=${healthy_count}/${DESIRED_REPLICAS} (попытка ${attempts})"
        fi
        sleep 2
    done

    log_err "Readiness timeout: не все реплики готовы за ${READINESS_TIMEOUT}s"
    return 1
}

# -----------------------------------------------------------------------------
# Rolling update через docker compose
#
# Compose (НЕ Swarm) не поддерживает deploy.update_config напрямую, но
# последовательность команд "up -d --no-deps --scale" эмулирует start-first.
# -----------------------------------------------------------------------------
rolling_update() {
    log_info "▶️  Rolling update: ${SERVICE_NAME} (${IMAGE_TAG})"

    local scale_up=$(( DESIRED_REPLICAS * 2 ))

    # Шаг 1: масштабируемся в 2x (старые + новые реплики одновременно).
    # --no-recreate — не трогаем существующие, только добавляем новые.
    log_info "1/4 Стартуем новые реплики (scale=${scale_up})..."
    IMAGE_TAG="${IMAGE_TAG}" dc up -d \
        --no-deps \
        --scale "${SERVICE_NAME}=${scale_up}" \
        --no-recreate \
        "${SERVICE_NAME}"

    # Даём Docker время поднять контейнеры
    sleep 3

    # Шаг 2: ждём, пока новые реплики пройдут readiness.
    log_info "2/4 Ждём readiness всех реплик..."
    if ! wait_for_readiness; then
        log_err "Новые реплики не стали ready"
        return 1
    fi

    # Шаг 3: reload nginx — он перечитает upstream через Docker DNS.
    log_info "3/4 Reload nginx upstream..."
    if dc exec -T nginx nginx -t 2>/dev/null; then
        dc exec -T nginx nginx -s reload
        log_ok "nginx reload OK"
    else
        log_warn "nginx -t упал — пропускаем reload"
    fi

    # Шаг 4: останавливаем старые реплики, возвращаем масштаб к целевому.
    # --scale ${DESIRED_REPLICAS} остановит ЛИШНИЕ контейнеры, причём docker
    # сам выберет самые старые по создания (FIFO).
    log_info "4/4 Graceful stop старых реплик → ${DESIRED_REPLICAS}..."
    IMAGE_TAG="${IMAGE_TAG}" dc up -d \
        --no-deps \
        --scale "${SERVICE_NAME}=${DESIRED_REPLICAS}" \
        --remove-orphans \
        "${SERVICE_NAME}"

    # Даём время на graceful shutdown (60s в compose)
    sleep 5

    log_ok "Rolling update завершён"
}

# -----------------------------------------------------------------------------
# Smoke test после деплоя — проверяет доступность ключевых эндпоинтов
# -----------------------------------------------------------------------------
smoke_test() {
    log_info "Smoke test против ${HEALTH_URL}..."
    local fail=0

    for i in {1..10}; do
        if curl -sfk --max-time 5 "${HEALTH_URL}" >/dev/null 2>&1; then
            fail=0
        else
            fail=$((fail + 1))
        fi
        sleep 1
    done

    if (( fail > 2 )); then
        log_err "Smoke test FAILED (${fail}/10 неудач)"
        return 1
    fi
    log_ok "Smoke test OK (${fail}/10 неудач — в пределах нормы)"
}

# -----------------------------------------------------------------------------
# Rollback к предыдущему образу
# -----------------------------------------------------------------------------
rollback_to() {
    local target_image="$1"
    log_warn "ROLLBACK → ${target_image}"

    # Валидируем формат image:tag. save_previous_image() уже проверил это,
    # но перестраховываемся на случай прямого вызова функции.
    if [[ "${target_image}" != *":"* ]]; then
        log_err "Невалидный image для rollback: '${target_image}' (нет тега)"
        return 1
    fi
    local target_tag="${target_image##*:}"

    if ! IMAGE_TAG="${target_tag}" dc up -d \
            --no-deps \
            --scale "${SERVICE_NAME}=${DESIRED_REPLICAS}" \
            --force-recreate \
            "${SERVICE_NAME}" 2>&1 | tee -a "${LOG_FILE}"; then
        log_err "docker compose up упал при rollback"
        return 1
    fi

    sleep 5
    if wait_for_readiness; then
        log_ok "Rollback успешен (tag=${target_tag})"
        return 0
    fi
    log_err "Rollback не достиг readiness"
    return 1
}

# -----------------------------------------------------------------------------
# Главный сценарий
# -----------------------------------------------------------------------------
main() {
    DEPLOY_START_TS=$(date +%s)

    log "============================================================"
    log "🚀 SMDG zero-downtime deploy"
    log "   tag=${IMAGE_TAG}  replicas=${DESIRED_REPLICAS}  log=${LOG_FILE}"
    log "============================================================"

    preflight
    save_previous_image
    pull_images
    run_migrations
    rolling_update

    if ! smoke_test; then
        log_err "Smoke test failed после деплоя"
        exit 1
    fi

    DEPLOY_SUCCESS=true
    log "============================================================"
    log_ok "Deploy completed: ${IMAGE_TAG}"
    log "============================================================"
}

main "$@"
